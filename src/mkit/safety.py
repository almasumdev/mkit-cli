"""The confirmation gate in front of every publish-class command.

At a terminal, mkit shows what is about to change and asks the person to type
the app name. Anywhere else (an agent's shell, a script) there is nobody to
ask, so it refuses with exit 6 unless the caller passes both --yes and
--confirm <package>. Naming the package is deliberate: it proves the caller
knows which app it is about to change, so a --yes carried over from another
project's command cannot publish to the wrong app.

--dry-run skips the gate, because a dry run publishes nothing.

`safety.no_prompt` (in ~/.mkit/config.toml or mkit.toml) lists commands a
person at a terminal runs without typing the name: what is about to change is
still shown, then it goes ahead. It only drops the prompt; off a terminal those
commands still need --yes --confirm, so an agent never gets through on it.
"""
import sys

from .errors import NeedsConfirm


def no_prompt(project):
    """Commands that skip the typed confirmation at a terminal."""
    value = project.get('safety.no_prompt', []) if project else []
    if isinstance(value, str):  # MKIT_SAFETY_NO_PROMPT="deploy,promote"
        value = value.split(',')
    return {str(name).strip() for name in value if str(name).strip()}


def confirm(ctx, action, changes=()):
    """Return normally when the publish may go ahead; raise NeedsConfirm otherwise."""
    if ctx.dry_run:
        return
    package = ctx.project.package if ctx.project else None
    expected = package or (ctx.project.name if ctx.project else '')

    if ctx.yes and ctx.confirm:
        if ctx.confirm not in (package, ctx.project.name if ctx.project else None):
            raise NeedsConfirm(f'--confirm {ctx.confirm} does not match this project ({expected})',
                               hint=f'Re-run with --confirm {expected} if this is the app you mean.')
        return

    interactive = not ctx.out.json and sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        raise NeedsConfirm(f'{action} changes {expected} and needs confirmation',
                           hint=f'A person must approve this. Re-run with --yes --confirm {expected}, '
                                f'or run it at a terminal. Use --dry-run to see what it would do.')

    out = ctx.out
    out.line()
    out.line(action, 'bold')
    for change in changes:
        out.line(f'  {change}')
    out.line()
    if getattr(ctx, 'command', '') in no_prompt(ctx.project):
        out.line('  Going ahead (safety.no_prompt).')
        return
    typed = input(f'  Type {ctx.project.name} to go ahead: ').strip()
    if typed.lower() != ctx.project.name.lower():
        raise NeedsConfirm('not confirmed; nothing was changed')
