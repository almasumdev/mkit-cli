"""Remote Config templates and Firebase app management (SHA fingerprints,
google-services.json), with this app's Firebase service account.

Remote Config is published whole: the template is read with its ETag and
written back with If-Match, so a change someone made in the console between
plan and apply is a conflict (exit 5), never silently overwritten.
"""
import json
import re
import time

from ..errors import Conflict, MkitError, NotFound, UsageError
from . import auth
from .firebase import project_id

RC = 'https://firebaseremoteconfig.googleapis.com/v1/projects/{p}/remoteConfig'
MGMT = 'https://firebase.googleapis.com/v1beta1/projects/{p}'
TEMPLATE_KEYS = ('conditions', 'parameters', 'parameterGroups')


def _session(ctx, scopes):
    import google.auth.transport.requests
    return google.auth.transport.requests.AuthorizedSession(auth.credentials(ctx, auth.FIREBASE, scopes))


def _check(r, what):
    if r.status_code in (401, 403):
        raise MkitError(f'{what} refused ({r.status_code}): {r.text[:200]}', code='PERMISSION_DENIED',
                        hint='Give the Firebase service account the matching role (Remote Config Admin, '
                             'Firebase Admin) in the Cloud console IAM page.')
    if r.status_code == 409 or r.status_code == 412:
        raise Conflict(f'{what}: the template changed since it was read; run plan again')
    if r.status_code == 404:
        raise NotFound(f'{what}: not found')
    if r.status_code >= 400:
        raise MkitError(f'{what} failed ({r.status_code}): {r.text[:300]}', code=f'HTTP_{r.status_code}')
    return r


# ------------------------------------------------------------------ Remote Config

def template_path(ctx):
    return ctx.project.path('firebase.remote_config', 'remoteconfig.template.json')


def rc_get(ctx):
    s = _session(ctx, [auth.SCOPE_REMOTE_CONFIG])
    r = _check(s.get(RC.format(p=project_id(ctx)), headers={'Accept-Encoding': 'gzip'}, timeout=60),
               'Remote Config')
    return r.json(), r.headers.get('ETag')


def local_template(ctx):
    path = template_path(ctx)
    if not path.is_file():
        raise UsageError(f'{path} not found', hint='`mkit remoteconfig pull` writes it from Firebase.',
                         code='NO_TEMPLATE')
    data = json.loads(path.read_text(encoding='utf-8'))
    return {k: data[k] for k in TEMPLATE_KEYS if k in data}


def rc_diff(remote, local):
    changes = []
    rp, lp = remote.get('parameters', {}), local.get('parameters', {})
    for key in sorted(set(rp) | set(lp)):
        if key not in lp:
            changes.append({'parameter': key, 'change': 'remove'})
        elif key not in rp:
            changes.append({'parameter': key, 'change': 'add'})
        elif rp[key] != lp[key]:
            changes.append({'parameter': key, 'change': 'update'})
    for key in ('conditions', 'parameterGroups'):
        if remote.get(key, [] if key == 'conditions' else {}) != local.get(key, [] if key == 'conditions' else {}):
            changes.append({'parameter': f'({key})', 'change': 'update'})
    return changes


def rc_publish(ctx, template, etag, validate_only=False):
    s = _session(ctx, [auth.SCOPE_REMOTE_CONFIG])
    r = _check(s.put(RC.format(p=project_id(ctx)), params={'validate_only': 'true'} if validate_only else None,
                     headers={'If-Match': etag, 'Content-Type': 'application/json; UTF-8'},
                     data=json.dumps(template), timeout=60), 'Remote Config publish')
    return r.json().get('version', {})


def rc_versions(ctx, limit=10):
    s = _session(ctx, [auth.SCOPE_REMOTE_CONFIG])
    r = _check(s.get(RC.format(p=project_id(ctx)) + ':listVersions', params={'pageSize': limit}, timeout=60),
               'Remote Config versions')
    return r.json().get('versions', [])


