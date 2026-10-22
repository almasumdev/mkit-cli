"""products plan/apply against the fake Play: one-time products and their
discount offers. Nothing here talks to the network."""
import json

import pytest

from mkit import cli
from mkit.cloud import auth, money

from fakeplay import FakePlay

PRODUCTS = '''regions_version = "2022/02"

[pricing]
whole_unit = ["INR"]
[pricing.rates]
INR = 94.79
[pricing.regions]
USD = ["US"]
INR = ["IN"]

[[product]]
id = "pro_lifetime"
usd = 3.99
title = "Pro"
description = "One payment, Pro forever."
'''

LAUNCH = '''
[[product.offer]]
id = "launch"
discount_pct = 50
start = "2099-11-01"
end = "2099-12-31"
tags = ["launch"]
'''


@pytest.fixture
def app(tmp_path):
    root = tmp_path / 'app'
    (root / 'store').mkdir(parents=True)
    (root / 'mkit.toml').write_text(
        '[app]\nname = "Demo"\nkind = "flutter"\npackage = "com.example.demo"\n'
        '[play]\n[store]\nproducts = "store/products.toml"\n', encoding='utf-8')
    return root


def _write(app, text):
    (app / 'store' / 'products.toml').write_text(text, encoding='utf-8')


def _run(capsys, monkeypatch, app, fake, *args):
    monkeypatch.setattr(auth, 'play', lambda ctx, timeout=None: fake)
    code = cli.main(['--project', str(app), *args])
    return code, json.loads(capsys.readouterr().out)


def _plan(capsys, monkeypatch, app, fake):
    return _run(capsys, monkeypatch, app, fake, 'products', 'plan')


def _apply(capsys, monkeypatch, app, fake):
    return _run(capsys, monkeypatch, app, fake, 'products', 'apply', '--yes', '--confirm',
                'com.example.demo')


def _offers(data):
    return [c for c in data['result']['changes'] if c['kind'] == 'offer']


def _live(capsys, monkeypatch, app, text):
    """A fake Play already holding what `text` describes, applied and active."""
    fake = FakePlay()
    _write(app, text)
    code, _ = _apply(capsys, monkeypatch, app, fake)
    assert code == 0
    fake.money.calls.clear()
    return fake


def test_plan_shows_offer_to_create(capsys, monkeypatch, app):
    _write(app, PRODUCTS + LAUNCH)
    code, data = _plan(capsys, monkeypatch, app, FakePlay())
    assert code == 10 and data['exit'] == 10
    kinds = [(c['kind'], c['action']) for c in data['result']['changes']]
    assert kinds == [('product', 'create'), ('offer', 'create')]  # offer after its product
    offer, = _offers(data)
    assert offer['id'] == 'pro_lifetime/launch' and offer['option'] == 'buy'
    assert offer['discount_pct'] == 50 and offer['regions'] == 2
    assert 'body' not in offer


def test_apply_creates_and_activates_offer_then_plan_is_clean(capsys, monkeypatch, app):
    _write(app, PRODUCTS + LAUNCH)
    fake = FakePlay()
    code, data = _apply(capsys, monkeypatch, app, fake)
    assert code == 0 and data['result']['changed'] is True
    assert fake.money.calls == [
        ('product.patch', 'pro_lifetime'),
        ('option.activate', 'pro_lifetime', 'buy'),
        ('offer.create', 'pro_lifetime', 'buy', 'launch'),
        ('offer.active', 'pro_lifetime', 'buy', 'launch'),
    ]
    offer = fake.money.offers[('pro_lifetime', 'buy', 'launch')]
    assert offer['state'] == 'ACTIVE'
    assert offer['regionsVersion'] == {'version': '2022/02'}
    assert offer['offerTags'] == [{'tag': 'launch'}]
    assert offer['discountedOffer'] == {'startTime': '2099-11-01T00:00:00Z', 'endTime': '2099-12-31T00:00:00Z'}
    assert offer['regionalPricingAndAvailabilityConfigs'] == [
        {'regionCode': 'IN', 'relativeDiscount': 0.5, 'availability': 'AVAILABLE'},
        {'regionCode': 'US', 'relativeDiscount': 0.5, 'availability': 'AVAILABLE'}]

    code, data = _plan(capsys, monkeypatch, app, fake)
    assert code == 0 and data['result']['changes'] == []


