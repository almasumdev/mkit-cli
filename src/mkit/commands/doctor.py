"""`mkit doctor`: what this project uses, and whether each part can work.

Every feature in mkit.toml is shown as one of:

    on       switched on and everything it needs is present
    broken   switched on but a credential or tool is missing; steps using it
             are skipped in pipelines and fail when asked for directly
    off      not in mkit.toml; this app does not use it

Credentials are opened and parsed, and the non-secret parts (the service
account email and its Cloud project) are shown, because "the key is there but
it belongs to another project" is the mistake worth catching early.
"""
import os
import platform
import shutil
import sys
from pathlib import Path

from .. import __version__, config
from ..errors import FAILED, MkitError
from ..registry import command

# feature -> credentials it cannot work without
FEATURE_CREDENTIALS = {
    'play': ('PLAY_SERVICE_ACCOUNT',),
    'firebase': ('FIREBASE_SERVICE_ACCOUNT',),
    'notify.telegram': ('TELEGRAM',),
}

FEATURE_WHAT = {
    'play': 'Google Play: upload, tracks, listing, products, reviews, vitals',
    'store': 'store listing, art, what\'s new and data safety files',
    'firebase': 'Firestore rules, update doc, Remote Config, symbols',
    'notify.telegram': 'Telegram message after deploy and promote',
    'aso': 'keyword rank and winnability checks',
    'hooks': 'project-specific scripts at fixed pipeline points',
}


def sdk_dir(project=None):
    for key in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        if os.environ.get(key):
            return Path(os.environ[key])
    if project:
        for props in (project.root / 'local.properties', project.root / 'android' / 'local.properties'):
            if props.is_file():
                for line in props.read_text(encoding='utf-8', errors='replace').splitlines():
                    if line.startswith('sdk.dir='):
                        return Path(line[8:].replace('\\:', ':').replace('\\\\', '\\'))
    guess = Path.home() / ('AppData/Local/Android/Sdk' if os.name == 'nt' else 'Android/Sdk')
    return guess if guess.is_dir() else None


def find_tool(name, project=None):
    if name == 'adb':
        # The SDK's adb first: other tools (scrcpy, phone suites) ship their own
        # adb on PATH, and two adb versions keep killing each other's server.
        sdk = sdk_dir(project)
        if sdk:
            exe = sdk / 'platform-tools' / ('adb.exe' if os.name == 'nt' else 'adb')
            if exe.is_file():
                return str(exe)
    return shutil.which(name)


def _credential(ctx, name):
    source = ctx.secrets.source(name)
    if not source:
        return {'name': name, 'status': 'missing'}
    try:
        data = ctx.secrets.json(name)
    except MkitError as e:
        return {'name': name, 'status': 'unreadable', 'source': source, 'error': e.message}
    info = {'name': name, 'status': 'ok', 'source': source}
    for key in ('client_email', 'project_id'):
        if data.get(key):
            info[key] = data[key]
    if name == 'TELEGRAM' and not (data.get('bot_token') and data.get('chat_id')):
        info.update(status='unreadable', error='needs bot_token and chat_id')
    return info


@command('doctor', 'Check tools, settings and credentials for this project', risk='read',
         needs_project=False, examples=('mkit doctor', 'mkit doctor --json'))
def doctor(ctx, args):
    out = ctx.out
    project = ctx.project
    report = {
        'engine': {'version': __version__, 'python': platform.python_version(),
                   'executable': sys.executable, 'home': str(config.home())},
        'project': None, 'tools': [], 'features': [], 'problems': [],
    }

    if project is None:
        report['problems'].append('no mkit.toml here or above; run `mkit init` in the app folder')
    else:
        report['project'] = {'root': str(project.root), 'name': project.name,
                             'kind': project.kind, 'package': project.package}
        for key in ('app.kind', 'app.package'):
            if not project.get(key):
                report['problems'].append(f'{key} is not set in mkit.toml')

    wanted = ['git', 'adb']
    if project and project.kind == 'flutter':
        wanted.append('flutter')
    if project and project.section('firebase').get('rules'):
        wanted.append('firebase')
    for tool in wanted:
        path = find_tool(tool, project)
        report['tools'].append({'name': tool, 'path': path, 'status': 'ok' if path else 'missing'})
        if not path:
            report['problems'].append(f'{tool} not found on PATH')

    if project:
        for feature in config.FEATURES:
            entry = {'feature': feature, 'what': FEATURE_WHAT.get(feature, ''), 'credentials': []}
            if not project.has(feature):
                entry['status'] = 'off'
            else:
                creds = [_credential(ctx, n) for n in FEATURE_CREDENTIALS.get(feature, ())]
                entry['credentials'] = creds
                bad = [c for c in creds if c['status'] != 'ok']
                entry['status'] = 'broken' if bad else 'on'
                for c in bad:
                    report['problems'].append(
                        f'[{feature}] {c["name"]} is {c["status"]}'
                        + (f': {c["error"]}' if c.get('error') else
                           f'; add MKIT_{c["name"]}_JSON_BASE64 to .env'))
            report['features'].append(entry)

    if not out.json:
        _print_report(out, report)
    if report['problems']:
        ctx.exit_code = FAILED
    return report


def _print_report(out, report):
    eng = report['engine']
    out.heading(f'mkit {eng["version"]}')
    out.line(f'  python {eng["python"]}   user settings {eng["home"]}', 'dim')
    proj = report['project']
    if proj:
        out.heading(f'{proj["name"]}   {proj["kind"] or "?"}   {proj["package"] or "?"}')
        out.line(f'  {proj["root"]}', 'dim')
    out.heading('tools')
    out.table([(t['name'], t['status'], t['path'] or '') for t in report['tools']],
              ('tool', 'status', 'path'))
    if report['features']:
        out.heading('features')
        rows = []
        for f in report['features']:
            creds = ', '.join(
                f'{c["name"]}: {c["status"]}' + (f' ({c["client_email"]})' if c.get('client_email') else '')
                for c in f['credentials'])
            rows.append((f['feature'], f['status'], creds or f['what']))
        out.table(rows, ('feature', 'status', 'details'))
    out.line()
    if report['problems']:
        out.line(f'{len(report["problems"])} problem(s):', 'yellow')
        for p in report['problems']:
            out.line(f'  - {p}', 'yellow')
    else:
        out.line('All good.', 'green')
