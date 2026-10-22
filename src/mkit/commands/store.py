"""Store listing, what's new, data safety and testers."""
import json
from datetime import datetime

from .. import datasafety, kinds, safety
from ..cloud import auth, play, store
from ..errors import DRIFT, UsageError
from ..git import Repo
from ..registry import Arg, command, group

group('listing', 'store listing text, images and contact details')
group('whatsnew', "release notes (what's new) files")
group('datasafety', 'the data safety declaration')
group('testers', 'Google Groups on testing tracks')

SCOPE_ARGS = (Arg('text_only', 'only the text', kind='flag'),
              Arg('images_only', 'only the images', kind='flag'))
LOCALES_ARG = Arg('locales', 'only these Play locales, comma separated, e.g. de-DE,es-ES (a staged rollout)')


def _only(args):
    if not getattr(args, 'locales', None):
        return None
    return {loc.strip() for loc in args.locales.split(',') if loc.strip()}


def _scope(args):
    if args.text_only and args.images_only:
        raise UsageError('pass only one of --text-only / --images-only')
    return not args.images_only, not args.text_only


def _show_plan(out, result):
    if out.json:
        return
    for c in result['text']:
        out.line(f'  text   {c["locale"]:8} {"new locale" if c["new"] else ", ".join(c["fields"])}')
    for c in result['images']:
        out.line(f'  images {c["locale"]:8} {c["type"]}: {c["remote"]} on Play -> {c["local"]} local')
    for k, v in result['details'].items():
        out.line(f'  detail {k}: {v["from"] or "(empty)"} -> {v["to"]}')
    if result['remote_only']:
        out.line(f'  on Play but not in the files (left alone): {", ".join(result["remote_only"])}', 'dim')
    if result.get('no_listing'):
        out.line(f'  images not planned, no listing on Play yet (apply the text first): '
                 f'{", ".join(result["no_listing"])}', 'yellow')
    if not store.plan_size(result):
        out.line('  no changes: Play matches the files', 'green')


def _compare(ctx, edit, text, images, only=None):
    out = ctx.out
    out.step('Compare with Play' + (f' ({len(only)} locale(s) only)' if only else ''))
    result = store.plan(edit, ctx.project, ctx.project.kind, with_images=images, with_text=text,
                        progress=lambda d, t, item: out.progress(d, t, item), only=only)
    out.done(f'{store.plan_size(result)} change(s), {store.upload_count(result)} image(s) to send')
    return result


@command('listing plan', 'Show how the listing files differ from Play (changes nothing)',
         risk='plan', needs=('play', 'store'), args=SCOPE_ARGS + (LOCALES_ARG,),
         examples=('mkit listing plan', 'mkit listing plan --text-only',
                   'mkit listing plan --locales de-DE,es-ES'))
def listing_plan(ctx, args):
    text, images = _scope(args)
    ctx.out.start(f'{ctx.project.name} listing plan', 1)
    with play.Edit(ctx) as edit:
        result = _compare(ctx, edit, text, images, _only(args))
    _show_plan(ctx.out, result)
    if store.plan_size(result):
        ctx.exit_code = DRIFT
    return store.public(result)


@command('listing apply', 'Push listing changes (only what differs) to Play', risk='publish',
         needs=('play', 'store'),
         args=SCOPE_ARGS + (LOCALES_ARG,
                            Arg('resubmit', 'cancel a review already running and resubmit everything',
                                kind='flag')),
         examples=('mkit listing apply', 'mkit listing apply --text-only --dry-run',
                   'mkit listing apply --locales de-DE,es-ES,es-419,pt-BR'))
