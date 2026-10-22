"""Releasing: deploy, status, promote, rollout, Firestore rules, update doc.

deploy is one pipeline for every app. Each step runs only if this app uses it
(its table is in mkit.toml) and its credential is present:

    1 Preflight          tools, JDK, signing, Play access, what will be skipped
    2 Snapshot           commit whatever was already uncommitted, on its own
    3 Bump               version name + code, committed on its own
    4 Firestore rules    [firebase] rules = true
    5 Build              release bundle(s); [hooks] post_build
    6 Upload             bundle, mapping, what's new -> track, commit
    7 Update doc         [firebase] update_doc
    8 Notify             [notify.telegram]; [hooks] post_deploy
    9 Push               the snapshot and bump commits, to the branch's upstream

A failure before step 6 commits undoes the bump commit (only if it is still
HEAD) and nothing ships. After step 6 the build is live, so later failures warn
and the bump stays: the repo must keep tracking what actually shipped.

--dry-run does the real build and a real upload into a Play edit, validates
it, and discards it. No git commits (the version file is put back), no rules,
no Firestore write, no message.
"""
import os
import re

from .. import hooks, kinds, notify, safety, toolchain
from ..cloud import auth, firebase, play
from ..errors import PARTIAL, MkitError, UsageError
from ..git import BUMP_PREFIX, Repo
from ..registry import Arg, command, group

TRACK_CHOICES = ('internal', 'closed', 'open', 'prod')
STEPS = 9


def feature_ready(ctx, feature, secret=None, extra=None):
    """(ready, reason). Not ready + switched on = a skip with a warning."""
    if not ctx.project.has(feature):
        return False, None
    if secret and not ctx.secrets.has(secret):
        return False, f'{secret} is not set (add MKIT_{secret}_JSON_BASE64 to .env)'
    if extra:
        return extra()
    return True, None


def skip_or_fail(ctx, step, reason):
    """A switched-on step that cannot run: warn and go on, or fail if --strict."""
    if ctx.strict:
        raise MkitError(f'{step}: {reason}', code='STEP_SKIPPED',
                        hint='Without --strict this step is skipped with a warning.')
    ctx.out.skip(step, reason)


def parse_percent(text):
    if text is None:
        return None
    value = float(str(text).rstrip('%'))
    if not 0 < value < 100:
        raise UsageError('rollout must be a percentage between 0 and 100 (exclusive)')
    return round(value / 100, 4)


def _rules_extra(ctx):
    if not ctx.project.section('firebase').get('rules'):
        return False, None
    try:
        toolchain.tool('firebase')
    except MkitError:
        return False, 'firebase CLI not found on PATH'
    return True, None


def _listing_url(ctx):
    return f'https://play.google.com/store/apps/details?id={ctx.project.package}'


def version_label(kind, moved):
    """"1.2.2 (8)" for what a promote moved, as deploy writes it.

    The name is the Play release name deploy sets (the version name), or Play's
    own default "8 (1.2.2)" for a release uploaded some other way; failing both,
    this checkout's version name when its code is the one that moved.
    """
    codes = [c for m in moved for c in m['versionCodes']]
    names = {m['name'] for m in moved if m.get('name')}
    name = names.pop() if len(names) == 1 else None
    if name and (default := re.fullmatch(r'\d+ \((.+)\)', name)):
        name = default.group(1)
    if not name:
        local_name, local_code = kind.current_version()
        if str(local_code) in codes:
            name = local_name
    joined = ', '.join(codes)
    return f'{name} ({joined})' if name else f'versionCode {joined}'



def _notes_written_for_this_release(repo, project):
    """A note left as it was at the last release describes that release, not this one."""
    last = repo.last_release()
    if last and not repo.changed_since(last, project.path('store.whatsnew_dir')):
        raise UsageError(f"the what's new notes have not changed since the last release ({last[:7]})",
                         code='WHATSNEW_UNCHANGED',
                         hint="Write this release's changes in store/whatsnew first, or pass "
                              '--same-notes to ship them again on purpose.')

