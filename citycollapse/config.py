"""Raster tile configuration; compatible with existing local raster env settings."""
import os
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from .data import ROOT

def environment_values():
    values = {}
    for name in ('.env', '.env.local'):
        path = ROOT / name
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip().strip('"\'')
    values.update(os.environ)
    return values


def settings():
    values = environment_values()
    template = values.get('CITYCOLLAPSE_TILE_URL') or values.get('VITE_MAP_TILE_URL') or 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
    parsed = urlsplit(template)
    if parsed.scheme not in ('http', 'https') or not all('{' + token + '}' in template for token in ('x', 'y', 'z')):
        raise ValueError('CITYCOLLAPSE_TILE_URL must be an HTTP raster URL with {z}, {x}, {y}')
    key = values.get('VITE_CARTO_API_KEY', '')
    if key and (parsed.hostname == 'basemaps.cartocdn.com' or (parsed.hostname or '').endswith('.basemaps.cartocdn.com')):
        query = dict(parse_qsl(parsed.query))
        query.setdefault('key', key)
        template = urlunsplit(parsed._replace(query=urlencode(query)))
    return {'tile_url': template, 'attribution': values.get('CITYCOLLAPSE_MAP_ATTRIBUTION') or '© OpenStreetMap contributors · © CARTO'}


def analyst_settings():
    values = environment_values()
    base_url = values.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    parsed = urlsplit(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('OLLAMA_BASE_URL must be an HTTP address, such as http://127.0.0.1:11434')
    model = values.get('OLLAMA_MODEL', 'llama3.1:8b').strip()
    if not model:
        raise ValueError('OLLAMA_MODEL cannot be empty')
    return {'ollama_url': base_url, 'model': model,
            'history_model': values.get('OLLAMA_HISTORY_MODEL', model).strip() or model,
            'history_csv': values.get('CITYCOLLAPSE_HISTORY_CSV') or str(ROOT / 'data' / 'synthetic' / 'bengaluru_road_traffic_synthetic_hourly.csv.gz'),
            'tomtom_key': values.get('TOMTOM_API_KEY') or values.get('CITYCOLLAPSE_TOMTOM_API_KEY', '')}