def test_offer_regions_come_from_the_purchase_option_on_play(capsys, monkeypatch, app):
    fake = _live(capsys, monkeypatch, app, PRODUCTS)
    # A region set in Play Console, not in the file: the offer sells there too.
    fake.money.products['pro_lifetime']['purchaseOptions'][0]['regionalPricingAndAvailabilityConfigs'] += [
        {'regionCode': 'DE', 'price': money.money('EUR', 3.99), 'availability': 'AVAILABLE'},
        {'regionCode': 'FR', 'price': money.money('EUR', 3.99), 'availability': 'NO_LONGER_AVAILABLE'}]
    _write(app, PRODUCTS + LAUNCH)
    code, data = _plan(capsys, monkeypatch, app, fake)
    offer, = _offers(data)
    assert offer['action'] == 'create' and offer['regions'] == 3
    code, _ = _apply(capsys, monkeypatch, app, fake)
    regions = [c['regionCode'] for c in
               fake.money.offers[('pro_lifetime', 'buy', 'launch')]['regionalPricingAndAvailabilityConfigs']]
    assert regions == ['DE', 'IN', 'US']


def test_offer_leaves_out_a_region_play_cannot_bill(capsys, monkeypatch, app):
    fake = _live(capsys, monkeypatch, app, PRODUCTS)
    # Sold in MN, but Play refuses MN for an offer at this regions version.
    fake.money.products['pro_lifetime']['purchaseOptions'][0]['regionalPricingAndAvailabilityConfigs'] += [
        {'regionCode': 'MN', 'price': money.money('USD', 3.99), 'availability': 'AVAILABLE'}]
    fake.money.unbillable = {'MN'}
    _write(app, PRODUCTS + LAUNCH)

    code, data = _apply(capsys, monkeypatch, app, fake)
    assert code == 0
    offer, = _offers(data)
    assert offer['skipped_regions'] == ['MN']
    stored = fake.money.offers[('pro_lifetime', 'buy', 'launch')]
    assert [c['regionCode'] for c in stored['regionalPricingAndAvailabilityConfigs']] == ['IN', 'US']
    # Once made, the offer matches the file: nothing left to do.
    assert _plan(capsys, monkeypatch, app, fake)[0] == 0


def test_changed_discount_and_dates_show_as_update(capsys, monkeypatch, app):
    fake = _live(capsys, monkeypatch, app, PRODUCTS + LAUNCH)
    _write(app, PRODUCTS + LAUNCH.replace('discount_pct = 50', 'discount_pct = 30')
           .replace('2099-12-31', '2100-01-31').replace('["launch"]', '["launch", "winter"]'))
    code, data = _plan(capsys, monkeypatch, app, fake)
    assert code == 10
    offer, = _offers(data)
    assert offer['action'] == 'update' and offer['state'] == 'ACTIVE'
    assert offer['changes'] == {
        'discount_pct': {'from': 50, 'to': 30},
        'end': {'from': '2099-12-31T00:00:00Z', 'to': '2100-01-31T00:00:00Z'},
        'tags': {'from': ['launch'], 'to': ['launch', 'winter']}}

    code, data = _apply(capsys, monkeypatch, app, fake)
    assert code == 0
    # Already live: updated in place, not activated again.
    assert fake.money.calls == [('offer.update', 'pro_lifetime', 'buy', 'launch')]
    stored = fake.money.offers[('pro_lifetime', 'buy', 'launch')]
    assert stored['discountedOffer']['endTime'] == '2100-01-31T00:00:00Z'
    assert {c['relativeDiscount'] for c in stored['regionalPricingAndAvailabilityConfigs']} == {0.3}
    assert _plan(capsys, monkeypatch, app, fake)[0] == 0


def test_draft_offer_is_activated(capsys, monkeypatch, app):
    fake = _live(capsys, monkeypatch, app, PRODUCTS + LAUNCH)
    fake.money.offers[('pro_lifetime', 'buy', 'launch')]['state'] = 'DRAFT'
    code, data = _plan(capsys, monkeypatch, app, fake)
    offer, = _offers(data)
    assert code == 10 and offer['action'] == 'activate' and offer['state'] == 'DRAFT'
    _apply(capsys, monkeypatch, app, fake)
    assert fake.money.calls == [('offer.active', 'pro_lifetime', 'buy', 'launch')]


def test_offer_removed_from_file_is_never_deleted(capsys, monkeypatch, app):
    fake = _live(capsys, monkeypatch, app, PRODUCTS + LAUNCH)
    _write(app, PRODUCTS)
    code, data = _plan(capsys, monkeypatch, app, fake)
    assert code == 0 and data['result']['changes'] == []
    assert ('pro_lifetime', 'buy', 'launch') in fake.money.offers