@command('deploy', 'Bump, build and release to a Play track (internal by default)', risk='publish',
         needs=('play',),
         args=(Arg('level', 'version bump', kind='positional', nargs='?',
                   choices=('major', 'minor', 'patch'), default='patch'),
               Arg('track', 'track to release to', choices=TRACK_CHOICES, default='internal'),
               Arg('rollout', 'production only: staged rollout percentage, e.g. 20'),
               Arg('same_notes', 'ship the release note unchanged from the last release', kind='flag')),
         examples=('mkit deploy', 'mkit deploy minor', 'mkit deploy --dry-run',
                   'mkit deploy --yes --confirm com.example.app'))
def deploy(ctx, args):
    out, project = ctx.out, ctx.project
    kind = kinds.for_project(project)
    repo = Repo(project.root)
    rollout = parse_percent(args.rollout)
    if rollout and args.track != 'prod':
        raise UsageError('--rollout only applies to --track prod')
    old_name, old_code = kind.current_version()
    subtitle = f'{args.level} bump to {play.label(play.track_id(args.track))}' + (' (dry run)' if ctx.dry_run else '')
    out.start(f'{project.name} deploy', STEPS, subtitle)

    # 1 -------------------------------------------------------------- preflight
    out.step('Preflight')
    if not repo.is_repo():
        raise MkitError(f'{project.root} is not a git repository', code='NO_GIT')
    ctx.secrets.json(auth.PLAY)  # required: fails now with the exact key to add
    if not kind.signing_file():
        raise MkitError('no signing config found (key.properties / keystore.properties)',
                        code='NO_SIGNING', hint='Put the release keystore config in place, or set '
                                                'signing under [app] in mkit.toml.')
    jdk = toolchain.find_jdk(project)
    if project.kind == 'flutter':
        toolchain.tool('flutter')
    notes = play.release_notes(project)
    play.check_note_style(notes)
    if notes and not args.same_notes:
        _notes_written_for_this_release(repo, project)
    rules_ok, rules_why = feature_ready(ctx, 'firebase', auth.FIREBASE, lambda: _rules_extra(ctx))
    doc_ok, doc_why = feature_ready(ctx, 'firebase', auth.FIREBASE,
                                    lambda: (bool(project.get('firebase.update_doc')), None))
    tg_ok, tg_why = feature_ready(ctx, 'notify.telegram', 'TELEGRAM')
    hooks.run(ctx, 'pre_deploy', version_name=old_name, version_code=old_code)
    out.done(f'JDK {toolchain.java_major(jdk)}; {len(notes)} what\'s new locale(s)')

    new_name = kinds.bump_name(old_name, args.level)
    safety.confirm(ctx, f'Release {project.name} {new_name} ({old_code + 1}) to '
                        f'{play.label(play.track_id(args.track))}',
                   [f'package {project.package}', f'from {old_name} ({old_code})'])

    # 2-3 ----------------------------------------------------------- git + bump
    out.step('Snapshot pending changes')
    if ctx.dry_run:
        out.done('dry run: nothing committed')
    else:
        dirty = repo.snapshot()
        out.done('clean' if not dirty else f'{dirty} file(s) committed')

    out.step('Bump version')
    version_file = kind.version.path
    original = version_file.read_bytes()
    _, _, name, code = kind.bump(args.level)
    bump_head = None
    if not ctx.dry_run:
        bump_head = repo.commit_files([version_file], f'{BUMP_PREFIX}{name} (versionCode {code})')
    out.done(f'{old_name} ({old_code}) -> {name} ({code})')

    version = f'{name} ({code})'
    result = {'from': {'versionName': old_name, 'versionCode': old_code},
              'versionName': name, 'versionCode': code, 'track': play.track_id(args.track),
              'dry_run': ctx.dry_run}
    stage = 'preflight'
    try:
        # 4 ---------------------------------------------------------- rules
        stage = 'Firestore rules'
        out.step('Deploy Firestore rules')
        if ctx.dry_run and rules_ok:
            out.detail('dry run: not deployed')
        elif rules_ok:
            fb_project, targets = firebase.deploy_rules(ctx)
            result['rules'] = {'project': fb_project, 'targets': targets}
        elif rules_why:
            skip_or_fail(ctx, 'Firestore rules', rules_why)
        out.done()

        # 5 ---------------------------------------------------------- build
        stage = 'the build'
        out.step('Build release bundle')
        env = dict(os.environ, JAVA_HOME=jdk)
        built = kind.bundle(env)
        hooks.run(ctx, 'post_build', version_name=name, version_code=code)
        out.done(', '.join(f'{m.label} {m.aab.stat().st_size / 1_000_000:.1f} MB' for m in built))

        # 6 ---------------------------------------------------------- upload
        stage = 'the Play upload'
        out.step(f'Upload to Play ({play.label(play.track_id(args.track))})')
        uploads = play.upload_release(ctx, kind, args.track, notes=notes, dry_run=ctx.dry_run,
                                      rollout=rollout, release_name=name)
        result['uploads'] = uploads
        out.done(('validated, discarded: ' if ctx.dry_run else '')
                 + ', '.join(f'{u["module"]} {u["versionCode"]}' for u in uploads))
    except BaseException as error:
        # BaseException: Ctrl+C during the build must undo the bump too.
        if ctx.dry_run:
            version_file.write_bytes(original)
        elif bump_head and repo.undo(bump_head):
            out.warn('version bump commit undone; nothing was released')
        if not ctx.dry_run and isinstance(error, Exception):
            notify.send(ctx, notify.message(ctx, version, f'<b>Deploy failed</b> at {notify.esc(stage)}',
                                            [('Branch', repo.branch()), ('Error', getattr(error, 'message', str(error))[:300])]))
        if isinstance(error, Exception) and not isinstance(error, MkitError):
            raise auth.translate(error, 'Play') from None
        raise

    if ctx.dry_run:
        version_file.write_bytes(original)
        for step in ('Update doc', 'Notify', 'Push'):
            out.step(step)
            out.detail('dry run: not done')
            out.done()
        out.finish(f'{version} validated on Play; nothing committed or released')
        return result

    # 7-8: the build is live. Failures from here on warn; the bump stays.
    #
    # Every exception, not only MkitError. The release is on Play by this line -
    # crashing now abandons the notify, the hooks and the closing summary over
    # something that no longer decides whether the release happened. A dropped
    # connection to Firestore did exactly that once, and printed a traceback
    # calling itself a bug in mkit.
    out.step('Publish update doc')
    try:
        if doc_ok:
            result['update_doc'] = firebase.publish_version(ctx, name, code)
            out.detail(result['update_doc'])
        elif doc_why:
            skip_or_fail(ctx, 'Update doc', doc_why)
    except Exception as e:
        out.warn(f'update doc not written: {getattr(e, "message", None) or e}. '
                 f'Re-run: mkit config set --latest')
        ctx.exit_code = PARTIAL
    out.done()

    out.step('Notify')
    if tg_ok:
        # Both links on an internal release: testers open the first, and the
        # second is where it lands once promoted.
        sent = notify.send(ctx, notify.message(
            ctx, version, f'Released to {play.label(play.track_id(args.track))}',
            [('Branch', repo.branch()), ('Commit', repo.head()),
             ('Internal test', project.get('play.internal_testing_url') if args.track == 'internal' else None),
             ('Play Store', _listing_url(ctx))]))
        result['notified'] = sent
    elif tg_why:
        skip_or_fail(ctx, 'Notify', tg_why)
    try:
        hooks.run(ctx, 'post_deploy', version_name=name, version_code=code)
    except Exception as e:
        out.warn(f'post_deploy hook failed: {getattr(e, "message", None) or e}')
        ctx.exit_code = PARTIAL
    out.done()

    # 9: the commits that made this release, on the remote.
    #
    # Last, and never a failure: the release is live by now, so a push that
    # cannot go leaves the user with a one-line instruction rather than a
    # traceback on top of a successful deploy. It is the release's own history
    # though - a bump commit that exists on one machine is a version on Play
    # that nothing else can reproduce - so not pushing is a partial result, not
    # a silence.
    out.step('Push')
    if not project.get('app.push_after_deploy', True):
        out.done('off for this app')
    elif (pushed := repo.push())[0]:
        result['pushed'] = pushed[1]
        out.done(f'{repo.branch()} -> {pushed[1]}')
    else:
        out.warn(f'not pushed: {pushed[1]}')
        ctx.exit_code = PARTIAL
        out.done()

    if out.skipped and not ctx.exit_code:
        ctx.exit_code = PARTIAL
    out.finish(f'Released {version} to {play.label(play.track_id(args.track))}')
    if not result.get('pushed'):
        out.line('Not pushed: git push', 'dim')
    return result


