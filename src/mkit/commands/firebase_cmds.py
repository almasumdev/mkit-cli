"""Remote Config, Firebase app settings, internal app sharing."""
import json
import os
import subprocess
from pathlib import Path

from .. import kinds, safety, toolchain
from ..cloud import auth, fbproject
from ..errors import DRIFT, MkitError, UsageError
from ..registry import Arg, command, group

group('remoteconfig', 'Firebase Remote Config template')
group('firebase', 'Firebase app settings (SHA fingerprints, google-services.json)')


@command('remoteconfig pull', 'Save the live Remote Config template to the template file', risk='write',
         needs=('firebase',))
def rc_pull(ctx, args):
    template, etag = fbproject.rc_get(ctx)
    path = fbproject.template_path(ctx)
    body = {k: template[k] for k in fbproject.TEMPLATE_KEYS if k in template}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    version = template.get('version', {}).get('versionNumber')
    if not ctx.out.json:
        ctx.out.line(f'version {version}: {len(body.get("parameters", {}))} parameter(s) -> {path}')
    return {'file': str(path), 'version': version}


@command('remoteconfig plan', 'Compare the template file with the live Remote Config', risk='plan',
         needs=('firebase',))
def rc_plan(ctx, args):
    remote, _ = fbproject.rc_get(ctx)
    changes = fbproject.rc_diff(remote, fbproject.local_template(ctx))
    if not ctx.out.json:
        for c in changes:
            ctx.out.line(f'  {c["change"]:7} {c["parameter"]}')
        if not changes:
            ctx.out.line('  no changes', 'green')
    if changes:
        ctx.exit_code = DRIFT
    return {'version': remote.get('version', {}).get('versionNumber'), 'changes': changes}


@command('remoteconfig apply', 'Publish the template file as the live Remote Config', risk='publish',
         needs=('firebase',))
def rc_apply(ctx, args):
    remote, etag = fbproject.rc_get(ctx)
    local = fbproject.local_template(ctx)
    changes = fbproject.rc_diff(remote, local)
    if not changes:
        return {'changes': [], 'changed': False}
    safety.confirm(ctx, f'Publish Remote Config ({len(changes)} change(s)) to {fbproject.project_id(ctx)}',
                   [f'{c["change"]} {c["parameter"]}' for c in changes])
    version = fbproject.rc_publish(ctx, local, etag, validate_only=ctx.dry_run)
    if not ctx.out.json:
        ctx.out.line('validated, not published (dry run)' if ctx.dry_run
                     else f'published version {version.get("versionNumber")}', 'green')
    return {'changes': changes, 'changed': not ctx.dry_run, 'version': version.get('versionNumber')}


@command('remoteconfig versions', 'Recent Remote Config versions', risk='read', needs=('firebase',),
         args=(Arg('limit', 'how many', type=int, default=10),))
def rc_versions(ctx, args):
    versions = fbproject.rc_versions(ctx, args.limit)
    if not ctx.out.json:
        ctx.out.table([(v.get('versionNumber'), v.get('updateTime', '')[:19], v.get('updateType', ''),
                        (v.get('updateUser') or {}).get('email', ''), v.get('description', ''))
                       for v in versions], ('version', 'time', 'type', 'by', 'description'))
    return {'versions': versions}


@command('remoteconfig rollback', 'Make an earlier Remote Config version live again', risk='publish',
         needs=('firebase',), args=(Arg('version', 'version number', kind='positional', type=int),))
def rc_rollback(ctx, args):
    safety.confirm(ctx, f'Roll Remote Config back to version {args.version}')
    if ctx.dry_run:
        return {'version': args.version, 'dry_run': True}
    version = fbproject.rc_rollback(ctx, args.version)
    return {'version': version.get('versionNumber'), 'rolledBackTo': args.version}


@command('firebase sha', 'SHA fingerprints registered for this app in Firebase', risk='read',
         needs=('firebase',))
def fb_sha(ctx, args):
    app, certs = fbproject.sha_list(ctx)
    if not ctx.out.json:
        ctx.out.line(f'{app.get("displayName") or app["packageName"]}  ({app["appId"]})', 'bold')
        for c in certs:
            ctx.out.line(f'  {c.get("certType")}  {c.get("shaHash")}')
        ctx.out.line('Add the Play App Signing key too: Play Console > Setup > App signing.', 'dim')
    return {'appId': app['appId'], 'certificates': certs}


@command('firebase sha-add', 'Register a signing SHA-1/SHA-256 with Firebase (then pull the config)',
         risk='write', needs=('firebase',), args=(Arg('sha', 'fingerprint, with or without colons', kind='positional'),))
def fb_sha_add(ctx, args):
    result = fbproject.sha_add(ctx, args.sha)
    if not ctx.out.json:
        ctx.out.line(('added ' if result['changed'] else 'already registered: ') + result['certType'])
    return result


