"""In-app products and subscriptions, described in a file and applied to Play.

The file is [store] products in mkit.toml (e.g. store/products.toml):

    regions_version = "2022/02"   # pinned: a region Google adds later does not re-price anything

    [pricing]                     # how an anchor USD price becomes local prices
    pin_nominal = ["USD", "EUR", "GBP"]   # 4.99 stays 4.99 in these
    whole_unit  = ["INR", "BDT"]          # prices like 499, not 4.99
    [pricing.rates]                        # units per USD, refresh by hand
    EUR = 0.86
    INR = 94.79
    [pricing.regions]                      # currency -> Play region codes set explicitly
    EUR = ["DE", "FR"]
    INR = ["IN"]

    [[product]]                   # one-time product
    id = "pro_lifetime"
    usd = 4.99
    title = "Pro"
    description = "One payment, Pro forever."

    [[product.offer]]             # a discount offer on that product's purchase option
    id = "launch"                 # offerId: lower-case letters, digits, hyphens
    discount_pct = 50             # 1..99, the same relative discount in every region it sells in
    start = "2026-11-01"          # optional; UTC midnight
    end = "2026-12-31"            # required
    tags = ["launch"]             # optional offer tags for the billing library
    purchase_option = "buy"       # optional; default: the product's own (single/legacy) option

    [[subscription]]
    id = "pro_monthly"
    base_plan = "monthly"
    period = "P1M"
    usd = 0.99
    grace = "P7D"
    account_hold = "P30D"
    title = "Pro, monthly"
    description = "Cancel any time."
    benefits = ["Unlimited layouts"]

Every price is the smallest amount ending in 99 that is worth at least the
anchor: rounding up is what makes "never below the dollar price" true by
construction. Regions not listed get Play's own conversion from the USD/EUR
anchor. apply never deletes anything: not products, not offers.

Offers are created in DRAFT and then activated, like purchase options. An
offer is sold in every region its purchase option is available in, at the
same relative discount.

Uses monetization.onetimeproducts (the legacy inappproducts endpoint is
refused for new work), monetization.onetimeproducts.purchaseOptions.offers
and monetization.subscriptions.
"""
import datetime as _dt
import re
import tomllib

from ..errors import Conflict, UsageError
from . import auth

DEFAULT_REGIONS_VERSION = '2022/02'


def load(project):
    path = project.path('store.products')
    if not path or not path.is_file():
        raise UsageError(f'products file not found ({path or "set products under [store]"})',
                         code='NO_PRODUCTS')
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    data.setdefault('pricing', {})
    for kind in ('product', 'subscription'):
        for item in data.get(kind, []):
            for key in ('id', 'usd', 'title'):
                if key not in item:
                    raise UsageError(f'{path.name}: a [[{kind}]] has no {key}', code='BAD_PRODUCTS')
    for item in data.get('product', []):
        _check_offers(path.name, item)
    for item in data.get('subscription', []):
        if 'offer' in item:
            raise UsageError(f'{path.name}: [[subscription.offer]] is not supported; offers are for '
                             f'one-time products ([[product.offer]]); a free trial is `trial = "P7D"`',
                             code='BAD_PRODUCTS')
        if 'trial' in item and not TRIAL_RE.match(str(item['trial'])):
            raise UsageError(f'{path.name}: {item["id"]}: trial {item["trial"]!r} is not a duration '
                             f'like "P3D", "P1W" or "P1M"', code='BAD_PRODUCTS')
        if 'trial_id' in item and not ID_RE.match(str(item['trial_id'])):
            raise UsageError(f'{path.name}: {item["id"]}: trial_id {item["trial_id"]!r}: a-z, 0-9 and '
                             f'hyphens, starting with a letter or digit', code='BAD_PRODUCTS')
    return data


# offerId and purchaseOptionId: Play's own rule, up to 63 characters.
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
# Offer tags: RFC-1034 style, up to 20 characters.
TAG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,19}$')
OFFER_KEYS = {'id', 'discount_pct', 'start', 'end', 'tags', 'purchase_option'}
# A free trial's length, as Play takes it: days, weeks or months.
TRIAL_RE = re.compile(r'^P[1-9][0-9]{0,2}[DWM]$')
TRIAL_ID = 'free-trial'
TRIAL_MASK = 'phases,regionalConfigs,otherRegionsConfig,targeting,offerTags'