@command('status', 'What every Play track holds (versions, rollout, notes)', risk='read', needs=('play',))
def status(ctx, args):
    rows = play.status(ctx)
    if not ctx.out.json:
        ctx.out.table([(r['track'], r['status'], ', '.join(r['versionCodes']) or '-', r['name'] or '',
                        f'{r["userFraction"] * 100:g}%' if r['userFraction'] else '',
                        f'{r["notes"]} notes' if r['notes'] else '') for r in rows],
                      ('track', 'status', 'versionCode', 'name', 'rollout', "what's new"))
    return {'tracks': rows}


@command('promote', 'Move a tested release to another track, keeping its notes and name',
         risk='publish', needs=('play',),
         args=(Arg('to', 'destination track', kind='positional', nargs='?', choices=TRACK_CHOICES,
                   default='prod'),
               Arg('from', 'source track', choices=TRACK_CHOICES, default='internal'),
               Arg('rollout', 'production only: staged rollout percentage, e.g. 20')),
         examples=('mkit promote', 'mkit promote closed', 'mkit promote prod --from closed --rollout 20'))
def promote(ctx, args):
    out = ctx.out
    source = getattr(args, 'from')
    rollout = parse_percent(args.rollout)
    if rollout and args.to != 'prod':
        raise UsageError('--rollout only applies when promoting to prod')
    kind = kinds.for_project(ctx.project)
    src, dst = play.label(play.track_id(source)), play.label(play.track_id(args.to))
    safety.confirm(ctx, f'Promote {ctx.project.name} from {src} to {dst}'
                        + (f' at {rollout * 100:g}%' if rollout else ''))
    out.start(f'{ctx.project.name} promote', 2, f'{src} to {dst}' + (' (dry run)' if ctx.dry_run else ''))
    out.step(f'Promote from {src}')
    moved = play.promote(ctx, kind, source, args.to, rollout, ctx.dry_run)
    codes = ', '.join(c for m in moved for c in m['versionCodes'])
    version = version_label(kind, moved)
    out.done(version)
    out.step('Notify')
    if not ctx.dry_run:
        notify.send(ctx, notify.message(ctx, version, f'Promoted to {dst} from {src}'
                                        + (f', {rollout * 100:g}% rollout' if rollout else ''),
                                        [('Play Store', _listing_url(ctx) if args.to == 'prod' else None)]))
        hooks.run(ctx, 'post_promote', version_code=codes)
    out.done()
    out.finish(f'{version} {"validated for" if ctx.dry_run else "live on"} {dst}')
    return {'promoted': moved, 'dry_run': ctx.dry_run}


