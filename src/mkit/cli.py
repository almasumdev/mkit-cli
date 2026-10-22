"""Entry point: parse, load the project, run one command, report, exit.

Global flags work before or after the command name:

    --json / --human     force the output mode (default: human at a terminal,
                         JSON anywhere else)
    --project PATH       the app folder, instead of searching up from here
    --yes --confirm PKG  approve a publish-class command without a prompt
    --dry-run            do everything except the change itself
    --strict             a skipped pipeline step is a failure, not a warning
    --no-color
"""
import argparse
import sys
import traceback
from dataclasses import dataclass, field

from . import __version__, config, output
from .errors import FAILED, INTERRUPTED, MkitError, UsageError
from .registry import GROUPS, REGISTRY
from .secrets import Secrets


@dataclass
class Context:
    out: object
    project: object = None
    secrets: Secrets = None
    command: str = ''
    yes: bool = False
    confirm: str | None = None
    dry_run: bool = False
    strict: bool = False
    exit_code: int = 0
    extra: dict = field(default_factory=dict)

    def require(self, feature):
        """For a command asked for directly: the feature must be switched on."""
        if not self.project.has(feature):
            raise UsageError(f'[{feature}] is not in {self.project.root / config.PROJECT_FILE}',
                             hint=f'Add a [{feature}] table to switch it on for this app. '
                                  '`mkit doctor` lists every feature.',
                             code='FEATURE_OFF')


def _global_flags(parser, suppress):
    default = argparse.SUPPRESS if suppress else None
    flag_default = argparse.SUPPRESS if suppress else False
    g = parser.add_argument_group('global options')
    g.add_argument('--json', dest='output_mode', action='store_const', const='json',
                   default=default, help='JSON result on stdout, JSONL events on stderr')
    g.add_argument('--human', dest='output_mode', action='store_const', const='human',
                   default=default, help='human output even when not at a terminal')
    g.add_argument('--project', default=default, metavar='PATH',
                   help='app folder holding mkit.toml (default: search up from here)')
    g.add_argument('--yes', action='store_true', default=flag_default,
                   help='approve a publish without a prompt (needs --confirm)')
    g.add_argument('--confirm', default=default, metavar='PACKAGE',
                   help='the package id being changed, required with --yes')
    g.add_argument('--dry-run', action='store_true', default=flag_default,
                   help='do everything except the change itself')
    g.add_argument('--strict', action='store_true', default=flag_default,
                   help='treat a skipped pipeline step as a failure')
    g.add_argument('--no-color', action='store_true', default=flag_default)


def _add_args(parser, cmd):
    for a in cmd.args:
        if a.kind == 'positional':
            kwargs = {'help': a.help, 'type': a.type}
            if a.nargs:
                kwargs['nargs'] = a.nargs
            if a.choices:
                kwargs['choices'] = a.choices
            if a.default is not None:
                kwargs['default'] = a.default
            parser.add_argument(a.name, **kwargs)
            continue
        flags = [] if a.short and not a.long else [f'--{a.name.replace("_", "-")}']
        if a.short:
            flags.insert(0, f'-{a.short}')
        if a.kind == 'flag':
            parser.add_argument(*flags, dest=a.name, help=a.help,
                                action='count' if a.repeat else 'store_true',
                                default=0 if a.repeat else False)
        else:
            kwargs = {'dest': a.name, 'help': a.help, 'type': a.type, 'default': a.default}
            if a.choices:
                kwargs['choices'] = a.choices
            if a.nargs:
                kwargs['nargs'] = a.nargs
            parser.add_argument(*flags, **kwargs)


def build_parser():
    from . import commands  # noqa: F401  (registers every command)

    parser = argparse.ArgumentParser(
        prog='mkit', description='Android release, Play Console and Firebase operations.',
        epilog='`mkit commands` lists everything; `mkit <command> -h` explains one.')
    parser.add_argument('--version', action='version', version=f'mkit {__version__}')
    _global_flags(parser, suppress=False)
    sub = parser.add_subparsers(dest='_cmd', metavar='<command>')

    group_parsers = {}
    for name in sorted(REGISTRY):
        cmd = REGISTRY[name]
        parts = name.split(' ')
        target = sub
        if len(parts) == 2:
            head = parts[0]
            if head not in group_parsers:
                gp = sub.add_parser(head, help=GROUPS.get(head, ''))
                group_parsers[head] = gp.add_subparsers(dest='_sub', metavar='<action>')
            target = group_parsers[head]
        p = target.add_parser(parts[-1], help=cmd.summary, description=cmd.summary,
                              epilog='examples:\n  ' + '\n  '.join(cmd.examples) if cmd.examples else None,
                              formatter_class=argparse.RawDescriptionHelpFormatter)
        _global_flags(p, suppress=True)
        _add_args(p, cmd)
        p.set_defaults(_command=name)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    out = output.configure(mode=args.output_mode, color=not args.no_color)
    name = getattr(args, '_command', None)
    if name is None:
        if getattr(args, '_cmd', None):
            # A group given without an action, e.g. `mkit listing`.
            parser.parse_args([args._cmd, '-h'])
        parser.print_help()
        return 2

    cmd = REGISTRY[name]
    ctx = Context(out=out, command=name, yes=args.yes, confirm=args.confirm,
                  dry_run=args.dry_run, strict=args.strict)
    try:
        if cmd.needs_project or args.project:
            ctx.project = config.load(project=args.project)
        else:
            try:
                ctx.project = config.load()
            except MkitError:
                ctx.project = None
        ctx.secrets = Secrets(ctx.project.root if ctx.project else None)
        for feature in cmd.needs:
            ctx.require(feature)
        if ctx.dry_run and cmd.risk in ('write', 'publish') and not cmd.dry_run:
            # A dry run that quietly does the real thing is worse than none.
            # read and plan commands change nothing, so the flag is harmless there.
            raise UsageError(f'`mkit {name}` has no dry run, so --dry-run would have made '
                             'the change for real. Nothing was done.',
                             hint=f'Run `mkit {name}` without --dry-run when you mean it.',
                             code='NO_DRY_RUN')
        data = cmd.handler(ctx, args)
        out.result(name, data if data is not None else {}, ctx.exit_code)
        return ctx.exit_code
    except MkitError as e:
        out.failure(name, e, e.exit_code)
        return e.exit_code
    except KeyboardInterrupt:
        err = MkitError('interrupted', code='INTERRUPTED')
        out.failure(name, err, INTERRUPTED)
        return INTERRUPTED
    except Exception as e:  # a bug in mkit, not an operational outcome
        err = MkitError(f'internal error: {type(e).__name__}: {e}', code='INTERNAL',
                        hint='This is a bug in mkit. The traceback is on stderr.')
        traceback.print_exc(file=sys.stderr)
        out.failure(name, err, FAILED)
        return FAILED


def run():
    sys.exit(main())


if __name__ == '__main__':
    run()
