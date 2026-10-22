"""The three kinds of app, and the only things that differ between them:
where the version lives, how a build is run, and where its outputs land.

    flutter        version: x.y.z+n in pubspec.yaml; Gradle project in android/
    android        versionCode/versionName in <module>/build.gradle(.kts), or
                   version.properties at the root if the project keeps it there
    android-wear   android, plus a `wear` module shipped on Play's Wear track

Every bump moves the name AND the code, and the code by exactly 1 whatever the
level: Play only needs it to increase, users only ever see the name, and moving
one without the other ships a build Play takes but users read as the old one.

Files are read and written with newline='' so a bump changes the version and
nothing else. (Reading in text mode turns CRLF into LF, and the whole file
would go back out rewritten in the bump commit.)
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import proc
from .errors import MkitError, UsageError
from .toolchain import gradlew, tool

LEVELS = ('major', 'minor', 'patch')


@dataclass(frozen=True)
class Module:
    label: str        # "phone" / "watch": what a person calls it
    factor: str       # "phone" / "wear": which Play track family it ships on
    gradle: str       # Gradle module name
    aab: Path
    mapping: Path


def bump_name(name, level):
    if level not in LEVELS:
        raise UsageError(f'bump must be one of {", ".join(LEVELS)}, not "{level}"')
    parts = [int(p) for p in re.findall(r'\d+', name)[:3]]
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts
    if level == 'major':
        return f'{major + 1}.0.0'
    if level == 'minor':
        return f'{major}.{minor + 1}.0'
    return f'{major}.{minor}.{patch + 1}'


def _read(path):
    try:
        with open(path, encoding='utf-8', newline='') as f:
            return f.read()
    except FileNotFoundError:
        raise MkitError(f'{path} not found', code='NO_VERSION_FILE') from None


def _write(path, text):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


# A lookahead for the line end, never a match: trailing spaces and the CR of a
# CRLF file stay exactly where they were.
_EOL = r'(?=[ \t]*\r?$)'


class VersionSource:
    """One file holding versionName and versionCode."""
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        raise NotImplementedError

    def write(self, name, code):
        raise NotImplementedError


class PubspecVersion(VersionSource):
    RE = re.compile(r'^(version:[ \t]*)(\d+\.\d+\.\d+)\+(\d+)' + _EOL, re.M)

    def read(self):
        m = self.RE.search(_read(self.path))
        if not m:
            raise MkitError(f'no "version: x.y.z+n" line in {self.path}', code='NO_VERSION')
        return m.group(2), int(m.group(3))

    def write(self, name, code):
        text = self.RE.sub(lambda m: f'{m.group(1)}{name}+{code}', _read(self.path), count=1)
        _write(self.path, text)


class GradleVersion(VersionSource):
    CODE = re.compile(r'^([ \t]*versionCode[ \t]*=?[ \t]*)(\d+)' + _EOL, re.M)
    NAME = re.compile(r'''^([ \t]*versionName[ \t]*=?[ \t]*["'])([^"']+)(["'])''' + _EOL, re.M)

    def read(self):
        text = _read(self.path)
        code, name = self.CODE.search(text), self.NAME.search(text)
        if not code or not name:
            raise MkitError(f'no literal versionCode/versionName in {self.path}', code='NO_VERSION',
                            hint='Set version_file under [app] if the version lives elsewhere.')
        return name.group(2), int(code.group(2))

    def write(self, name, code):
        text = _read(self.path)
        text = self.CODE.sub(lambda m: f'{m.group(1)}{code}', text, count=1)
        text = self.NAME.sub(lambda m: f'{m.group(1)}{name}{m.group(3)}', text, count=1)
        _write(self.path, text)


class PropertiesVersion(VersionSource):
    CODE = re.compile(r'^([ \t]*versionCode[ \t]*=[ \t]*)(\d+)' + _EOL, re.M)
    NAME = re.compile(r'^([ \t]*versionName[ \t]*=[ \t]*)([^\s#]+)' + _EOL, re.M)

    def read(self):
        text = _read(self.path)
        code, name = self.CODE.search(text), self.NAME.search(text)
        if not code or not name:
            raise MkitError(f'no versionCode/versionName in {self.path}', code='NO_VERSION')
        return name.group(2), int(code.group(2))

    def write(self, name, code):
        text = _read(self.path)
        text = self.CODE.sub(lambda m: f'{m.group(1)}{code}', text, count=1)
        text = self.NAME.sub(lambda m: f'{m.group(1)}{name}', text, count=1)
        _write(self.path, text)


def version_source(path):
    path = Path(path)
    if path.name == 'pubspec.yaml':
        return PubspecVersion(path)
    if path.suffix == '.properties':
        return PropertiesVersion(path)
    return GradleVersion(path)


_DEBUG_BLOCK = re.compile(r'(?:\bdebug\s*|getByName\(\s*"debug"\s*\)\s*|named\(\s*"debug"\s*\)\s*)\{')
_ID_SUFFIX = re.compile(r'''applicationIdSuffix\s*=?\s*["']([^"']*)["']''')


def gradle_debug_suffix(text):
    """The debug build type's applicationIdSuffix in a module's Gradle file
    (Groovy or Kotlin DSL), or '' when it sets none.

    Only the debug block counts: a suffix on another build type or a flavour
    says nothing about where a debug build installs.
    """
    for match in _DEBUG_BLOCK.finditer(text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            depth += {'{': 1, '}': -1}.get(text[i], 0)
            i += 1
        found = _ID_SUFFIX.search(text, match.end(), i)
        if found:
            return found.group(1)
    return ''


class Kind:
    name = ''

    def __init__(self, project):
        self.project = project
        self.root = project.root
        self.module = project.get('app.module', 'app')

    # ---------------------------------------------------------------- version

    def default_version_file(self):
        raise NotImplementedError

    @property
    def version(self):
        custom = self.project.get('app.version_file')
        return version_source(self.root / custom if custom else self.default_version_file())

    def current_version(self):
        return self.version.read()

    def bump(self, level='patch'):
        """Rewrite the version file. Returns (old_name, old_code, new_name, new_code)."""
        old_name, old_code = self.current_version()
        new_name, new_code = bump_name(old_name, level), old_code + 1
        self.version.write(new_name, new_code)
        return old_name, old_code, new_name, new_code

    # ---------------------------------------------------------------- packages

    def module_gradle_file(self):
        for name in ('build.gradle.kts', 'build.gradle'):
            path = self.android_dir / self.module / name
            if path.is_file():
                return path
        return None

    def debug_package(self):
        """Where a debug build installs.

        `app.debug_suffix` in mkit.toml wins; otherwise it is read from the
        debug build type in Gradle. It used to be assumed to be ".debug", so on
        an app without a suffix `run -c` cleaned a package that did not exist
        and left the real one alone.
        """
        suffix = self.project.get('app.debug_suffix')
        if suffix is None:
            gradle = self.module_gradle_file()
            suffix = gradle_debug_suffix(gradle.read_text(encoding='utf-8')) if gradle else ''
        return self.project.package + suffix

    def installed_package(self, release=False):
        """The package a run of that variant puts on the device."""
        return self.project.package if release else self.debug_package()

    # ---------------------------------------------------------------- build

    @property
    def android_dir(self):
        return self.root

    def signing_candidates(self):
        return [self.android_dir / 'key.properties', self.root / 'keystore.properties',
                self.root / 'key.properties']

    def signing_file(self):
        custom = self.project.get('app.signing')
        if custom:
            path = self.root / custom
            return path if path.is_file() else None
        return next((p for p in self.signing_candidates() if p.is_file()), None)

    def modules(self):
        base = self.root / self.module / 'build' / 'outputs'
        return [Module('phone', 'phone', self.module,
                       base / 'bundle' / 'release' / f'{self.module}-release.aab',
                       base / 'mapping' / 'release' / 'mapping.txt')]

    def prepare(self, variant, env):
        """Anything that must run before Gradle for this variant."""

    def bundle(self, env):
        """Build every module's release bundle. Returns the modules built."""
        self.prepare('release', env)
        tasks = [f':{m.gradle}:bundleRelease' for m in self.modules()]
        proc.stream([gradlew(self.android_dir), *tasks], 'gradlew ' + ' '.join(tasks),
                    cwd=self.android_dir, env=env)
        return self.modules()

    def apk_dir(self, variant):
        return self.root / self.module / 'build' / 'outputs' / 'apk' / variant

    def assemble(self, variant, env):
        """Build the phone APK for `variant`; return (applicationId, apk path)."""
        self.prepare(variant, env)
        task = f':{self.module}:assemble{variant.capitalize()}'
        proc.stream([gradlew(self.android_dir), task], f'gradlew {task}',
                    cwd=self.android_dir, env=env)
        directory = self.apk_dir(variant)
        meta_file = directory / 'output-metadata.json'
        if not meta_file.is_file():
            raise MkitError(f'no output-metadata.json in {directory}', code='NO_APK')
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        elements = meta.get('elements', [])
        if len(elements) != 1:
            raise MkitError('expected one APK for this variant; split APKs are not supported by run',
                            code='NO_APK')
        return meta['applicationId'], directory / elements[0]['outputFile']

    def test(self, device, env):
        """Run the project's tests against `device`. Returns the exit code."""
        task = f':{self.module}:connectedDebugAndroidTest'
        return proc.interactive([gradlew(self.android_dir), task], cwd=self.android_dir, env=env)


