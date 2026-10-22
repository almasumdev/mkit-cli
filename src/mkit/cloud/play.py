"""Google Play publishing: edits, bundle upload, tracks, promote, rollout.

Everything that changes Play happens inside an edit: open it, make changes,
validate, then commit or discard. A dry run does all of it on Play's servers
and only skips the commit, which catches a bad bundle or a permission gap
before anything goes live, and a discarded edit spends no versionCode.

Track names: the CLI uses Play Console's words (internal, closed, open, prod);
the API kept older ids (internal, alpha, beta, production). A raw id, such as a
custom closed track, is accepted as-is. A Wear OS module ships on its own
`wear:` track family, found by asking Play which tracks exist rather than by
building names, because Google's naming there is not reliably documented.
"""
import threading
import os
import re
from pathlib import Path

from .. import output
from ..errors import Conflict, MkitError, NotFound, UsageError
from . import auth

TRACKS = {'internal': 'internal', 'closed': 'alpha', 'open': 'beta',
          'prod': 'production', 'production': 'production'}
LABELS = {'internal': 'internal testing', 'alpha': 'closed testing', 'beta': 'open testing',
          'production': 'production'}
WEAR_PREFIX = 'wear:'
WEAR_SUFFIXES = {'internal': ('internal', 'qa'), 'alpha': ('alpha',), 'beta': ('beta',),
                 'production': ('production',)}

WHATSNEW_PREFIX = 'whatsnew-'
WHATSNEW_LIMIT = 500
UPLOAD_RETRIES = 6
_DRAFT_ONLY = 'Only releases with status draft may be created on draft app'
_EDIT_EXPIRED = 'This edit has expired'
# Play's refusal to send an edit for review by itself, which it gives while the
# app has a rejected update or an open policy issue.
_MANUAL_REVIEW = 'changesNotSentForReview'
MANUAL_REVIEW_NOTE = ('Play would not send these changes for review by itself (the app has a '
                      'rejected update or an open policy issue), so they are saved but not '
                      'submitted. Send them in Play Console > Publishing overview > Send '
                      'changes for review.')

NO_WEAR_TRACK = ('No Wear OS track exists on Play, so the watch bundle was not uploaded. Add it '
                 'once in Play Console > Test and release > Advanced settings > Form factors > '
                 'Wear OS, and opt in to the Wear OS review policy on that page.')


def track_id(name):
    return TRACKS.get(name, name)


def label(track):
    base = track[len(WEAR_PREFIX):] if track.startswith(WEAR_PREFIX) else track
    text = LABELS.get(base, base)
    return f'Wear {text}' if track.startswith(WEAR_PREFIX) else text


