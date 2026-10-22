"""How the app is doing: bulk reports, Android vitals, crash clusters, reviews.

    stats     the Play Console bulk reports (Cloud Storage bucket, UTF-16 CSVs,
              3-7 days behind). The service account needs "View app information
              and download bulk reports"; the bucket is MKIT_PLAY_REPORTS_BUCKET.
    vitals    Play Developer Reporting API crash and ANR rates.
    crashes   Reporting API error issues: crash/ANR clusters with stack location.
    reviews   Android Publisher reviews: only the last 7 days with text.
"""
import csv
import io
from collections import defaultdict
from datetime import date, timedelta

from ..errors import CredentialMissing, MkitError, UsageError
from . import auth

REPORTING = 'https://playdeveloperreporting.googleapis.com/v1beta1'


# ------------------------------------------------------------------ bulk reports

def _bucket(ctx):
    bucket = ctx.project.get('play.reports_bucket') or ctx.secrets.value('MKIT_PLAY_REPORTS_BUCKET')
    if not bucket:
        raise UsageError('no reports bucket', code='NO_BUCKET',
                         hint='Set MKIT_PLAY_REPORTS_BUCKET in ~/.mkit/.env (Play Console > Download '
                              'reports > copy the Cloud Storage URI, the part after gs://).')
    return bucket.removeprefix('gs://').strip('/')


def _decode(raw):
    for encoding in ('utf-16', 'utf-8-sig', 'utf-8'):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if '\x00' not in text:
            rows = list(csv.reader(io.StringIO(text)))
            return (rows[0], rows[1:]) if rows else ([], [])
    return [], []


def _col(header, *names):
    lowered = [h.strip().lower() for h in header]
    for n in names:
        if n.lower() in lowered:
            return lowered.index(n.lower())
    return None


def _int(v):
    try:
        return int(float(v or 0))
    except ValueError:
        return 0


def store_daily(ctx):
    """Store listing visitors and acquisitions per day, all countries summed:
    {'YYYY-MM-DD': (visitors, acquisitions)}. Days Play has no row for are
    left out (no visitors that day, or under Play's reporting threshold)."""
    from googleapiclient.errors import HttpError
    bucket, package = _bucket(ctx), ctx.project.package
    st = auth.build(ctx, 'storage', 'v1', auth.PLAY, [auth.SCOPE_STORAGE_READ])
    prefix = f'stats/store_performance/store_performance_{package}_'
    try:
        names, token = [], None
        while True:
            res = st.objects().list(bucket=bucket, prefix=prefix, maxResults=1000, pageToken=token).execute()
            names += [o['name'] for o in res.get('items', [])]
            token = res.get('nextPageToken')
            if not token:
                break
    except HttpError as e:
        raise auth.translate(e, 'Play reports bucket') from None
    daily = defaultdict(lambda: [0, 0])
    for name in sorted(names):
        if not name.endswith('_country.csv'):
            continue
        header, rows = _decode(st.objects().get_media(bucket=bucket, object=name).execute())
        v, a = _col(header, 'Store listing visitors'), _col(header, 'Store listing acquisitions')
        if None in (v, a):
            continue
        for r in rows:
            if len(r) > max(v, a) and r[0]:
                daily[r[0]][0] += _int(r[v])
                daily[r[0]][1] += _int(r[a])
    return {d: tuple(x) for d, x in sorted(daily.items())}


