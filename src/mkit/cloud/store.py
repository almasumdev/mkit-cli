"""The store listing as files in the repo, diffed against Play and applied.

Layout, all paths from [store] in mkit.toml:

    listing_dir/<code>.md        three fenced blocks: title (30), short (80), full (4000)
    art_dir/feature/<code>.png   or art_dir/feature-graphic.png for every language
    art_dir/screenshots/<code>/  frames, or screenshots/<code>.png, a panorama
                                 sliced into 9:16 frames, or screenshots/ itself
    art_dir/wear/<code>/         Wear OS screenshots (android-wear apps), or wear/
    icon                         512x512 PNG (default art_dir/icon.png)

    [store.locales]              file code -> Play locale(s)
    en = ["en-US"]
    es = ["es-419", "es-ES"]     one text, two listings

    [store.details]              contactEmail, contactWebsite, contactPhone,
                                 defaultLanguage

Images are compared by sha256 against what Play reports, so a plan knows which
languages' art actually changed and apply re-uploads only those. Locales that
exist on Play but not in the files are reported and never deleted.
"""
import hashlib
import io
import re
import struct
from pathlib import Path

from ..errors import UsageError

LIMITS = {'title': 30, 'shortDescription': 80, 'fullDescription': 4000}
FIELDS = ('title', 'shortDescription', 'fullDescription')
IMAGE_EXT = ('.png', '.jpg', '.jpeg')


def locales(project):
    table = project.section('store').get('locales')
    if not table:
        raise UsageError('no [store.locales] table in mkit.toml',
                         hint='Map each listing file to its Play locale(s), e.g. en = ["en-US"].',
                         code='NO_LOCALES')
    return {code: [v] if isinstance(v, str) else list(v) for code, v in table.items()}


def parse_listing(path):
    text = path.read_text(encoding='utf-8')
    blocks = re.findall(r'```[^\n]*\r?\n(.*?)\r?\n```', text, re.S)
    if len(blocks) < 3:
        raise UsageError(f'{path}: expected 3 fenced blocks (title, short, full), found {len(blocks)}',
                         code='BAD_LISTING')
    values = dict(zip(FIELDS, (b.strip() for b in blocks[:3])))
    for field, value in values.items():
        if len(value) > LIMITS[field]:
            raise UsageError(f'{path.name}: {field} is {len(value)} characters, limit {LIMITS[field]}',
                             code='LISTING_TOO_LONG')
    return values


def desired_text(project):
    """{play_locale: {title, shortDescription, fullDescription}}"""
    folder = project.path('store.listing_dir', 'docs/store-listing')
    out = {}
    for code, targets in locales(project).items():
        path = folder / f'{code}.md'
        if not path.is_file():
            raise UsageError(f'listing file {path} is missing', code='NO_LISTING')
        values = parse_listing(path)
        for loc in targets:
            out[loc] = values
    return out


# ------------------------------------------------------------------ images

def _png_size(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return struct.unpack('>II', data[16:24])
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def _frames_from(path):
    """A panorama sliced into 9:16 frames, as PNG bytes."""
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
        n = max(1, round(w / (h * 9 / 16)))
        frames = []
        for i in range(n):
            buf = io.BytesIO()
            im.crop((round(i * w / n), 0, round((i + 1) * w / n), h)).save(buf, 'PNG')
            frames.append(buf.getvalue())
        return frames


def _folder_images(folder):
    if not folder.is_dir():
        return None
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT and p.is_file())
    return [p.read_bytes() for p in files]


def _feature_bytes(path):
    data = path.read_bytes()
    if _png_size(data) == (1024, 500):
        return data
    from PIL import Image
    with Image.open(path) as im:
        buf = io.BytesIO()
        im.convert('RGB').resize((1024, 500), Image.LANCZOS).save(buf, 'PNG')
        return buf.getvalue()