class Edit:
    """One Play edit, discarded on exit unless it was committed."""

    def __init__(self, ctx, svc=None):
        self.ctx = ctx
        self.package = ctx.project.get('play.package') or ctx.project.package
        if not self.package:
            raise UsageError('app.package is not set in mkit.toml', code='BAD_CONFIG')
        self.svc = svc or auth.play(ctx)
        self.id = None
        self.committed = False
        # Set once Play refuses to send this edit for review by itself.
        self.manual_review = False
        # The Google client is not thread-safe: each worker thread gets its
        # own (an injected test service is shared as is).
        self._local = threading.local()
        self._make = None if svc else (lambda: auth.play(ctx))

    def __enter__(self):
        from googleapiclient.errors import HttpError
        try:
            self.id = auth.retry(lambda: self.svc.edits().insert(packageName=self.package, body={}),
                                 'open edit')['id']
        except HttpError as e:
            err = auth.translate(e, 'Play')
            if auth.status_of(e) == 404:
                err = NotFound(f'Play has no app {self.package}',
                               hint='Create it in Play Console and upload once by hand; the API '
                                    'cannot create apps. See `mkit manual`.', code='NO_APP')
            raise err from None
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.committed and self.id:
            try:
                self.svc.edits().delete(packageName=self.package, editId=self.id).execute()
            except Exception:
                pass
        return False

    @property
    def edits(self):
        return self.svc.edits()

    def _edits(self):
        if self._make is None or threading.current_thread() is threading.main_thread():
            return self.svc.edits()
        if not hasattr(self._local, 'svc'):
            self._local.svc = self._make()
        return self._local.svc.edits()

    def call(self, fn, what):
        """fn(edits, package, edit_id) -> request, run with retry. Safe from
        worker threads: each has its own client."""
        return auth.retry(lambda: fn(self._edits(), self.package, self.id), what)

    def tracks(self):
        resp = self.call(lambda e, p, i: e.tracks().list(packageName=p, editId=i), 'list tracks')
        return resp.get('tracks', [])

    def track(self, track):
        return self.call(lambda e, p, i: e.tracks().get(packageName=p, editId=i, track=track),
                         f'read {track}')

    def set_track(self, track, releases):
        return self.call(lambda e, p, i: e.tracks().update(
            packageName=p, editId=i, track=track, body={'track': track, 'releases': releases}),
            f'stage {track}')

    def validate(self):
        """Validate. When Play will not send the edit for review by itself, it
        refuses to validate it too; the commit, marked to be sent from Play
        Console, then validates it instead (the client has no such mark on
        validate), and the rest of this edit remembers that."""
        from googleapiclient.errors import HttpError
        if self.manual_review:
            return
        try:
            self.call(lambda e, p, i: e.validate(packageName=p, editId=i), 'validate')
        except HttpError as error:
            if _MANUAL_REVIEW not in str(error):
                raise
            self.manual_review = True

    def commit(self, in_review='resubmit'):
        """Commit. in_review='error' refuses instead of cancelling a review that
        is already running (listing and product changes use that)."""
        from googleapiclient.errors import HttpError
        kwargs = {}
        if in_review == 'error':
            kwargs['changesInReviewBehavior'] = 'ERROR_IF_IN_REVIEW'

        def run():
            extra = {'changesNotSentForReview': True} if self.manual_review else {}
            self.call(lambda e, p, i: e.commit(packageName=p, editId=i, **kwargs, **extra),
                      'commit')
        try:
            run()
        except HttpError as error:
            if self.manual_review or _MANUAL_REVIEW not in str(error):
                raise
            self.manual_review = True
            run()
        self.committed = True
        if self.manual_review:
            output.out.warn(MANUAL_REVIEW_NOTE)

    def finish(self, dry_run, in_review='resubmit'):
        """Validate, then commit unless this is a dry run."""
        self.validate()
        if not dry_run:
            self.commit(in_review)


# ------------------------------------------------------------------ tracks

def resolve_track(available, factor, name):
    """The real track id for a form factor and a CLI name, or None."""
    wanted = track_id(name)
    if factor == 'phone':
        return wanted if wanted in available else None
    if wanted.startswith(WEAR_PREFIX):
        return wanted if wanted in available else None
    wear = [t for t in available if t.startswith(WEAR_PREFIX)]
    for suffix in WEAR_SUFFIXES.get(wanted, ()):
        if WEAR_PREFIX + suffix in wear:
            return WEAR_PREFIX + suffix
    if wanted != 'alpha':
        return None
    known = {WEAR_PREFIX + s for group in WEAR_SUFFIXES.values() for s in group}
    custom = [t for t in wear if t not in known]
    if len(custom) == 1:
        return custom[0]
    if len(custom) > 1:
        raise UsageError(f'several Wear closed tracks exist ({", ".join(custom)}); name one with --track')
    return None


def release_notes(project):
    """whatsnew-<locale> files in the configured folder, as Play releaseNotes.
    Checked here because Play rejects an over-long note only at commit, after
    the whole bundle has gone up."""
    folder = project.path('store.whatsnew_dir')
    if not folder or not folder.is_dir():
        return []
    notes = []
    for f in sorted(folder.iterdir()):
        if not f.name.startswith(WHATSNEW_PREFIX):
            continue
        text = f.read_text(encoding='utf-8').strip()
        if len(text) > WHATSNEW_LIMIT:
            raise UsageError(f'{f.name} is {len(text)} characters; Play allows {WHATSNEW_LIMIT}',
                             code='WHATSNEW_TOO_LONG')
        if text:
            notes.append({'language': f.name[len(WHATSNEW_PREFIX):], 'text': text})
    return notes


