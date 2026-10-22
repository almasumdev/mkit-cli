"""How the app is doing: installs, conversion, vitals, crashes, reviews."""
from datetime import datetime, timezone

from .. import safety
from ..cloud import auth, insight
from ..registry import Arg, command, group

group('reviews', 'Play reviews: read and reply')


def _wrap(fn, what):
    try:
        return fn()
    except Exception as e:
        raise auth.translate(e, what) from None


@command('stats', 'Installs, uninstalls, active devices, store conversion, ratings, countries',
         risk='read', needs=('play',),
         args=(Arg('days', 'daily rows to show (human output)', type=int, default=14),))
def stats(ctx, args):
    data = _wrap(lambda: insight.stats(ctx), 'Play reports bucket')
    out = ctx.out
    if not out.json:
        if data['window']:
            out.line(f'{ctx.project.name}   {data["window"][0]} to {data["window"][1]}   '
                     '(Play reports lag 3-7 days)', 'dim')
        s, i, r = data['store'], data['installs'], data['ratings']
        out.heading('store listing')
        out.line(f'  visitors {s["visitors"]}   acquisitions {s["acquisitions"]}'
                 + (f'   conversion {s["conversion"]}%' if s['conversion'] is not None else ''))
        out.heading('installs')
        out.line(f'  installs {i["installs"]}   uninstalls {i["uninstalls"]}   '
                 f'net {i["installs"] - i["uninstalls"]:+d}')
        out.line(f'  active devices: latest {i["active_latest"]}, peak {i["active_peak"]}')
        out.heading('ratings')
        out.line(f'  {r["count"]} rating(s)' + (f', average {r["average"]}' if r['average'] else ''))
        if data['countries']:
            out.heading('installs by country')
            out.line('  ' + '   '.join(f'{c} {n}' for c, n in list(data['countries'].items())[:12] if n))
        if data['daily']:
            out.heading('daily')
            out.table([(d['date'], d['installs'], d['uninstalls'], d['active'])
                       for d in data['daily'][-args.days:]], ('date', 'installs', 'uninstalls', 'active'))
    return data


@command('vitals', 'Crash and ANR rates per version (Play Developer Reporting API)', risk='read',
         needs=('play',), args=(Arg('days', 'window in days', type=int, default=28),))
def vitals(ctx, args):
    data = insight.vitals(ctx, args.days)
    if not ctx.out.json:
        for key, label, rate, perceived in (('crash', 'crashes', 'crashRate', 'userPerceivedCrashRate'),
                                            ('anr', 'ANRs', 'anrRate', 'userPerceivedAnrRate')):
            block = data[key]
            ctx.out.heading(f'{label}' + (f'   {block["window"][0]} to {block["window"][1]}' if block.get('window') else ''))
            if not block['rows']:
                ctx.out.line(f'  {block.get("note", "no data")}')
                continue
            ctx.out.table([(r['versionCode'], r['users'], f'{r.get(rate, 0):.2f}%', f'{r.get(perceived, 0):.2f}%')
                           for r in block['rows']], ('versionCode', 'users', label, 'user-perceived'))
        ctx.out.line()
        ctx.out.line("Play's bad-behaviour thresholds: user-perceived crashes 1.09%, ANRs 0.47%", 'dim')
    return data


@command('crashes', 'Top crash and ANR clusters with where they happen', risk='read', needs=('play',),
         args=(Arg('limit', 'how many', type=int, default=10),))
def crashes(ctx, args):
    issues = insight.crashes(ctx, args.limit)
    if not ctx.out.json:
        if not issues:
            ctx.out.line('no crash or ANR clusters reported')
        for i in issues:
            ctx.out.line(f'  {i["reports"]:>5} reports  {i["users"]:>4} users  {i["type"]}  '
                         f'v{i["firstVersion"]}-{i["lastVersion"]}')
            ctx.out.line(f'        {i["cause"] or ""}', 'bold')
            ctx.out.line(f'        {i["location"] or ""}', 'dim')
    return {'issues': issues}


@command('reviews list', 'Reviews with text from the last 7 days (the API limit)', risk='read',
         needs=('play',),
         args=(Arg('limit', 'how many', type=int, default=50),
               Arg('translate', 'translate into this language, e.g. en'),
               Arg('unanswered', 'only reviews without a reply', kind='flag')))
def reviews_list(ctx, args):
    items = _wrap(lambda: insight.reviews(ctx, args.limit, args.translate), 'Play reviews')
    if args.unanswered:
        items = [r for r in items if not r['replied']]
    if not ctx.out.json:
        if not items:
            ctx.out.line('no reviews with text in the last 7 days (older ones: `mkit stats` has ratings)')
        for r in items:
            when = datetime.fromtimestamp(int(r['date']), timezone.utc).date() if r['date'] else ''
            ctx.out.line(f'  {"*" * (r["stars"] or 0):5} {when}  {r["author"]}  v{r["version"] or "?"}  '
                         f'{"replied" if r["replied"] else "NO REPLY"}   id {r["id"]}')
            ctx.out.line(f'        {r["text"]}')
    return {'reviews': items}


@command('reviews reply', 'Reply to a review (public, 350 characters)', risk='publish', needs=('play',),
         args=(Arg('id', 'review id from `mkit reviews list`', kind='positional'),
               Arg('text', 'the reply', kind='positional')))
def reviews_reply(ctx, args):
    safety.confirm(ctx, 'Post a public reply to a review', [args.text])
    if ctx.dry_run:
        return {'id': args.id, 'text': args.text, 'dry_run': True}
    _wrap(lambda: insight.reply(ctx, args.id, args.text), 'Play reviews')
    return {'id': args.id, 'replied': True}