def desired_images(project, kind_name, default_language='en-US'):
    """{play_locale: {imageType: [bytes, ...]}} for whatever art exists.

    The icon goes with every language. Play shows the default language's icon
    for a language with none of its own, but a language can hold its own (an
    older upload), which then wins on its store page, so plan() compares the
    icon wherever Play reports one and leaves a language without one alone."""
    art = project.path('store.art_dir', 'store')
    icon_path = project.path('store.icon') or art / 'icon.png'
    icon = icon_path.read_bytes() if icon_path.is_file() else None
    if icon and _png_size(icon) != (512, 512):
        raise UsageError(f'{icon_path} must be 512x512, is {"x".join(map(str, _png_size(icon)))}',
                         code='BAD_ICON')
    # Explicit single paths win over the per-language layout; art_locales limits
    # which Play locales get art at all (the others inherit the default one's).
    store = project.section('store')
    feature_one = project.path('store.feature')
    shots_one = project.path('store.screenshots')
    wear_one = project.path('store.wear_screenshots')
    art_locales = store.get('art_locales')
    out = {}
    for code, targets in locales(project).items():
        images = {}
        feature = feature_one or art / 'feature' / f'{code}.png'
        feature = feature if feature.is_file() else art / 'feature-graphic.png'
        if feature.is_file():
            images['featureGraphic'] = [_feature_bytes(feature)]
        pano = art / 'screenshots' / f'{code}.png'
        if shots_one:
            shots = _folder_images(shots_one)
        else:
            shots = (_frames_from(pano) if pano.is_file()
                     else _folder_images(art / 'screenshots' / code) or _folder_images(art / 'screenshots'))
        if shots:
            images['phoneScreenshots'] = shots
        if kind_name == 'android-wear':
            wear = (_folder_images(wear_one) if wear_one
                    else _folder_images(art / 'wear' / code) or _folder_images(art / 'wear'))
            if wear:
                images['wearScreenshots'] = wear
        for loc in targets:
            if art_locales is not None and loc not in art_locales:
                images_here = {}
            else:
                images_here = dict(images)
            if icon:
                images_here['icon'] = [icon]
            if images_here:
                out[loc] = images_here
    return out


def check_screenshot(data, what):
    """Warn, don't refuse: art already live on Play can sit outside the published
    guideline (tall phones are over 2:1), and Play is the one that decides."""
    from .. import output
    w, h = _png_size(data)
    lo, hi = min(w, h), max(w, h)
    if lo < 320 or hi > 3840 or hi > 2 * lo:
        output.out.warn(f'{what} is {w}x{h}; Play asks for sides 320-3840 and the long side at most '
                        'twice the short one')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ diff

WORKERS = 6


def _workers(project):
    return max(1, int(project.get('play.upload_workers', WORKERS)))


