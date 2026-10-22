"""Everyday development: run on a device, emulators, logs, version bump."""
import os
import sys

from .. import device as dev
from .. import kinds, proc, toolchain
from ..errors import UsageError
from ..git import BUMP_PREFIX, Repo
from ..registry import Arg, command

DEVICE_ARG = Arg('device', 'adb serial to use when several are attached')


def default_log_tags(project):
    tags = project.get('app.log_tags')
    if tags is not None:
        return list(tags)
    return ['flutter:V', 'AndroidRuntime:E'] if project.kind == 'flutter' else []


@command('run', 'Build, install and launch the app on a device', risk='read',
         args=(Arg('phone', 'use a physical phone', kind='flag', short='p'),
               Arg('emulator', 'use a running emulator', kind='flag', short='e'),
               Arg('clean', 'first-install state: uninstall for every user and wipe backup first',
                   kind='flag', short='c'),
               Arg('test', "run the project's tests on the device instead", kind='flag', short='t'),
               Arg('release', 'build the release variant', kind='flag', short='r'),
               Arg('logs', "native apps: follow this app's logcat afterwards "
                           "(Shift+R rebuilds, installs and restarts)", kind='flag', short='l'),
               Arg('install', 'Flutter apps: build, install and open without attaching '
                              '(no hot reload); used automatically when not at a terminal', kind='flag'),
               DEVICE_ARG),
         examples=('mkit run', 'mkit run -p', 'mkit run -c -p', 'mkit run -r', 'mkit run -t',
                   'mkit run --install -l'),
         description='Flutter apps run through `flutter run`: r hot reload, R hot restart, q quit, '
                     'logs in the same terminal. Native apps are built with Gradle, installed and '
                     'opened; -l then follows logcat, where Shift+R builds and installs the '
                     'current code and restarts the app.')
def run(ctx, args):
    if args.phone and args.emulator:
        raise UsageError('pass only one of -p or -e')
    out, project = ctx.out, ctx.project
    kind = kinds.for_project(project)
    adb = dev.Adb(project.root)
    serial = dev.pick(adb, 'phone' if args.phone else 'emulator' if args.emulator else None, args.device)
    env = dict(os.environ, ANDROID_SERIAL=serial)
    model = adb.model(serial)
    variant = 'release' if args.release else 'debug'
    package = kind.installed_package(args.release)
    if not args.release and package == project.package:
        # Same id as the store build, and a different signature: Android can
        # only install one over the other by removing it, data and all.
        out.warn(f'debug builds install as {package}, the same package as the Play app, so '
                 'installing replaces it. Give the debug build type an applicationIdSuffix '
                 '(".debug") to keep both.')

    # flutter run stays attached to the terminal, so it is only for a person
    # at one; an agent's shell gets the install-and-open path instead.
    attached = not out.json and sys.stdin.isatty()
    if project.kind == 'flutter' and not args.test and not args.install and attached:
        if args.clean:
            dev.clean_state(adb, serial, package)
        out.line(f'flutter run on {model} ({serial})   r hot reload, R hot restart, q quit', 'bold')
        ctx.exit_code = proc.interactive(
            [toolchain.tool('flutter'), 'run', '-d', serial] + (['--release'] if args.release else []),
            cwd=project.root, env=env)
        return {'device': serial, 'flutter_run': True}

    if args.test:
        toolchain.find_jdk(project)
        env.update({k: os.environ[k] for k in ('JAVA_HOME', 'ANDROID_HOME') if k in os.environ})
        out.line(f'testing on {model} ({serial})', 'bold')
        ctx.exit_code = kind.test(serial, env)
        return {'device': serial, 'tests': 'passed' if ctx.exit_code == 0 else 'failed'}

    steps = 4 if args.clean else 3
    out.start(f'{project.name} run', steps, f'{variant} on {model}')
    out.step(f'Build {variant} APK')
    toolchain.find_jdk(project)
    env.update({k: os.environ[k] for k in ('JAVA_HOME', 'ANDROID_HOME') if k in os.environ})
    package, apk = kind.assemble(variant, env)
    out.done(f'{apk.stat().st_size / 1_000_000:.1f} MB')

    if args.clean:
        out.step('Clean install state')
        removed, transports = dev.clean_state(adb, serial, package)
        out.done(f'removed for {removed} user(s), backup wiped on {transports} transport(s)'
                 if removed or transports else 'nothing installed')

    def install(built):
        result = adb('install', '-r', str(built), device=serial, timeout=600)
        if 'Success' not in result:
            raise UsageError(f'install failed: {result.strip()[-300:]}', code='INSTALL_FAILED',
                             hint='If the signatures differ, uninstall the app first (mkit run -c).')

    out.step('Install')
    install(apk)
    out.done(package)

    out.step('Launch')
    component = dev.launch(adb, serial, package)
    out.done(component)
    out.finish(f'{package} running on {model}')
    if args.logs:
        def rebuild():
            """What Shift+R does: the same build and install this command just did.

            Shift+R used to relaunch whatever was already installed, so somebody who had edited
            a file and pressed it watched the log of the code they had changed away from, with
            nothing on screen saying why it had not taken.
            """
            _, built = kind.assemble(variant, env)
            install(built)

        dev.follow_logs(adb, serial, package, default_log_tags(project), rebuild=rebuild)
    return {'device': serial, 'model': model, 'package': package, 'variant': variant, 'apk': str(apk)}


