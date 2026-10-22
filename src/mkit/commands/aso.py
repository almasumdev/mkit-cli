"""Search rank checks, keyword research and listing impact (no official API; see mkit/aso.py)."""
from datetime import date

from .. import aso
from ..cloud import insight
from ..errors import UsageError
from ..registry import Arg, command, group

group('aso', 'search rank, keyword research and listing impact')


@command('aso rank', "Where the app ranks in Play search for each keyword, vs the last run",
         risk='read', needs=('aso',), args=(Arg('workers', 'parallel requests', type=int, default=6),))
def aso_rank(ctx, args):
    items, path = aso.load_keywords(ctx.project)
    out = ctx.out
    out.start(f'{ctx.project.name} search rank', 1, f'{len(items)} keywords')
    out.step('Search Play')
    results = aso.rank(ctx.project.package, items, args.workers)
    folder = aso.results_dir(ctx.project, path)
    saved = aso.save(folder, 'results', results)
    out.done(f'saved {saved.name}')
    before_file, before = aso.previous(folder, 'results', saved)
    for r in results:
        r['previous'] = before.get((r['kw'], r['gl']))
    ranked = [r for r in results if r['pos']]
    if not out.json:
        for r in sorted(ranked, key=lambda r: r['pos']):
            move = ''
            if r['previous'] and r['previous'] != r['pos']:
                move = f'  (was #{r["previous"]})'
            elif (r['kw'], r['gl']) in before and not r['previous']:
                move = '  (new)'
            out.line(f'  #{r["pos"]:>3}  {r["gl"]}  {r["kw"]}{move}')
        lost = [r for r in results if not r['pos'] and r['previous']]
        for r in lost:
            out.line(f'   --   {r["gl"]}  {r["kw"]}  (was #{r["previous"]})', 'yellow')
    errors = [r for r in results if r.get('error')]
    out.finish(f'ranked for {len(ranked)} of {len(results)} keywords'
               + (f', {len(errors)} fetch error(s)' if errors else ''))
    return {'file': str(saved), 'previous_file': str(before_file) if before_file else None,
            'ranked': len(ranked), 'total': len(results), 'results': results}


@command('aso research', 'Find phrases people type and score which are worth targeting (mkit guide aso)',
         risk='read', needs=('aso',),
         args=(Arg('market', 'only this country (gl), e.g. DE'),
               Arg('top', 'phrases to show per market (human output)', type=int, default=15),
               Arg('workers', 'parallel requests', type=int, default=3)),
         examples=('mkit aso research', 'mkit aso research --market DE'))
def aso_research(ctx, args):
    markets, path = aso.load_markets(ctx.project)
    if args.market:
        markets = [m for m in markets if m['gl'].upper() == args.market.upper()]
        if not markets:
            raise UsageError(f'no [[market]] with gl = "{args.market}" in {path.name}', code='NO_MARKET')
    out = ctx.out
    out.start(f'{ctx.project.name} keyword research', 1,
              f'{len(markets)} market(s); slow on purpose, thousands of requests')
    out.step('Ask autocomplete, then score each phrase')
    results = aso.research(ctx.project.package, markets, args.workers,
                           progress=lambda d, t, item: out.progress(d, t, item))
    saved = aso.save(aso.results_dir(ctx.project, path), 'research', results)
    out.done(f'saved {saved.name}')
    if not out.json:
        for m in markets:
            rows = [r for r in results if r['gl'] == m['gl']][:args.top]
            out.heading(f'{m["gl"]} ({m["lang"]})')
            out.table([(f'{r["score"]:.0f}', r['kw'], f'{r["demand"]:.2f}', f'{r["median_top5"]:,}',
                        r['in_title'], f'#{r["pos"]}' if r['pos'] else '-') for r in rows],
                      ('score', 'phrase', 'demand', 'median top 5', 'in titles', 'us'))
    out.finish(f'{len(results)} phrase(s) scored; pick from the top, see `mkit guide aso`, "The ladder"')
    return {'file': str(saved), 'results': results}


@command('aso impact', 'What a listing change did: store visitors and keywords before vs after a date',
         risk='read', needs=('aso', 'play'),
         args=(Arg('since', 'the day the change went live, YYYY-MM-DD'),
               Arg('days', 'days to compare on each side', type=int, default=14)),
         examples=('mkit aso impact --since 2026-10-02',))
def aso_impact(ctx, args):
    if not args.since:
        raise UsageError('pass --since YYYY-MM-DD, the day the listing change went live', code='NO_SINCE')
    try:
        date.fromisoformat(args.since)
    except ValueError:
        raise UsageError(f'--since {args.since!r} is not a date (YYYY-MM-DD)', code='BAD_DATE') from None
    _, path = aso.load_keywords(ctx.project)
    out = ctx.out
    out.start(f'{ctx.project.name} listing impact since {args.since}', 1)
    out.step('Read Play store reports')
    daily = insight.store_daily(ctx)
    out.done(f'{len(daily)} day(s), to {max(daily) if daily else "none"}')
    b_file, b_ranks, a_file, a_ranks = aso.scan_around(aso.results_dir(ctx.project, path), 'results', args.since)
    data = aso.impact(daily, args.since, args.days, b_ranks, a_ranks)
    data['scans'] = {'before': b_file.name if b_file else None, 'after': a_file.name if a_file else None}
    if not out.json:
        for side in ('before', 'after'):
            s = data[side]
            out.line(f'  {side:6}  {s["days"]:>2} days   visitors {s["visitors"]:>4} '
                     f'({s["visitors_per_day"]}/day)   acquisitions {s["acquisitions"]:>3}   '
                     f'conversion {s["conversion"]}%')
        if not (b_file and a_file):
            out.line('  rank: needs an `aso rank` scan before the date and one after it', 'yellow')
        else:
            out.line(f'  rank: {data["ranked_before"]} -> {data["ranked_after"]} keyword(s) ranked '
                     f'({b_file.name} vs {a_file.name})')
            for g in data['gained'][:10]:
                out.line(f'    + #{g["pos"]:<3} {g["gl"]}  {g["kw"]}', 'green')
            for x in data['lost'][:10]:
                out.line(f'    -  was #{x["was"]:<3} {x["gl"]}  {x["kw"]}', 'yellow')
    out.finish('Play reports lag 3-7 days; small numbers swing, judge over two weeks or more')
    return data


@command('aso score','How beatable page one is for each keyword (weakest top-5 install count)',
         risk='read', needs=('aso',), args=(Arg('workers', 'parallel requests', type=int, default=6),))
def aso_score(ctx, args):
    items, path = aso.load_keywords(ctx.project)
    out = ctx.out
    out.start(f'{ctx.project.name} keyword winnability', 1, f'{len(items)} keywords')
    out.step('Search Play and read top-5 installs')
    results = aso.score(ctx.project.package, items, args.workers)
    saved = aso.save(aso.results_dir(ctx.project, path), 'winnability', results)
    out.done(f'saved {saved.name}')
    if not out.json:
        out.table([(r['gl'], r['kw'], f'{r["weakest"]:,}', f'#{r["pos"]}' if r['pos'] else '-')
                   for r in results[:30]], ('market', 'keyword', 'weakest top-5', 'us'))
    out.finish(f'{sum(1 for r in results if r["weakest"] < 10_000)} keyword(s) with a top-5 app under 10k installs')
    return {'file': str(saved), 'results': results}
