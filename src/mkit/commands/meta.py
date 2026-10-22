"""Commands that describe mkit itself: for agents first, humans second."""
from .. import __version__
from ..errors import EXIT_CODES, NotFound
from ..registry import GROUPS, REGISTRY, RISKS, Arg, command


@command('commands', 'List every command with its risk class and what it needs',
         risk='read', needs_project=False,
         examples=('mkit commands', 'mkit commands --json'))
def commands(ctx, args):
    """Every registered command. In JSON mode each entry carries a JSON Schema of
    its input, so an agent can build a valid call without reading help text."""
    entries = [REGISTRY[n].describe() for n in sorted(REGISTRY)]
    out = ctx.out
    if not out.json:
        for risk in RISKS:
            rows = [(e['name'], e['summary']) for e in entries if e['risk'] == risk]
            if rows:
                out.heading(f'{risk}')
                out.table(rows, ('command', 'what'))
        out.line()
        out.line('publish commands always ask first; agents pass --yes --confirm <package>.', 'dim')
    return {'version': __version__, 'groups': GROUPS, 'commands': entries,
            'exit_codes': {str(k): v for k, v in EXIT_CODES.items()}}


@command('schema', 'Input schema and details of one command', risk='read', needs_project=False,
         args=(Arg('name', 'command name, e.g. "deploy" or "listing plan"', kind='positional', nargs='+'),),
         examples=('mkit schema deploy --json', 'mkit schema listing plan'))
def schema(ctx, args):
    name = ' '.join(args.name)
    if name not in REGISTRY:
        raise NotFound(f'no command "{name}"', hint='`mkit commands` lists them all.')
    entry = REGISTRY[name].describe()
    entry['description'] = REGISTRY[name].description
    if not ctx.out.json:
        ctx.out.heading(f'mkit {name}   [{entry["risk"]}]')
        ctx.out.line(entry['description'] or entry['summary'])
        props = entry['input']['properties']
        if props:
            ctx.out.table([(k, v.get('type'), v.get('description', '')) for k, v in props.items()],
                          ('argument', 'type', 'what'))
    return entry


# What the Play Developer API cannot do, checked against the API reference on
# 2026-09-18. `applies` narrows the list to what matters for this app.
MANUAL = (
    {'id': 'create-app', 'what': 'Create the app and make its first upload',
     'where': 'Play Console > Create app', 'applies': 'new apps only'},
    {'id': 'privacy-policy', 'what': 'Set the privacy policy URL (needed before data safety)',
     'where': 'App content > Privacy policy', 'applies': 'every app'},
    {'id': 'datasafety-export', 'what': 'Read back the data safety answers Play holds (the API only uploads; `mkit datasafety build` writes the CSV from mkit.toml, `apply` uploads it)',
     'where': 'App content > Data safety > Export to CSV', 'applies': 'only to check what is declared now'},
    {'id': 'declarations', 'what': 'App content declarations other than data safety: ads, target '
     'audience, content rating, permissions and foreground services, account deletion URL',
     'where': 'App content', 'applies': 'every app, and again when the app changes'},
    {'id': 'production-access', 'what': 'Production access for a new personal developer '
     'account: 12 testers opted in for 14 days of closed testing, then apply',
     'where': 'Play Console > Testing > Closed testing, then Production', 'applies': 'new personal accounts'},
    {'id': 'app-access', 'what': 'Test credentials for an app behind a sign-in, so Play review '
     'can get past the login screen', 'where': 'App content > App access', 'applies': 'apps that need an account'},
    {'id': 'managed-publishing', 'what': 'Turn managed publishing on/off, press Publish, and "Send '
     'for review" for changes held back', 'where': 'Publishing overview', 'applies': 'when used'},
    {'id': 'tester-emails', 'what': 'Tester email lists (the API only takes Google Groups)',
     'where': 'Testing > Testers', 'applies': 'closed testing with email lists'},
    {'id': 'track-countries', 'what': 'Countries for a testing track (the API can only read them)',
     'where': 'Testing > track > Countries/regions', 'applies': 'testing tracks'},
    {'id': 'custom-listings', 'what': 'Custom store listings and store listing experiments',
     'where': 'Grow users > Store presence', 'applies': 'when used'},
    {'id': 'crashlytics', 'what': 'Crashlytics issues (no stable service-account API; `mkit crashes` '
     'reads Play vitals instead)', 'where': 'Firebase console > Crashlytics', 'applies': 'firebase apps'},
)


@command('manual', 'What only Play Console can do (no API), as a checklist', risk='read',
         needs_project=False, examples=('mkit manual',))
def manual(ctx, args):
    if not ctx.out.json:
        ctx.out.heading('Only in Play Console (no API)')
        for m in MANUAL:
            ctx.out.line(f'  - {m["what"]}')
            ctx.out.line(f'    {m["where"]}   ({m["applies"]})', 'dim')
    return {'manual': list(MANUAL)}
