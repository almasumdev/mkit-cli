"""`mkit init`: link an app folder to the engine.

Writes three small files and nothing else:

    mkit.toml        settings, detected from the project, committed
    mkit.ps1         PowerShell launcher (./mkit): one Ctrl+C stops it
    mkit.bat         cmd launcher: runs the installed engine on this folder
    mkit.sh          macOS/Linux launcher, same thing

and makes sure `.env` (this app's secrets) is gitignored. Existing files are
left alone unless --force is given.
"""
import re
from pathlib import Path

from .. import __version__
from ..errors import UsageError
from ..registry import Arg, command

# No < > | & here: the text is echoed by cmd.exe, which reads those as redirects.
# The engine that writes a new mkit.toml is the oldest one known to read it.
REQUIRES = '.'.join(__version__.split('.')[:2])

INSTALL_HINT = 'Install it with: uv tool install mkit-cli  (or pipx install mkit-cli)'

# mkit.exe by full name: plain `mkit` from inside mkit.bat can resolve to this
# very file (cmd searches the current folder first) and call itself forever.
BAT = f'''@echo off
where mkit.exe >nul 2>nul || (echo mkit is not installed. {INSTALL_HINT} 1>&2 & exit /b 9009)
mkit.exe --project "%~dp0." %*
'''

# PowerShell runs .\mkit.ps1 ahead of .\mkit.bat for `./mkit`, and a script,
# unlike a batch file, stops on one Ctrl+C: cmd's "Terminate batch job (Y/N)?"
# only exists for .bat/.cmd.
PS1 = f'''# mkit launcher for PowerShell: ./mkit run
if (-not (Get-Command mkit.exe -ErrorAction SilentlyContinue)) {{
    Write-Error 'mkit is not installed. {INSTALL_HINT}'
    exit 9009
}}
& mkit.exe --project $PSScriptRoot @args
exit $LASTEXITCODE
'''

SH = f'''#!/usr/bin/env sh
set -eu
command -v mkit >/dev/null 2>&1 || {{ echo "mkit is not installed. {INSTALL_HINT}" >&2; exit 127; }}
exec mkit --project "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" "$@"
'''

_APP_ID = re.compile(r'''applicationId\s*=?\s*["']([\w.]+)["']''')


def _read(path):
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def detect(root):
    """(kind, package, name) guessed from the files present; any may be None."""
    root = Path(root)
    if (root / 'pubspec.yaml').is_file():
        kind = 'flutter'
        gradle_dir = root / 'android' / 'app'
        m = re.search(r'^name:\s*(\S+)', _read(root / 'pubspec.yaml'), re.M)
        name = m.group(1).replace('_', ' ').title().replace(' ', '') if m else None
    else:
        gradle_dir = root / 'app'
        wear = (root / 'wear').is_dir() and any((root / 'wear' / f).is_file()
                                                for f in ('build.gradle.kts', 'build.gradle'))
        kind = 'android-wear' if wear else 'android'
        name = None
        for settings in ('settings.gradle.kts', 'settings.gradle'):
            m = re.search(r'rootProject\.name\s*=\s*["\']([^"\']+)', _read(root / settings))
            if m:
                name = m.group(1)
                break
    package = None
    for f in ('build.gradle.kts', 'build.gradle'):
        m = _APP_ID.search(_read(gradle_dir / f))
        if m:
            package = m.group(1)
            break
    if not (gradle_dir / 'build.gradle.kts').is_file() and not (gradle_dir / 'build.gradle').is_file():
        kind = kind if kind == 'flutter' else None
    return kind, package, name or root.name


def render_toml(name, kind, package):
    return f'''# mkit settings for {name}. Secrets never go here: they live in .env
# (this app) and ~/.mkit/.env (all apps). `mkit doctor` checks everything.
requires = ">={REQUIRES}"

[app]
name     = "{name}"
kind     = "{kind}"            # flutter | android | android-wear
package  = "{package}"
activity = ".MainActivity"

# A table switches a feature on. Leave one out and every step that uses it is
# skipped quietly, because this app does not use it.

# [play]
# internal_testing_url = ""

# [store]
# listing_dir  = "store/listing"      # everything the store shows lives under store/
# art_dir      = "store"
# icon         = "android/app/src/main/ic_launcher-playstore.png"
# whatsnew_dir = "distribution/whatsnew"

# [firebase]
# rules      = true
# update_doc = "config/app"

# [notify.telegram]
'''


