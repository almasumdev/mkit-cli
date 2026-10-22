"""Running noisy external tools.

Gradle and the Firebase CLI print hundreds of lines and bury their own cause
when they fail. Output is captured rather than inherited, only lines that
matter surface as step detail, every other line is a heartbeat for the run
bar, and a failure carries the tail with the boilerplate stripped.
"""
import os
import re
import subprocess

from . import output
from .errors import MkitError

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


class ToolFailed(MkitError):
    code = 'TOOL_FAILED'

    def __init__(self, command, returncode, tail):
        super().__init__(f'{command} exited {returncode}', lines=tail,
                         hint='The last lines of its output are below.')
        self.command = command
        self.returncode = returncode


# Compile errors are worth seeing live even on a build that goes on to pass:
# Dart "lib/x.dart:3:5: Error:", Kotlin "e: file:///...", javac "error:".
# Kotlin's marker only counts at the start of a line: "Note: " contains it too.
_BUILD_SIGNALS = ('error:', 'Error:')

_BUILD_NOISE = (
    'Deprecated Gradle features were used', "You can use '--warning-mode",
    'For more on this, please refer to', 'Run with --stacktrace', 'Run with --info',
    'Run with --scan', 'Get more help at', 'actionable task', '* Try:', '* Get more help',
    'Note: Recompile with', 'Note: Some input files use', 'Daemon will be stopped', 'w: ',
)

_FIREBASE_SIGNALS = ('rules', 'indexes', 'deploy complete', 'error', 'warning')


def build_interesting(line):
    return bool(line) and (line.startswith('e: ') or any(m in line for m in _BUILD_SIGNALS))


def firebase_interesting(line):
    return any(w in line.lower() for w in _FIREBASE_SIGNALS)


def never(line):
    return False


def useful_tail(lines, limit=25):
    kept = []
    for line in lines:
        if any(m in line for m in _BUILD_NOISE):
            continue
        if not line.strip() and (not kept or not kept[-1].strip()):
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept[-limit:]


def stream(argv, command, interesting=build_interesting, cwd=None, env=None, quiet=False,
           done_marker=None):
    """Run a tool with its output captured; raise ToolFailed with the tail on a
    non-zero exit. Returns the last 60 lines.

    [done_marker] is a line a tool prints once its work is actually finished. A
    tool that says so and *then* exits non-zero failed at something it does
    after the job -- telemetry, a cleanup, a version check -- and treating that
    as a failed deploy is worse than wrong: the caller rolls back a change the
    tool already made. When the marker was seen the exit code is reported as a
    warning and the run counts as a success.
    """
    out = output.out
    try:
        proc = subprocess.Popen([str(a) for a in argv], cwd=cwd or os.getcwd(), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', bufsize=1)
    except FileNotFoundError as e:
        raise MkitError(f'could not start {command}: {e}', code='TOOL_MISSING') from e
    tail = []
    # Tracked as the lines go by rather than read back off the tail, which only keeps the
    # last 60 and would lose the marker behind a talkative epilogue.
    finished = False
    for raw in proc.stdout:
        clean = ANSI.sub('', raw.rstrip()).strip()
        tail.append(clean)
        if len(tail) > 60:
            tail.pop(0)
        if done_marker and done_marker in clean:
            finished = True
        if interesting(clean) and not quiet:
            out.detail(clean)
        else:
            out.tick()
    code = proc.wait()
    if code != 0:
        if finished:
            out.warn(f'{command} finished its work, then exited {code} on its own; continuing')
            return tail
        raise ToolFailed(command, code, useful_tail(tail))
    return tail


def run(argv, cwd=None, env=None, check=True, timeout=None):
    """Run quietly and return stdout (stderr folded in)."""
    try:
        result = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, text=True,
                                encoding='utf-8', errors='replace', capture_output=True,
                                timeout=timeout)
    except FileNotFoundError as e:
        raise MkitError(f'could not start {argv[0]}: {e}', code='TOOL_MISSING') from e
    text = (result.stdout or '') + (result.stderr or '')
    if check and result.returncode != 0:
        raise ToolFailed(os.path.basename(str(argv[0])) + ' ' + ' '.join(str(a) for a in argv[1:3]),
                         result.returncode, useful_tail(text.splitlines()))
    return text


def detach(argv, cwd=None, env=None):
    """Start a windowed tool (Android Studio) and return its pid.

    Detached on purpose: mkit exits while the IDE stays open, and nothing of
    the IDE's own chatter lands in mkit's output or JSON envelope.
    """
    kwargs = ({'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == 'nt' else {'start_new_session': True})
    try:
        started = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **kwargs)
    except OSError as e:
        raise MkitError(f'could not start {argv[0]}: {e}', code='TOOL_MISSING') from e
    return started.pid


def interactive(argv, cwd=None, env=None):
    """Run with the terminal attached (flutter run, tests). Returns the exit code.

    Ctrl+C reaches the tool and mkit alike. mkit ignores it while the tool runs,
    so the tool decides how to stop (flutter run detaches cleanly) and mkit then
    ends with its exit code, instead of a second "interrupted" error on top."""
    import signal
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return subprocess.run([str(a) for a in argv], cwd=cwd, env=env).returncode
    finally:
        signal.signal(signal.SIGINT, previous)
