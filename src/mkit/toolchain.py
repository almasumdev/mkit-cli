"""Finding the tools a build needs: Android SDK, adb, emulator, a JDK, Gradle.

Nothing here is per project except where a project may pin a value in
mkit.toml ([app].java_home) or the environment (MKIT_JAVA_HOME, JAVA_HOME,
ANDROID_HOME).
"""
import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

from .errors import MkitError

EXE = '.exe' if os.name == 'nt' else ''

# Gradle 8 runs on JDK 17-24. Android Studio's bundled jbr is tried last: recent
# Studio builds ship a JDK newer than Gradle 8 accepts.
JDK_MIN, JDK_MAX = 17, 24
JDK_CANDIDATES = (
    r'C:\Program Files\Microsoft\jdk-17*',
    r'C:\Program Files\Microsoft\jdk-21*',
    r'C:\Program Files\Eclipse Adoptium\jdk-17*',
    r'C:\Program Files\Eclipse Adoptium\jdk-21*',
    r'C:\Program Files\Java\jdk-17*',
    r'C:\Program Files\Java\jdk-21*',
    os.path.join(str(Path.home()), '.jdks', 'jbr-17*'),
    os.path.join(str(Path.home()), '.jdks', '*-17*'),
    os.path.join(str(Path.home()), '.jdks', '*-21*'),
    '/usr/lib/jvm/*-17*',
    '/usr/lib/jvm/*-21*',
    '/Library/Java/JavaVirtualMachines/*17*/Contents/Home',
    '/Library/Java/JavaVirtualMachines/*21*/Contents/Home',
    r'C:\Program Files\Android\Android Studio\jbr',
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Android Studio', 'jbr'),
    '/Applications/Android Studio.app/Contents/jbr/Contents/Home',
    '/opt/android-studio/jbr',
)


# Where Android Studio lives, newest first within a pattern. The Toolbox keeps
# every build in its own folder, so those are globbed and sorted.
STUDIO_CANDIDATES = (
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Android Studio*', 'bin', 'studio64.exe'),
    r'C:\Program Files\Android\Android Studio*\bin\studio64.exe',
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'JetBrains', 'Toolbox', 'apps', '*ndroid*',
                 '**', 'bin', 'studio64.exe'),
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Android Studio*', 'bin', 'studio.exe'),
    '/Applications/Android Studio*.app/Contents/MacOS/studio',
    os.path.join(str(Path.home()), 'Applications', 'Android Studio*.app', 'Contents', 'MacOS', 'studio'),
    '/opt/android-studio*/bin/studio.sh',
    '/usr/local/android-studio*/bin/studio.sh',
    os.path.join(str(Path.home()), '.local', 'share', 'JetBrains', 'Toolbox', 'apps', '*ndroid*',
                 '**', 'bin', 'studio.sh'),
)

STUDIO_EXES = ('studio64.exe', 'studio.exe') if os.name == 'nt' else ('studio.sh', 'studio')


def _studio_inside(path):
    """The launcher inside a folder somebody pinned: an install dir, a macOS
    bundle, or the bin/ folder itself."""
    path = Path(path)
    if path.is_file():
        return str(path)
    for relative in ('Contents/MacOS/studio', *(f'bin/{e}' for e in STUDIO_EXES), *STUDIO_EXES):
        found = path / relative
        if found.is_file():
            return str(found)
    return None


def studio(project=None):
    """Android Studio's launcher: [app].studio or MKIT_STUDIO taken as given,
    then the usual install locations, then PATH."""
    pinned = (project.get('app.studio') if project else None) or os.environ.get('MKIT_STUDIO')
    if pinned:
        found = _studio_inside(pinned)
        if not found:
            raise MkitError(f'studio {pinned} is not an Android Studio launcher', code='TOOL_MISSING',
                            hint='Point it at studio64.exe / studio.sh, or at the install folder.')
        return found
    for pattern in STUDIO_CANDIDATES:
        for candidate in sorted(glob.glob(pattern, recursive=True), reverse=True):
            if Path(candidate).is_file():
                return candidate
    for name in STUDIO_EXES:
        found = shutil.which(name)
        if found:
            return found
    raise MkitError('Android Studio not found', code='TOOL_MISSING',
                    hint='Install it, or set studio under [app] in mkit.toml (or MKIT_STUDIO) '
                         'to the studio64.exe / studio.sh path.')


def tool(name):
    """A PATH tool's full path. shutil.which follows PATHEXT, so firebase.cmd
    and flutter.bat launch without shell=True."""
    path = shutil.which(name)
    if not path:
        raise MkitError(f'{name} not found on PATH', code='TOOL_MISSING',
                        hint=f'Install {name} or add it to PATH, then re-run `mkit doctor`.')
    return path


