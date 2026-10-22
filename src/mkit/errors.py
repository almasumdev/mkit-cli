"""Errors and exit codes.

Every failure mkit reports is an MkitError: a stable machine code, a sentence a
human can read, and a hint that says what to do about it. The exit code is part
of the contract, so an agent can branch on it without parsing text.
"""

OK = 0
FAILED = 1
USAGE = 2
AUTH = 3
NOT_FOUND = 4
CONFLICT = 5
NEEDS_CONFIRM = 6
PARTIAL = 7
DRIFT = 10
INTERRUPTED = 130

EXIT_CODES = {
    OK: 'ok',
    FAILED: 'failed',
    USAGE: 'usage error',
    AUTH: 'credential missing or rejected',
    NOT_FOUND: 'not found',
    CONFLICT: 'conflict: remote changed, edit expired, or already in review',
    NEEDS_CONFIRM: 'needs confirmation (--yes --confirm <package>)',
    PARTIAL: 'done, with skipped steps',
    DRIFT: 'plan found differences',
    INTERRUPTED: 'interrupted',
}


class MkitError(Exception):
    exit_code = FAILED
    code = 'FAILED'

    def __init__(self, message, hint=None, code=None, retryable=False, lines=None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.retryable = retryable
        # The captured tail of a failed tool, shown as-is under the headline.
        self.lines = lines or []
        if code:
            self.code = code

    def as_dict(self):
        out = {'code': self.code, 'message': self.message, 'retryable': self.retryable}
        if self.hint:
            out['hint'] = self.hint
        if self.lines:
            out['lines'] = self.lines
        return out


class UsageError(MkitError):
    exit_code = USAGE
    code = 'USAGE'


class CredentialMissing(MkitError):
    exit_code = AUTH
    code = 'CREDENTIAL_MISSING'


class NotFound(MkitError):
    exit_code = NOT_FOUND
    code = 'NOT_FOUND'


class Conflict(MkitError):
    exit_code = CONFLICT
    code = 'CONFLICT'


class NeedsConfirm(MkitError):
    exit_code = NEEDS_CONFIRM
    code = 'NEEDS_CONFIRM'
