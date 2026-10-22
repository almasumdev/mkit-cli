"""Project settings: find mkit.toml, read it, and answer "is this feature on?".

A project is the folder holding mkit.toml. mkit walks up from where it was
started, so it works from any subfolder of the app, the same way git does.

Settings are layered, first match wins:

    command flags  >  MKIT_* environment  >  <project>/mkit.toml
                   >  ~/.mkit/config.toml  >  built-in defaults

A table in mkit.toml switches a feature on. `[firebase]` present means this app
uses Firebase; absent means every Firebase step is skipped without a word, since
the app simply does not use it. That is how one pipeline serves apps that need
different parts of it.
"""
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .errors import MkitError, NotFound, UsageError

PROJECT_FILE = 'mkit.toml'
KINDS = ('flutter', 'android', 'android-wear')

# Tables that switch a feature on by being present. Order is how doctor lists them.
FEATURES = ('play', 'store', 'firebase', 'notify.telegram', 'aso', 'art', 'hooks')


def home():
    """User-level folder shared by every project: config.toml and .env."""
    override = os.environ.get('MKIT_HOME')
    return Path(override) if override else Path.home() / '.mkit'


def find_root(start=None):
    """The nearest folder at or above `start` that holds mkit.toml, or None."""
    here = Path(start or os.getcwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / PROJECT_FILE).is_file():
            return folder
    return None


def _read_toml(path):
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise UsageError(f'{path} is not valid TOML: {e}',
                         hint='Fix the file; `mkit doctor` re-checks it.',
                         code='BAD_CONFIG') from e


def _version_tuple(text):
    return tuple(int(p) for p in re.findall(r'\d+', text)[:3])


def check_requires(spec, have=__version__):
    """True when the running engine satisfies `requires = ">=x.y"`."""
    m = re.fullmatch(r'\s*>=\s*([\d.]+)\s*', spec or '')
    if not m:
        raise UsageError(f'requires = "{spec}" is not understood',
                         hint='Use the form requires = ">=0.1".', code='BAD_CONFIG')
    return _version_tuple(have) >= _version_tuple(m.group(1))


def _dig(data, dotted):
    node = data
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@dataclass
class Project:
    root: Path
    data: dict = field(default_factory=dict)
    user: dict = field(default_factory=dict)

    @property
    def name(self):
        return self.get('app.name') or self.root.name

    @property
    def kind(self):
        return self.get('app.kind')

    @property
    def package(self):
        return self.get('app.package')

    def has(self, feature):
        """Whether the feature's table is in mkit.toml (the app opted in)."""
        return isinstance(_dig(self.data, feature), dict)

    def section(self, feature):
        found = _dig(self.data, feature)
        return found if isinstance(found, dict) else {}

    def get(self, dotted, default=None):
        """Environment first (MKIT_APP_PACKAGE for app.package), then the
        project file, then the user file."""
        env = os.environ.get('MKIT_' + dotted.replace('.', '_').replace('-', '_').upper())
        if env is not None:
            return env
        for source in (self.data, self.user):
            value = _dig(source, dotted)
            if value is not None:
                return value
        return default

    def path(self, dotted, default=None):
        """A project-relative path setting, resolved against the project root."""
        value = self.get(dotted, default)
        return (self.root / value) if value else None


def load(start=None, project=None):
    """Load the project containing `start` (or the explicit `project` folder)."""
    root = Path(project).resolve() if project else find_root(start)
    if root is None or not (root / PROJECT_FILE).is_file():
        where = project or os.getcwd()
        raise NotFound(f'no {PROJECT_FILE} in {where} or any folder above it',
                       hint='Run `mkit init` in the app folder to create one.',
                       code='NO_PROJECT')
    data = _read_toml(root / PROJECT_FILE)
    user_file = home() / 'config.toml'
    user = _read_toml(user_file) if user_file.is_file() else {}

    spec = data.get('requires')
    if spec and not check_requires(spec):
        raise MkitError(f'this project needs mkit {spec}, but {__version__} is installed',
                        hint='Run `mkit self update`: it upgrades a git checkout, or names '
                             'the command for the package manager that installed mkit.',
                        code='ENGINE_TOO_OLD')

    kind = _dig(data, 'app.kind')
    if kind is not None and kind not in KINDS:
        raise UsageError(f'app.kind = "{kind}" is not one of {", ".join(KINDS)}',
                         code='BAD_CONFIG')
    return Project(root=root, data=data, user=user)
