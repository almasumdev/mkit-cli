"""`mkit self`: the engine's own version and updates.

mkit is installed one of two ways, and each updates differently:

- **As a package** (`uv tool install mkit-cli`, pipx, pip). Updating is the
  package manager's job, and it has to be: on Windows a running mkit.exe cannot
  replace itself. So `self update` names the exact command for the manager that
  installed it, and `self status` says whether a newer release is on PyPI.
- **Editable, from a git checkout** (`uv tool install -e <checkout>`), which is
  how one studio runs it across many apps: a pull into the checkout reaches every
  app at once. `self update` does the pull, and says when the dependencies
  changed (pyproject.toml), which needs one reinstall a pull cannot do.
"""
import sys
from pathlib import Path

from .. import __version__, proc
from ..errors import MkitError
from ..registry import command, group
from ..toolchain import tool

# The distribution name on PyPI. The command stays `mkit`; `mkit` itself on
# PyPI is an unrelated, abandoned package.
DIST = 'mkit-cli'

group('self', "the mkit engine itself: version, updates")


def engine_repo():
    """The git checkout this engine runs from, or None (a package install)."""
    here = Path(__file__).resolve()
    for folder in here.parents:
        if (folder / '.git').exists() and (folder / 'pyproject.toml').is_file():
            return folder
    return None


def upgrade_command(executable=None):
    """The command that upgrades a package install, for the manager that did it.

    Read off the interpreter's own path, which each manager puts somewhere
    recognisable. Wrong guesses are cheap - the alternatives are always printed
    alongside - but the first command offered should be the one that works.
    """
    exe = str(executable or sys.executable).replace('\\', '/').lower()
    if '/uv/tools/' in exe or '/uv/tool/' in exe:
        return f'uv tool upgrade {DIST}'
    if '/pipx/' in exe:
        return f'pipx upgrade {DIST}'
    return f'pip install --upgrade {DIST}'


ALTERNATIVES = (f'uv tool upgrade {DIST}', f'pipx upgrade {DIST}', f'pip install --upgrade {DIST}')


def latest_on_pypi(timeout=4):
    """The newest release on PyPI, or None when it cannot be asked.

    Offline, a proxy, PyPI being slow: none of those is worth a failed status
    check, so every failure means "unknown", never an error.
    """
    try:
        import requests
        reply = requests.get(f'https://pypi.org/pypi/{DIST}/json', timeout=timeout)
        if reply.ok:
            return reply.json()['info']['version']
    except Exception:
        pass
    return None


def _newer(latest, current):
    def parts(v):
        return tuple(int(p) if p.isdigit() else 0 for p in v.split('.')[:3])
    try:
        return parts(latest) > parts(current)
    except Exception:
        return False


def _git(repo, *args, check=True):
    return proc.run([tool('git'), *args], cwd=repo, check=check).strip()


@command('self status', "The engine's version, how it was installed, and whether a newer one exists",
         risk='read', needs_project=False)
def self_status(ctx, args):
    repo = engine_repo()
    info = {'version': __version__, 'python': sys.executable, 'repo': str(repo) if repo else None,
            'install': 'editable' if repo else 'package'}
    if repo:
        _git(repo, 'fetch', '--quiet', '--tags', check=False)
        info.update(branch=_git(repo, 'rev-parse', '--abbrev-ref', 'HEAD'),
                    commit=_git(repo, 'rev-parse', '--short', 'HEAD'),
                    tag=_git(repo, 'describe', '--tags', '--abbrev=0', check=False) or None,
                    dirty=bool(_git(repo, 'status', '--porcelain')),
                    behind=int(_git(repo, 'rev-list', '--count', 'HEAD..@{u}', check=False) or 0),
                    ahead=int(_git(repo, 'rev-list', '--count', '@{u}..HEAD', check=False) or 0))
    else:
        latest = latest_on_pypi()
        info.update(latest=latest, outdated=bool(latest and _newer(latest, __version__)),
                    upgrade_command=upgrade_command())

    if not ctx.out.json:
        out = ctx.out
        if repo:
            out.line(f'mkit {__version__}   {info["repo"]}', 'bold')
            out.line(f'  {info["branch"]} {info["commit"]}   last tag {info["tag"] or "none"}'
                     + ('   uncommitted changes' if info['dirty'] else ''))
            if info['behind']:
                out.line(f'  {info["behind"]} commit(s) behind; run `mkit self update`', 'yellow')
            elif info['ahead']:
                out.line(f'  {info["ahead"]} commit(s) not pushed', 'yellow')
            else:
                out.line('  up to date', 'green')
        else:
            out.line(f'mkit {__version__}   installed as the {DIST} package', 'bold')
            if info['outdated']:
                out.line(f'  {info["latest"]} is out; upgrade with: {info["upgrade_command"]}', 'yellow')
            elif info['latest']:
                out.line('  up to date', 'green')
            else:
                out.line('  could not check PyPI for a newer release', 'dim')
    return info


@command('self update', 'Update mkit: pull an editable checkout, or name the upgrade command',
         risk='write', needs_project=False)
def self_update(ctx, args):
    repo = engine_repo()
    if not repo:
        # A package install cannot upgrade itself from inside: on Windows the
        # running mkit.exe is locked. Say exactly what to run instead, and make
        # it plain in the result that nothing changed, so a script does not
        # mistake this for an update.
        command_line = upgrade_command()
        if not ctx.out.json:
            ctx.out.line(f'mkit is installed as the {DIST} package, so its package manager updates it:',
                         'bold')
            ctx.out.line(f'  {command_line}')
            others = [c for c in ALTERNATIVES if c != command_line]
            ctx.out.line(f'  (or: {"  /  ".join(others)})', 'dim')
        return {'changed': False, 'install': 'package', 'upgrade_command': command_line}

    if _git(repo, 'status', '--porcelain'):
        raise MkitError(f'{repo} has uncommitted changes; commit or stash them first', code='DIRTY_ENGINE')
    before = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'pull', '--ff-only', '--tags')
    after = _git(repo, 'rev-parse', 'HEAD')
    changed = before != after
    # New dependencies: an editable install picks up code, not packages. The
    # reinstall is left to the user because it replaces the very mkit.exe that
    # is running this command, which Windows refuses.
    reinstall = bool(changed and _git(repo, 'diff', '--name-only', before, after, '--', 'pyproject.toml'))
    log = _git(repo, 'log', '--oneline', f'{before}..{after}') if changed else ''
    if not ctx.out.json:
        ctx.out.line('already up to date' if not changed else f'updated {before[:7]} -> {after[:7]}',
                     'green')
        for line in log.splitlines():
            ctx.out.line(f'  {line}')
        if reinstall:
            ctx.out.line(f'dependencies changed; finish with: uv tool install -e {repo} --reinstall',
                         'yellow')
    return {'changed': changed, 'install': 'editable', 'from': before, 'to': after,
            'needs_reinstall': reinstall,
            'reinstall_command': f'uv tool install -e {repo} --reinstall' if reinstall else None,
            'commits': log.splitlines()}