def stats(ctx):
    from googleapiclient.errors import HttpError
    bucket, package = _bucket(ctx), ctx.project.package
    st = auth.build(ctx, 'storage', 'v1', auth.PLAY, [auth.SCOPE_STORAGE_READ])

    def listing(prefix):
        names, token = [], None
        while True:
            res = st.objects().list(bucket=bucket, prefix=prefix, maxResults=1000, pageToken=token).execute()
            names += [o['name'] for o in res.get('items', [])]
            token = res.get('nextPageToken')
            if not token:
                return sorted(names)

    def fetch(name):
        return _decode(st.objects().get_media(bucket=bucket, object=name).execute())

    try:
        installs = listing(f'stats/installs/installs_{package}_')
        store_perf = listing(f'stats/store_performance/store_performance_{package}_')
        reviews = listing(f'reviews/reviews_{package}_')
    except HttpError as e:
        err = auth.translate(e, 'Play reports bucket')
        if isinstance(err, CredentialMissing):
            err.hint = ('In Play Console > Users and permissions, give the service account "View app '
                        'information and download bulk reports" (account level).')
        raise err from None

    daily, by_country = [], defaultdict(int)
    for name in installs:
        header, rows = fetch(name)
        if name.endswith('_overview.csv'):
            i, u, a = (_col(header, 'Daily User Installs'), _col(header, 'Daily User Uninstalls'),
                       _col(header, 'Active Device Installs'))
            if None in (i, u, a):
                continue
            daily += [{'date': r[0], 'installs': _int(r[i]), 'uninstalls': _int(r[u]), 'active': _int(r[a])}
                      for r in rows if len(r) > max(i, u, a)]
        elif name.endswith('_country.csv'):
            c, i = _col(header, 'Country', 'Country / region'), _col(header, 'Daily User Installs')
            if None in (c, i):
                continue
            for r in rows:
                if len(r) > max(c, i):
                    by_country[r[c] or '??'] += _int(r[i])
    daily.sort(key=lambda d: d['date'])

    visitors = acquisitions = 0
    for name in store_perf:
        if not name.endswith('_country.csv'):
            continue
        header, rows = fetch(name)
        v, a = _col(header, 'Store listing visitors'), _col(header, 'Store listing acquisitions')
        if None in (v, a):
            continue
        for r in rows:
            if len(r) > max(v, a):
                visitors += _int(r[v])
                acquisitions += _int(r[a])

    stars = []
    for name in reviews:
        header, rows = fetch(name)
        s = _col(header, 'Star Rating')
        if s is not None:
            stars += [_int(r[s]) for r in rows if len(r) > s and (r[s] or '').strip()]

    active = [d['active'] for d in daily]
    return {
        'window': [daily[0]['date'], daily[-1]['date']] if daily else None,
        'store': {'visitors': visitors, 'acquisitions': acquisitions,
                  'conversion': round(acquisitions / visitors * 100, 1) if visitors else None},
        'installs': {'installs': sum(d['installs'] for d in daily),
                     'uninstalls': sum(d['uninstalls'] for d in daily),
                     'active_peak': max(active, default=0), 'active_latest': active[-1] if active else 0},
        'ratings': {'count': len(stars), 'average': round(sum(stars) / len(stars), 2) if stars else None},
        'countries': dict(sorted(by_country.items(), key=lambda kv: -kv[1])),
        'daily': daily,
    }


# ------------------------------------------------------------------ Reporting API

def _session(ctx):
    import google.auth.transport.requests
    creds = auth.credentials(ctx, auth.PLAY, [auth.SCOPE_REPORTING])
    return google.auth.transport.requests.AuthorizedSession(creds)


def _call(session, method, url, **kw):
    r = session.request(method, url, timeout=60, **kw)
    if r.status_code in (401, 403):
        raise CredentialMissing(f'Play Developer Reporting API refused the request ({r.status_code})',
                                hint='Enable the "Google Play Developer Reporting API" in the service '
                                     "account's Cloud project and give it \"View app information\" in Play Console.",
                                code='PERMISSION_DENIED')
    if r.status_code >= 400:
        raise MkitError(f'Reporting API error {r.status_code}: {r.text[:300]}', code=f'HTTP_{r.status_code}')
    return r.json()


def _date(d):
    return {'year': d.year, 'month': d.month, 'day': d.day}


METRICS = {
    'crash': ('crashRateMetricSet', ['crashRate', 'userPerceivedCrashRate', 'distinctUsers']),
    'anr': ('anrRateMetricSet', ['anrRate', 'userPerceivedAnrRate', 'distinctUsers']),
}


