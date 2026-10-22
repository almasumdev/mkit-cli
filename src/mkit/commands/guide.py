"""`mkit guide`: how an app should do what every app has to do.

The guides ship inside the package, so they read the same on every machine and
offline. Each is filled in from this studio's settings - [studio], [about] -
so the About guide names your email and your developer, not an example's.
"""
from .. import guides
from ..errors import NotFound, UsageError
from ..registry import Arg, command


@command('guide', "How an app should do what every app has to do, filled in with your studio's details",
         risk='read', needs_project=False,
         args=(Arg('name', 'which guide; leave it out for the list', kind='positional', nargs='?',
                   choices=tuple(guides.GUIDES)),
               Arg('raw', 'the guide as written, placeholders and all', kind='flag')),
         examples=('mkit guide', 'mkit guide about', 'mkit guide review --json', 'mkit guide about --raw'))
def guide(ctx, args):
    out = ctx.out
    if not args.name:
        rows = [{'name': n, 'about': d, 'available': guides._locate(f) is not None}
                for n, (f, d) in guides.GUIDES.items()]
        if not out.json:
            out.heading('guides')
            out.table([(r['name'], r['about']) for r in rows], ('name', 'what it covers'))
            out.line()
            out.line('Read one with `mkit guide <name>`. Your details come from [studio] and [about] '
                     'in ~/.mkit/config.toml or this app\'s mkit.toml; an app\'s own rules go in '
                     'its docs/guides/<file>.', 'dim')
        return {'guides': rows}

    try:
        text, info = guides.render(args.name, ctx.project, raw=args.raw)
    except FileNotFoundError:
        raise NotFound(f'the {args.name} guide is missing from this install',
                       hint='Reinstall mkit; the guides ship inside the package.',
                       code='NO_GUIDE') from None
    except KeyError:
        raise UsageError(f'no guide called {args.name}', code='NO_GUIDE') from None

    if not out.json:
        out.line(text)
        if info['unset']:
            out.line()
            out.line('Not set, so shown as ‹...› above: ' + ', '.join(info['unset']), 'yellow')
            out.line('Add them under their table in ~/.mkit/config.toml (all apps) or mkit.toml '
                     '(this app).', 'dim')
    return {**info, 'text': text}
