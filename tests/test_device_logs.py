"""Following a log means following one app's log.

A handset's own firmware writes thousands of lines a minute. An unfiltered stream is not a log of
your app in any useful sense, so `mkit run -l` and `mkit logs` narrow to the app and `--all` is
how you ask for the rest.
"""
import pytest

from mkit import device


class FakeAdb:
    """Records the logcat it would run, and answers pm queries."""

    exe = 'adb'

    def __init__(self, listing=None):
        self.listing = listing
        self.argv = None

    def __call__(self, *args, device=None, check=False, timeout=120):
        if args[:4] == ('shell', 'pm', 'list', 'packages'):
            if self.listing is None:
                raise RuntimeError('device went away')
            return self.listing
        raise AssertionError(f'unexpected adb call: {args}')

    app_uid = device.Adb.app_uid


class Process:
    def poll(self):
        return 0

    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass


@pytest.fixture
def spy(monkeypatch):
    """follow_logs without actually spawning adb or reading the keyboard."""
    seen = {'argv': None, 'runs': []}

    def popen(argv, *a, **k):
        seen['argv'] = argv
        seen['runs'].append(argv)
        return Process()

    monkeypatch.setattr(device.subprocess, 'Popen', popen)
    return seen


@pytest.fixture
def one_restart(monkeypatch):
    """Shift+R pressed once, then the stream ends. Records what followed, in order."""
    order = []
    presses = [True, False]

    monkeypatch.setattr(device, '_wait_for_restart', lambda process, restart: presses.pop(0))
    monkeypatch.setattr(device, 'launch',
                        lambda adb, dev_, pkg, clear_log=True: order.append('launch'))
    return order


def test_the_uid_is_read_from_the_package_listing():
    adb = FakeAdb('package:com.example.demo uid:10813\n')
    assert adb.app_uid('serial', 'com.example.demo') == '10813'


def test_a_package_that_is_not_installed_has_no_uid():
    assert FakeAdb('').app_uid('serial', 'com.example.demo') is None


def test_another_packages_line_is_not_mistaken_for_this_one():
    # `pm list packages -U <name>` matches on substring, so asking about one app can answer with
    # its own debug build beside it.
    adb = FakeAdb('package:com.example.demo.debug uid:10999\n'
                  'package:com.example.demo uid:10813\n')
    assert adb.app_uid('serial', 'com.example.demo') == '10813'


def test_a_device_that_will_not_answer_does_not_raise():
    assert FakeAdb(None).app_uid('serial', 'com.example.demo') is None


def test_logs_are_narrowed_to_the_app_by_default(spy):
    adb = FakeAdb('package:com.example.demo uid:10813\n')
    device.follow_logs(adb, 'serial', 'com.example.demo', [], restart=False)
    assert spy['argv'] == ['adb', '-s', 'serial', 'logcat', '--uid', '10813']


def test_configured_tags_win_over_the_uid(spy):
    # A project that named its tags meant them, and tags cross process boundaries where a uid
    # does not: a Flutter app's engine logs under flutter whatever it is running as.
    adb = FakeAdb('package:com.example.demo uid:10813\n')
    device.follow_logs(adb, 'serial', 'com.example.demo',
                       ['flutter:V', 'AndroidRuntime:E'], restart=False)
    assert spy['argv'] == ['adb', '-s', 'serial', 'logcat', '-s',
                           'flutter:V', 'AndroidRuntime:E']


def test_all_asks_for_the_whole_device(spy):
    adb = FakeAdb('package:com.example.demo uid:10813\n')
    device.follow_logs(adb, 'serial', 'com.example.demo', [], restart=False, everything=True)
    assert spy['argv'] == ['adb', '-s', 'serial', 'logcat']


def test_an_uninstalled_app_falls_back_rather_than_failing(spy):
    # Following the whole log is a poor answer; refusing to follow anything is a worse one.
    device.follow_logs(FakeAdb(''), 'serial', 'com.example.demo', [], restart=False)
    assert spy['argv'] == ['adb', '-s', 'serial', 'logcat']


def test_shift_r_builds_before_it_relaunches(spy, one_restart):
    """The bug this key had: it relaunched whatever was already installed.

    Somebody who edits a file and presses R is asking to see their change run. Restarting the old
    install shows them the log of the code they changed away from, and nothing on screen says why
    it did not take.
    """
    adb = FakeAdb('package:com.example.demo uid:10813\n')
    device.follow_logs(adb, 'serial', 'com.example.demo', [],
                       rebuild=lambda: one_restart.append('rebuild'))

    assert one_restart == ['rebuild', 'launch'], 'the build must happen before the relaunch'


def test_the_stream_is_restarted_so_the_filter_is_worked_out_again(spy, one_restart):
    # An install can move the app to a new uid. Keeping the old --uid filter leaves the log empty
    # while the app is plainly running, which reads as the app being broken.
    adb = FakeAdb('package:com.example.demo uid:10813\n')
    device.follow_logs(adb, 'serial', 'com.example.demo', [], rebuild=lambda: None)

    assert len(spy['runs']) == 2, 'logcat should be stopped and started around a restart'


def test_a_failed_build_leaves_the_app_alone_and_keeps_following(spy, one_restart):
    """A build breaks constantly, and the point of this key is not having to leave the log."""
    def explode():
        raise RuntimeError('compilation error')

    adb = FakeAdb('package:com.example.demo uid:10813\n')
    device.follow_logs(adb, 'serial', 'com.example.demo', [], rebuild=explode)

    assert 'launch' not in one_restart, 'a build that failed must not relaunch the old app'
    assert len(spy['runs']) == 2, 'and the log carries on'


def test_without_a_rebuild_shift_r_still_just_relaunches(spy, one_restart):
    # `mkit logs` runs outside a build, so restarting what is installed is all it can offer.
    adb = FakeAdb('package:com.example.demo uid:10813\n')
    device.follow_logs(adb, 'serial', 'com.example.demo', [])

    assert one_restart == ['launch']
