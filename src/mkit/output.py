"""Output for two readers: a person at a terminal and an agent reading a pipe.

Human mode keeps the look of the per-project kits: a bold title, one checked
line per finished step with its detail underneath, and a sticky run bar as the
last line, rewritten in place. Detail is buffered until its step closes so it
always sits under its own heading.

JSON mode is for anything that is not a terminal (an agent's shell, CI, a pipe)
or `--json`. stdout then carries exactly one JSON document, the result, and
stderr carries one JSON event per line while the command runs:

    {"event": "step", "title": "Build release bundle", "index": 5, "total": 11}
    {"event": "detail", "text": "..."}   {"event": "warn", "text": "..."}
    {"event": "skipped", "step": "...", "reason": "..."}
    {"event": "upload", "percent": 40}

The result is always the same envelope, so a caller parses one shape:

    {"ok": true,  "command": "doctor", "exit": 0, "result": {...},
     "warnings": [...], "skipped": [...]}
    {"ok": false, "command": "deploy", "exit": 3, "error": {"code", "message", "hint", "retryable"}}

MKIT_OUTPUT=human|json overrides the terminal check. Every string passes
through secrets.redact before it is written anywhere.
"""
import json
import os
import shutil
import sys
import time

from .secrets import redact

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

_CODES = {
    'dim': '\x1b[90m', 'bold': '\x1b[1m', 'green': '\x1b[32m',
    'cyan': '\x1b[36m', 'yellow': '\x1b[33m', 'red': '\x1b[31m',
}
_RESET = '\x1b[0m'
BAR_WIDTH = 24
UPLOAD_WIDTH = 14
INDENT = '        '


