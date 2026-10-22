"""Credentials, from two .env files, never from the repo tree.

    ~/.mkit/.env        shared by every app: the Play service account (one
                        developer account), Telegram, the reports bucket
    <project>/.env      this app only: its Firebase service account, overrides

The shell environment wins over both, then the project file, then the user
file. A credential is JSON, stored one of two ways:

    MKIT_<NAME>_JSON_BASE64=eyJ0eXBlIjoi...    base64, survives .env quoting
    MKIT_<NAME>_FILE=C:/keys/play.json          a path outside the repo

The unprefixed spelling (<NAME>_JSON_BASE64) is accepted too, because the
older per-project kits and CI used it.

Every secret value that is read is registered with the output layer, so it is
masked if it ever reaches a log line, an error, or a JSON result.
"""
import base64
import binascii
import json
import os
from pathlib import Path

from . import config
from .errors import CredentialMissing

# name -> what it is for; doctor and error hints use the description.
KNOWN = {
    'PLAY_SERVICE_ACCOUNT': 'Google Play Android Publisher service account (JSON)',
    'FIREBASE_SERVICE_ACCOUNT': "Firebase/Google Cloud service account for this app's project (JSON)",
    'TELEGRAM': 'Telegram bot, JSON {"bot_token": "...", "chat_id": "..."}',
}

_registered = set()


def register(value):
    """Mark a string as secret so the output layer masks it."""
    if isinstance(value, str) and len(value) >= 8:
        _registered.add(value)


def redact(text):
    if not isinstance(text, str) or not _registered:
        return text
    for secret in sorted(_registered, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, '***')
    return text


def parse_env_file(path):
    """KEY=VALUE lines; # comments; optional quotes. No interpolation."""
    values = {}
    try:
        with open(path, encoding='utf-8-sig') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key.startswith('export '):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        values[key] = value
    return values


class Secrets:
    def __init__(self, project_root=None, user_home=None):
        self.user_file = Path(user_home or config.home()) / '.env'
        self.project_file = Path(project_root) / '.env' if project_root else None
        self._user = parse_env_file(self.user_file)
        self._project = parse_env_file(self.project_file) if self.project_file else {}

    def lookup(self, key):
        """(value, source) for a plain key, or (None, None)."""
        if os.environ.get(key):
            return os.environ[key], 'environment'
        if self._project.get(key):
            return self._project[key], str(self.project_file)
        if self._user.get(key):
            return self._user[key], str(self.user_file)
        return None, None

    def value(self, key, default=None):
        """A plain setting such as MKIT_PLAY_REPORTS_BUCKET."""
        for candidate in (key, key[5:] if key.startswith('MKIT_') else None):
            if candidate:
                found, _ = self.lookup(candidate)
                if found:
                    return found
        return default

    def _raw(self, name):
        for prefix in ('MKIT_', ''):
            b64, source = self.lookup(f'{prefix}{name}_JSON_BASE64')
            if b64:
                return 'base64', b64, source
            path, source = self.lookup(f'{prefix}{name}_FILE')
            if path:
                return 'file', path, source
        return None, None, None

    def source(self, name):
        """Where a credential would come from, for doctor. None if absent."""
        _, _, source = self._raw(name)
        return source

    def has(self, name):
        return self._raw(name)[0] is not None

    def json(self, name, required=True):
        """The credential as a dict. Missing and `required` raises exit 3 with
        a hint naming the exact key and file to put it in."""
        form, raw, source = self._raw(name)
        if form is None:
            if not required:
                return None
            raise CredentialMissing(
                f'{KNOWN.get(name, name)} is not set',
                hint=(f'Add MKIT_{name}_JSON_BASE64=<base64 of the JSON> to '
                      f'{self.project_file or "<project>/.env"} (this app) or '
                      f'{self.user_file} (all apps). `mkit doctor` shows what is set.'),
                code=f'MISSING_{name}')
        register(raw)
        try:
            if form == 'base64':
                text = base64.b64decode(''.join(raw.split()), validate=True).decode('utf-8')
            else:
                text = Path(raw).expanduser().read_text(encoding='utf-8-sig')
            data = json.loads(text)
        except (binascii.Error, UnicodeDecodeError, ValueError, OSError) as e:
            raise CredentialMissing(
                f'{name} from {source} could not be read as JSON ({type(e).__name__})',
                hint='Re-encode it: PowerShell [Convert]::ToBase64String([IO.File]::'
                     'ReadAllBytes("key.json")), macOS/Linux base64 -w 0 key.json',
                code=f'BAD_{name}') from e
        for field in ('private_key', 'private_key_id', 'bot_token'):
            register(data.get(field))
        return data