def listing_apply(ctx, args):
    text, images = _scope(args)
    out = ctx.out
    out.start(f'{ctx.project.name} listing', 4)
    with play.Edit(ctx) as edit:
        result = _compare(ctx, edit, text, images, _only(args))
        _show_plan(out, result)
        if not store.plan_size(result):
            return dict(store.public(result), changed=False)
        safety.confirm(ctx, f'Publish {store.plan_size(result)} listing change(s) for {ctx.project.name}')
        workers = store._workers(ctx.project)
        out.step(f'Send text ({len(result["text"])} language(s))')
        progress = lambda d, t, item: out.progress(d, t, item)  # noqa: E731
        store.apply(edit, {**result, 'images': [], 'details': {}}, workers, on_text=progress)
        out.done()
        out.step(f'Send images ({store.upload_count(result)} file(s), {workers} at a time)')
        store.apply(edit, {**result, 'text': []}, workers, on_image=progress)
        out.done()
        out.step('Validate and commit')
        edit.finish(ctx.dry_run, in_review='resubmit' if args.resubmit else 'error')
        out.done()
    if not ctx.out.json:
        if ctx.dry_run:
            ctx.out.line('validated on Play; nothing committed (dry run)', 'green')
        elif edit.manual_review:
            ctx.out.line('committed; send it for review in Play Console (see the warning)', 'green')
        else:
            ctx.out.line('committed; Play reviews listing changes before they show', 'green')
    return dict(store.public(result), changed=not ctx.dry_run, dry_run=ctx.dry_run,
                sent_for_review=not ctx.dry_run and not edit.manual_review)


@command('listing pull', 'Save the live listing (all locales) to a JSON backup', risk='read',
         needs=('play',), args=(Arg('out', 'file to write (default: a timestamped backup)'),))
def listing_pull(ctx, args):
    with play.Edit(ctx) as edit:
        listings = edit.call(lambda e, p, i: e.listings().list(packageName=p, editId=i),
                             'read listings').get('listings', [])
        details = edit.call(lambda e, p, i: e.details().get(packageName=p, editId=i), 'read details')
    data = {'package': ctx.project.package, 'details': details,
            'listings': {l['language']: l for l in listings}}
    if args.out:
        path = ctx.project.root / args.out
    else:
        folder = ctx.project.path('store.backup_dir', 'console')
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'backup-listings-{datetime.now():%Y%m%d-%H%M%S}.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    if not ctx.out.json:
        ctx.out.line(f'{len(listings)} locale(s) saved to {path}')
    return {'file': str(path), 'locales': sorted(data['listings'])}


@command('whatsnew check', "Check the what's new files: lengths and locales", risk='read', needs=('store',))
def whatsnew_check(ctx, args):
    notes = play.release_notes(ctx.project)
    configured = set()
    if ctx.project.section('store').get('locales'):
        configured = {loc for t in store.locales(ctx.project).values() for loc in t}
    have = {n['language'] for n in notes}
    missing = sorted(configured - have)
    style = {n['language']: why for n in notes if (why := play.note_problems(n['text']))}
    repo = Repo(ctx.project.root)
    last = repo.last_release() if notes and repo.is_repo() else ''
    unchanged = bool(last) and not repo.changed_since(last, ctx.project.path('store.whatsnew_dir'))
    if not ctx.out.json:
        for n in notes:
            ctx.out.line(f'  {n["language"]:8} {len(n["text"]):3}/{play.WHATSNEW_LIMIT}  '
                         f'{n["text"].splitlines()[0][:60]}')
        for lang, why in sorted(style.items()):
            ctx.out.line(f'  {lang}: {", ".join(why)}', 'red')
        if missing:
            ctx.out.line(f'  no note for: {", ".join(missing)} (those languages see the default)', 'yellow')
        if unchanged:
            ctx.out.line(f'  unchanged since the last release ({last[:7]}): deploy will refuse it '
                         'without --same-notes', 'yellow')
    if style:
        ctx.exit_code = 1
    return {'notes': notes, 'missing': missing, 'style': style, 'unchanged_since_release': unchanged}


@command('datasafety check', 'Check the data safety CSV (no upload)', risk='read', needs=('store',))
def datasafety_check(ctx, args):
    info = store.read_datasafety(ctx.project)
    info.pop('text')
    if not ctx.out.json:
        ctx.out.line(f'{info["path"]}: {info["rows"]} rows, {info["answered"]} answered')
        ctx.out.line(f'  collects data: {info["collects_data"] or "?"}')
        ctx.out.line(f'  data types:    {", ".join(info["data_types"]) or "none"}')
        for q in info['required_blank']:
            ctx.out.line(f'  REQUIRED but blank: {q}', 'yellow')
    if info['required_blank']:
        ctx.exit_code = 1
    return info


@command('datasafety build', 'Write the data safety CSV from [datasafety] in mkit.toml',
         risk='write', needs=('store',),
         examples=('mkit datasafety build', 'mkit datasafety build --show'),
         args=(Arg('show', 'print the answers without writing the file', kind='flag'),))
