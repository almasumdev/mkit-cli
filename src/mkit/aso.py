"""Search rank and keyword winnability, read from Play's public web pages.

There is no official API for search rank. This fetches the same search page
a visitor sees (play.google.com/store/search, per market) and finds the app's
position; it is a measurement, not a guarantee, and results vary by device and
account. Keep request volume modest.

Keywords file ([aso] keywords in mkit.toml), TOML:

    [[market]]
    lang = "en"          # label only
    hl = "en_US"         # Play UI language
    gl = "US"            # country
    keywords = ["shopping list", "grocery list"]

A JSON list of {"kw", "hl", "gl", "lang"} is accepted too. Each run is saved
as results-YYYYMMDD.json beside the keywords file (or [aso] results_dir), and
compared with the previous run.
"""
import json
import math
import re
import threading
import time
import tomllib
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import output
from .errors import UsageError

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
_DETAILS = re.compile(r'/store/apps/details\?id=([A-Za-z0-9_.]+)')
_NUM = {'K': 1e3, 'M': 1e6, 'B': 1e9}


def load_keywords(project):
    path = project.path('aso.keywords')
    if not path or not path.is_file():
        raise UsageError(f'keywords file not found ({path or "set keywords under [aso]"})', code='NO_KEYWORDS')
    if path.suffix == '.json':
        items = json.loads(path.read_text(encoding='utf-8'))
        return [(k['kw'], k['hl'], k['gl'], k.get('lang', k['hl'])) for k in items], path
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    items = []
    for m in data.get('market', []):
        for kw in m.get('keywords', []):
            items.append((kw, m['hl'], m['gl'], m.get('lang', m['hl'])))
    return items, path


def load_markets(project):
    """The keywords file's markets, for `aso research`: each with its seeds
    (the words autocomplete is asked about; the tracked keywords when none are
    given) and its topic (a found phrase must hold one of these words)."""
    path = project.path('aso.keywords')
    if not path or not path.is_file() or path.suffix != '.toml':
        raise UsageError(f'keywords file not found or not TOML ({path or "set keywords under [aso]"})',
                         code='NO_KEYWORDS')
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    markets = []
    for m in data.get('market', []):
        seeds = m.get('seeds') or m.get('keywords', [])
        topic = m.get('topic') or sorted({w for s in seeds for w in s.lower().split() if len(w) > 2})
        markets.append({'lang': m.get('lang', m['hl']), 'hl': m['hl'], 'gl': m['gl'],
                        'seeds': list(seeds), 'topic': [t.lower() for t in topic],
                        'keywords': list(m.get('keywords', []))})
    return markets, path


def results_dir(project, keywords_path):
    return project.path('aso.results_dir') or keywords_path.parent


def _fetch(url, lang='en-US'):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': lang + ',en;q=0.5'})
            return urllib.request.urlopen(req, timeout=45).read().decode('utf-8', 'ignore')
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 + attempt * 3)


def _search(word, hl, gl):
    url = f'https://play.google.com/store/search?q={urllib.parse.quote(word)}&c=apps&hl={hl}&gl={gl}'
    html = _fetch(url, hl.replace('_', '-'))
    if html is None:
        return None
    seen = []
    for i in _DETAILS.findall(html):
        if i not in seen:
            seen.append(i)
    return seen


def rank(package, items, workers=6):
    out = output.out
    done = [0]
    lock = threading.Lock()

    def one(item):
        word, hl, gl, lang = item
        found = _search(word, hl, gl)
        with lock:
            done[0] += 1
            out.upload(done[0] / len(items) * 100)
        if found is None:
            return {'kw': word, 'lang': lang, 'gl': gl, 'pos': None, 'total': 0, 'error': 'fetch failed'}
        return {'kw': word, 'lang': lang, 'gl': gl, 'pos': found.index(package) + 1 if package in found else None,
                'total': len(found)}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, items))


def _to_int(s):
    s = s.replace('+', '').replace(',', '').replace('.', '').strip()
    if s and s[-1] in _NUM:
        return int(float(s[:-1]) * _NUM[s[-1]])
    try:
        return int(s)
    except ValueError:
        return 0