# What a release note may not hold (docs/store.md): Play shows it as plain text
# under its own "What's new" heading, one change per line.
NOTE_BANNED = {'—': 'em dash', '–': 'en dash', '→': 'arrow', '←': 'arrow',
               '•': 'bullet', '●': 'bullet', '▪': 'bullet', '‣': 'bullet',
               '·': 'middle dot'}
NOTE_MARKERS = ('- ', '* ', '+ ')
NOTE_HEADINGS = {"what's new", 'whats new', 'new in this version', 'release notes'}
_EMOJI = re.compile('[🀀-🫿☀-➿️]')


def note_problems(text):
    """Why one note breaks the house style, as short phrases; empty when it is fine."""
    found = [name for ch, name in NOTE_BANNED.items() if ch in text]
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if ' - ' in text:
        found.append('hyphen used as a dash')
    if any(l.startswith(NOTE_MARKERS) for l in lines):
        found.append('list marker')
    if _EMOJI.search(text):
        found.append('emoji')
    # English only: a translated heading cannot be told from a first change.
    if lines and lines[0].rstrip(':').replace('’', "'").casefold() in NOTE_HEADINGS:
        found.append('heading line (Play shows its own)')
    return list(dict.fromkeys(found))


def check_note_style(notes):
    """Stop a release whose notes break the house style, naming every locale at once."""
    bad = {n['language']: note_problems(n['text']) for n in notes}
    bad = {lang: why for lang, why in bad.items() if why}
    if bad:
        raise UsageError('release notes break the house style: '
                         + '; '.join(f'{lang}: {", ".join(why)}' for lang, why in sorted(bad.items())),
                         code='WHATSNEW_STYLE',
                         hint='Plain lines, one change each: no bullets, dashes, arrows, emoji or '
                              'heading (docs/store.md). `mkit whatsnew check` lists them.')


def _is_draft_only(error):
    # Play answers a completed release on a never-published app with a clean
    # 400 on some tracks and a bare 500 on others; a 500 that survived retry
    # is treated as the same refusal and checked by re-staging as draft.
    from googleapiclient.errors import HttpError
    return isinstance(error, HttpError) and (_DRAFT_ONLY in str(error) or auth.status_of(error) >= 500)


def _stage(edit, track, release):
    """Stage `release` on `track` and validate; fall back to a draft release on
    an app Play still treats as a draft. Returns the status that validated."""
    from googleapiclient.errors import HttpError
    edit.set_track(track, [release])
    try:
        edit.validate()
        return release['status']
    except HttpError as error:
        if release['status'] == 'draft' or not _is_draft_only(error):
            raise
        draft = {k: v for k, v in release.items() if k != 'userFraction'}
        draft['status'] = 'draft'
        edit.set_track(track, [draft])
        try:
            edit.validate()
        except HttpError:
            raise error from None
        output.out.warn('the app is still a draft on Play, so this went up as a DRAFT release; '
                        'publish it once in Play Console, after which releases complete on their own')
        return 'draft'


# ------------------------------------------------------------------ upload

def _upload(request):
    """Run a resumable upload, reporting real transferred percentage and
    riding out stalls: the resumable session survives a dropped connection."""
    out = output.out
    response, stalls = None, 0
    while response is None:
        try:
            status, response = request.next_chunk(num_retries=5)
        except auth.TRANSIENT as error:
            stalls += 1
            if stalls > UPLOAD_RETRIES:
                raise
            out.warn(f'upload stalled ({type(error).__name__}), resuming [{stalls}/{UPLOAD_RETRIES}]')
            continue
        if status:
            out.upload(int(status.progress() * 100))
    out.upload(100)
    return response


def _media(path, chunk_mb):
    from googleapiclient.http import MediaFileUpload
    return MediaFileUpload(str(path), mimetype='application/octet-stream', resumable=True,
                           chunksize=chunk_mb * 1024 * 1024)


