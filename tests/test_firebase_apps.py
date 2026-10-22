"""Registering a debug build's package with Firebase (never against live Firebase)."""
import pytest

from mkit.cloud import fbproject
from mkit.errors import MkitError

KEYTOOL = """Alias name: androiddebugkey
Certificate fingerprints:
\t SHA1: AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD
\t SHA256: 01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF
Signature algorithm name: SHA256withRSA
"""


def test_fingerprints_from_keytool():
    found = fbproject.parse_fingerprints(KEYTOOL)
    assert found['SHA_1'].startswith('AA:BB') and len(found['SHA_1'].replace(':', '')) == 40
    assert len(found['SHA_256'].replace(':', '')) == 64
    assert fbproject.parse_fingerprints('nothing here') == {}


class _Response:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, ''

    def json(self):
        return self._body


class _FakeFirebase:
    """Just enough of the Management API: list apps, create one as an operation."""

    def __init__(self, apps, polls_until_done=1):
        self.apps = list(apps)
        self.created = []
        self.polls = polls_until_done

    def get(self, url, **kw):
        if url.endswith('/androidApps'):
            return _Response({'apps': self.apps})
        self.polls -= 1
        if self.polls > 0:
            return _Response({'name': 'operations/x', 'done': False})
        return _Response({'name': 'operations/x', 'done': True, 'response': self.created[-1]})

    def post(self, url, json=None, **kw):
        app = {'packageName': json['packageName'], 'appId': '1:2:android:3', 'name': 'projects/p/androidApps/3'}
        self.created.append(app)
        self.apps.append(app)
        return _Response({'name': 'operations/x', 'done': False})


@pytest.fixture
def firebase(monkeypatch):
    def install(fake):
        monkeypatch.setattr(fbproject, '_session', lambda ctx, scopes: fake)
        monkeypatch.setattr(fbproject, 'project_id', lambda ctx: 'p')
        monkeypatch.setattr(fbproject.time, 'sleep', lambda s: None)
        return fake
    return install


def test_registers_a_missing_debug_app_and_waits_for_it(firebase):
    fake = firebase(_FakeFirebase([{'packageName': 'com.x', 'appId': 'a'}], polls_until_done=2))
    app, created = fbproject.ensure_android_app(None, 'com.x.debug', 'X (debug)')
    assert created and app['packageName'] == 'com.x.debug'
    assert [a['packageName'] for a in fake.created] == ['com.x.debug']


def test_an_existing_debug_app_is_left_alone(firebase):
    fake = firebase(_FakeFirebase([{'packageName': 'com.x'}, {'packageName': 'com.x.debug', 'appId': 'd'}]))
    app, created = fbproject.ensure_android_app(None, 'com.x.debug', 'X (debug)')
    assert not created and app['appId'] == 'd' and fake.created == []


def test_gives_up_waiting_with_a_retry_hint(firebase):
    firebase(_FakeFirebase([], polls_until_done=10**6))
    with pytest.raises(MkitError) as e:
        fbproject.ensure_android_app(None, 'com.x.debug', 'X (debug)', wait=0)
    assert e.value.code == 'FIREBASE_PENDING'