def score(package, items, workers=6):
    """For each keyword, how beatable page one is: the install count of the
    weakest of the top five apps. Under ~10k installs, a new app can get in."""
    cache, lock = {}, threading.Lock()

    def downloads(pkg):
        with lock:
            if pkg in cache:
                return cache[pkg]
        html = _fetch(f'https://play.google.com/store/apps/details?id={pkg}&hl=en_US&gl=US') or ''
        m = re.search(r'<div class="ClM7O">([0-9.,]+[KMB]?\+?)</div><div class="g1rdde">Downloads', html)
        t = re.search(r'<h1[^>]*><span[^>]*>(.*?)</span>', html)
        info = {'installs': _to_int(m.group(1)) if m else 0, 'label': m.group(1) if m else '?',
                'title': re.sub('<[^>]+>', '', t.group(1)) if t else pkg}
        with lock:
            cache[pkg] = info
        return info

    def one(item):
        word, hl, gl, lang = item
        found = _search(word, hl, gl) or []
        top = [dict(downloads(p), package=p) for p in found[:5]]
        counts = [t['installs'] for t in top]
        return {'kw': word, 'lang': lang, 'gl': gl,
                'pos': found.index(package) + 1 if package in found else None,
                'weakest': min(counts) if counts else 0, 'strongest': max(counts) if counts else 0,
                'top5': [{'title': t['title'][:40], 'installs': t['label']} for t in top]}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, items))
    return sorted(results, key=lambda r: r['weakest'])


# ------------------------------------------------------------------ research

_pace_lock = threading.Lock()
_last_request = [0.0]
PACE = 0.35   # seconds between requests: research makes thousands


def _paced(fn, *a):
    with _pace_lock:
        wait = PACE - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.time()
    return fn(*a)


def _post(url, body, lang):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers={
                'User-Agent': UA, 'Accept-Language': lang + ',en;q=0.5',
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'})
            return urllib.request.urlopen(req, timeout=45).read().decode('utf-8', 'ignore')
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 + attempt * 3)


def suggest(term, hl, gl):
    """Play's own search autocomplete for `term`: the phrases people type,
    most typed first. The same call the Play website makes as you type."""
    inner = json.dumps([[None, [term], [10], [2], 4]])
    body = urllib.parse.urlencode({'f.req': json.dumps([[['IJ4APc', inner, None, 'generic']]])}).encode()
    raw = _paced(_post, f'https://play.google.com/_/PlayStoreUi/data/batchexecute?rpcids=IJ4APc'
                        f'&hl={hl}&gl={gl}&authuser&soc-app=121&soc-platform=1&soc-device=1',
                 body, hl.replace('_', '-'))
    try:
        data = json.loads(raw[raw.index('['):])
        payload = json.loads(data[0][2])
        return [s[0].lower() for s in payload[0][0]] if payload and payload[0] else []
    except (TypeError, ValueError, IndexError):
        return []


def demand(phrase, hl, gl, suggest_fn=None):
    """How much people type `phrase`: 1.0 when autocomplete offers it after
    two letters, falling towards 0 the more letters it takes, 0 when never
    offered. Returns (demand, letters needed or None)."""
    suggest_fn = suggest_fn or suggest
    n = len(phrase)
    for k in list(range(2, n, 2)) + [n]:
        if phrase in suggest_fn(phrase[:k], hl, gl):
            return round(1 - (k - 2) / max(n - 1, 1), 2), k
    return 0.0, None


def opportunity(demand_value, median_installs, in_title):
    """Demand a new app can reach: discounted by how big page one is (median
    of the top five's installs, on a log scale) and by how many of those five
    carry the phrase in their title. 0 to 100."""
    ease = 1 / math.log10(median_installs + 10)
    return round(demand_value * ease * (1 - 0.12 * in_title) * 100, 1)


