"""`mkit self`: the engine's own version and updates.

Every app runs the engine installed on this computer, and the install is
editable: it runs straight from the engine's git checkout. So a change pulled
into that checkout reaches every app at once, with nothing to copy into any
app repo. `self update` does the pull, and says when the dependencies
changed (pyproject.toml), which needs one reinstall a pull cannot do.
"""
import sys
from pathlib import Path

from .. import __version__, proc
from ..errors import MkitError
from ..registry import command, group
from ..toolchain import tool

group('self', "the mkit engine itself: version, updates")


def engine_repo():
    """The git checkout this engine runs from, or None (non-editable install)."""
    here = Path(__file__).resolve()
    for folder in here.parents:
        if (folder / '.git').exists() and (folder / 'pyproject.toml').is_file():
            return folder
    return None


def _git(repo, *args, check=True):
    return proc.run([tool('git'), *args], cwd=repo, check=check).strip()


@command('self status', "The engine's version, where it runs from, and whether it is behind", risk='read',
         needs_project=False)
def self_status(ctx, args):
    repo = engine_repo()
    info = {'version': __version__, 'python': sys.executable, 'repo': str(repo) if repo else None}
    if repo:
        _git(repo, 'fetch', '--quiet', '--tags', check=False)
        info.update(branch=_git(repo, 'rev-parse', '--abbrev-ref', 'HEAD'),
                    commit=_git(repo, 'rev-parse', '--short', 'HEAD'),
                    tag=_git(repo, 'describe', '--tags', '--abbrev=0', check=False) or None,
                    dirty=bool(_git(repo, 'status', '--porcelain')),
                    behind=int(_git(repo, 'rev-list', '--count', 'HEAD..@{u}', check=False) or 0),
                    ahead=int(_git(repo, 'rev-list', '--count', '@{u}..HEAD', check=False) or 0))
    if not ctx.out.json:
        ctx.out.line(f'mkit {__version__}' + (f'   {info["repo"]}' if repo else '   (not an editable install)'), 'bold')
        if repo:
            ctx.out.line(f'  {info["branch"]} {info["commit"]}   last tag {info["tag"] or "none"}'
                         + ('   uncommitted changes' if info['dirty'] else ''))
            if info['behind']:
                ctx.out.line(f'  {info["behind"]} commit(s) behind; run `mkit self update`', 'yellow')
            elif info['ahead']:
                ctx.out.line(f'  {info["ahead"]} commit(s) not pushed', 'yellow')
            else:
                ctx.out.line('  up to date', 'green')
    return info


@command('self update', 'Pull the latest engine; every app uses it immediately', risk='write',
         needs_project=False)
def self_update(ctx, args):
    repo = engine_repo()
    if not repo:
        raise MkitError('this mkit is not an editable install from a git checkout',
                        hint='Reinstall with: uv tool install -e <path to the mkit repo>', code='NOT_EDITABLE')
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
    return {'changed': changed, 'from': before, 'to': after, 'needs_reinstall': reinstall,
            'reinstall_command': f'uv tool install -e {repo} --reinstall' if reinstall else None,
            'commits': log.splitlines()}