def upload_release(ctx, kind, track='internal', notes=None, dry_run=False, rollout=None,
                   release_name=None, attempts=3):
    """Upload every module's bundle (and mapping) and point its track at it.

    One release per form factor: Play refuses a watch bundle inside the phone's
    release at review time. A watch bundle with no Wear track is not uploaded
    at all -- an artifact on no track spends a versionCode for nothing.

    An expired edit (someone committed in the Console meanwhile) restarts the
    whole upload on a fresh edit; the bundles in the dead edit went with it.
    Returns [{"module", "track", "versionCode", "status"}].
    """
    from googleapiclient.errors import HttpError
    out = output.out
    modules = kind.modules()
    missing = [str(m.aab) for m in modules if not m.aab.is_file()]
    if missing:
        raise MkitError('bundle not built: ' + ', '.join(missing), code='NO_BUNDLE',
                        hint='`mkit deploy` builds before uploading.')
    notes = release_notes(ctx.project) if notes is None else notes
    chunk = int(ctx.project.get('play.upload_chunk_mb', 4))
    for attempt in range(attempts):
        try:
            with Edit(ctx) as edit:
                available = [t['track'] for t in edit.tracks()]
                plan = []
                for m in modules:
                    target = resolve_track(available, m.factor, track)
                    if target:
                        plan.append((m, target))
                    elif m.factor == 'wear':
                        out.warn(f'{m.label}: {NO_WEAR_TRACK}')
                    else:
                        raise NotFound(f'Play has no "{track}" track for this app '
                                       f'(it has: {", ".join(available) or "none"})')
                out.detail(f"what's new for {len(notes)} locale(s)" if notes else "no what's new notes")
                results = []
                for m, target in plan:
                    out.detail(f'{m.label} bundle {m.aab.stat().st_size / 1_000_000:.1f} MB')
                    try:
                        uploaded = _upload(edit.edits.bundles().upload(
                            packageName=edit.package, editId=edit.id, media_body=_media(m.aab, chunk)))
                    except HttpError as e:
                        if 'already been used' in str(e):
                            raise Conflict(f'Play already has a {m.label} bundle with this versionCode',
                                           hint='Bump before releasing again; `mkit deploy` bumps and builds together.',
                                           code='VERSION_CODE_USED') from None
                        raise
                    code = str(uploaded['versionCode'])
                    if m.mapping.is_file():
                        _upload(edit.edits.deobfuscationfiles().upload(
                            packageName=edit.package, editId=edit.id, apkVersionCode=int(code),
                            deobfuscationFileType='proguard', media_body=_media(m.mapping, chunk)))
                        out.detail(f'{m.label} mapping uploaded')
                    release = {'versionCodes': [code], 'status': 'completed'}
                    if release_name:
                        release['name'] = release_name
                    if notes:
                        release['releaseNotes'] = notes
                    if rollout is not None and target.endswith('production'):
                        release.update(status='inProgress', userFraction=rollout)
                    status = _stage(edit, target, release)
                    out.detail(f'{m.label} versionCode {code} staged on {target} ({status})')
                    results.append({'module': m.label, 'track': target, 'versionCode': code,
                                    'status': status})
                if not dry_run:
                    edit.commit()
                return results
        except HttpError as e:
            if _EDIT_EXPIRED in str(e) and attempt < attempts - 1:
                out.warn(f'Play expired the edit mid-upload; starting again ({attempt + 1}/{attempts - 1})')
                continue
            raise auth.translate(e, 'Play') from None


# ------------------------------------------------------------------ promote / rollout / status

def _source_release(releases):
    """A completed release first; a draft one will do on a never-published app."""
    for status in ('completed', 'inProgress', 'draft'):
        found = next((r for r in releases if r.get('status') == status and r.get('versionCodes')), None)
        if found:
            return found
    return None


