"""adb and emulator helpers: pick a device, install, launch, follow logs."""
import os
import re
import subprocess
import sys
import time

from . import output, proc, toolchain
from .errors import MkitError, UsageError


class Adb:
    def __init__(self, root=None):
        self.exe = toolchain.adb(root)

    def __call__(self, *args, device=None, check=False, timeout=120):
        argv = [self.exe] + (['-s', device] if device else []) + list(args)
        return proc.run(argv, check=check, timeout=timeout)

    def devices(self):
        found = []
        for line in self('devices').splitlines()[1:]:
            m = re.match(r'^(\S+)\s+(device|unauthorized|offline)$', line.strip())
            if m:
                found.append((m.group(1), m.group(2)))
        return found

    def model(self, device):
        try:
            return self('shell', 'getprop', 'ro.product.model', device=device).strip() or device
        except Exception:
            return device

    def app_uid(self, device, package):
        """The Linux uid the package runs as, or None if it is not installed.

        Used to narrow logcat to one app. The uid rather than the pid because the pid changes
        every time the app restarts, and restarting the app without leaving the log is the whole
        point of the Shift+R in follow_logs.
        """
        try:
            out = self('shell', 'pm', 'list', 'packages', '-U', package, device=device)
        except Exception:
            return None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith(f'package:{package} ') and 'uid:' in line:
                uid = line.rsplit('uid:', 1)[1].strip()
                return uid if uid.isdigit() else None
        return None


def is_emulator(serial):
    return serial.startswith('emulator-')


def pick(adb, want=None, serial=None):
    """One ready device. want: 'phone' | 'emulator' | None. Asks at a terminal
    when several match; anywhere else that is an error naming --device."""
    listed = adb.devices()
    if serial:
        if not any(s == serial and st == 'device' for s, st in listed):
            raise MkitError(f'device {serial} is not attached and ready', code='NO_DEVICE')
        return serial
    for s, state in listed:
        if state == 'unauthorized':
            output.out.warn(f'{s} is unauthorized: accept the USB debugging prompt on the phone')
    ready = [s for s, st in listed if st == 'device']
    if want == 'phone':
        ready = [s for s in ready if not is_emulator(s)]
    elif want == 'emulator':
        ready = [s for s in ready if is_emulator(s)]
    if not ready:
        what = {'phone': 'phone', 'emulator': 'running emulator'}.get(want, 'device')
        raise MkitError(f'no {what} attached', code='NO_DEVICE',
                        hint='Plug in a phone with USB debugging on, or start one with `mkit emu`.')
    if len(ready) == 1:
        return ready[0]
    out = output.out
    if out.json or not sys.stdin.isatty():
        raise UsageError(f'{len(ready)} devices attached ({", ".join(ready)}); pass --device SERIAL',
                         code='SEVERAL_DEVICES')
    out.line()
    for i, s in enumerate(ready, 1):
        out.line(f'  {i}) {adb.model(s)}  ({s}, {"emulator" if is_emulator(s) else "phone"})')
    choice = input(f'\nWhich one? (1-{len(ready)}, Enter for 1) ').strip() or '1'
    try:
        return ready[int(choice) - 1]
    except (ValueError, IndexError):
        raise UsageError(f'not one of the choices: {choice}') from None


def clean_state(adb, device, package):
    """Remove the app for every user and wipe its backup, so the next install
    is a true first run (Auto Backup would otherwise restore old prefs)."""
    users = re.findall(r'UserInfo\{(\d+):', adb('shell', 'pm', 'list', 'users', device=device)) or ['0']
    removed = 0
    for user in users:
        adb('shell', 'pm', 'clear', '--user', user, package, device=device)
        if 'Success' in adb('shell', 'pm', 'uninstall', '--user', user, package, device=device):
            removed += 1
    if 'Success' in adb('uninstall', package, device=device):
        removed += 1
    transports = []
    for line in adb('shell', 'bmgr', 'list', 'transports', device=device).splitlines():
        t = re.sub(r'^\s*\*?\s*', '', line).strip()
        if '/' in t:
            transports.append(t)
    for t in transports:
        adb('shell', 'bmgr', 'wipe', t, package, device=device)
    return removed, len(transports)


def launch(adb, device, package, clear_log=True):
    listed = adb('shell', 'cmd', 'package', 'resolve-activity', '--brief', '-a',
                 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', package,
                 device=device, check=True).splitlines()
    component = next((l.strip() for l in reversed(listed) if l.strip().startswith(package + '/')), None)
    if not component:
        raise MkitError(f'no launcher activity for {package}', code='NO_LAUNCHER')
    adb('shell', 'am', 'force-stop', package, device=device, check=True)
    if clear_log:
        adb('logcat', '-c', device=device)
    result = adb('shell', 'am', 'start', '-n', component, device=device, check=True)
    if 'Error' in result or 'Exception' in result:
        raise MkitError(result.strip(), code='LAUNCH_FAILED')
    return component


