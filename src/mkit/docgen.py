"""docs/commands.md, generated from the command registry.

The reference is built from the same declarations the CLI is built from, so
it cannot describe a flag that does not exist. tests/test_docs.py fails when
the committed file is stale; `python scripts/gen_docs.py` rewrites it.
"""
from . import __version__
from .registry import GROUPS, REGISTRY, RISKS

RISK_NOTE = {
    'read': 'looks only, changes nothing',
    'plan': 'reads remote state and shows a diff, changes nothing',
    'write': 'changes local files/git or a non-user-facing remote thing',
    'publish': 'changes what users, testers or Play review see; always confirmed',
}

SECTIONS = (
    ('Develop', ('run', 'devices', 'logs', 'emu', 'studio', 'version', 'bump', 'gradle')),
    ('Release', ('deploy', 'status', 'promote', 'rollout', 'share')),
    ('Store', ('listing', 'whatsnew', 'datasafety', 'testers')),
    ('Money', ('products', 'prices')),
    ('Insight', ('stats', 'vitals', 'crashes', 'reviews', 'aso')),
    ('Firebase', ('rules', 'config', 'remoteconfig', 'firebase')),
    ('About mkit', ('doctor', 'commands', 'schema', 'manual', 'init', 'self')),
)


def _usage(cmd):
    parts = [f'mkit {cmd.name}']
    for a in cmd.args:
        flag = f'--{a.name.replace("_", "-")}'
        if a.kind == 'positional':
            parts.append(f'[{a.name}]' if a.nargs in ('?', '*') else f'<{a.name}...>' if a.nargs == '...' else f'<{a.name}>')
        elif a.kind == 'flag':
            parts.append(f'[-{a.short}]' if a.short and not a.long
                         else f'[-{a.short}|{flag}]' if a.short else f'[{flag}]')
        else:
            parts.append(f'[{flag} {a.name.upper()}]')
    return ' '.join(parts)


def _section_of(name):
    head = name.split(' ')[0]
    for title, names in SECTIONS:
        if head in names:
            return title
    return 'Other'


def render():
    lines = [
        '# mkit command reference',
        '',
        f'Generated from the command registry (mkit {__version__.rsplit(".", 1)[0]}.x). '
        'Do not edit by hand: run `python scripts/gen_docs.py`.',
        '',
        'Global options, accepted before or after any command: `--json`, `--human`, '
        '`--project PATH`, `--dry-run`, `--strict`, `--yes --confirm PACKAGE`, `--no-color`.',
        '',
        '## Risk classes',
        '',
        '| Class | Meaning |',
        '|---|---|',
    ]
    lines += [f'| {r} | {RISK_NOTE[r]} |' for r in RISKS]
    by_section = {}
    for name in sorted(REGISTRY):
        by_section.setdefault(_section_of(name), []).append(REGISTRY[name])
    for title, _ in SECTIONS + (('Other', ()),):
        cmds = by_section.get(title)
        if not cmds:
            continue
        lines += ['', f'## {title}', '']
        lines += ['| Command | Risk | What |', '|---|---|---|']
        lines += [f'| `{c.name}` | {c.risk} | {c.summary} |' for c in cmds]
        for c in cmds:
            lines += ['', f'### mkit {c.name}', '', f'`{c.risk}`'
                      + (f', needs `[{"]`, `[".join(c.needs)}]` in mkit.toml' if c.needs else ''), '']
            text = c.description or c.summary
            lines += [text.split('\n\n')[0].replace('\n', ' ').strip(), '', '```', _usage(c), '```']
            if c.args:
                lines += ['', '| Argument | What |', '|---|---|']
                for a in c.args:
                    label = a.name if a.kind == 'positional' else f'--{a.name.replace("_", "-")}'
                    if a.short:
                        label = f'-{a.short}' if not a.long else f'-{a.short}, {label}'
                    extra = f' (one of {", ".join(a.choices)})' if a.choices else ''
                    extra += f' (default {a.default})' if a.default not in (None, False) else ''
                    lines.append(f'| `{label}` | {a.help}{extra} |')
            if c.examples:
                lines += ['', 'Examples:', '', '```'] + list(c.examples) + ['```']
    group_lines = [f'- `{g}`: {s}' for g, s in sorted(GROUPS.items())]
    lines += ['', '## Command groups', ''] + group_lines + ['']
    return '\n'.join(lines)