def promote(ctx, kind, source='internal', dest='prod', rollout=None, dry_run=False):
    """Point `dest` at what `source` holds, for every form factor. No rebuild.

    The release name and "What's new" travel with the build: they are what the
    testers saw and belong to that binary, not to today's working tree.
    Returns [{"factor", "from", "to", "versionCodes", "status"}].
    """
    from googleapiclient.errors import HttpError
    if track_id(source) == track_id(dest):
        raise UsageError(f'from and to are both {dest}; nothing to promote')
    out = output.out
    factors = sorted({m.factor for m in kind.modules()}, key=lambda f: f != 'phone')
    try:
        with Edit(ctx) as edit:
            available = [t['track'] for t in edit.tracks()]
            moved = []
            for factor in factors:
                src, dst = resolve_track(available, factor, source), resolve_track(available, factor, dest)
                if not src or not dst:
                    out.warn(f'{factor}: no {"source" if not src else "destination"} track, skipped')
                    continue
                found = _source_release(edit.track(src).get('releases', []))
                if not found:
                    out.warn(f'{factor}: nothing on {src} to promote')
                    continue
                release = {'versionCodes': found['versionCodes'], 'status': 'completed'}
                for field in ('releaseNotes', 'name'):
                    if field in found:
                        release[field] = found[field]
                if 'releaseNotes' not in release:
                    out.warn(f'{factor}: no release notes on {src}; {dst} will show none')
                if rollout is not None and dst.endswith('production'):
                    release.update(status='inProgress', userFraction=rollout)
                status = _stage(edit, dst, release)
                out.detail(f'{factor}: versionCode {", ".join(found["versionCodes"])} {src} -> {dst} ({status})')
                moved.append({'factor': factor, 'from': src, 'to': dst,
                              'versionCodes': found['versionCodes'], 'status': status,
                              'name': found.get('name')})
            if not moved:
                raise NotFound(f'nothing on {source} to promote', hint='`mkit status` shows every track.')
            if not dry_run:
                edit.commit()
            return moved
    except HttpError as e:
        raise auth.translate(e, 'Play') from None


def rollout(ctx, track, action, fraction=None, dry_run=False):
    """Change a staged rollout: set a fraction, halt, resume, or complete."""
    from googleapiclient.errors import HttpError
    target = track_id(track)
    try:
        with Edit(ctx) as edit:
            releases = edit.track(target).get('releases', [])
            staged = next((r for r in releases if r.get('status') in ('inProgress', 'halted')), None)
            if not staged:
                raise NotFound(f'no staged rollout on {target}',
                               hint='Only a production release promoted with --rollout is staged.')
            release = {k: v for k, v in staged.items() if k in ('versionCodes', 'name', 'releaseNotes',
                                                                 'userFraction', 'countryTargeting')}
            if action == 'complete':
                release.pop('userFraction', None)
                release['status'] = 'completed'
            elif action == 'halt':
                release['status'] = 'halted'
            elif action == 'resume':
                release['status'] = 'inProgress'
            else:
                if not 0 < fraction < 1:
                    raise UsageError('rollout percentage must be between 0 and 100 (exclusive); '
                                     'use `complete` for 100')
                release.update(status='inProgress', userFraction=fraction)
            # Keep the completed release beside the staged one: it is what
            # everyone outside the rollout still gets.
            others = [r for r in releases if r is not staged and r.get('status') == 'completed']
            edit.set_track(target, others + [release] if action != 'complete' else [release])
            edit.finish(dry_run)
            return {'track': target, 'versionCodes': release['versionCodes'],
                    'status': release['status'], 'userFraction': release.get('userFraction')}
    except HttpError as e:
        raise auth.translate(e, 'Play') from None


def status(ctx):
    """Every track and what it holds. Read-only: the edit is always discarded."""
    from googleapiclient.errors import HttpError
    try:
        with Edit(ctx) as edit:
            rows = []
            for t in sorted(edit.tracks(), key=lambda t: (':' in t['track'], t['track'])):
                for r in t.get('releases', []) or [{}]:
                    rows.append({'track': t['track'], 'status': r.get('status', 'empty'),
                                 'versionCodes': r.get('versionCodes', []), 'name': r.get('name', ''),
                                 'userFraction': r.get('userFraction'),
                                 'notes': len(r.get('releaseNotes', []))})
            return rows
    except HttpError as e:
        raise auth.translate(e, 'Play') from None
