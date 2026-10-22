"""Firebase: the in-app update document, and Firestore rules/indexes deploy.

The Firebase project is the one named under [firebase] project in mkit.toml, or
else the one the service account belongs to. When both are set they must
agree: a key for the wrong project is the mistake this catches before a rules
deploy lands somewhere it should not.
"""
from urllib.parse import urlsplit
import json
import os
import tempfile
from datetime import datetime, timezone

from .. import output, proc
from ..errors import MkitError, UsageError
from ..toolchain import tool
from . import auth

FIRESTORE = 'https://firestore.googleapis.com/v1'


def project_id(ctx):
    configured = ctx.project.get('firebase.project')
    from_key = auth.service_account_project(ctx) if ctx.secrets.has(auth.FIREBASE) else None
    if configured and from_key and configured != from_key:
        raise UsageError(f'[firebase] project is {configured} but the service account belongs to {from_key}',
                         hint='Use the key for this app\'s Firebase project, or fix mkit.toml.',
                         code='PROJECT_MISMATCH')
    project = configured or from_key
    if not project:
        raise UsageError('no Firebase project: set project under [firebase] or add the service account',
                         code='NO_FIREBASE_PROJECT')
    return project


def _value(v):
    if isinstance(v, bool):
        return {'booleanValue': v}
    if isinstance(v, int):
        return {'integerValue': str(v)}
    if isinstance(v, datetime):
        return {'timestampValue': v.strftime('%Y-%m-%dT%H:%M:%SZ')}
    return {'stringValue': str(v)}


def _send(method, url, **kw):
    """One request, with a transport failure turned into an MkitError.

    Timeouts, refused connections and DNS failures arrive as requests'
    own exceptions, which are not MkitErrors - so they used to travel all the
    way out of a command as an "internal error" with a traceback, and past the
    handlers that exist to degrade gracefully. A dropped connection is the most
    ordinary failure there is and says nothing about a bug.
    """
    import requests
    try:
        return requests.request(method, url, **kw)
    except requests.exceptions.RequestException as error:
        raise MkitError(f'could not reach {urlsplit(url).netloc}: '
                        f'{type(error).__name__.replace("Error", "").lower() or "failed"}',
                        hint='Check the connection and run it again; nothing was written.',
                        code='NETWORK', retryable=True) from None


def patch_document(ctx, path, values):
    """Write only the given fields of one document (updateMask), creating it if
    needed. Fields not named are left exactly as they are."""
    project = project_id(ctx)
    token = auth.token(ctx, auth.FIREBASE, [auth.SCOPE_DATASTORE])
    fields = {k: _value(v) for k, v in values.items()}
    response = _send(
        'PATCH', f'{FIRESTORE}/projects/{project}/databases/(default)/documents/{path}',
        params=[('updateMask.fieldPaths', k) for k in fields],
        json={'fields': fields}, headers={'Authorization': f'Bearer {token}'}, timeout=30)
    if response.status_code in (401, 403):
        raise MkitError(f'Firestore refused the write ({response.status_code})', code='PERMISSION_DENIED',
                        hint='Give the service account the Cloud Datastore User role on the project.')
    if response.status_code >= 400:
        raise MkitError(f'Firestore write failed ({response.status_code}): {response.text[:300]}',
                        code=f'HTTP_{response.status_code}')
    return project


def get_document(ctx, path):
    project = project_id(ctx)
    token = auth.token(ctx, auth.FIREBASE, [auth.SCOPE_DATASTORE])
    response = _send('GET', f'{FIRESTORE}/projects/{project}/databases/(default)/documents/{path}',
                     headers={'Authorization': f'Bearer {token}'}, timeout=30)
    if response.status_code == 404:
        return {}
    if response.status_code >= 400:
        raise MkitError(f'Firestore read failed ({response.status_code}): {response.text[:300]}',
                        code=f'HTTP_{response.status_code}')
    out = {}
    for key, value in response.json().get('fields', {}).items():
        (kind, raw), = value.items()
        out[key] = int(raw) if kind == 'integerValue' else raw
    return out


def update_doc_path(ctx):
    return ctx.project.get('firebase.update_doc', 'config/app')


def publish_version(ctx, version_name, version_code):
    """The document the app reads to decide whether to offer an update."""
    path = update_doc_path(ctx)
    project = patch_document(ctx, path, {'latestBuild': int(version_code),
                                         'latestVersionName': version_name,
                                         'updatedAt': datetime.now(timezone.utc)})
    return f'{project}/{path}'


def deploy_targets(ctx):
    custom = ctx.project.get('firebase.deploy')
    if custom:
        return list(custom)
    targets = []
    if (ctx.project.root / 'firestore.rules').is_file():
        targets.append('firestore:rules')
    if (ctx.project.root / 'firestore.indexes.json').is_file():
        targets.append('firestore:indexes')
    return targets


def deploy_rules(ctx):
    """`firebase deploy --only firestore:rules,firestore:indexes` as the
    project's service account, not whoever happens to be logged in to the CLI.

    The key is written to a private temp file for the one command and deleted
    straight after. Rules go out before a build on purpose: rules live ahead of
    the app that needs them only widen what older clients may do, while an app
    that reaches users before its rules gets PERMISSION_DENIED.
    """
    targets = deploy_targets(ctx)
    if not targets:
        raise UsageError('nothing to deploy: no firestore.rules or firestore.indexes.json',
                         code='NO_RULES')
    if not (ctx.project.root / 'firebase.json').is_file():
        raise UsageError('firebase.json not found in the project root', code='NO_FIREBASE_JSON')
    project = project_id(ctx)
    info = ctx.secrets.json(auth.FIREBASE)
    fd, key_path = tempfile.mkstemp(prefix='mkit-sa-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(info, f)
        env = dict(os.environ, GOOGLE_APPLICATION_CREDENTIALS=key_path)
        env.pop('FIREBASE_TOKEN', None)
        # "Deploy complete!" is the CLI's own word that the rules and indexes are live. It
        # can still exit non-zero afterwards: on a success it posts a Google Analytics event
        # with a 5s timeout (command.js -> withTimeout(5000, trackGA4)), and where that call
        # cannot reach Google the timeout escapes as "An unexpected error has occurred". The
        # deploy is done by then, and failing here would roll back a version bump over a
        # telemetry ping.
        proc.stream([tool('firebase'), 'deploy', '--only', ','.join(targets), '--project', project,
                     '--non-interactive'], 'firebase deploy', proc.firebase_interesting,
                    cwd=ctx.project.root, env=env, quiet=True,
                    done_marker='Deploy complete!')
    finally:
        try:
            os.remove(key_path)
        except OSError:
            output.out.warn(f'could not delete the temporary key file {key_path}; delete it by hand')
    return project, targets