@command('devices', 'List attached devices and emulators', risk='read', needs_project=False)
def devices(ctx, args):
    adb = dev.Adb(ctx.project.root if ctx.project else None)
    rows = [{'serial': s, 'state': st, 'type': 'emulator' if dev.is_emulator(s) else 'phone',
             'model': adb.model(s) if st == 'device' else ''} for s, st in adb.devices()]
    if not ctx.out.json:
        if rows:
            ctx.out.table([(r['serial'], r['type'], r['state'], r['model']) for r in rows],
                          ('serial', 'type', 'state', 'model'))
        else:
            ctx.out.line('no devices attached')
    return {'devices': rows}


@command('logs', "Follow the app's logcat (Shift+R restarts the app)", risk='read',
         args=(DEVICE_ARG, Arg('all', "the whole device log, not just this app's", kind='flag'),
               Arg('release', 'the release (Play) install instead of the debug one',
                   kind='flag', short='r')),
         description='Follows the debug install by default, the same one `mkit run` puts on the '
                     'device; Shift+R restarts that app. -r switches to the release install.')
def logs(ctx, args):
    adb = dev.Adb(ctx.project.root)
    serial = dev.pick(adb, None, args.device)
    # The debug install unless asked: it is the one being developed, and the
    # store package used to be restarted by Shift+R here instead.
    package = kinds.for_project(ctx.project).installed_package(args.release)
    dev.follow_logs(adb, serial, package, default_log_tags(ctx.project), everything=args.all)
    return {'device': serial, 'package': package}


@command('emu', 'Start an Android emulator (cold boot) and wait for it', risk='read',
         needs_project=False,
         args=(Arg('avd', 'emulator name (default: ask, or the only one)', kind='positional', nargs='?'),
               Arg('list', 'only list the emulators', kind='flag')),
         examples=('mkit emu', 'mkit emu Pixel_8_API_35', 'mkit emu --list'))
def emu(ctx, args):
    root = ctx.project.root if ctx.project else None
    exe, names = dev.avds(root)
    out = ctx.out
    if args.list or not names:
        if not out.json:
            for n in names:
                out.line(f'  {n}')
            if not names:
                out.line("no emulators; create one in Android Studio's Device Manager")
        return {'avds': names}
    if args.avd:
        if args.avd not in names:
            raise UsageError(f'unknown emulator "{args.avd}"; have: {", ".join(names)}')
        avd = args.avd
    elif len(names) == 1 or out.json:
        avd = names[0]
    else:
        for i, n in enumerate(names, 1):
            out.line(f'  {i}) {n}')
        choice = input(f'\nWhich one? (1-{len(names)}, Enter for 1) ').strip() or '1'
        try:
            avd = names[int(choice) - 1]
        except (ValueError, IndexError):
            raise UsageError(f'not one of the choices: {choice}') from None
    out.start('emulator', 1, avd)
    out.step(f'Boot {avd}')
    serial = dev.start_emulator(dev.Adb(root), exe, avd, root)
    out.done(serial)
    out.finish(f'{avd} ready')
    return {'avd': avd, 'serial': serial}