@command('rollout', 'Change a staged production rollout: a percentage, halt, resume or complete',
         risk='publish', needs=('play',),
         args=(Arg('action', 'a percentage like 50, or halt | resume | complete', kind='positional'),
               Arg('track', 'track with the staged release', default='prod')),
         examples=('mkit rollout 50', 'mkit rollout halt', 'mkit rollout complete'))
def rollout(ctx, args):
    action = args.action.lower()
    fraction = None
    if action not in ('halt', 'resume', 'complete'):
        fraction = parse_percent(action)
        action = 'set'
    what = {'set': f'set rollout to {fraction * 100:g}%' if fraction else '', 'halt': 'halt the rollout',
            'resume': 'resume the rollout', 'complete': 'roll out to 100%'}[action]
    safety.confirm(ctx, f'{ctx.project.name}: {what} on {args.track}')
    result = play.rollout(ctx, args.track, action, fraction, ctx.dry_run)
    if not ctx.out.json:
        pct = f'{result["userFraction"] * 100:g}%' if result.get('userFraction') else '100%'
        ctx.out.line(f'{result["track"]}: versionCode {", ".join(result["versionCodes"])} '
                     f'{result["status"]} {pct}' + (' (dry run, nothing committed)' if ctx.dry_run else ''))
    return dict(result, dry_run=ctx.dry_run)