class Flutter(Kind):
    name = 'flutter'

    def default_version_file(self):
        return self.root / 'pubspec.yaml'

    @property
    def android_dir(self):
        return self.root / 'android'

    def modules(self):
        base = self.root / 'build' / 'app' / 'outputs'
        return [Module('phone', 'phone', 'app',
                       base / 'bundle' / 'release' / 'app-release.aab',
                       base / 'mapping' / 'release' / 'mapping.txt')]

    def apk_dir(self, variant):
        return self.root / 'build' / 'app' / 'outputs' / 'apk' / variant

    def prepare(self, variant, env):
        """`flutter build apk --<variant> --config-only` regenerates the plugin
        registrant and Gradle config for this mode. A registrant last written by
        `flutter test` still names integration_test, which release does not
        compile in. Needs no JDK; the Gradle wrapper then builds with ours."""
        proc.stream([tool('flutter'), 'build', 'apk', f'--{variant}', '--config-only'],
                    f'flutter build apk --{variant} --config-only', cwd=self.root, env=env,
                    quiet=True)

    def test(self, device, env):
        flutter = tool('flutter')
        code = proc.interactive([flutter, 'test'], cwd=self.root, env=env)
        if code != 0 or not (self.root / 'integration_test').is_dir():
            return code
        return proc.interactive([flutter, 'test', 'integration_test', '-d', device],
                                cwd=self.root, env=env)


class Android(Kind):
    name = 'android'

    def default_version_file(self):
        if (self.root / 'version.properties').is_file():
            return self.root / 'version.properties'
        for f in ('build.gradle.kts', 'build.gradle'):
            if (self.root / self.module / f).is_file():
                return self.root / self.module / f
        return self.root / self.module / 'build.gradle.kts'


class AndroidWear(Android):
    """A phone module plus a watch module. Play has required the watch to ship on
    its own Wear OS track since August 2023; the upload step resolves that."""
    name = 'android-wear'

    def modules(self):
        wear = self.project.get('app.wear_module', 'wear')
        base = self.root / wear / 'build' / 'outputs'
        return super().modules() + [
            Module('watch', 'wear', wear,
                   base / 'bundle' / 'release' / f'{wear}-release.aab',
                   base / 'mapping' / 'release' / 'mapping.txt')]


KINDS = {k.name: k for k in (Flutter, Android, AndroidWear)}


def for_project(project):
    kind = project.kind
    if kind not in KINDS:
        raise UsageError(f'app.kind is "{kind}"; set it to one of {", ".join(KINDS)} in mkit.toml',
                         code='BAD_CONFIG')
    return KINDS[kind](project)
