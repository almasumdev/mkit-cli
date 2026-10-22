"""The command registry: one declaration per command, read by every front end.

A command declares its name, a one-line summary, its risk class, the features
it needs, and its arguments. The CLI builds argparse from this, `mkit commands
--json` and `mkit schema` print it for agents, and a later MCP server will turn
the same entries into tools. Nothing about a command is described twice.

Risk classes, lowest first:

    read      looks, never changes anything anywhere
    plan      reads remote state and computes a diff; changes nothing
    write     changes local files or git, or a remote thing that is not user
              facing (an internal app-sharing link, symbols)
    publish   changes what users, testers or Play review see; always confirmed
"""
from dataclasses import dataclass, field

RISKS = ('read', 'plan', 'write', 'publish')


@dataclass(frozen=True)
class Arg:
    name: str
    help: str
    kind: str = 'option'          # positional | option | flag
    short: str | None = None
    long: bool = True              # False: the short flag is the only spelling
    type: type = str
    choices: tuple | None = None
    default: object = None
    nargs: str | None = None
    repeat: bool = False           # flag that may be given more than once

    def schema(self):
        json_type = {str: 'string', int: 'integer', float: 'number'}.get(self.type, 'string')
        if self.kind == 'flag':
            json_type = 'boolean'
        node = {'type': json_type, 'description': self.help}
        if self.nargs in ('*', '+', '...'):
            node = {'type': 'array', 'items': {'type': json_type}, 'description': self.help}
        if self.choices:
            node['enum'] = list(self.choices)
        if self.default is not None:
            node['default'] = self.default
        return node


@dataclass(frozen=True)
class Command:
    name: str                      # "doctor", or "listing plan" for a group member
    summary: str
    risk: str
    handler: object
    args: tuple = ()
    needs: tuple = ()              # features that must be on, e.g. ("play",)
    needs_project: bool = True
    examples: tuple = ()
    description: str = ''
    # Whether --dry-run is honoured. A command that cannot preview its change
    # must not pretend to: the CLI refuses the flag rather than letting it run
    # for real. Every publish-class command supports it, by policy.
    dry_run: bool = False

    def describe(self):
        required = [a.name for a in self.args if a.kind == 'positional' and a.nargs not in ('?', '*', '...')]
        return {
            'name': self.name,
            'summary': self.summary,
            'risk': self.risk,
            'needs': list(self.needs),
            'needs_project': self.needs_project,
            'confirm': self.risk == 'publish',
            'dry_run': self.dry_run,
            'input': {
                'type': 'object',
                'properties': {a.name: a.schema() for a in self.args},
                'required': required,
            },
            'examples': list(self.examples),
        }


REGISTRY: dict[str, Command] = {}
GROUPS: dict[str, str] = {}


def group(name, summary):
    GROUPS[name] = summary


def command(name, summary, risk, args=(), needs=(), needs_project=True, examples=(),
            description='', dry_run=None):
    if risk not in RISKS:
        raise ValueError(f'{name}: risk must be one of {RISKS}')

    def wrap(fn):
        if name in REGISTRY:
            raise ValueError(f'command {name!r} registered twice')
        REGISTRY[name] = Command(name=name, summary=summary, risk=risk, handler=fn,
                                 args=tuple(args), needs=tuple(needs),
                                 needs_project=needs_project, examples=tuple(examples),
                                 description=description or (fn.__doc__ or '').strip(),
                                 dry_run=(risk == 'publish') if dry_run is None else dry_run)
        return fn
    return wrap