def _supports(text):
    try:
        text.encode(sys.stdout.encoding or 'utf-8')
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def human(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f'{seconds}s'
    return f'{seconds // 60}m {seconds % 60:02d}s'


def _visible_len(text):
    out, i = 0, 0
    while i < len(text):
        if text[i] == '\x1b':
            i = text.find('m', i) + 1
            continue
        out += 1
        i += 1
    return out


class Output:
    def __init__(self, mode=None, color=None):
        forced = os.environ.get('MKIT_OUTPUT')
        tty = sys.stdout.isatty()
        self.json = (mode or forced or ('human' if tty else 'json')) == 'json'
        self.tty = tty and not self.json
        if color is None:
            color = not os.environ.get('NO_COLOR')
        self.color = self.tty and color
        unicode_ok = _supports('█░✓')
        self.fill, self.empty = ('█', '░') if unicode_ok else ('#', '-')
        self.warnings = []
        self.skipped = []
        self._reset_run()

    # ------------------------------------------------------------ plumbing

    def _reset_run(self):
        self.total = 0
        self.done_count = 0
        self.title = None
        self.run_started = None
        self.step_started = None
        self.buffer = []
        self.sticky = False
        self.upload_pct = None
        self.count = None
        self.count_mark = -1
        self.last_draw = 0.0

    def paint(self, style, text):
        if not self.color or not style:
            return text
        return f'{_CODES[style]}{text}{_RESET}'

    def event(self, name, **fields):
        """One JSON line on stderr (JSON mode only)."""
        if not self.json:
            return
        payload = {'event': name, **fields}
        sys.stderr.write(redact(json.dumps(payload, ensure_ascii=False, default=str)) + '\n')
        sys.stderr.flush()

    def _print(self, line=''):
        self._clear_sticky()
        print(redact(line))
        self._draw_sticky()

    def _clear_sticky(self):
        if self.sticky:
            sys.stdout.write('\r\x1b[2K')
            self.sticky = False

    def _bar(self, pct, width):
        filled = int(round(pct / 100 * width))
        return self.fill * filled + self.empty * (width - filled)

    def _width(self):
        # One short of the real width: writing the last column makes some
        # terminals wrap, and a wrapped sticky line cannot be erased.
        try:
            return max(28, shutil.get_terminal_size(fallback=(80, 24)).columns - 1)
        except Exception:
            return 79

    def _draw_sticky(self):
        if not self.tty or not self.total:
            return
        width = self._width()
        pct = int(round(self.done_count / self.total * 100))
        uploading = self.upload_pct is not None
        run_w = BAR_WIDTH if width >= 90 else (14 if width >= 60 else 8)
        up_w = UPLOAD_WIDTH if width >= 100 else (8 if width >= 70 else 6)
        segments = [
            ('dim', '  run  '),
            ('cyan', self._bar(pct, run_w)),
            ('dim', f'  {pct:>3}%  {min(self.done_count + 1, self.total)} of {self.total}'),
        ]
        if self.title and not (uploading and width < 96):
            segments.append((None, '  ' + self.title))
        if uploading:
            counted = f'  {self.count[0]}/{self.count[1]}' if self.count else ''
            segments += [('dim', '  upload '), ('cyan', self._bar(self.upload_pct, up_w)),
                         ('dim', f' {self.upload_pct:>3}%{counted}')]
        elif self.step_started:
            segments.append(('dim', '  ' + human(time.time() - self.step_started)))
        out, used = [], 0
        for style, text in segments:
            if used >= width:
                break
            if used + len(text) > width:
                text = text[:width - used]
            out.append(self.paint(style, text))
            used += len(text)
        sys.stdout.write('\r\x1b[2K' + ''.join(out))
        sys.stdout.flush()
        self.sticky = True

    def _buffer(self, style, text, kind):
        text = redact(str(text))
        if self.json:
            self.event(kind, text=text, step=self.title)
            return
        if self.title is None:
            print(INDENT + self.paint(style, text))
            return
        self.buffer.append((style, text))
        self._draw_sticky()

    # ------------------------------------------------------------ run API

    def start(self, title, total, subtitle=None):
        self._reset_run()
        self.total = total
        self.run_started = time.time()
        if self.json:
            self.event('start', title=title, subtitle=subtitle, total=total)
            return
        print()
        head = self.paint('bold', title)
        if subtitle:
            head += self.paint('dim', '   ' + subtitle)
        print(redact(head))
        print()

    def step(self, title):
        self.title = title
        self.step_started = time.time()
        self.buffer = []
        self.upload_pct = None
        self.count = None
        self.count_mark = -1
        self.event('step', title=title, index=self.done_count + 1, total=self.total)
        self._draw_sticky()

    def detail(self, message):
        self._buffer(None, message, 'detail')

    def ok(self, message='done'):
        self._buffer('green', message, 'detail')

    def warn(self, message):
        self.warnings.append(redact(str(message)))
        self._buffer('yellow', message, 'warn')

    def skip(self, step, reason):
        """A pipeline step that did not run. Collected into the result."""
        self.skipped.append({'step': step, 'reason': redact(reason)})
        if self.json:
            self.event('skipped', step=step, reason=redact(reason))
        else:
            self._buffer('yellow', f'skipped: {reason}', 'skipped')

    def done(self, note=None):
        if self.title is None:
            return
        elapsed = time.time() - self.step_started if self.step_started else 0
        index = self.done_count + 1
        if self.json:
            self.event('done', title=self.title, index=index, seconds=round(elapsed, 1), note=note)
        else:
            heading = (self.paint('dim', f'  [{index:02d}/{self.total:02d}] ')
                       + self.paint('green', 'OK') + '  ' + self.paint('bold', self.title))
            if elapsed >= 5:
                heading += self.paint('dim', '  ' + human(elapsed))
            if note:
                heading += self.paint('dim', '  ' + note)
            self._clear_sticky()
            print(redact(heading))
            for style, text in self.buffer:
                print(INDENT + self.paint(style, text))
        self.done_count = index
        self.title = None
        self.step_started = None
        self.buffer = []
        self.upload_pct = None
        self.count = None
        self._draw_sticky()

    def upload(self, percent):
        pct = max(0, min(100, int(percent)))
        if self.json:
            if pct != self.upload_pct:
                self.event('upload', percent=pct)
            self.upload_pct = pct
            return
        self.upload_pct = pct
        self._draw_sticky()

    def progress(self, done, total, item=None):
        """Work counted in items (files uploaded, calls made). At a terminal it
        is the upload bar with "done/total"; piped, a line at every tenth; in
        JSON a progress event per item."""
        if self.json:
            self.event('progress', done=done, total=total, item=item, step=self.title)
            return
        pct = int(done * 100 / total) if total else 100
        self.count = (done, total)
        self.upload_pct = pct
        if self.tty:
            self.tick() if done < total else self._draw_sticky()
            return
        mark = pct // 10
        if mark != self.count_mark or done == total:
            self.count_mark = mark
            print(redact(f'{INDENT}{self.title or "progress"}: {done}/{total}'), flush=True)

    def tick(self, throttle=0.15):
        now = time.time()
        if now - self.last_draw < throttle:
            return
        self.last_draw = now
        self._draw_sticky()

    def finish(self, message):
        total = time.time() - self.run_started if self.run_started else 0
        if self.json:
            self.event('finish', message=message, seconds=round(total, 1))
            return
        self._clear_sticky()
        if self.tty and self.total:
            print(self.paint('dim', '  run  ') + self.paint('green', self._bar(100, BAR_WIDTH))
                  + self.paint('dim', f'  100%  {self.total} of {self.total}'))
        print()
        colour = 'yellow' if self.skipped else 'green'
        suffix = f' ({len(self.skipped)} skipped)' if self.skipped else ''
        print(self.paint(colour, redact('DONE  ' + message + suffix
                                        + (f' in {human(total)}' if total >= 5 else ''))))

    # ------------------------------------------------------------ plain text

    def line(self, text='', style=None):
        """A plain informational line. JSON mode sends it to stderr as a log event."""
        if self.json:
            if text:
                self.event('log', text=redact(str(text)))
            return
        self._print(self.paint(style, str(text)))

    def heading(self, text):
        self.line()
        self.line(text, 'bold')

    def table(self, rows, headers):
        """Aligned columns for humans. JSON callers read the result instead."""
        if self.json or not rows:
            return
        cells = [[str(c) for c in headers]] + [[str(c) for c in r] for r in rows]
        widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
        for n, row in enumerate(cells):
            text = '  ' + '  '.join(c.ljust(w) for c, w in zip(row, widths)).rstrip()
            self._print(self.paint('dim' if n == 0 else None, text))

    # ------------------------------------------------------------ endings

    def result(self, command, data, exit_code=0):
        if not self.json:
            return
        envelope = {'ok': True, 'command': command, 'exit': exit_code, 'result': data,
                    'warnings': self.warnings, 'skipped': self.skipped}
        print(redact(json.dumps(envelope, ensure_ascii=False, indent=2, default=str)))

    def failure(self, command, error, exit_code):
        """Report an MkitError. Human: headline, detail, tool tail. JSON: envelope."""
        if self.json:
            envelope = {'ok': False, 'command': command, 'exit': exit_code,
                        'error': error.as_dict(), 'warnings': self.warnings,
                        'skipped': self.skipped}
            print(redact(json.dumps(envelope, ensure_ascii=False, indent=2, default=str)))
            return
        self._clear_sticky()
        if self.buffer:
            # The open step never finished, so its held lines were never shown;
            # among them is often the one that matters ("bump commit undone").
            title = self.title or 'In progress'
            print(self.paint('dim', f'  [--/{self.total:02d}] ') + self.paint('red', '!!')
                  + '  ' + self.paint('bold', title))
            for style, text in self.buffer:
                print(INDENT + self.paint(style, text))
            self.buffer = []
        headline = redact(error.message)
        print()
        print(self.paint('red', headline))
        print(self.paint('dim', '-' * min(_visible_len(headline), self._width())))
        if error.hint:
            print('  ' + redact(error.hint))
        if error.lines:
            print()
            print(self.paint('dim', '  Last output:'))
            for line in error.lines:
                print('    ' + redact(line))
        print()


out = Output()


def configure(mode=None, color=None):
    """Replace the shared instance once flags are parsed."""
    global out
    out = Output(mode=mode, color=color)
    return out
