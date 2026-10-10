"""Atomic user preferences with Windows DPAPI protection for API keys."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
import sys
import tempfile

from .paths import USER_DIR

SETTINGS_FILE = USER_DIR / 'settings.json'
SECRET_KEYS = frozenset(('TOMTOM_API_KEY', 'VITE_CARTO_API_KEY'))
PLAIN_KEYS = frozenset(('OLLAMA_BASE_URL', 'OLLAMA_MODEL'))


class DataBlob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(payload, decrypt=False):
    if sys.platform != 'win32':
        raise ValueError('Saving API keys is supported on Windows. Environment variables remain available.')
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    pointer = ctypes.POINTER(DataBlob)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [pointer, ctypes.c_void_p, pointer, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, pointer]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(payload)
    incoming = DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN, without machine-wide protection: current user.
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError('Windows could not unlock the saved API keys.' if decrypt else
                         'Windows could not protect the API keys. Settings were not saved.')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel32.LocalFree(outgoing.data)


def read_user_settings():
    try:
        document = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        if not isinstance(document, dict) or not isinstance(document.get('values', {}), dict):
            return {}
        values = {key: value for key, value in document.get('values', {}).items()
                  if key in PLAIN_KEYS and isinstance(value, str)}
        protected = document.get('protected_keys')
        if protected:
            secrets = json.loads(_crypt(base64.b64decode(protected, validate=True), decrypt=True))
            values.update({key: value for key, value in secrets.items()
                           if key in SECRET_KEYS and isinstance(value, str)})
        return values
    except (OSError, ValueError, TypeError, AttributeError):
        # An unreadable profile must not prevent launching the app and opening
        # Settings to replace it (e.g. an encrypted profile from another user).
        return {}


def save_user_settings(values):
    plain = {key: values[key] for key in PLAIN_KEYS if key in values}
    secrets = {key: values[key] for key in SECRET_KEYS if key in values}
    document = {'version': 1, 'values': plain}
    if secrets:
        document['protected_keys'] = base64.b64encode(_crypt(json.dumps(secrets).encode('utf-8'))).decode('ascii')
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='settings-', suffix='.tmp', dir=SETTINGS_FILE.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, indent=2)
        os.replace(temporary, SETTINGS_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