ENV_TEMPLATE = """\
# Secrets for this app. Gitignored, and never committed - `mkit doctor` names
# the key it wants when one is missing, and prints none of them.
#
# Each is the service account JSON, base64 encoded, on one line:
#   Windows : [Convert]::ToBase64String([IO.File]::ReadAllBytes("key.json"))
#   macOS   : base64 -i key.json
#   Linux   : base64 -w0 key.json
#
# Anything every app shares goes in ~/.mkit/.env instead of here.

# Google Play, for releases, the listing, products, reviews and vitals.
# Play Console > Users and permissions, invite the service account.
# MKIT_PLAY_SERVICE_ACCOUNT_JSON_BASE64=

# Firebase, for Firestore rules, Remote Config and the update document.
# Project settings > Service accounts > Generate new private key.
# MKIT_FIREBASE_SERVICE_ACCOUNT_JSON_BASE64=

# A Telegram bot, if this app sends a message after a release.
# {"bot_token": "...", "chat_id": 123}, base64 encoded.
# MKIT_TELEGRAM_JSON_BASE64=
"""


def _ensure_gitignored(root, entry='.env'):
    gi = root / '.gitignore'
    text = _read(gi)
    lines = [l.strip() for l in text.splitlines()]
    if entry in lines or f'/{entry}' in lines:
        return False
    with open(gi, 'a', encoding='utf-8', newline='\n') as f:
        if text and not text.endswith('\n'):
            f.write('\n')
        f.write(f'\n# mkit: this app\'s secrets\n{entry}\n')
    return True


@command('init', 'Link this app folder to mkit (mkit.toml + launchers)', risk='write',
         needs_project=False,
         args=(Arg('path', 'app folder (default: current folder)', kind='positional', nargs='?'),
               Arg('kind', 'override the detected kind', choices=('flutter', 'android', 'android-wear')),
               Arg('package', 'override the detected package id'),
               Arg('name', 'override the detected app name'),
               Arg('force', 'overwrite existing mkit.toml and launchers', kind='flag')),
         examples=('mkit init', 'mkit init H:/flutter/onGoing/listkin --name Listkin'))
def init(ctx, args):
    root = Path(args.path or '.').resolve()
    if not root.is_dir():
        raise UsageError(f'{root} is not a folder')
    kind, package, name = detect(root)
    kind = args.kind or kind
    package = args.package or package
    name = args.name or name
    if not kind:
        raise UsageError(f'could not tell what kind of app {root} is',
                         hint='Pass --kind flutter|android|android-wear.')

    written, kept = [], []
    files = {'mkit.toml': render_toml(name, kind, package or ''), 'mkit.bat': BAT, 'mkit.ps1': PS1,
             'mkit.sh': SH}
    # The .env is the step everybody gets stuck on: which keys, in what format,
    # from where. A commented skeleton answers all three in the folder where it
    # is needed. It is never replaced, not even with --force: that file holds
    # the only copy of somebody's credentials.
    if not (root / '.env').exists():
        files['.env'] = ENV_TEMPLATE
    else:
        kept.append('.env (exists; left alone)')
    for fname, content in files.items():
        target = root / fname
        if target.exists() and not args.force:
            kept.append(fname)
            continue
        newline = '\r\n' if fname.endswith('.bat') else '\n'
        with open(target, 'w', encoding='utf-8', newline=newline) as f:
            f.write(content)
        written.append(fname)
    if _ensure_gitignored(root):
        written.append('.gitignore (.env)')

    out = ctx.out
    if not out.json:
        out.heading(f'{name}   {kind}   {package or "package not found"}')
        for f in written:
            out.line(f'  wrote {f}', 'green')
        for f in kept:
            out.line(f'  kept  {f} (exists; --force to replace)', 'dim')
        out.line()
        out.line('Next: add secrets to .env, switch features on in mkit.toml, then `mkit doctor`.')
    return {'root': str(root), 'kind': kind, 'package': package, 'name': name,
            'written': written, 'kept': kept}
