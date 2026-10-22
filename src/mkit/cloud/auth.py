"""Service-account clients, retries, and Google errors turned into MkitErrors.

Two credentials, from secrets.py:

    PLAY_SERVICE_ACCOUNT      Android Publisher, Play Developer Reporting, and
                              the Play reports bucket. One per developer
                              account, so it normally lives in ~/.mkit/.env.
    FIREBASE_SERVICE_ACCOUNT  This app's Firebase / Cloud project: Firestore,
                              rules, Remote Config, Firebase Management.
"""
import json
import socket
import ssl
import time

from .. import output
from ..errors import Conflict, CredentialMissing, MkitError, NotFound

PLAY = 'PLAY_SERVICE_ACCOUNT'
FIREBASE = 'FIREBASE_SERVICE_ACCOUNT'

SCOPE_PUBLISHER = 'https://www.googleapis.com/auth/androidpublisher'
SCOPE_REPORTING = 'https://www.googleapis.com/auth/playdeveloperreporting'
SCOPE_STORAGE_READ = 'https://www.googleapis.com/auth/devstorage.read_only'
SCOPE_CLOUD = 'https://www.googleapis.com/auth/cloud-platform'
SCOPE_FIREBASE = 'https://www.googleapis.com/auth/firebase'
SCOPE_DATASTORE = 'https://www.googleapis.com/auth/datastore'
SCOPE_REMOTE_CONFIG = 'https://www.googleapis.com/auth/firebase.remoteconfig'

# A bundle is large and uploads from a home connection; httplib2's default
# socket timeout kills a release on one slow chunk.
UPLOAD_TIMEOUT = 600

TRANSIENT = (TimeoutError, socket.timeout, ssl.SSLError, ConnectionError)


def credentials(ctx, secret, scopes):
    from google.oauth2 import service_account
    info = ctx.secrets.json(secret)
    return service_account.Credentials.from_service_account_info(info, scopes=list(scopes))


def service_account_project(ctx, secret=FIREBASE):
    project = ctx.secrets.json(secret).get('project_id')
    if not project:
        raise CredentialMissing(f'{secret} names no project_id', code='BAD_CREDENTIAL')
    return project


def token(ctx, secret, scopes):
    import google.auth.transport.requests
    creds = credentials(ctx, secret, scopes)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def build(ctx, api, version, secret, scopes, timeout=120):
    """A discovery client. static_discovery=False reads the live discovery
    document, so methods Google added after this library was released (the
    monetization and changesInReviewBehavior additions, for example) exist."""
    import google_auth_httplib2
    import httplib2
    from googleapiclient.discovery import build as _build

    creds = credentials(ctx, secret, scopes)
    transport = httplib2.Http(timeout=timeout)
    # A resumable upload's "308 Resume Incomplete" is progress, not a redirect.
    transport.redirect_codes = set(range(300, 400)) - {308}
    http = google_auth_httplib2.AuthorizedHttp(creds, http=transport)
    return _build(api, version, http=http, cache_discovery=False, static_discovery=False)


def play(ctx, timeout=None):
    upload_timeout = int(ctx.project.get('play.upload_timeout', UPLOAD_TIMEOUT))
    return build(ctx, 'androidpublisher', 'v3', PLAY, [SCOPE_PUBLISHER],
                 timeout=timeout or upload_timeout)


def status_of(error):
    return getattr(getattr(error, 'resp', None), 'status', 0) or 0


def api_message(error):
    """The sentence out of a Google API error, not googleapiclient's repr of
    the whole request. Play's rejections are one actionable line."""
    try:
        return json.loads(error.content.decode('utf-8', 'ignore'))['error']['message']
    except Exception:
        return str(error)


def translate(error, what='Google API'):
    """An HttpError as the MkitError a caller can branch on."""
    from googleapiclient.errors import HttpError
    if not isinstance(error, HttpError):
        return error
    status, message = status_of(error), api_message(error)
    if status in (401, 403):
        return CredentialMissing(
            f'{what} refused the service account ({status}): {message}',
            hint='In Play Console > Users and permissions (or the Cloud/Firebase IAM page), give '
                 "the service account's email access to this app, then retry.",
            code='PERMISSION_DENIED')
    if status == 404:
        return NotFound(f'{what}: {message}', code='NOT_FOUND')
    if status == 409 or 'expired' in message.lower() or 'in review' in message.lower():
        return Conflict(f'{what}: {message}', retryable=True)
    return MkitError(f'{what} rejected the request ({status}): {message}',
                     code=f'HTTP_{status}', retryable=status >= 500)


def retry(call, what, tries=5):
    """Run one API call, retrying 5xx and dropped connections with backoff.
    Anything below 500 is Google telling us something real and is raised at
    once. `call` is a zero-arg function returning an executable request."""
    from googleapiclient.errors import HttpError
    for attempt in range(tries):
        try:
            return call().execute()
        except HttpError as error:
            if status_of(error) < 500 or attempt == tries - 1:
                raise
            reason = f'HTTP {status_of(error)}'
        except TRANSIENT as error:
            if attempt == tries - 1:
                raise
            reason = type(error).__name__
        wait = 2 ** attempt
        output.out.warn(f'{what}: {reason}, retrying in {wait}s ({attempt + 1}/{tries - 1})')
        time.sleep(wait)