def _local_properties(root):
    for props in (root / 'local.properties', root / 'android' / 'local.properties'):
        if props.is_file():
            for line in props.read_text(encoding='utf-8', errors='replace').splitlines():
                m = re.match(r'\s*sdk\.dir\s*=\s*(.+?)\s*$', line)
                if m:
                    return Path(m.group(1).replace('\\\\', '\\').replace('\\:', ':'))
    return None


def sdk_dir(root=None):
    if root is not None:
        found = _local_properties(Path(root))
        if found and found.is_dir():
            return found
    for key in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        if os.environ.get(key) and Path(os.environ[key]).is_dir():
            return Path(os.environ[key])
    guess = (Path(os.environ.get('LOCALAPPDATA', '')) / 'Android' / 'Sdk' if os.name == 'nt'
             else Path.home() / ('Library/Android/sdk' if os.uname().sysname == 'Darwin' else 'Android/Sdk'))
    return guess if guess.is_dir() else None


def adb(root=None):
    """The SDK's adb before any on PATH: other tools (scrcpy, phone suites)
    ship their own, and two adb versions keep killing each other's server."""
    sdk = sdk_dir(root)
    if sdk:
        exe = sdk / 'platform-tools' / f'adb{EXE}'
        if exe.is_file():
            return str(exe)
    found = shutil.which('adb')
    if found:
        return found
    raise MkitError('adb not found', code='TOOL_MISSING',
                    hint='Install the Android SDK platform-tools, or set ANDROID_HOME.')


def emulator(root=None):
    sdk = sdk_dir(root)
    exe = sdk / 'emulator' / f'emulator{EXE}' if sdk else None
    if not exe or not exe.is_file():
        raise MkitError('Android emulator not found', code='TOOL_MISSING',
                        hint='Install it from the SDK Manager, or set sdk.dir in local.properties.')
    return str(exe)


def java_major(home):
    java = Path(home) / 'bin' / f'java{EXE}'
    if not java.is_file():
        return 0
    try:
        out = subprocess.run([str(java), '-version'], capture_output=True, text=True, timeout=30).stderr
    except Exception:
        return 0
    m = re.search(r'version "(\d+)', out)
    return int(m.group(1)) if m else 0


def find_jdk(project=None):
    """A JDK for Gradle (JAVA_HOME) and the Android SDK (ANDROID_HOME), both
    exported for the processes we spawn. See _find_jdk for the JDK order."""
    jdk = _find_jdk(project)
    if not os.environ.get('ANDROID_HOME') and not os.environ.get('ANDROID_SDK_ROOT'):
        # A checkout without local.properties (it is gitignored) still builds.
        sdk = sdk_dir(project.root if project else None)
        if sdk:
            os.environ['ANDROID_HOME'] = str(sdk)
    return jdk


def _find_jdk(project=None):
    """A JDK Gradle accepts, exported as JAVA_HOME for the processes we spawn.

    Order: [app].java_home / MKIT_JAVA_HOME (taken as given), JAVA_HOME if it is
    in range, then the first candidate in range. Deliberately not left to
    `flutter build`, which prefers Android Studio's bundled JDK -- the one that
    is often too new.
    """
    pinned = project.get('app.java_home') if project else os.environ.get('MKIT_APP_JAVA_HOME')
    pinned = pinned or os.environ.get('MKIT_JAVA_HOME')
    if pinned:
        if not java_major(pinned):
            raise MkitError(f'java_home {pinned} has no bin/java', code='TOOL_MISSING')
        os.environ['JAVA_HOME'] = str(pinned)
        return str(pinned)
    current = os.environ.get('JAVA_HOME', '').rstrip('\\/')
    if current and JDK_MIN <= java_major(current) <= JDK_MAX:
        return current
    for pattern in JDK_CANDIDATES:
        for candidate in sorted(glob.glob(pattern), reverse=True):
            if JDK_MIN <= java_major(candidate) <= JDK_MAX:
                os.environ['JAVA_HOME'] = candidate
                return candidate
    raise MkitError(f'no JDK {JDK_MIN}-{JDK_MAX} found', code='TOOL_MISSING',
                    hint='Install JDK 17 or 21, or set java_home under [app] in mkit.toml.')


def gradlew(android_dir):
    path = Path(android_dir) / ('gradlew.bat' if os.name == 'nt' else 'gradlew')
    if not path.is_file():
        raise MkitError(f'no Gradle wrapper at {path}', code='TOOL_MISSING',
                        hint='Commit the Gradle wrapper (gradlew, gradlew.bat, gradle/wrapper).')
    return str(path)