@command('rules', 'Deploy Firestore rules and indexes', risk='publish', needs=('firebase',))
def rules(ctx, args):
    targets = firebase.deploy_targets(ctx)
    project = firebase.project_id(ctx)
    safety.confirm(ctx, f'Deploy {", ".join(targets)} to Firebase project {project}')
    if ctx.dry_run:
        ctx.out.line(f'dry run: would deploy {", ".join(targets)} to {project}')
        return {'project': project, 'targets': targets, 'dry_run': True}
    ctx.out.start(f'{ctx.project.name} rules', 1, project)
    ctx.out.step('Deploy ' + ', '.join(targets))
    firebase.deploy_rules(ctx)
    ctx.out.done()
    ctx.out.finish(f'live on {project}')
    return {'project': project, 'targets': targets}


group('config', 'the in-app update document (config/app)')


@command('config show', 'Show the in-app update document', risk='read', needs=('firebase',))
def config_show(ctx, args):
    path = firebase.update_doc_path(ctx)
    doc = firebase.get_document(ctx, path)
    if not ctx.out.json:
        ctx.out.heading(f'{firebase.project_id(ctx)}/{path}')
        for k, v in sorted(doc.items()):
            ctx.out.line(f'  {k:18} {v}')
        if not doc:
            ctx.out.line('  (no document yet)')
    return {'path': path, 'document': doc}


@command('config set', 'Write the in-app update document: latest version, block old builds, nudge delay',
         risk='publish', needs=('firebase',),
         args=(Arg('latest', 'publish the current version as the latest', kind='flag'),
               Arg('latest_build', 'set latestBuild explicitly (e.g. what Play already has)', type=int),
               Arg('latest_version_name', 'set latestVersionName explicitly, with --latest-build'),
               Arg('min_supported_build', 'block every build below this versionCode (0 = none)', type=int),
               Arg('nudge_after_days', 'days an update must be known before the app mentions it', type=int)),
         examples=('mkit config set --latest', 'mkit config set --latest-build 12 --latest-version-name 1.2.0',
                   'mkit config set --min-supported-build 42',
                   'mkit config set --min-supported-build 0'))
def config_set(ctx, args):
    values = {}
    if args.latest:
        name, code = kinds.for_project(ctx.project).current_version()
        values.update(latestBuild=code, latestVersionName=name)
    if (args.latest_build is None) != (args.latest_version_name is None):
        raise UsageError('pass --latest-build and --latest-version-name together')
    if args.latest_build is not None:
        values.update(latestBuild=args.latest_build, latestVersionName=args.latest_version_name)
    if args.min_supported_build is not None:
        values['minSupportedBuild'] = args.min_supported_build
    if args.nudge_after_days is not None:
        values['nudgeAfterDays'] = args.nudge_after_days
    if not values:
        raise UsageError('nothing to set; pass --latest, --latest-build/--latest-version-name, '
                         '--min-supported-build or --nudge-after-days')
    path = firebase.update_doc_path(ctx)
    safety.confirm(ctx, f'Write {path} in {firebase.project_id(ctx)}',
                   [f'{k} = {v}' for k, v in values.items()])
    if ctx.dry_run:
        return {'path': path, 'would_set': values, 'dry_run': True}
    from datetime import datetime, timezone
    firebase.patch_document(ctx, path, dict(values, updatedAt=datetime.now(timezone.utc)))
    if not ctx.out.json:
        ctx.out.line(f'{path}: ' + ', '.join(f'{k}={v}' for k, v in values.items()), 'green')
    return {'path': path, 'set': values}
