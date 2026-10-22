"""Cut an engine release: bump the version, date the changelog, commit, tag.

    uv run python scripts/release.py patch|minor|major      # show what would happen
    uv run python scripts/release.py patch|minor|major go   # do it (then: git push --follow-tags)

Refuses to run with uncommitted changes, with failing tests, with stale
generated docs, or with nothing under "## Unreleased" in CHANGELOG.md, so a
tag always marks a tested, documented, described state.

Semantic versioning (see CONTRIBUTING.md):
    patch   fixes, no change to commands, flags, mkit.toml or JSON output
    minor   new commands, flags, config keys or output fields (backwards compatible)
    major   anything an app's mkit.toml, a script or an agent relying on the old
            behaviour would break on
"""
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / 'src' / 'mkit' / '__init__.py'
CHANGELOG = ROOT / 'CHANGELOG.md'


def run(*argv, check=True):
    return subprocess.run(argv, cwd=ROOT, check=check, capture_output=True, text=True).stdout.strip()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('patch', 'minor', 'major'):
        raise SystemExit(__doc__)
    level, go = sys.argv[1], len(sys.argv) > 2 and sys.argv[2] == 'go'

    text = INIT.read_text(encoding='utf-8')
    current = re.search(r"__version__ = '(\d+)\.(\d+)\.(\d+)'", text)
    major, minor, patch = (int(x) for x in current.groups())
    new = {'major': f'{major + 1}.0.0', 'minor': f'{major}.{minor + 1}.0',
           'patch': f'{major}.{minor}.{patch + 1}'}[level]

    log = CHANGELOG.read_text(encoding='utf-8')
    unreleased = re.search(r'## Unreleased\n(.*?)(?=\n## |\Z)', log, re.S)
    if not unreleased or not unreleased.group(1).strip():
        raise SystemExit('Nothing under "## Unreleased" in CHANGELOG.md; describe the change first.')
    if run('git', 'status', '--porcelain'):
        raise SystemExit('Uncommitted changes; commit them first.')

    print(f'{".".join(current.groups())} -> {new}')
    print(unreleased.group(1).strip())
    if not go:
        print('\nDry run. Add "go" to release.')
        return

    tests = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT)
    if tests.returncode != 0:
        raise SystemExit('Tests failed; nothing changed.')

    INIT.write_text(text.replace(current.group(0), f"__version__ = '{new}'"), encoding='utf-8', newline='\n')
    CHANGELOG.write_text(log.replace('## Unreleased\n', f'## Unreleased\n\n## {new} - {date.today()}\n', 1),
                         encoding='utf-8', newline='\n')
    run('git', 'add', str(INIT), str(CHANGELOG))
    run('git', 'commit', '-m', f'Release {new}')
    run('git', 'tag', '-a', f'v{new}', '-m', f'mkit {new}')
    print(f'Tagged v{new}. Publish with: git push --follow-tags')


if __name__ == '__main__':
    main()