def _each(items, work, workers, progress=None):
    """Run work(item) on worker threads; results in the items' order.
    progress(done, total, item) after each one."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    items = list(items)
    results = [None] * len(items)
    if not items:
        return results
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, it): n for n, it in enumerate(items)}
        done = 0
        for f in as_completed(futures):
            n = futures[f]
            results[n] = f.result()
            done += 1
            if progress:
                progress(done, len(items), items[n])
    return results


def plan(edit, project, kind_name, with_images=True, with_text=True, progress=None, only=None):
    """Compare local files with the listing in `edit`. Changes nothing.
    progress(done, total, item) is called as Play's images are read.
    only: a set of Play locales to limit the plan to (a staged rollout); the
    other locales and the app-wide contact details are then left alone."""
    if only:
        configured = {loc for targets in locales(project).values() for loc in targets}
        unknown = sorted(set(only) - configured)
        if unknown:
            raise UsageError(f'not in [store.locales]: {", ".join(unknown)}', code='UNKNOWN_LOCALE',
                             hint='Use Play locale codes as mkit.toml maps them, e.g. de-DE,es-ES.')
    listings = {l['language']: l for l in edit.call(
        lambda e, p, i: e.listings().list(packageName=p, editId=i), 'read listings').get('listings', [])}
    result = {'text': [], 'images': [], 'details': {}, 'remote_only': [], 'no_listing': []}

    if with_text:
        for loc, want in desired_text(project).items():
            if only and loc not in only:
                continue
            have = listings.get(loc, {})
            changed = {f: {'from': have.get(f, ''), 'to': want[f]} for f in FIELDS if have.get(f, '') != want[f]}
            if changed:
                result['text'].append({'locale': loc, 'new': loc not in listings, 'fields': changed})
        configured = {loc for targets in locales(project).values() for loc in targets}
        result['remote_only'] = sorted(set(listings) - configured)

    details_now = edit.call(lambda e, p, i: e.details().get(packageName=p, editId=i), 'read details')
    default_language = details_now.get('defaultLanguage') or 'en-US'

    if with_images:
        # A language Play has no listing for has no images, and Play answers a
        # read of them with 404. Its images can go up in the same edit once
        # its text is created; without the text (--images-only) they cannot.
        creating = {c['locale'] for c in result['text'] if c['new']}
        sets = []
        for loc, types in desired_images(project, kind_name, default_language).items():
            if only and loc not in only:
                continue
            exists = loc in listings
            if not exists and loc not in creating:
                if types:
                    result['no_listing'].append(loc)
                continue
            for image_type, blobs in types.items():
                if image_type.endswith('Screenshots'):
                    for n, b in enumerate(blobs, 1):
                        check_screenshot(b, f'{loc} {image_type} #{n}')
                sets.append((loc, image_type, blobs, exists))

        def read(item):
            loc, image_type, blobs, exists = item
            if not exists:
                return []
            remote = edit.call(lambda e, p, i: e.images().list(
                packageName=p, editId=i, language=loc, imageType=image_type), f'read {loc} {image_type}')
            return [img.get('sha256') for img in remote.get('images', [])]

        remotes = _each(sets, read, _workers(project),
                        progress and (lambda d, t, it: progress(d, t, f'{it[0]} {it[1]}')))
        for (loc, image_type, blobs, _), remote_sha in zip(sets, remotes):
            # No icon of its own: the language shows the default one's.
            if image_type == 'icon' and loc != default_language and not remote_sha:
                continue
            if remote_sha != [sha256(b) for b in blobs]:
                result['images'].append({'locale': loc, 'type': image_type, 'local': len(blobs),
                                         'remote': len(remote_sha), '_blobs': blobs})

    details = project.section('store').get('details') or {}
    if details and not only:
        result['details'] = {k: {'from': details_now.get(k, ''), 'to': v} for k, v in details.items()
                             if details_now.get(k, '') != v}
    return result


def plan_size(result):
    return len(result['text']) + len(result['images']) + len(result['details'])


def upload_count(result):
    """Files apply will send: every image in every changed set."""
    return sum(c['local'] for c in result['images'])


def apply(edit, result, workers=WORKERS, on_text=None, on_image=None):
    """Stage every change from `plan` in the edit (the caller commits).

    Languages go up in parallel on worker threads; within one image set the
    files go one after another, since Play keeps screenshots in upload order.
    Text first, so a language new to Play exists before its images.
    on_text(done, total, locale) and on_image(done, total, name) report each
    one as it lands."""
    import threading
    from googleapiclient.http import MediaIoBaseUpload

    def text(change):
        # patch keeps what the files don't hold (a promo video); a brand-new
        # locale has nothing to keep, so it is created whole.
        body = {'language': change['locale'], **{f: v['to'] for f, v in change['fields'].items()}}
        method = 'update' if change['new'] else 'patch'
        edit.call(lambda e, p, i: getattr(e.listings(), method)(
            packageName=p, editId=i, language=body['language'], body=body), f'text {change["locale"]}')

    _each(result['text'], text, workers, on_text and (lambda d, t, c: on_text(d, t, c['locale'])))

    total = upload_count(result)
    sent = [0]
    lock = threading.Lock()

    def images(change):
        loc, image_type = change['locale'], change['type']
        edit.call(lambda e, p, i: e.images().deleteall(packageName=p, editId=i, language=loc,
                                                       imageType=image_type), f'clear {loc} {image_type}')
        for n, blob in enumerate(change['_blobs'], 1):
            mime = 'image/png' if blob[:4] == b'\x89PNG' else 'image/jpeg'
            edit.call(lambda e, p, i: e.images().upload(
                packageName=p, editId=i, language=loc, imageType=image_type,
                media_body=MediaIoBaseUpload(io.BytesIO(blob), mimetype=mime)), f'{loc} {image_type} #{n}')
            with lock:
                sent[0] += 1
                done = sent[0]
            if on_image:
                on_image(done, total, f'{loc} {image_type} #{n}')

    _each(result['images'], images, workers)
    if result['details']:
        body = {k: v['to'] for k, v in result['details'].items()}
        edit.call(lambda e, p, i: e.details().patch(packageName=p, editId=i, body=body), 'details')


def public(result):
    """The plan without image bytes, for JSON output."""
    return {**result, 'images': [{k: v for k, v in c.items() if k != '_blobs'} for c in result['images']]}


# ------------------------------------------------------------------ data safety

REQUIRED_COLUMNS = ('Question ID (machine readable)', 'Response value', 'Answer requirement')


def read_datasafety(project):
    import csv
    path = project.path('store.datasafety')
    if not path or not path.is_file():
        raise UsageError(f'data safety CSV not found ({path or "set datasafety under [store]"})',
                         hint='Export it once from Play Console > App content > Data safety.',
                         code='NO_DATASAFETY')
    text = path.read_text(encoding='utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or any(c not in rows[0] for c in REQUIRED_COLUMNS):
        raise UsageError(f'{path} is not a Play data safety CSV (columns missing)', code='BAD_DATASAFETY')
    required = [r for r in rows if r['Answer requirement'] == 'REQUIRED']
    blank = [r['Question ID (machine readable)'] for r in required if not r['Response value'].strip()]

    def answer(question, response=''):
        return next((r['Response value'].strip().upper() for r in rows
                     if r['Question ID (machine readable)'] == question
                     and (r.get('Response ID (machine readable)') or '') == response), '')

    # MAYBE_REQUIRED, and Play does require them: an app where people make
    # accounts must link a page for deleting one, and an app that says data
    # can be deleted must link a page for that.
    creates_accounts = any(
        r['Response value'].strip().upper() == 'TRUE'
        for r in rows
        if r['Question ID (machine readable)'] == 'PSL_SUPPORTED_ACCOUNT_CREATION_METHODS'
        and r.get('Response ID (machine readable)') != 'PSL_ACM_NONE')
    for needed, question in ((creates_accounts, 'PSL_ACCOUNT_DELETION_URL'),
                             (answer('PSL_SUPPORT_DATA_DELETION_BY_USER', 'DATA_DELETION_YES') == 'TRUE',
                              'PSL_DATA_DELETION_URL')):
        if needed and not answer(question):
            blank.append(question)
    collects = next((r['Response value'] for r in rows
                     if r['Question ID (machine readable)'] == 'PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA'), '')
    # Labels read "Category / Type" or put the type on a line of its own.
    types = sorted({(r.get('Human-friendly question label') or '').replace('\n', ' / ').split(' / ')[-1].strip()
                    for r in rows if r['Question ID (machine readable)'].startswith('PSL_DATA_TYPES_')
                    and r['Response value'].strip().upper() == 'TRUE'})
    return {'path': str(path), 'text': text, 'rows': len(rows),
            'answered': sum(1 for r in rows if r['Response value'].strip()),
            'required_blank': blank, 'collects_data': collects, 'data_types': types}
