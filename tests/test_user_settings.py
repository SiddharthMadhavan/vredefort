"""User-entered keys are protected, persistent, and used by API clients."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from citycollapse import config, user_settings
from citycollapse.app import CityCollapseApp


class UserSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for target, attribute, value in (
            (user_settings, 'SETTINGS_FILE', self.folder / 'settings.json'),
            (config, 'ENV_ROOT', self.folder),
            (config, 'MAP_PREFERENCES', self.folder / 'map-preferences.json'),
        ):
            mock = patch.object(target, attribute, value)
            mock.start()
            self.addCleanup(mock.stop)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows DPAPI')
    def test_keys_roundtrip_without_plaintext_on_disk(self):
        values = {'TOMTOM_API_KEY': 'fixture-tomtom-key', 'VITE_CARTO_API_KEY': 'fixture-carto-key',
                  'OLLAMA_BASE_URL': 'http://127.0.0.1:11434', 'OLLAMA_MODEL': 'llama3.1:8b'}
        user_settings.save_user_settings(values)
        saved = user_settings.SETTINGS_FILE.read_text()
        self.assertNotIn(values['TOMTOM_API_KEY'], saved)
        self.assertNotIn(values['VITE_CARTO_API_KEY'], saved)
        self.assertEqual(user_settings.read_user_settings(), values)
        self.assertEqual(json.loads(saved)['values']['OLLAMA_MODEL'], 'llama3.1:8b')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows DPAPI')
    def test_saved_keys_override_env_and_clearing_disables_legacy_alias(self):
        (self.folder / '.env').write_text('TOMTOM_API_KEY=old-key\nCITYCOLLAPSE_TOMTOM_API_KEY=legacy-key\nVITE_CARTO_API_KEY=old-carto')
        with patch.dict(os.environ, {}, clear=True):
            user_settings.save_user_settings({'TOMTOM_API_KEY': 'new-key', 'VITE_CARTO_API_KEY': 'new-carto'})
            self.assertEqual(config.analyst_settings()['tomtom_key'], 'new-key')
            self.assertIn('key=new-carto', config.settings()['tile_url'])
            user_settings.save_user_settings({'TOMTOM_API_KEY': '', 'VITE_CARTO_API_KEY': ''})
            self.assertEqual(config.analyst_settings()['tomtom_key'], '')
            self.assertNotIn('key=', config.settings()['tile_url'])

    def test_bad_or_foreign_profile_does_not_prevent_startup(self):
        for content in ('invalid JSON', '[]', '{"values": []}',
                        '{"protected_keys": "not-valid-base64"}'):
            user_settings.SETTINGS_FILE.write_text(content)
            self.assertEqual(user_settings.read_user_settings(), {})

    def test_plaintext_section_cannot_supply_keys_or_unrelated_configuration(self):
        user_settings.SETTINGS_FILE.write_text(json.dumps({'values': {
            'TOMTOM_API_KEY': 'not-protected', 'OLLAMA_MODEL': 'model', 'CITYCOLLAPSE_MAP_PATH': 'unexpected'}}))
        self.assertEqual(user_settings.read_user_settings(), {'OLLAMA_MODEL': 'model'})

    @unittest.skipUnless(sys.platform == 'win32', 'Windows DPAPI')
    def test_failed_encryption_keeps_previous_profile(self):
        user_settings.save_user_settings({'TOMTOM_API_KEY': 'old-key'})
        original = user_settings.SETTINGS_FILE.read_bytes()
        with patch.object(user_settings, '_crypt', side_effect=ValueError('protection failed')):
            with self.assertRaises(ValueError):
                user_settings.save_user_settings({'TOMTOM_API_KEY': 'new-key'})
        self.assertEqual(user_settings.SETTINGS_FILE.read_bytes(), original)

    def test_validation_accepts_optional_keys_and_rejects_bad_connections(self):
        valid = {'TOMTOM_API_KEY': '', 'VITE_CARTO_API_KEY': '',
                 'OLLAMA_BASE_URL': 'http://127.0.0.1:11434', 'OLLAMA_MODEL': 'llama3.1:8b'}
        CityCollapseApp.validate_connection_settings(valid)
        for override in ({'OLLAMA_BASE_URL': 'file:///invalid'}, {'OLLAMA_MODEL': ''},
                         {'TOMTOM_API_KEY': 'contains\na-newline'}):
            with self.assertRaises(ValueError):
                CityCollapseApp.validate_connection_settings({**valid, **override})

    def test_new_map_key_replaces_embedded_carto_key(self):
        result = config.settings({'CITYCOLLAPSE_TILE_URL': 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png?key=old',
                                  'VITE_CARTO_API_KEY': 'new'})
        self.assertIn('key=new', result['tile_url'])
        self.assertNotIn('key=old', result['tile_url'])
        result = config.settings({'CITYCOLLAPSE_TILE_URL': result['tile_url'], 'VITE_CARTO_API_KEY': ''})
        self.assertNotIn('key=', result['tile_url'])


if __name__ == '__main__':
    unittest.main()