def vitals(ctx, days=28):
    """Crash and ANR rates over the last `days` days Play has data for, per
    version code, plus the overall figure for the window."""
    session = _session(ctx)
    package = ctx.project.package
    out = {}
    for key, (metric_set, metrics) in METRICS.items():
        name = f'apps/{package}/{metric_set}'
        meta = _call(session, 'GET', f'{REPORTING}/{name}')
        latest = next((f['latestEndTime'] for f in meta.get('freshnessInfo', {}).get('freshnesses', [])
                       if f.get('aggregationPeriod') == 'DAILY'), None)
        if not latest:
            out[key] = {'rows': [], 'note': 'no data yet'}
            continue
        end = date(latest['year'], latest['month'], latest['day'])
        start = end - timedelta(days=days)
        tz = {'id': 'America/Los_Angeles'}
        body = {'timelineSpec': {'aggregationPeriod': 'DAILY',
                                 'startTime': dict(_date(start), timeZone=tz),
                                 'endTime': dict(_date(end), timeZone=tz)},
                'dimensions': ['versionCode'], 'metrics': metrics, 'pageSize': 1000}
        rows = _call(session, 'POST', f'{REPORTING}/{name}:query', json=body).get('rows', [])
        per_version = defaultdict(lambda: {'users': 0, 'weighted': defaultdict(float)})
        for row in rows:
            version = next((d.get('stringValue') or str(d.get('int64Value', '')) for d in row.get('dimensions', [])
                            if d.get('dimension') == 'versionCode'), '?')
            values = {m['metric']: float(m.get('decimalValue', {}).get('value', m.get('int64Value', 0)) or 0)
                      for m in row.get('metrics', [])}
            users = values.get('distinctUsers', 0)
            entry = per_version[version]
            entry['users'] += users
            for m in metrics:
                if m != 'distinctUsers':
                    entry['weighted'][m] += values.get(m, 0) * users
        table = []
        for version, e in sorted(per_version.items(), key=lambda kv: kv[0]):
            users = e['users'] or 1
            table.append({'versionCode': version, 'users': int(e['users']),
                          **{m: round(v / users * 100, 3) for m, v in e['weighted'].items()}})
        out[key] = {'window': [str(start), str(end)], 'rows': table}
    return out


def crashes(ctx, limit=10):
    session = _session(ctx)
    data = _call(session, 'GET', f'{REPORTING}/apps/{ctx.project.package}/errorIssues:search',
                 params={'pageSize': max(1, min(limit, 50))})
    issues = []
    for i in data.get('errorIssues', []):
        issues.append({'type': i.get('type'), 'cause': i.get('cause'), 'location': i.get('location'),
                       'reports': _int(i.get('errorReportCount')), 'users': _int(i.get('distinctUsers')),
                       'firstVersion': (i.get('firstAppVersion') or {}).get('versionCode'),
                       'lastVersion': (i.get('lastAppVersion') or {}).get('versionCode'),
                       'link': i.get('issueUri')})
    issues.sort(key=lambda i: -i['reports'])
    return issues[:limit]


# ------------------------------------------------------------------ reviews

def reviews(ctx, limit=50, translate=None):
    svc = auth.play(ctx, timeout=60)
    kw = {'packageName': ctx.project.package, 'maxResults': min(limit, 100)}
    if translate:
        kw['translationLanguage'] = translate
    data = auth.retry(lambda: svc.reviews().list(**kw), 'reviews')
    out = []
    for r in data.get('reviews', []):
        user = next((c['userComment'] for c in r.get('comments', []) if 'userComment' in c), {})
        reply = next((c['developerComment'] for c in r.get('comments', []) if 'developerComment' in c), None)
        out.append({'id': r['reviewId'], 'author': r.get('authorName', ''), 'stars': user.get('starRating'),
                    'text': user.get('text', '').strip(), 'language': user.get('reviewerLanguage'),
                    'version': user.get('appVersionName'), 'device': (user.get('deviceMetadata') or {}).get('productName'),
                    'date': (user.get('lastModified') or {}).get('seconds'),
                    'replied': bool(reply), 'reply': (reply or {}).get('text')})
    return out


def reply(ctx, review_id, text):
    if len(text) > 350:
        raise UsageError(f'reply is {len(text)} characters; Play allows 350', code='REPLY_TOO_LONG')
    svc = auth.play(ctx, timeout=60)
    return auth.retry(lambda: svc.reviews().reply(packageName=ctx.project.package, reviewId=review_id,
                                                  body={'replyText': text}), 'reply')
