"""In-app products, subscriptions and prices."""
from .. import safety
from ..cloud import auth, money
from ..errors import DRIFT
from ..registry import Arg, command, group

group('products', 'one-time products, their offers, and subscriptions')
group('prices', "Google Play's regional prices")


def _svc(ctx):
    return auth.play(ctx, timeout=120), ctx.project.get('play.package') or ctx.project.package


@command('products list', 'What Play holds: every one-time product and subscription', risk='read',
         needs=('play',))
def products_list(ctx, args):
    svc, package = _svc(ctx)
    try:
        products, subs = money.list_remote(svc, package)
    except Exception as e:
        raise auth.translate(e, 'Play') from None
    rows = []
    for p in products:
        for o in p.get('purchaseOptions', []) or [{}]:
            rows.append({'kind': 'product', 'id': p['productId'], 'part': o.get('purchaseOptionId', ''),
                         'state': o.get('state', ''), 'title': (p.get('listings') or [{}])[0].get('title', '')})
    for s in subs:
        for b in s.get('basePlans', []) or [{}]:
            rows.append({'kind': 'subscription', 'id': s['productId'], 'part': b.get('basePlanId', ''),
                         'state': b.get('state', ''), 'title': (s.get('listings') or [{}])[0].get('title', '')})
    if not ctx.out.json:
        if rows:
            ctx.out.table([(r['kind'], r['id'], r['part'], r['state'], r['title']) for r in rows],
                          ('kind', 'id', 'option/plan', 'state', 'title'))
        else:
            ctx.out.line('no products or subscriptions on Play')
    return {'items': rows}


def _show(out, changes):
    if out.json:
        return
    if not changes:
        out.line('  no changes: Play matches the products file', 'green')
    for c in changes:
        detail = ''
        if c['kind'] == 'offer':
            detail = _offer_detail(c)
        elif c['kind'] == 'trial':
            detail = {'create': f'free for {c["trial"]}, then activate',
                      'update': f'length {c.get("from")} -> {c["trial"]}',
                      'activate': f'state {c.get("state")} -> ACTIVE'}[c['action']]
        elif c['action'] == 'update':
            parts = []
            if c['prices']:
                parts.append('prices ' + ', '.join(f'{r} {v["from"]}->{v["to"]}' for r, v in sorted(c['prices'].items())))
            if c['listings']:
                parts.append('listing ' + ', '.join(c['listings']))
            if c.get('state') != 'ACTIVE':
                parts.append(f'state {c.get("state")} -> ACTIVE')
            detail = '; '.join(parts)
        out.line(f'  {c["action"]:8} {c["kind"]:12} {c["id"]}  {detail}')


def _day(value):
    """2026-12-31T00:00:00Z reads as 2026-12-31; any other time stays whole."""
    if isinstance(value, str) and value.endswith('T00:00:00Z'):
        return value[:10]
    return value


def _offer_detail(c):
    window = c['body']['discountedOffer']
    if c['action'] == 'create':
        when = f'until {_day(window["endTime"])}'
        if 'startTime' in window:
            when = f'{_day(window["startTime"])} to {_day(window["endTime"])}'
        return f'{c["discount_pct"]}% off in {c["regions"]} region(s), {when}, then activate'
    parts = []
    for field, v in c['changes'].items():
        if field == 'regions':
            parts.append(f'add region(s) {", ".join(v["added"])}')
        elif field == 'discount_pct':
            fix = f' (fix {", ".join(v["regions"])})' if v.get('regions') else ''
            parts.append(f'discount {v["from"]}% -> {v["to"]}%{fix}')
        elif field == 'tags':
            parts.append(f'tags {v["from"]} -> {v["to"]}')
        else:
            parts.append(f'{field} {_day(v["from"]) or "none"} -> {_day(v["to"])}')
    if c.get('state') != 'ACTIVE':
        parts.append(f'state {c.get("state")} -> ACTIVE')
    return '; '.join(parts)


def _public(changes):
    return [{k: v for k, v in c.items() if k != 'body'} for c in changes]


@command('products plan', 'Compare the products file with Play (changes nothing)', risk='plan',
         needs=('play', 'store'))
def products_plan(ctx, args):
    data = money.load(ctx.project)
    svc, package = _svc(ctx)
    try:
        changes = money.plan(svc, package, data)
    except Exception as e:
        raise auth.translate(e, 'Play') from None
    _show(ctx.out, changes)
    if changes:
        ctx.exit_code = DRIFT
    return {'changes': _public(changes)}


@command('products apply',
         'Create or update products, their offers and subscriptions to match the file, and activate them',
         risk='publish', needs=('play', 'store'))
def products_apply(ctx, args):
    data = money.load(ctx.project)
    svc, package = _svc(ctx)
    try:
        changes = money.plan(svc, package, data)
        _show(ctx.out, changes)
        if not changes:
            return {'changes': [], 'changed': False}
        safety.confirm(ctx, f'Apply {len(changes)} product change(s) to {package}',
                       [f'{c["action"]} {c["kind"]} {c["id"]}' for c in changes])
        if ctx.dry_run:
            return {'changes': _public(changes), 'dry_run': True}
        money.apply(svc, package, data, changes)
    except Exception as e:
        raise auth.translate(e, 'Play') from None
    if not ctx.out.json:
        ctx.out.line(f'{len(changes)} change(s) applied and activated', 'green')
    return {'changes': _public(changes), 'changed': True}


@command('prices convert', "Google Play's own local price for every region, from one price",
         risk='read', needs=('play',),
         args=(Arg('amount', 'price, tax exclusive, e.g. 4.99', kind='positional', type=float),
               Arg('currency', 'currency of the amount', default='USD')),
         examples=('mkit prices convert 4.99',))
def prices_convert(ctx, args):
    svc, package = _svc(ctx)
    try:
        result = money.convert(svc, package, args.amount, args.currency)
    except Exception as e:
        raise auth.translate(e, 'Play') from None
    if not ctx.out.json:
        ctx.out.table([(r, v['currency'], v['amount']) for r, v in sorted(result.items())],
                      ('region', 'currency', 'amount'))
    return {'amount': args.amount, 'currency': args.currency, 'regions': result}