def _logcat_argv(adb, device, package, tags, everything):
    """What to follow, resolved fresh each time the stream starts.

    The uid is looked up here rather than once at the top, because an install can move an app to a
    new uid. A filter worked out before a reinstall goes on matching the old one, and the log then
    runs empty while the app is plainly doing things, which looks like the app broke.
    """
    if tags:
        return [adb.exe, '-s', device, 'logcat', '-s', *tags]
    if everything:
        return [adb.exe, '-s', device, 'logcat']
    uid = adb.app_uid(device, package)
    if uid:
        return [adb.exe, '-s', device, 'logcat', '--uid', uid]
    output.out.line(f'{package} is not installed, so the whole log follows', 'dim')
    return [adb.exe, '-s', device, 'logcat']


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def _wait_for_restart(process, restart):
    """True when R was pressed, False when the stream ended or Ctrl+C arrived."""
    try:
        if os.name == 'nt':
            import msvcrt
            while process.poll() is None:
                if restart and msvcrt.kbhit() and msvcrt.getwch() == 'R':
                    return True
                time.sleep(0.05)
        else:
            import select
            while process.poll() is None:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if restart and ready and sys.stdin.read(1) == 'R':
                    return True
    except KeyboardInterrupt:
        pass
    return False


def follow_logs(adb, device, package, tags, restart=True, everything=False, rebuild=None):
    """logcat until Ctrl+C. Shift+R puts the current code on the device without leaving.

    Narrowed to the app unless asked otherwise. Named tags win where a project sets them; with
    none, the app's own uid does it, which needs nothing configured and still catches the lines
    an app never chose a tag for, crashes included. A phone's own firmware can write a thousand
    lines a minute, so an unfiltered stream is not a log of your app in any useful sense.

    Given a [rebuild], Shift+R builds and installs before launching, which is what somebody
    watching their own log almost always means by restart: it used to relaunch whatever was
    already on the device, so the log filled with the code they had just changed away from and
    nothing said why. Without one it relaunches, which is all `mkit logs` can do from outside a
    project.

    The stream is stopped and started around each restart rather than left running. A rebuild
    prints over the top of a live log otherwise, and after an install the filter has to be worked
    out again; see [_logcat_argv].
    """
    out = output.out
    out.line('following logs; Shift+R rebuilds, installs and restarts, Ctrl+C stops' if rebuild
             else 'following logs; Shift+R restarts the app, Ctrl+C stops' if restart
             else 'following logs; Ctrl+C stops', 'dim')

    while True:
        process = subprocess.Popen(_logcat_argv(adb, device, package, tags, everything))
        try:
            asked = _wait_for_restart(process, restart)
        finally:
            _stop(process)
        if not asked:
            return

        if rebuild:
            out.line('rebuilding', 'dim')
            try:
                rebuild()
            except Exception as error:
                # Back to the log rather than out of it. A build breaks constantly and the
                # whole point of this key is not having to leave; the app on the device is
                # simply still the last one that built.
                out.warn(f'rebuild failed, app left as it was: {error}')
                continue
        out.line('restarting app', 'dim')
        launch(adb, device, package, clear_log=False)


def avds(root=None):
    exe = toolchain.emulator(root)
    return exe, [l.strip() for l in proc.run([exe, '-list-avds'], check=False).splitlines()
                 if l.strip() and not l.startswith('INFO')]


def start_emulator(adb, exe, avd, root=None, wait=240):
    """Kill running emulators, boot `avd` cold, wait for boot to complete."""
    adb('emu', 'kill')
    if os.name == 'nt':
        for image in ('emulator.exe', 'qemu-system-x86_64.exe'):
            subprocess.run(['taskkill', '/F', '/IM', image, '/T'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    subprocess.Popen([exe, '-avd', avd, '-no-boot-anim', '-no-audio', '-gpu', 'host', '-no-snapshot'],
                     cwd=root, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(2)
        output.out.tick()
        serial = next((s for s, st in adb.devices() if is_emulator(s) and st == 'device'), None)
        if serial and adb('shell', 'getprop', 'sys.boot_completed', device=serial).strip() == '1':
            return serial
    raise MkitError(f'{avd} did not finish booting in {wait}s', code='EMULATOR_TIMEOUT')