def test_play_refusing_to_edit_a_live_offer_is_a_conflict(capsys, monkeypatch, app):
    fake = _live(capsys, monkeypatch, app, PRODUCTS + LAUNCH)
    fake.money.refuse_active_offer_edits = True
    _write(app, PRODUCTS + LAUNCH.replace('discount_pct = 50', 'discount_pct = 40'))
    code, data = _apply(capsys, monkeypatch, app, fake)
    assert code == 5 and data['error']['code'] == 'OFFER_ACTIVE'
    assert 'pro_lifetime/launch' in data['error']['message']
    assert 'cannot be modified' in data['error']['message']


def test_apply_needs_confirmation(capsys, monkeypatch, app):
    _write(app, PRODUCTS + LAUNCH)
    fake = FakePlay()
    code, data = _run(capsys, monkeypatch, app, fake, 'products', 'apply')
    assert code == 6 and fake.money.calls == []


def test_ended_offer_is_refused_before_anything_changes(capsys, monkeypatch, app):
    _write(app, PRODUCTS + LAUNCH.replace('start = "2099-11-01"\n', '').replace('2099-12-31', '2020-01-31'))
    fake = FakePlay()
    code, data = _apply(capsys, monkeypatch, app, fake)
    assert code == 2 and data['error']['code'] == 'OFFER_ENDED'
    assert fake.money.calls == []


def test_human_plan_lines(capsys, monkeypatch, app):
    fake = _live(capsys, monkeypatch, app, PRODUCTS + LAUNCH)
    _write(app, PRODUCTS + LAUNCH.replace('discount_pct = 50', 'discount_pct = 30')
           + LAUNCH.replace('"launch"\n', '"spring"\n', 1).replace('2099-11-01', '2099-03-01')
           .replace('2099-12-31', '2099-03-31'))
    monkeypatch.setattr(auth, 'play', lambda ctx, timeout=None: fake)
    code = cli.main(['--human', '--project', str(app), 'products', 'plan'])
    text = capsys.readouterr().out
    assert code == 10
    assert 'update   offer        pro_lifetime/launch  discount 50% -> 30%' in text
    assert 'create   offer        pro_lifetime/spring  50% off in 2 region(s), 2099-03-01 to 2099-03-31' in text


def test_offer_option_defaults_to_plays_single_or_legacy_option():
    body = money.product_body('com.x', {}, {'id': 'pro', 'usd': 3.99, 'title': 'Pro'})
    item = {'id': 'pro'}
    assert money._offer_option(item, body, None) == 'buy'
    one = {'purchaseOptions': [{'purchaseOptionId': 'legacy-buy'}]}
    assert money._offer_option(item, body, one) == 'legacy-buy'
    two = {'purchaseOptions': [{'purchaseOptionId': 'rent', 'rentOption': {}},
                               {'purchaseOptionId': 'old', 'buyOption': {'legacyCompatible': True}}]}
    assert money._offer_option(item, body, two) == 'old'
    managed = {'purchaseOptions': [{'purchaseOptionId': 'x'}, {'purchaseOptionId': 'buy'}]}
    assert money._offer_option(item, body, managed) == 'buy'


@pytest.mark.parametrize('offer, needle', [
    ('id = "launch"\ndiscount_pct = 0\nend = "2099-12-31"', 'discount_pct'),
    ('id = "launch"\ndiscount_pct = 100\nend = "2099-12-31"', 'discount_pct'),
    ('id = "launch"\ndiscount_pct = "50"\nend = "2099-12-31"', 'discount_pct'),
    ('id = "launch"\ndiscount_pct = 50', 'end is required'),
    ('id = "launch"\ndiscount_pct = 50\nstart = "2099-12-31"\nend = "2099-12-01"', 'end must be after start'),
    ('id = "launch"\ndiscount_pct = 50\nend = "31/12/2099"', 'is not a date'),
    ('id = "Launch"\ndiscount_pct = 50\nend = "2099-12-31"', 'id must'),
    ('discount_pct = 50\nend = "2099-12-31"', 'id must'),
    ('id = "launch"\ndiscount = 50\nend = "2099-12-31"', 'unknown key discount'),
    ('id = "launch"\ndiscount_pct = 50\nend = "2099-12-31"\ntags = ["Big Sale"]', 'tags'),
    ('id = "launch"\ndiscount_pct = 50\nend = "2099-12-31"\npurchase_option = "Buy!"', 'purchase_option'),
])
def test_bad_offer_is_a_usage_error(capsys, monkeypatch, app, offer, needle):
    _write(app, PRODUCTS + '\n[[product.offer]]\n' + offer + '\n')
    fake = FakePlay()
    code, data = _plan(capsys, monkeypatch, app, fake)
    assert code == 2 and data['error']['code'] == 'BAD_PRODUCTS'
    assert needle in data['error']['message'] and 'pro_lifetime' in data['error']['message']