def _write_config(ctx, out=None):
    """Pull google-services.json into the app module. It lists every Android app
    in the project, so it carries the debug client too once that exists."""
    text = fbproject.config_file(ctx)
    kind = kinds.for_project(ctx.project)
    module_dir = kind.android_dir / ('app' if ctx.project.kind == 'flutter' else kind.module)
    path = ctx.project.root / out if out else module_dir / 'google-services.json'
    changed = not path.is_file() or path.read_text(encoding='utf-8') != text
    if changed:
        path.write_text(text, encoding='utf-8')
    return path, changed


@command('firebase config', 'Download google-services.json for this app', risk='write', needs=('firebase',),
         args=(Arg('out', 'where to write it (default: the Android app module)'),))
def fb_config(ctx, args):
    path, changed = _write_config(ctx, args.out)
    if not ctx.out.json:
        ctx.out.line(f'{"wrote" if changed else "unchanged"} {path}')
    return {'file': str(path), 'changed': changed}


def _debug_key_fingerprints(ctx):
    """SHA-1 and SHA-256 of this computer's Android debug key, or {} without one."""
    keystore = Path.home() / '.android' / 'debug.keystore'
    if not keystore.is_file():
        return {}
    jdk = Path(toolchain.find_jdk(ctx.project))
    keytool = jdk / 'bin' / ('keytool.exe' if os.name == 'nt' else 'keytool')
    result = subprocess.run([str(keytool), '-list', '-v', '-keystore', str(keystore),
                             '-alias', 'androiddebugkey', '-storepass', 'android', '-keypass', 'android'],
                            capture_output=True, text=True, timeout=60)
    return fbproject.parse_fingerprints(result.stdout) if result.returncode == 0 else {}


@command('firebase debug-app', "Register the debug build's package with Firebase, then pull the config",
         risk='write', needs=('firebase',),
         description='For a debug build type with an applicationIdSuffix: Firebase, and the '
                     'google-services Gradle plugin, only accept packages registered in the '
                     "project. Registers it when missing, adds this computer's debug key "
                     '(SHA-1 and SHA-256, for Google sign-in) and writes google-services.json. '
                     'Safe to run again.')
def fb_debug_app(ctx, args):
    out, project = ctx.out, ctx.project
    package = kinds.for_project(project).debug_package()
    if package == project.package:
        raise UsageError(f'debug builds install as {package}, the store package, so there is nothing '
                         'to register',
                         hint='Give the debug build type an applicationIdSuffix (".debug") first.',
                         code='NO_DEBUG_SUFFIX')
    app, created = fbproject.ensure_android_app(ctx, package, f'{project.name} (debug)')
    certificates = []
    for cert_type, sha in _debug_key_fingerprints(ctx).items():
        certificates.append(fbproject.sha_add(ctx, sha, package))
    path, changed = _write_config(ctx)
    if not out.json:
        out.line(f'{"registered" if created else "already registered"} {package}')
        for c in certificates:
            out.line(f'  {c["certType"]} {"added" if c["changed"] else "already there"}')
        if not certificates:
            out.line('  no debug key found in ~/.android; Google sign-in in debug builds needs one', 'dim')
        out.line(f'{"wrote" if changed else "unchanged"} {path}')
    return {'package': package, 'appId': app.get('appId'), 'created': created,
            'certificates': certificates, 'file': str(path), 'config_changed': changed}


@command('share', 'Build the release bundle and get an internal app sharing link', risk='write',
         needs=('play',), args=(Arg('no_build', 'upload the bundle already built', kind='flag'),))
def share(ctx, args):
    kind = kinds.for_project(ctx.project)
    out = ctx.out
    out.start(f'{ctx.project.name} share', 2, 'internal app sharing')
    out.step('Build release bundle')
    if not args.no_build:
        jdk = toolchain.find_jdk(ctx.project)
        kind.bundle(dict(os.environ, JAVA_HOME=jdk))
    module = kind.modules()[0]
    if not module.aab.is_file():
        raise MkitError(f'no bundle at {module.aab}', code='NO_BUNDLE')
    out.done(f'{module.aab.stat().st_size / 1_000_000:.1f} MB')
    out.step('Upload')
    from googleapiclient.http import MediaFileUpload
    svc = auth.play(ctx)
    try:
        result = svc.internalappsharingartifacts().uploadbundle(
            packageName=ctx.project.package,
            media_body=MediaFileUpload(str(module.aab), mimetype='application/octet-stream')).execute()
    except Exception as e:
        raise auth.translate(e, 'Play') from None
    out.done()
    out.finish(result.get('downloadUrl', ''))
    return {'downloadUrl': result.get('downloadUrl'), 'sha256': result.get('sha256')}