def parse_time(value):
    """A products-file date or datetime as an aware UTC datetime.
    "2026-12-31" (or an unquoted TOML date) is UTC midnight."""
    if isinstance(value, _dt.datetime):
        moment = value
    elif isinstance(value, _dt.date):
        moment = _dt.datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            moment = _dt.datetime.fromisoformat(text)
        else:
            moment = _dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    else:
        raise ValueError(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return moment.astimezone(_dt.timezone.utc)


def rfc3339(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def _check_offers(name, item):
    """Refuse a malformed [[product.offer]] before anything talks to Play."""
    offers = item.get('offer', [])
    if not isinstance(offers, list):
        raise UsageError(f'{name}: product {item["id"]}: write offers as [[product.offer]] tables',
                         code='BAD_PRODUCTS')
    seen = set()
    for offer in offers:
        where = f'{name}: product {item["id"]}, offer {offer.get("id", "?")}'

        def bad(problem):
            return UsageError(f'{where}: {problem}', code='BAD_PRODUCTS')
        unknown = sorted(set(offer) - OFFER_KEYS)
        if unknown:
            raise bad(f'unknown key {", ".join(unknown)} (allowed: {", ".join(sorted(OFFER_KEYS))})')
        oid = offer.get('id')
        if not isinstance(oid, str) or not ID_RE.match(oid):
            raise bad('id must start with a lower-case letter or digit and use only a-z, 0-9 and '
                      'hyphens, up to 63 characters')
        pct = offer.get('discount_pct')
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 1 <= pct <= 99:
            raise bad('discount_pct must be a number from 1 to 99 (percent off)')
        if 'end' not in offer:
            raise bad('end is required for a discount offer ("YYYY-MM-DD", UTC midnight)')
        times = {}
        for key in ('start', 'end'):
            if key in offer:
                try:
                    times[key] = parse_time(offer[key])
                except (TypeError, ValueError):
                    raise bad(f'{key} = {offer[key]!r} is not a date ("YYYY-MM-DD") or ISO datetime') from None
        if 'start' in times and times['end'] <= times['start']:
            raise bad('end must be after start')
        tags = offer.get('tags', [])
        if not isinstance(tags, list) or len(tags) > 20 or not all(
                isinstance(t, str) and TAG_RE.match(t) for t in tags):
            raise bad('tags must be a list of up to 20 tags of a-z, 0-9 and hyphens, 20 characters each')
        option = offer.get('purchase_option')
        if option is not None and (not isinstance(option, str) or not ID_RE.match(option)):
            raise bad('purchase_option must be a purchase option id (a-z, 0-9, hyphens)')
        key = (option, oid)
        if key in seen:
            raise bad('the same offer id appears twice')
        seen.add(key)


def price_for(pricing, currency, usd):
    """The smallest price in `currency` ending in 99 worth at least `usd`."""
    if currency in pricing.get('pin_nominal', ['USD', 'EUR', 'GBP']):
        return round(usd, 2)
    rates = pricing.get('rates', {})
    if currency not in rates:
        raise UsageError(f'no rate for {currency} under [pricing.rates]', code='BAD_PRODUCTS')
    want = usd * rates[currency]
    if currency in pricing.get('whole_unit', []):
        hundreds = 0
        while hundreds * 100 + 99 < want:
            hundreds += 1
        return float(hundreds * 100 + 99)
    units = 0
    while units + 0.99 < want - 1e-9:
        units += 1
    return round(units + 0.99, 2)


def money(currency, amount):
    units = int(amount)
    return {'currencyCode': currency, 'units': str(units), 'nanos': int(round((amount - units) * 1e9))}


def amount_of(m):
    return round(int(m.get('units', 0) or 0) + (m.get('nanos', 0) or 0) / 1e9, 2)


def regional_prices(pricing, usd):
    """{region: (currency, amount)} for every explicitly listed region."""
    out = {}
    for currency, regions in pricing.get('regions', {}).items():
        amount = price_for(pricing, currency, usd)
        for region in regions:
            out[region] = (currency, amount)
    return out


def _listings(item):
    if 'listings' in item:
        return [dict(languageCode=lang, **v) for lang, v in item['listings'].items()]
    listing = {'languageCode': item.get('language', 'en-US'), 'title': item['title'],
               'description': item.get('description', '')}
    if item.get('benefits'):
        listing['benefits'] = item['benefits']
    return [listing]


def product_body(package, pricing, item):
    usd_anchor = price_for(pricing, 'USD', item['usd'])
    eur_anchor = price_for(pricing, 'EUR', item['usd'])
    return {
        'packageName': package, 'productId': item['id'], 'listings': _listings(item),
        'purchaseOptions': [{
            'purchaseOptionId': item.get('option', 'buy'), 'state': 'ACTIVE',
            # Legacy-compatible so an older Billing Library still sees a buyable product.
            'buyOption': {'legacyCompatible': True, 'multiQuantityEnabled': False},
            'regionalPricingAndAvailabilityConfigs': [
                {'regionCode': r, 'price': money(c, a), 'availability': 'AVAILABLE'}
                for r, (c, a) in sorted(regional_prices(pricing, item['usd']).items())],
            # Without this, a market Google adds later is silently unbuyable.
            'newRegionsConfig': {'usdPrice': money('USD', usd_anchor), 'eurPrice': money('EUR', eur_anchor),
                                 'availability': 'AVAILABLE'},
        }],
    }


def subscription_body(pricing, item):
    usd_anchor = price_for(pricing, 'USD', item['usd'])
    eur_anchor = price_for(pricing, 'EUR', item['usd'])
    return {
        'productId': item['id'], 'listings': _listings(item),
        'basePlans': [{
            'basePlanId': item.get('base_plan', 'monthly'), 'state': 'ACTIVE',
            'autoRenewingBasePlanType': {
                'billingPeriodDuration': item.get('period', 'P1M'),
                'gracePeriodDuration': item.get('grace', 'P7D'),
                'accountHoldDuration': item.get('account_hold', 'P30D'),
                'resubscribeState': 'RESUBSCRIBE_STATE_ACTIVE',
                'prorationMode': 'SUBSCRIPTION_PRORATION_MODE_CHARGE_ON_NEXT_BILLING_DATE',
                'legacyCompatible': True,
            },
            'regionalConfigs': [{'regionCode': r, 'price': money(c, a), 'newSubscriberAvailability': True}
                                for r, (c, a) in sorted(regional_prices(pricing, item['usd']).items())],
            'otherRegionsConfig': {'usdPrice': money('USD', usd_anchor), 'eurPrice': money('EUR', eur_anchor),
                                   'newSubscriberAvailability': True},
        }],
    }


def trial_body(package, item, base):
    """The free trial on a subscription's base plan: free for `trial`, then the
    base plan's price, offered in every region the base plan is sold in, once
    per person across all of this app's subscriptions (a trial on monthly and
    on yearly is still one trial)."""
    plan_id = base['basePlanId']
    regions = [c['regionCode'] for c in base['regionalConfigs']]
    return {
        'packageName': package, 'productId': item['id'], 'basePlanId': plan_id,
        'offerId': item.get('trial_id', TRIAL_ID), 'offerTags': [{'tag': 'trial'}],
        'phases': [{'recurrenceCount': 1, 'duration': item['trial'],
                    'regionalConfigs': [{'regionCode': r, 'free': {}} for r in regions],
                    'otherRegionsConfig': {'free': {}}}],
        'regionalConfigs': [{'regionCode': r, 'newSubscriberAvailability': True} for r in regions],
        'otherRegionsConfig': {'otherRegionsNewSubscriberAvailability': True},
        'targeting': {'acquisitionRule': {'scope': {'anySubscriptionInApp': {}}}},
    }


def _remote_trial(svc, package, product_id, plan_id, offer_id):
    from googleapiclient.errors import HttpError
    offers = svc.monetization().subscriptions().basePlans().offers()
    try:
        return offers.get(packageName=package, productId=product_id, basePlanId=plan_id,
                          offerId=offer_id).execute()
    except HttpError as e:
        if auth.status_of(e) == 404:
            return None
        raise


def _plan_trial(svc, package, item, body, exists):
    """The trial's change, if any: create, change its length, or activate."""
    if 'trial' not in item:
        return []
    base = body['basePlans'][0]
    trial = trial_body(package, item, base)
    current = _remote_trial(svc, package, item['id'], base['basePlanId'], trial['offerId']) if exists else None
    change = {'kind': 'trial', 'id': f'{item["id"]}/{trial["offerId"]}', 'product': item['id'],
              'plan': base['basePlanId'], 'offer': trial['offerId'], 'trial': item['trial'], 'body': trial}
    if current is None:
        return [dict(change, action='create')]
    have = [p.get('duration') for p in current.get('phases', [])]
    if have != [item['trial']]:
        return [dict(change, action='update', state=current.get('state'), **{'from': have[0] if have else None})]
    if current.get('state') != 'ACTIVE':
        return [dict(change, action='activate', state=current.get('state'))]
    return []


def _apply_trial(svc, package, version, c):
    offers = svc.monetization().subscriptions().basePlans().offers()
    ids = dict(packageName=package, productId=c['product'], basePlanId=c['plan'], offerId=c['offer'])
    if c['action'] == 'create':
        auth.retry(lambda: offers.create(regionsVersion_version=version, body=c['body'], **ids), c['id'])
    elif c['action'] == 'update':
        auth.retry(lambda: offers.patch(updateMask=TRIAL_MASK, regionsVersion_version=version,
                                        body=c['body'], **ids), c['id'])
    auth.retry(lambda: offers.activate(body=dict(ids), **ids), f'activate {c["id"]}')


def _get_product(svc, package, pid):
    from googleapiclient.errors import HttpError
    try:
        return svc.monetization().onetimeproducts().get(packageName=package, productId=pid).execute()
    except HttpError as e:
        if auth.status_of(e) == 404:
            return None
        raise


def _subscriptions(svc, package):
    out, token = {}, None
    while True:
        resp = svc.monetization().subscriptions().list(packageName=package, pageToken=token).execute()
        for s in resp.get('subscriptions', []):
            out[s['productId']] = s
        token = resp.get('nextPageToken')
        if not token:
            return out


def list_remote(svc, package):
    products, token = [], None
    while True:
        resp = svc.monetization().onetimeproducts().list(packageName=package, pageToken=token).execute()
        products += resp.get('oneTimeProducts', [])
        token = resp.get('nextPageToken')
        if not token:
            break
    return products, list(_subscriptions(svc, package).values())


def _price_diff(current_configs, desired_configs, key):
    have = {c['regionCode']: amount_of(c.get('price', {})) for c in current_configs or []}
    want = {c['regionCode']: amount_of(c['price']) for c in desired_configs}
    return {r: {'from': have.get(r), 'to': a} for r, a in want.items() if have.get(r) != a}


# ------------------------------------------------------------------ offers

OFFER_MASK = 'offerTags,regionalPricingAndAvailabilityConfigs,discountedOffer'
# A purchase option region an offer can be sold in.
OFFERABLE = ('AVAILABLE', 'AVAILABLE_FOR_OFFERS_ONLY')


def _offer_option(item, body, current):
    """The purchase option an offer attaches to: the one the offer names, else
    the one this file manages when Play has it (or is about to), else Play's
    only option, else its legacy-compatible buy option."""
    managed = body['purchaseOptions'][0]['purchaseOptionId']
    options = (current or {}).get('purchaseOptions', []) or []
    ids = [o.get('purchaseOptionId') for o in options]
    if 'option' in item or not options or managed in ids:
        return managed
    if len(options) == 1:
        return ids[0]
    legacy = [o.get('purchaseOptionId') for o in options
              if (o.get('buyOption') or {}).get('legacyCompatible')]
    return legacy[0] if legacy else managed


def _offer_regions(option_id, body, current):
    """Every region the purchase option sells in, after this apply."""
    regions = set()
    for o in (current or {}).get('purchaseOptions', []) or []:
        if o.get('purchaseOptionId') == option_id:
            regions |= {c['regionCode'] for c in o.get('regionalPricingAndAvailabilityConfigs', []) or []
                        if c.get('availability') in OFFERABLE}
    desired = body['purchaseOptions'][0]
    if desired['purchaseOptionId'] == option_id:
        regions |= {c['regionCode'] for c in desired['regionalPricingAndAvailabilityConfigs']}
    return sorted(regions)


def offer_body(package, product_id, option_id, offer, regions):
    discount = round(offer['discount_pct'] / 100, 4)
    window = {'endTime': rfc3339(parse_time(offer['end']))}
    if 'start' in offer:
        window['startTime'] = rfc3339(parse_time(offer['start']))
    return {
        'packageName': package, 'productId': product_id, 'purchaseOptionId': option_id,
        'offerId': offer['id'],
        'offerTags': [{'tag': t} for t in offer.get('tags', [])],
        # relativeDiscount is the fraction off: 0.5 turns $12 into $6.
        'regionalPricingAndAvailabilityConfigs': [
            {'regionCode': r, 'relativeDiscount': discount, 'availability': 'AVAILABLE'} for r in regions],
        'discountedOffer': window,
    }


def _remote_offers(svc, package, product_id, option_id):
    offers = svc.monetization().onetimeproducts().purchaseOptions().offers()
    out, token = {}, None
    while True:
        resp = offers.list(packageName=package, productId=product_id, purchaseOptionId=option_id,
                           pageSize=1000, pageToken=token).execute()
        for o in resp.get('oneTimeProductOffers', []):
            out[o['offerId']] = o
        token = resp.get('nextPageToken')
        if not token:
            return out


def _time_of(value):
    try:
        return parse_time(value) if value else None
    except (TypeError, ValueError):
        return None


def _pct(value):
    """A percentage as 50, not 50.0; 12.5 stays 12.5."""
    value = round(float(value), 2)
    return int(value) if value == int(value) else value


def _discount_of(current):
    """The relative discount the remote offer uses, as whole percent, or the
    set of them when regions differ; None when any region is not relative."""
    values = set()
    for c in current.get('regionalPricingAndAvailabilityConfigs', []) or []:
        if c.get('availability', 'AVAILABLE') != 'AVAILABLE':
            continue
        d = c.get('relativeDiscount')
        values.add(None if d is None else _pct(float(d) * 100))
    if len(values) == 1:
        return values.pop()
    return None if None in values or not values else sorted(values)


def _offer_diff(current, body, offer, priced=()):
    """What differs between Play's offer and the file's: {field: {from, to}}.

    A region missing from the offer counts only when the file prices it
    (`priced`). One the purchase option has from Play alone may be one Play
    will not bill at the file's regions version (see _send_offer), so it
    would never stop showing; it is still sent with any other change."""
    diff = {}
    want_pct = _pct(offer['discount_pct'])
    have_pct = _discount_of(current)
    have = {c['regionCode']: c for c in current.get('regionalPricingAndAvailabilityConfigs', []) or []}
    missing, wrong = [], []
    for c in body['regionalPricingAndAvailabilityConfigs']:
        h = have.get(c['regionCode'])
        if h is None:
            if c['regionCode'] in priced:
                missing.append(c['regionCode'])
        elif (h.get('availability') != 'AVAILABLE' or h.get('relativeDiscount') is None
              or abs(float(h['relativeDiscount']) - c['relativeDiscount']) > 1e-6):
            wrong.append(c['regionCode'])
    if have_pct != want_pct or wrong:
        diff['discount_pct'] = {'from': have_pct, 'to': want_pct}
        if have_pct == want_pct:
            diff['discount_pct']['regions'] = wrong
    if missing:
        diff['regions'] = {'added': missing}
    window = current.get('discountedOffer') or {}
    for key, field in (('start', 'startTime'), ('end', 'endTime')):
        if key not in offer:
            continue  # start left to Play when the file does not set it
        want = parse_time(offer[key])
        if _time_of(window.get(field)) != want:
            diff[key] = {'from': window.get(field), 'to': rfc3339(want)}
    have_tags = sorted(t.get('tag') for t in current.get('offerTags', []) or [])
    want_tags = sorted(offer.get('tags', []))
    if have_tags != want_tags:
        diff['tags'] = {'from': have_tags, 'to': want_tags}
    return diff


def _plan_offers(svc, package, item, body, current, now):
    offers = item.get('offer', [])
    if not offers:
        return []
    changes = []
    remote_by_option = {}
    for offer in offers:
        option_id = offer.get('purchase_option') or _offer_option(item, body, current)
        regions = _offer_regions(option_id, body, current)
        if not regions:
            raise UsageError(f'offer {item["id"]}/{offer["id"]}: purchase option {option_id} is not available '
                             f'in any region on Play (does it exist?), so the offer could not be sold anywhere',
                             code='NO_OFFER_REGIONS')
        if option_id not in remote_by_option:
            known = any(o.get('purchaseOptionId') == option_id
                        for o in (current or {}).get('purchaseOptions', []) or [])
            remote_by_option[option_id] = _remote_offers(svc, package, item['id'], option_id) if known else {}
        have = remote_by_option[option_id].get(offer['id'])
        wanted = offer_body(package, item['id'], option_id, offer, regions)
        base = {'kind': 'offer', 'id': f'{item["id"]}/{offer["id"]}', 'product': item['id'],
                'option': option_id, 'offer': offer['id'], 'discount_pct': offer['discount_pct'],
                'body': wanted}
        if have is None:
            change = dict(base, action='create', state=None, regions=len(regions))
        else:
            desired = body['purchaseOptions'][0]
            priced = ({c['regionCode'] for c in desired['regionalPricingAndAvailabilityConfigs']}
                      if desired['purchaseOptionId'] == option_id else set())
            diff = _offer_diff(have, wanted, offer, priced)
            state = have.get('state')
            if diff:
                change = dict(base, action='update', changes=diff, state=state)
            elif state != 'ACTIVE':
                change = dict(base, action='activate', changes={}, state=state)
            else:
                continue
        if change['action'] != 'activate' and parse_time(offer['end']) <= now:
            raise UsageError(f'offer {change["id"]}: end {offer["end"]} has already passed; '
                             f'set a future end or remove the offer from the file',
                             code='OFFER_ENDED')
        changes.append(change)
    return changes


_UNBILLABLE = re.compile(r'Region code (\w+) is not billable')


def _send_offer(offers, path, request, c):
    """Sends one offer, leaving out a region Play says is not billable at the
    file's regions version (a product can sell in a region added to Play after
    that version, which an offer pinned to it cannot name). The regions left
    out are recorded on the change as `skipped_regions`."""
    from googleapiclient.errors import HttpError
    configs = request['oneTimeProductOffer'].setdefault('regionalPricingAndAvailabilityConfigs', [])
    for _ in range(len(configs) + 1):
        try:
            return auth.retry(lambda: offers.batchUpdate(body={'requests': [request]}, **path),
                              f'offer {c["id"]}')
        except HttpError as e:
            m = _UNBILLABLE.search(auth.api_message(e) or '')
            if auth.status_of(e) != 400 or not m:
                raise
            region = m.group(1)
            kept = [r for r in configs if r.get('regionCode') != region]
            if len(kept) == len(configs):
                raise
            configs[:] = kept
            c.setdefault('skipped_regions', []).append(region)
    raise RuntimeError(f'offer {c["id"]}: no billable region left')


def _apply_offer(svc, package, version, c):
    offers = svc.monetization().onetimeproducts().purchaseOptions().offers()
    path = dict(packageName=package, productId=c['product'], purchaseOptionId=c['option'])
    if c['action'] in ('create', 'update'):
        request = {'oneTimeProductOffer': c['body'], 'regionsVersion': {'version': version},
                   'updateMask': OFFER_MASK, 'allowMissing': True}
        try:
            _send_offer(offers, path, request, c)
        except Exception as e:
            from googleapiclient.errors import HttpError
            if (c['action'] == 'update' and c.get('state') == 'ACTIVE' and isinstance(e, HttpError)
                    and auth.status_of(e) in (400, 409, 412)):
                raise Conflict(
                    f'Play refused to change the active offer {c["id"]}: {auth.api_message(e)}',
                    hint='Play may not allow editing a live offer. Deactivate it in Play Console and '
                         'give the new terms a new offer id, or put the file back to the live terms.',
                    code='OFFER_ACTIVE') from None
            raise
    if c.get('state') != 'ACTIVE':
        auth.retry(lambda: offers.batchUpdateStates(body={'requests': [{'activateOneTimeProductOfferRequest': {
            'packageName': package, 'productId': c['product'], 'purchaseOptionId': c['option'],
            'offerId': c['offer']}}]}, **path), f'activate {c["id"]}')


# ------------------------------------------------------------------ plan / apply

def plan(svc, package, data, now=None):
    pricing = data['pricing']
    now = now or _dt.datetime.now(_dt.timezone.utc)
    subs = _subscriptions(svc, package)
    changes, offer_changes = [], []
    for item in data.get('product', []):
        body = product_body(package, pricing, item)
        current = _get_product(svc, package, item['id'])
        offer_changes += _plan_offers(svc, package, item, body, current, now)
        if current is None:
            changes.append({'kind': 'product', 'id': item['id'], 'action': 'create', 'body': body})
            continue
        option = next((o for o in current.get('purchaseOptions', [])
                       if o.get('purchaseOptionId') == body['purchaseOptions'][0]['purchaseOptionId']), {})
        prices = _price_diff(option.get('regionalPricingAndAvailabilityConfigs'),
                             body['purchaseOptions'][0]['regionalPricingAndAvailabilityConfigs'], 'price')
        listing = [l for l in body['listings'] if l not in current.get('listings', [])]
        if prices or listing or option.get('state') != 'ACTIVE':
            changes.append({'kind': 'product', 'id': item['id'], 'action': 'update', 'prices': prices,
                            'listings': [l['languageCode'] for l in listing],
                            'state': option.get('state'), 'body': body})
    for item in data.get('subscription', []):
        body = subscription_body(pricing, item)
        current = subs.get(item['id'])
        offer_changes += _plan_trial(svc, package, item, body, exists=current is not None)
        if current is None:
            changes.append({'kind': 'subscription', 'id': item['id'], 'action': 'create', 'body': body})
            continue
        plan_id = body['basePlans'][0]['basePlanId']
        base = next((b for b in current.get('basePlans', []) if b.get('basePlanId') == plan_id), {})
        prices = _price_diff(base.get('regionalConfigs'), body['basePlans'][0]['regionalConfigs'], 'price')
        listing = [l for l in body['listings'] if l not in current.get('listings', [])]
        if prices or listing or base.get('state') != 'ACTIVE':
            changes.append({'kind': 'subscription', 'id': item['id'], 'action': 'update', 'prices': prices,
                            'listings': [l['languageCode'] for l in listing],
                            'state': base.get('state'), 'body': body})
    # Offers last: apply needs their product and purchase option in place first.
    return changes + offer_changes


def apply(svc, package, data, changes):
    """Create or update, then activate: Play creates purchase options and base
    plans in DRAFT whatever the body says, and a draft looks present but cannot
    be bought."""
    version = data.get('regions_version', DEFAULT_REGIONS_VERSION)
    mono = svc.monetization()
    for c in changes:
        body = c['body']
        if c['kind'] == 'offer':
            _apply_offer(svc, package, version, c)
        elif c['kind'] == 'trial':
            _apply_trial(svc, package, version, c)
        elif c['kind'] == 'product':
            auth.retry(lambda: mono.onetimeproducts().patch(
                packageName=package, productId=c['id'], allowMissing=True,
                updateMask='listings,purchaseOptions', regionsVersion_version=version, body=body), c['id'])
            option = body['purchaseOptions'][0]['purchaseOptionId']
            auth.retry(lambda: mono.onetimeproducts().purchaseOptions().batchUpdateStates(
                packageName=package, productId=c['id'], body={'requests': [{'activatePurchaseOptionRequest': {
                    'packageName': package, 'productId': c['id'], 'purchaseOptionId': option}}]}),
                f'activate {c["id"]}')
        else:
            if c['action'] == 'create':
                auth.retry(lambda: mono.subscriptions().create(
                    packageName=package, productId=c['id'], regionsVersion_version=version, body=body), c['id'])
            else:
                auth.retry(lambda: mono.subscriptions().patch(
                    packageName=package, productId=c['id'], updateMask='listings,basePlans',
                    regionsVersion_version=version, body=body), c['id'])
            plan_id = body['basePlans'][0]['basePlanId']
            auth.retry(lambda: mono.subscriptions().basePlans().activate(
                packageName=package, productId=c['id'], basePlanId=plan_id,
                body={'packageName': package, 'productId': c['id'], 'basePlanId': plan_id}),
                f'activate {c["id"]}/{plan_id}')


def convert(svc, package, amount, currency='USD'):
    units = int(amount)
    body = {'price': {'currencyCode': currency, 'units': str(units),
                      'nanos': int(round((amount - units) * 1e9))}}
    resp = auth.retry(lambda: svc.monetization().convertRegionPrices(packageName=package, body=body),
                      'convert prices')
    return {region: {'currency': v['price']['currencyCode'], 'amount': amount_of(v['price'])}
            for region, v in resp.get('convertedRegionPrices', {}).items()}
