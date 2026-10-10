"""Raster tile configuration; compatible with existing local raster env settings."""
import os
import json
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from .data import ROOT
from .paths import CACHE_DIR, ENV_ROOT
from .user_settings import read_user_settings

def environment_values():
    values = {}
    for name in ('.env', '.env.local'):
        path = ENV_ROOT / name
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip().strip('"\'')
    values.update(os.environ)
    user = read_user_settings()
    values.update(user)
    if 'TOMTOM_API_KEY' in user:
        values['VREDEFORT_TOMTOM_API_KEY'] = user['TOMTOM_API_KEY']
    return values


MAP_PREFERENCES = CACHE_DIR / 'map-preferences.json'
DEFAULT_TILE_URL = 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'


def settings(values=None):
    values = environment_values() if values is None else values
    template = values.get('VREDEFORT_TILE_URL') or values.get('VITE_MAP_TILE_URL') or DEFAULT_TILE_URL
    parsed = urlsplit(template)
    if parsed.scheme not in ('http', 'https') or not all('{' + token + '}' in template for token in ('x', 'y', 'z')):
        raise ValueError('VREDEFORT_TILE_URL must be an HTTP raster URL with {z}, {x}, {y}')
    key = values.get('VITE_CARTO_API_KEY', '')
    if 'VITE_CARTO_API_KEY' in values and (parsed.hostname == 'basemaps.cartocdn.com' or (parsed.hostname or '').endswith('.basemaps.cartocdn.com')):
        query = dict(parse_qsl(parsed.query))
        if key:
            query['key'] = key
        else:
            query.pop('key', None)
        template = urlunsplit(parsed._replace(query=urlencode(query)))
    try:
        preferences = json.loads(MAP_PREFERENCES.read_text(encoding='utf-8'))
        if not isinstance(preferences, dict):
            preferences = {}
    except (OSError, ValueError):
        preferences = {}
    offline = values.get('VREDEFORT_MAP_OFFLINE', str(preferences.get('offline', False))).lower() in ('true', '1', 'yes')
    local_path = values.get('VREDEFORT_MAP_PATH', preferences.get('local_path')) or None
    if local_path is not None and not isinstance(local_path, str):
        raise ValueError('VREDEFORT_MAP_PATH must be a local raster map path')
    return {'tile_url': template, 'offline': offline, 'local_path': local_path,
            'attribution': values.get('VREDEFORT_MAP_ATTRIBUTION') or '© OpenStreetMap contributors · © CARTO'}


def save_map_preferences(offline, local_path):
    MAP_PREFERENCES.parent.mkdir(parents=True, exist_ok=True)
    temporary = MAP_PREFERENCES.with_suffix('.tmp')
    temporary.write_text(json.dumps({'offline': bool(offline), 'local_path': str(local_path) if local_path else None}), encoding='utf-8')
    temporary.replace(MAP_PREFERENCES)


def analyst_settings(values=None):
    values = environment_values() if values is None else values
    base_url = values.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    parsed = urlsplit(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('OLLAMA_BASE_URL must be an HTTP address, such as http://127.0.0.1:11434')
    model = values.get('OLLAMA_MODEL', 'llama3.1:8b').strip()
    if not model:
        raise ValueError('OLLAMA_MODEL cannot be empty')
    return {'ollama_url': base_url, 'model': model,
            'history_model': values.get('OLLAMA_HISTORY_MODEL', model).strip() or model,
            'network_model': values.get('OLLAMA_NETWORK_MODEL', model).strip() or model,
            'planner_model': values.get('OLLAMA_PLANNER_MODEL', model).strip() or model,
            'review_model': values.get('OLLAMA_REVIEW_MODEL', model).strip() or model,
            'history_csv': values.get('VREDEFORT_HISTORY_CSV') or str(ROOT / 'data' / 'synthetic' / 'bengaluru_road_traffic_synthetic_hourly.csv.gz'),
            'tomtom_key': values.get('TOMTOM_API_KEY') or values.get('VREDEFORT_TOMTOM_API_KEY', '')}
