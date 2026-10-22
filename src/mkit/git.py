"""The git safety net around a release.

deploy commits in two steps before it touches Play: whatever was already
uncommitted gets a commit of its own (so it is never at risk), then the
version bump gets its own commit. If anything fails before Play accepts the
release, exactly that one bump commit is undone -- and only if it is still the
commit at HEAD, so a failure can never drop someone else's work.
"""
from . import proc
from .toolchain import tool

SNAPSHOT_MESSAGE = 'chore: snapshot pending changes before release'
# How deploy names its version bump, so the last release can be found again.
BUMP_PREFIX = 'chore: bump version to '


class Repo:
    def __init__(self, root):
        self.root = root

    def _git(self, *args, check=True):
        return proc.run([tool('git'), *args], cwd=self.root, check=check)

    def read(self, *args):
        try:
            return self._git(*args).strip()
        except Exception:
            return ''

    def is_repo(self):
        return self.read('rev-parse', '--is-inside-work-tree') == 'true'

    def branch(self):
        return self.read('rev-parse', '--abbrev-ref', 'HEAD')

    def head(self, short=True):
        return self.read('rev-parse', '--short' if short else '--verify', 'HEAD')

    def dirty(self):
        return [l for l in self._git('status', '--porcelain').splitlines() if l.strip()]

    def snapshot(self):
        """Commit everything already dirty on its own. Returns how many paths."""
        dirty = self.dirty()
        if dirty:
            self._git('add', '-A')
            self._git('commit', '-m', SNAPSHOT_MESSAGE)
        return len(dirty)

    def commit_files(self, files, message):
        self._git('add', '--', *[str(f) for f in files])
        self._git('commit', '-m', message)
        return self.head(short=False)

    def undo(self, expected_head):
        """Drop HEAD only if it is still the commit we made."""
        if self.head(short=False) != expected_head:
            return False
        self._git('reset', '--hard', 'HEAD~1')
        return True

    def last_release(self):
        """The commit of the last version bump deploy made, or "" before the first."""
        return self.read('log', '-1', '--format=%H', f'--grep=^{BUMP_PREFIX}')

    def changed_since(self, commit, path):
        """Whether path differs from commit, counting uncommitted and untracked files."""
        return bool(self.read('diff', '--name-only', commit, '--', str(path))
                    or self.read('ls-files', '--others', '--exclude-standard', '--', str(path)))

    def upstream(self):
        """The branch this one pushes to, or "" when it has none."""
        return self.read('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')

    def push(self):
        """Push the current branch. Returns (ok, detail); never raises.

        By the time a release pushes, the build is already on Play. A push that
        cannot go - no remote, no upstream, a branch someone else moved - is a
        thing to tell the user about, not a reason to end a finished release in
        a traceback. The detail is what to say next, not a diagnosis.
        """
        upstream = self.upstream()
        if not upstream:
            return False, f'no upstream; run: git push -u origin {self.branch()}'
        try:
            self._git('push')
        except Exception as e:
            lines = [l for l in getattr(e, 'lines', []) if l.strip()]
            return False, (lines[-1] if lines else str(e))[:200]
        return True, upstream

    def restore(self, files):
        """Put files back to HEAD (a dry run's temporary bump)."""
        self._git('checkout', '--', *[str(f) for f in files])
