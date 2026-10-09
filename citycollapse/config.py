"""Raster tile configuration; compatible with existing local raster env settings."""
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from .data import ROOT

def settings():
    values = {}
    for name in ('.env', '.env.local'):
        path = ROOT / name
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip().strip('"\'')
    values.update(os.environ)
    template = values.get('CITYCOLLAPSE_TILE_URL') or values.get('VITE_MAP_TILE_URL') or 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
    parsed = urlsplit(template)
    if parsed.scheme not in ('http', 'https') or not all('{' + token + '}' in template for token in ('x', 'y', 'z')):
        raise ValueError('CITYCOLLAPSE_TILE_URL must be an HTTP raster URL with {z}, {x}, {y}')
    key = values.get('VITE_CARTO_API_KEY', '')
    if key and (parsed.hostname == 'basemaps.cartocdn.com' or (parsed.hostname or '').endswith('.basemaps.cartocdn.com')):
        query = dict(parse_qsl(parsed.query))
        query.setdefault('key', key)
        template = urlunsplit(parsed._replace(query=urlencode(query)))
    return {'tile_url': template, 'attribution': values.get('CITYCOLLAPSE_MAP_ATTRIBUTION') or '© OpenStreetMap contributors · © CARTO | Hospital matches: OSM / ODbL'}