def rc_rollback(ctx, version):
    s = _session(ctx, [auth.SCOPE_REMOTE_CONFIG])
    r = _check(s.post(RC.format(p=project_id(ctx)) + ':rollback', json={'versionNumber': str(version)},
                      timeout=60), 'Remote Config rollback')
    return r.json().get('version', {})


# ------------------------------------------------------------------ Firebase apps

def android_apps(ctx):
    s = _session(ctx, [auth.SCOPE_FIREBASE])
    r = _check(s.get(MGMT.format(p=project_id(ctx)) + '/androidApps', params={'pageSize': 100},
                     timeout=60), 'Firebase apps')
    return s, r.json().get('apps', [])


def android_app(ctx, package=None):
    package = package or ctx.project.package
    s, apps = android_apps(ctx)
    app = next((a for a in apps if a.get('packageName') == package), None)
    if not app:
        raise NotFound(f'no Android app {package} in Firebase project {project_id(ctx)}',
                       hint=f'It has: {", ".join(a.get("packageName", "?") for a in apps) or "none"}')
    return s, app


def ensure_android_app(ctx, package, display_name, wait=120):
    """The project's Android app for `package`, registering it when missing.
    Returns (app, created). Creation is a long-running operation; it is waited
    for, so the config pulled right after already carries the new client."""
    s, apps = android_apps(ctx)
    app = next((a for a in apps if a.get('packageName') == package), None)
    if app:
        return app, False
    op = _check(s.post(MGMT.format(p=project_id(ctx)) + '/androidApps',
                       json={'packageName': package, 'displayName': display_name}, timeout=60),
                f'Registering {package}').json()
    deadline = time.monotonic() + wait
    while not op.get('done'):
        if time.monotonic() > deadline:
            raise MkitError(f'Firebase is still registering {package}',
                            hint='Run the same command again in a minute; it picks up where this left off.',
                            code='FIREBASE_PENDING')
        time.sleep(2)
        op = _check(s.get(f'https://firebase.googleapis.com/v1beta1/{op["name"]}', timeout=60),
                    f'Registering {package}').json()
    if op.get('error'):
        raise MkitError(f'Firebase could not register {package}: {op["error"].get("message", op["error"])}',
                        code='FIREBASE_CREATE_FAILED')
    return op.get('response', {}), True


def parse_fingerprints(keytool_text):
    """SHA-1 and SHA-256 of a certificate, from `keytool -list -v` output."""
    found = {}
    for label, key in (('SHA1', 'SHA_1'), ('SHA256', 'SHA_256')):
        m = re.search(rf'{label}:\s*([0-9A-Fa-f:]+)', keytool_text)
        if m:
            found[key] = m.group(1)
    return found


def sha_list(ctx):
    s, app = android_app(ctx)
    r = _check(s.get(f'https://firebase.googleapis.com/v1beta1/{app["name"]}/sha', timeout=60), 'SHA list')
    return app, r.json().get('certificates', [])


def sha_add(ctx, sha, package=None):
    clean = sha.replace(':', '').lower()
    cert_type = {40: 'SHA_1', 64: 'SHA_256'}.get(len(clean))
    if not cert_type:
        raise UsageError('a SHA-1 has 40 hex digits and a SHA-256 has 64 (colons are fine)')
    s, app = android_app(ctx, package)
    r = s.post(f'https://firebase.googleapis.com/v1beta1/{app["name"]}/sha',
               json={'shaHash': clean, 'certType': cert_type}, timeout=60)
    if r.status_code == 409:
        return {'shaHash': clean, 'certType': cert_type, 'changed': False}
    _check(r, 'SHA add')
    return {'shaHash': clean, 'certType': cert_type, 'changed': True}


def config_file(ctx):
    import base64
    s, app = android_app(ctx)
    r = _check(s.get(f'https://firebase.googleapis.com/v1beta1/{app["name"]}/config', timeout=60),
               'google-services.json')
    return base64.b64decode(r.json()['configFileContents']).decode('utf-8')