def datasafety_build(ctx, args):
    """The 782 questions are the same for every app; only the answers differ.

    So the question set ships with the engine and an app declares what it
    collects, rather than each repo carrying its own filled copy of Google's
    sample CSV and drifting from the others.
    """
    text, info = datasafety.build(ctx.project.section('datasafety'))
    path = ctx.project.path('store.datasafety')
    if not path:
        raise UsageError('no datasafety path set under [store]',
                         hint='Add datasafety = "docs/data-safety/<app>.csv" under [store].',
                         code='NO_DATASAFETY_PATH')
    if not args.show:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='')
    if not ctx.out.json:
        ctx.out.line(f'{"would write" if args.show else "wrote"} {path}: {info["rows"]} rows')
        ctx.out.line(f'  collects:   {", ".join(info["data_types"]) or "nothing"}')
    return {'path': str(path), 'written': not args.show, **info}


@command('datasafety types', 'Every data type a declaration can name', risk='read')
def datasafety_types(ctx, args):
    """What [datasafety.collected] accepts, so nobody has to guess a spelling."""
    types = [{'id': t['id'], 'names': t['names'], 'label': t['label']}
             for t in datasafety.data_types().values()]
    if not ctx.out.json:
        for t in types:
            ctx.out.line(f'  {t["names"][0]:26s} {t["label"]}')
        ctx.out.line('')
        ctx.out.line('  purposes: ' + ', '.join(sorted(datasafety.PURPOSES)))
    return {'types': types, 'purposes': sorted(datasafety.PURPOSES)}


@command('datasafety apply', 'Upload the data safety declaration (replaces the one on Play)',
         risk='publish', needs=('play', 'store'))
def datasafety_apply(ctx, args):
    info = store.read_datasafety(ctx.project)
    if info['required_blank']:
        raise UsageError(f'{len(info["required_blank"])} REQUIRED question(s) are blank; Play would reject it',
                         code='DATASAFETY_INCOMPLETE')
    safety.confirm(ctx, f'Replace the data safety declaration of {ctx.project.package}',
                   [f'collects data: {info["collects_data"]}',
                    f'data types: {", ".join(info["data_types"]) or "none"}'])
    if ctx.dry_run:
        return {'dry_run': True, 'rows': info['rows']}
    svc = auth.play(ctx)
    auth.retry(lambda: svc.applications().dataSafety(packageName=ctx.project.package,
                                                      body={'safetyLabels': info['text']}), 'data safety')
    if not ctx.out.json:
        ctx.out.line('data safety declaration uploaded', 'green')
    return {'uploaded': True, 'rows': info['rows']}


@command('testers show', 'Google Groups on each testing track', risk='read', needs=('play',))
def testers_show(ctx, args):
    rows = []
    with play.Edit(ctx) as edit:
        for t in edit.tracks():
            if t['track'] == 'production':
                continue
            groups = edit.call(lambda e, p, i, tr=t['track']: e.testers().get(
                packageName=p, editId=i, track=tr), f'testers {t["track"]}').get('googleGroups', [])
            rows.append({'track': t['track'], 'googleGroups': groups})
    if not ctx.out.json:
        ctx.out.table([(r['track'], ', '.join(r['googleGroups']) or '-') for r in rows], ('track', 'groups'))
        ctx.out.line('email tester lists are Console-only (see `mkit manual`)', 'dim')
    return {'tracks': rows}


@command('testers set', 'Set the Google Groups on a testing track', risk='publish', needs=('play',),
         args=(Arg('track', 'testing track', kind='positional'),
               Arg('groups', 'group emails', kind='positional', nargs='+')))
def testers_set(ctx, args):
    track = play.track_id(args.track)
    safety.confirm(ctx, f'Set testers of {track} to {", ".join(args.groups)}')
    with play.Edit(ctx) as edit:
        edit.call(lambda e, p, i: e.testers().update(packageName=p, editId=i, track=track,
                                                     body={'googleGroups': args.groups}), 'testers')
        edit.finish(ctx.dry_run, in_review='error')
    return {'track': track, 'googleGroups': args.groups, 'dry_run': ctx.dry_run}