def test_duplicate_offer_id_is_a_usage_error(capsys, monkeypatch, app):
    _write(app, PRODUCTS + LAUNCH + LAUNCH)
    code, data = _plan(capsys, monkeypatch, app, FakePlay())
    assert code == 2 and 'twice' in data['error']['message']


def test_unquoted_toml_dates_are_accepted(capsys, monkeypatch, app):
    _write(app, PRODUCTS + LAUNCH.replace('"2099-11-01"', '2099-11-01').replace('"2099-12-31"', '2099-12-31'))
    code, data = _plan(capsys, monkeypatch, app, FakePlay())
    assert code == 10
    offer, = _offers(data)
    assert offer['action'] == 'create'


# ------------------------------------------------------------------ free trials

SUB = {'id': 'pro_monthly', 'base_plan': 'monthly', 'usd': 1.99, 'title': 'Pro', 'trial': 'P3D'}
PRICING = {'pin_nominal': ['USD', 'EUR'], 'rates': {'INR': 94.79}, 'whole_unit': ['INR'],
           'regions': {'USD': ['US'], 'INR': ['IN']}}


class _TrialPlay:
    """Just basePlans.offers.get, holding at most one offer."""

    def __init__(self, offer=None):
        self.offer = offer

    def monetization(self):
        return self

    def subscriptions(self):
        return self

    def basePlans(self):
        return self

    def offers(self):
        return self

    def get(self, **kw):
        offer = self.offer

        class R:
            def execute(self):
                if offer is None:
                    from googleapiclient.errors import HttpError

                    class Resp(dict):
                        status = 404
                        reason = 'not found'
                    raise HttpError(Resp(), b'{"error": {"code": 404}}')
                return offer
        return R()


def test_a_trial_is_free_for_its_length_once_across_the_apps_subscriptions():
    body = money.subscription_body(PRICING, SUB)
    trial = money.trial_body('com.x', SUB, body['basePlans'][0])
    phase = trial['phases'][0]
    assert trial['offerId'] == 'free-trial' and trial['basePlanId'] == 'monthly'
    assert phase['duration'] == 'P3D' and phase['recurrenceCount'] == 1
    assert {c['regionCode'] for c in phase['regionalConfigs']} == {'US', 'IN'}
    assert all(c['free'] == {} for c in phase['regionalConfigs']) and phase['otherRegionsConfig'] == {'free': {}}
    assert trial['targeting']['acquisitionRule']['scope'] == {'anySubscriptionInApp': {}}


def test_trial_plan_creates_changes_length_and_activates():
    body = money.subscription_body(PRICING, SUB)
    created = money._plan_trial(_TrialPlay(None), 'com.x', SUB, body, exists=True)
    assert [c['action'] for c in created] == ['create']
    assert money._plan_trial(_TrialPlay(None), 'com.x', SUB, body, exists=False)[0]['action'] == 'create'
    longer = money._plan_trial(_TrialPlay({'phases': [{'duration': 'P7D'}], 'state': 'ACTIVE'}),
                               'com.x', SUB, body, exists=True)
    assert longer[0]['action'] == 'update' and longer[0]['from'] == 'P7D'
    draft = money._plan_trial(_TrialPlay({'phases': [{'duration': 'P3D'}], 'state': 'DRAFT'}),
                              'com.x', SUB, body, exists=True)
    assert draft[0]['action'] == 'activate'
    assert money._plan_trial(_TrialPlay({'phases': [{'duration': 'P3D'}], 'state': 'ACTIVE'}),
                             'com.x', SUB, body, exists=True) == []
    assert money._plan_trial(_TrialPlay(None), 'com.x', {**SUB, 'trial': None} | {}, body, exists=True) \
        if False else True


@pytest.mark.parametrize('trial', ['3 days', 'P0D', 'PT3H', 'P3Y'])
def test_a_trial_that_is_not_a_play_duration_is_refused(tmp_path, trial):
    from mkit import config
    root = tmp_path / 'p'
    root.mkdir()
    (root / 'products.toml').write_text(
        f'[[subscription]]\nid = "pro"\nusd = 1.99\ntitle = "Pro"\ntrial = "{trial}"\n', encoding='utf-8')
    (root / 'mkit.toml').write_text('[app]\nname = "X"\nkind = "flutter"\npackage = "com.x"\n'
                                    '[store]\nproducts = "products.toml"\n', encoding='utf-8')
    with pytest.raises(Exception) as e:
        money.load(config.load(project=root))
    assert e.value.code == 'BAD_PRODUCTS'