@command('studio', 'Open this app in Android Studio', risk='read',
         args=(Arg('android', 'Flutter apps: open the android/ Gradle project instead',
                   kind='flag', short='a', long=False),),
         examples=('mkit studio', 'mkit studio -a'),
         description="Opens the folder Android Studio should have: the repo root for a Flutter "
                     "app, where the Flutter plugin gives Dart analysis, hot reload and the "
                     "device list, with android/ indexed underneath. -a opens android/ on its "
                     "own instead, a plain Gradle project for native work (manifests, AGP, "
                     "Gradle plugins) with no Dart support. Native apps open at their Gradle "
                     "root either way. Studio is left running when mkit exits.")
def studio(ctx, args):
    project = ctx.project
    kind = kinds.for_project(project)
    folder = kind.android_dir if args.android else project.root
    exe = toolchain.studio(project)
    if ctx.dry_run:
        if not ctx.out.json:
            ctx.out.line(f'would open {folder} in {exe}')
        return {'folder': str(folder), 'studio': exe, 'pid': None, 'dry_run': True}
    pid = proc.detach([exe, str(folder)], cwd=project.root)
    if not ctx.out.json:
        where = folder if folder == project.root else folder.relative_to(project.root)
        ctx.out.line(f'Android Studio opening {where}')
    return {'folder': str(folder), 'studio': exe, 'pid': pid}


@command('version', "Show this app's version, as the version file has it", risk='read')
def version(ctx, args):
    kind = kinds.for_project(ctx.project)
    name, code = kind.current_version()
    if not ctx.out.json:
        ctx.out.line(f'{name} ({code})   {kind.version.path.relative_to(ctx.project.root)}')
    return {'versionName': name, 'versionCode': code, 'file': str(kind.version.path)}


@command('bump', 'Bump the version name and code (and commit it, unless --no-commit)', risk='write',
         args=(Arg('level', 'which part of the name', kind='positional', nargs='?',
                   choices=('major', 'minor', 'patch'), default='patch'),
               Arg('no_commit', 'change the file only', kind='flag')),
         examples=('mkit bump', 'mkit bump minor', 'mkit bump --no-commit', 'mkit bump --dry-run'),
         dry_run=True)
def bump(ctx, args):
    kind = kinds.for_project(ctx.project)
    if ctx.dry_run:
        # The same arithmetic kind.bump does, without touching the file: the
        # name moves by the level, the code by exactly one.
        old_name, old_code = kind.current_version()
        name, code = kinds.bump_name(old_name, args.level), old_code + 1
        if not ctx.out.json:
            ctx.out.line(f'{old_name} ({old_code}) -> {name} ({code})   dry run: nothing written')
        return {'from': {'versionName': old_name, 'versionCode': old_code},
                'to': {'versionName': name, 'versionCode': code}, 'commit': None, 'dry_run': True}
    old_name, old_code, name, code = kind.bump(args.level)
    committed = None
    if not args.no_commit:
        repo = Repo(ctx.project.root)
        committed = repo.commit_files([kind.version.path],
                                      f'{BUMP_PREFIX}{name} (versionCode {code})')[:8]
    if not ctx.out.json:
        ctx.out.line(f'{old_name} ({old_code}) -> {name} ({code})' + (f'   commit {committed}' if committed else ''))
    return {'from': {'versionName': old_name, 'versionCode': old_code},
            'to': {'versionName': name, 'versionCode': code}, 'commit': committed}


@command('gradle', "Run Gradle tasks with the right JDK and folder (lint, clean, test, profiles...)",
         risk='write',
         args=(Arg('tasks', 'Gradle tasks and flags, passed through as-is', kind='positional', nargs='...'),),
         examples=('mkit gradle :app:lintDebug', 'mkit gradle clean', 'mkit gradle :app:testDebugUnitTest',
                   'mkit gradle :app:generateBaselineProfile'))
def gradle(ctx, args):
    """Anything a project did through Gradle before, with the JDK mkit picks and
    from the Gradle root (android/ for Flutter apps). Output streams as-is."""
    if not args.tasks:
        raise UsageError('name at least one Gradle task, e.g. mkit gradle :app:lintDebug')
    kind = kinds.for_project(ctx.project)
    jdk = toolchain.find_jdk(ctx.project)
    env = dict(os.environ, JAVA_HOME=jdk)
    ctx.exit_code = proc.interactive([toolchain.gradlew(kind.android_dir), *args.tasks],
                                     cwd=kind.android_dir, env=env)
    return {'tasks': args.tasks, 'exit': ctx.exit_code}