def research(package, markets, workers=3, *, suggest_fn=None, search_fn=None, details_fn=None,
             progress=None):
    """Finds phrases through each market's seeds and scores every one.

    A seed is asked about alone and with each letter after it ("grocery list
    a", "grocery list b", ...), which is how autocomplete gives up its long
    tail. Phrases of one word, or without a topic word, are dropped. The
    tracked keywords are always scored, found or not."""
    suggest_fn, search_fn = suggest_fn or suggest, search_fn or (lambda w, hl, gl: _paced(_search, w, hl, gl))
    cache, lock = {}, threading.Lock()

    def details(pkg):
        with lock:
            if pkg in cache:
                return cache[pkg]
        info = details_fn(pkg) if details_fn else _details(pkg)
        with lock:
            cache[pkg] = info
        return info

    results = []
    for m in markets:
        hl, gl = m['hl'], m['gl']
        found = set(k.lower() for k in m['keywords'])
        for seed in m['seeds']:
            tails = [seed] + ([f'{seed} {c}' for c in 'abcdefghijklmnopqrstuvwxyz'] if seed.isascii() else [])
            for q in tails:
                for s in suggest_fn(q, hl, gl):
                    if len(s.split()) >= 2 and any(t in s for t in m['topic']):
                        found.add(s)
        phrases = sorted(found)
        done = [0]

        def one(phrase, m=m, phrases=phrases, done=done):
            d, letters = demand(phrase, m['hl'], m['gl'], suggest_fn)
            apps = search_fn(phrase, m['hl'], m['gl']) or []
            top = [dict(details(p), package=p) for p in apps[:5]]
            words = [w for w in phrase.split() if len(w) > 2]
            in_title = sum(1 for t in top if all(w in t['title'].lower() for w in words))
            counts = sorted(t['installs'] for t in top) or [0]
            with lock:
                done[0] += 1
                if progress:
                    progress(done[0], len(phrases), f'{m["gl"]} {phrase}')
            return {'kw': phrase, 'lang': m['lang'], 'gl': m['gl'], 'demand': d, 'letters': letters,
                    'median_top5': counts[len(counts) // 2], 'weakest_top5': counts[0],
                    'in_title': in_title, 'pos': apps.index(package) + 1 if package in apps else None,
                    'tracked': phrase in {k.lower() for k in m['keywords']},
                    'score': opportunity(d, counts[len(counts) // 2], in_title),
                    'top5': [{'title': t['title'][:40], 'installs': t['label']} for t in top]}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results += sorted(ex.map(one, phrases), key=lambda r: -r['score'])
    return results


def _details(pkg):
    html = _paced(_fetch, f'https://play.google.com/store/apps/details?id={pkg}&hl=en_US&gl=US') or ''
    m = re.search(r'<div class="ClM7O">([0-9.,]+[KMB]?\+?)</div><div class="g1rdde">Downloads', html)
    t = re.search(r'<h1[^>]*><span[^>]*>(.*?)</span>', html)
    return {'installs': _to_int(m.group(1)) if m else 0, 'label': m.group(1) if m else '?',
            'title': re.sub('<[^>]+>', '', t.group(1)) if t else pkg}


# ------------------------------------------------------------------ impact

def impact(daily, since, days, before_ranks, after_ranks):
    """What a listing change did: store visitors and acquisitions per day in
    the `days` before `since` against the `days` from it, and the keywords
    gained and lost between the rank scans either side.

    daily: {date 'YYYY-MM-DD': (visitors, acquisitions)}; a day with no row
    counts as zero. *_ranks: {(kw, gl): position or None}."""
    start = date.fromisoformat(since)
    last = max((date.fromisoformat(d) for d in daily), default=start)

    def window(first, count):
        dates = [first + timedelta(days=i) for i in range(count)]
        dates = [d for d in dates if d <= last]
        v = sum(daily.get(d.isoformat(), (0, 0))[0] for d in dates)
        a = sum(daily.get(d.isoformat(), (0, 0))[1] for d in dates)
        n = len(dates)
        return {'days': n, 'visitors': v, 'acquisitions': a,
                'visitors_per_day': round(v / n, 1) if n else None,
                'conversion': round(a / v * 100, 1) if v else None}

    before = window(start - timedelta(days=days), days)
    after = window(start, days)
    keys = set(before_ranks) & set(after_ranks)
    gained = sorted((k for k in keys if after_ranks[k] and not before_ranks[k]), key=lambda k: after_ranks[k])
    lost = sorted(k for k in keys if before_ranks[k] and not after_ranks[k])
    moved = sorted(((k, before_ranks[k], after_ranks[k]) for k in keys
                    if before_ranks[k] and after_ranks[k] and before_ranks[k] != after_ranks[k]),
                   key=lambda x: x[2] - x[1])
    return {'since': since, 'before': before, 'after': after,
            'ranked_before': sum(1 for k in keys if before_ranks[k]),
            'ranked_after': sum(1 for k in keys if after_ranks[k]),
            'gained': [{'kw': k[0], 'gl': k[1], 'pos': after_ranks[k]} for k in gained],
            'lost': [{'kw': k[0], 'gl': k[1], 'was': before_ranks[k]} for k in lost],
            'moved': [{'kw': k[0], 'gl': k[1], 'from': a, 'to': b} for k, a, b in moved]}


def scan_around(folder, prefix, since):
    """The last rank scan before `since` and the latest one from it on."""
    scans = sorted(folder.glob(f'{prefix}-*.json'))
    tag = since.replace('-', '')
    before = [p for p in scans if p.stem.split('-')[-1] < tag]
    after = [p for p in scans if p.stem.split('-')[-1] >= tag]

    def ranks(p):
        return {(r['kw'], r['gl']): r.get('pos') for r in json.loads(p.read_text(encoding='utf-8'))}

    return (before[-1] if before else None, ranks(before[-1]) if before else {},
            after[-1] if after else None, ranks(after[-1]) if after else {})


def save(folder, prefix, results):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{prefix}-{date.today():%Y%m%d}.json'
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    return path


def previous(folder, prefix, current):
    older = sorted(p for p in folder.glob(f'{prefix}-*.json') if p != current)
    if not older:
        return None, {}
    data = json.loads(older[-1].read_text(encoding='utf-8'))
    return older[-1], {(r['kw'], r['gl']): r.get('pos') for r in data}
