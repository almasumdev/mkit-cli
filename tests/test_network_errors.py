"""A dropped connection is an ordinary failure, not a bug in mkit.

A Firestore write timed out during a real deploy, after the bundle was already
live on Play. requests' own exception is not an MkitError, so it went straight
past the handler that exists to warn and carry on, out of the command, and was
printed as a traceback headed "This is a bug in mkit" - abandoning the notify
and the closing summary of a release that had in fact succeeded.
"""
from types import SimpleNamespace

import pytest
import requests

from mkit.cloud import firebase
from mkit.errors import MkitError
from mkit.output import Output


def _ctx(monkeypatch, tmp_path):
    from mkit import config
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'mkit.toml').write_text('[app]\nname = "X"\nkind = "flutter"\npackage = "com.x"\n'
                                    '[firebase]\nproject = "demo"\n', encoding='utf-8')
    monkeypatch.setattr(firebase.auth, 'token', lambda *a, **k: 'token')
    secrets = SimpleNamespace(has=lambda *a, **k: False)
    return SimpleNamespace(project=config.load(project=root), out=Output(mode='json'),
                           dry_run=False, secrets=secrets)


@pytest.mark.parametrize('failure', (
    requests.exceptions.ConnectTimeout('timed out'),
    requests.exceptions.ConnectionError('refused'),
    requests.exceptions.ReadTimeout('slow'),
))
def test_a_firestore_write_that_cannot_connect_is_a_clean_error(monkeypatch, tmp_path, failure):
    ctx = _ctx(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise failure

    monkeypatch.setattr(requests, 'request', boom)
    with pytest.raises(MkitError) as e:
        firebase.publish_version(ctx, '1.1.0', 23)
    assert e.value.code == 'NETWORK'
    assert e.value.retryable
    assert 'firestore.googleapis.com' in e.value.message
    # It says the write did not land, because that is what the reader needs next.
    assert 'again' in (e.value.hint or '')


def test_a_firestore_read_that_cannot_connect_is_a_clean_error(monkeypatch, tmp_path):
    ctx = _ctx(monkeypatch, tmp_path)
    monkeypatch.setattr(requests, 'request',
                        lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectTimeout()))
    with pytest.raises(MkitError) as e:
        firebase.get_document(ctx, 'config/app')
    assert e.value.code == 'NETWORK'


def test_an_http_error_still_says_what_play_said(monkeypatch, tmp_path):
    """The translation is only for transport failures; a 403 keeps its own message."""
    ctx = _ctx(monkeypatch, tmp_path)
    monkeypatch.setattr(requests, 'request',
                        lambda *a, **k: SimpleNamespace(status_code=403, text='denied'))
    with pytest.raises(MkitError) as e:
        firebase.publish_version(ctx, '1.1.0', 23)
    assert e.value.code == 'PERMISSION_DENIED'


def test_deploy_warns_rather_than_crashing_once_the_build_is_live():
    """The step that publishes the update doc catches every exception.

    Read from the source rather than run a whole deploy: what matters is that
    the handler is not narrowed back to MkitError, which is exactly how this
    escaped the first time.
    """
    from pathlib import Path
    source = Path(firebase.__file__).parent.parent / 'commands' / 'release.py'
    text = source.read_text(encoding='utf-8')
    live = text.split('# 7-8: the build is live')[1]
    assert 'except Exception as e:' in live.split('out.step(\'Notify\')')[0]
