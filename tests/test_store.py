import pytest

from mkit import aso, config
from mkit.cloud import money, store


def _project(tmp_path, toml, files=None):
    root = tmp_path / 'p'
    root.mkdir()
    for rel, content in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    (root / 'mkit.toml').write_text('[app]\nname = "X"\nkind = "flutter"\npackage = "com.x"\n' + toml,
                                    encoding='utf-8')
    return config.load(project=root)


LISTING = 'Title\n```\nMy App\n```\nShort\n```\nA short line\n```\nFull\n```\nLong text\nmore\n```\n'


def test_listing_text_maps_one_file_to_several_locales(tmp_path):
    p = _project(tmp_path, '[store]\nlisting_dir = "l"\n[store.locales]\nes = ["es-419", "es-ES"]\n',
                 {'l/es.md': LISTING})
    text = store.desired_text(p)
    assert set(text) == {'es-419', 'es-ES'}
    assert text['es-ES'] == {'title': 'My App', 'shortDescription': 'A short line',
                             'fullDescription': 'Long text\nmore'}


def test_listing_title_over_limit_is_refused(tmp_path):
    p = _project(tmp_path, '[store]\nlisting_dir = "l"\n[store.locales]\nen = "en-US"\n',
                 {'l/en.md': LISTING.replace('My App', 'x' * 31)})
    with pytest.raises(Exception) as e:
        store.desired_text(p)
    assert e.value.code == 'LISTING_TOO_LONG'


def test_datasafety_flags_blank_required(tmp_path):
    csv = ('Question ID (machine readable),Response ID (machine readable),Response value,'
           'Answer requirement,Human-friendly question label\n'
           'PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA,,,REQUIRED,Does your app collect?\n')
    p = _project(tmp_path, '[store]\ndatasafety = "ds.csv"\n', {'ds.csv': csv})
    info = store.read_datasafety(p)
    assert info['required_blank'] == ['PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA']


PRICING = {'pin_nominal': ['USD', 'EUR', 'GBP'], 'whole_unit': ['INR', 'BDT'],
           'rates': {'INR': 94.79, 'BDT': 123.03, 'JPY': 150.0},
           'regions': {'USD': ['US'], 'INR': ['IN']}}


def test_prices_end_in_99_and_never_below_anchor():
    assert money.price_for(PRICING, 'USD', 4.99) == 4.99
    assert money.price_for(PRICING, 'EUR', 4.99) == 4.99
    inr = money.price_for(PRICING, 'INR', 4.99)
    assert inr == 499.0 and inr / 94.79 >= 4.99
    assert money.price_for(PRICING, 'BDT', 0.99) == 199.0
    jpy = money.price_for(PRICING, 'JPY', 4.99)
    assert str(jpy).endswith('.99') and jpy / 150 >= 4.99


def test_money_units_and_nanos_round_trip():
    m = money.money('USD', 4.99)
    assert m == {'currencyCode': 'USD', 'units': '4', 'nanos': 990000000}
    assert money.amount_of(m) == 4.99


def test_product_body_prices_every_listed_region():
    body = money.product_body('com.x', PRICING, {'id': 'pro', 'usd': 4.99, 'title': 'Pro'})
    configs = body['purchaseOptions'][0]['regionalPricingAndAvailabilityConfigs']
    assert {c['regionCode'] for c in configs} == {'US', 'IN'}
    assert body['purchaseOptions'][0]['newRegionsConfig']['usdPrice']['units'] == '4'


def test_keywords_toml(tmp_path):
    p = _project(tmp_path, '[aso]\nkeywords = "k.toml"\n',
                 {'k.toml': '[[market]]\nlang = "de"\nhl = "de"\ngl = "DE"\nkeywords = ["einkaufsliste", "liste"]\n'})
    items, path = aso.load_keywords(p)
    assert items == [('einkaufsliste', 'de', 'DE', 'de'), ('liste', 'de', 'DE', 'de')]
    assert aso.results_dir(p, path) == path.parent


class _Req:
    def __init__(self, value):
        self.value = value

    def execute(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Edits:
    """Play with one listing, en-US, and no images anywhere."""

    def listings(self):
        edits = self

        class L:
            def list(self, **kw):
                return _Req({'listings': [{'language': 'en-US', 'title': 'Old',
                                           'shortDescription': 's', 'fullDescription': 'f'}]})
        return L()

    def details(self):
        class D:
            def get(self, **kw):
                return _Req({'defaultLanguage': 'en-US'})
        return D()

    def images(self):
        class I:
            def list(self, language, **kw):
                if language != 'en-US':
                    return _Req(RuntimeError(f'404 Listing for language {language!r} not found.'))
                return _Req({'images': []})
        return I()


class _Edit:
    def call(self, fn, what):
        return fn(_Edits(), 'com.x', 'e1').execute()


def _png(path, size):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', size, 'white').save(path)


def test_a_language_new_to_play_gets_its_images_with_its_text(tmp_path):
    p = _project(tmp_path, '[store]\nlisting_dir = "l"\n[store.locales]\nen = ["en-US"]\nde = ["de-DE"]\n',
                 {'l/en.md': LISTING, 'l/de.md': LISTING})
    for code in ('en', 'de'):
        _png(p.root / 'store' / 'feature' / f'{code}.png', (1024, 500))
    both = store.plan(_Edit(), p, 'flutter')
    assert {c['locale'] for c in both['text']} == {'en-US', 'de-DE'}
    assert {(c['locale'], c['type']) for c in both['images']} == {('en-US', 'featureGraphic'),
                                                                  ('de-DE', 'featureGraphic')}
    assert both['no_listing'] == []
    images_only = store.plan(_Edit(), p, 'flutter', with_text=False)
    assert [c['locale'] for c in images_only['images']] == ['en-US']
    assert images_only['no_listing'] == ['de-DE']


class _IconEdits(_Edits):
    """en-US with the current icon, de-DE with an old one of its own, fr-FR
    with none."""

    def __init__(self, current):
        self.current = current

    def listings(self):
        class L:
            def list(self, **kw):
                return _Req({'listings': [{'language': loc, 'title': 'T', 'shortDescription': 's',
                                           'fullDescription': 'f'} for loc in ('en-US', 'de-DE', 'fr-FR')]})
        return L()

    def images(self):
        current = self.current

        class I:
            def list(self, language, imageType, **kw):
                held = {'en-US': current, 'de-DE': 'old'}.get(language)
                return _Req({'images': [{'sha256': held}] if imageType == 'icon' and held else []})
        return I()


def test_a_language_holding_an_old_icon_of_its_own_is_updated(tmp_path):
    p = _project(tmp_path, '[store]\nlisting_dir = "l"\n[store.locales]\nen = ["en-US"]\n'
                           'de = ["de-DE"]\nfr = ["fr-FR"]\n',
                 {'l/en.md': LISTING, 'l/de.md': LISTING, 'l/fr.md': LISTING})
    _png(p.root / 'store' / 'icon.png', (512, 512))
    current = store.sha256((p.root / 'store' / 'icon.png').read_bytes())

    class E(_Edit):
        def call(self, fn, what):
            return fn(_IconEdits(current), 'com.x', 'e1').execute()

    plan = store.plan(E(), p, 'flutter', with_text=False)
    assert [(c['locale'], c['type']) for c in plan['images']] == [('de-DE', 'icon')]


class _Recorder:
    """A stand-in edit that records every write, from any thread."""

    def __init__(self):
        import threading
        self.log = []
        self.lock = threading.Lock()

    def call(self, fn, what):
        rec = self

        class Req:
            def execute(self):
                with rec.lock:
                    rec.log.append(what)
                return {}

        class Any:
            def __getattr__(self, name):
                return lambda *a, **k: (Any() if not k else Req())

        return fn(Any(), 'com.x', 'e1').execute()


def test_apply_sends_text_first_keeps_screenshot_order_and_counts_every_file():
    result = {
        'text': [{'locale': loc, 'new': True, 'fields': {'title': {'from': '', 'to': 'T'}}}
                 for loc in ('en-US', 'de-DE', 'fr-FR')],
        'images': [{'locale': loc, 'type': 'phoneScreenshots', 'local': 3, 'remote': 0,
                    '_blobs': [b'\x89PNG1', b'\x89PNG2', b'\x89PNG3']} for loc in ('en-US', 'de-DE', 'fr-FR')],
        'details': {},
    }
    rec, seen, texts = _Recorder(), [], []
    store.apply(rec, result, workers=3, on_text=lambda d, t, loc: texts.append((d, t)),
                on_image=lambda d, t, name: seen.append((d, t)))
    first_image = next(n for n, w in enumerate(rec.log) if w.startswith('clear'))
    assert all(w.startswith('text') for w in rec.log[:first_image]) and len(texts) == 3
    for loc in ('en-US', 'de-DE', 'fr-FR'):
        mine = [w for w in rec.log if w.startswith(f'{loc} phoneScreenshots')]
        assert mine == [f'{loc} phoneScreenshots #{n}' for n in (1, 2, 3)]
    assert sorted(d for d, _ in seen) == list(range(1, 10)) and {t for _, t in seen} == {9}
    assert store.upload_count(result) == 9


def test_a_staged_rollout_plans_only_the_named_locales(tmp_path):
    p = _project(tmp_path, '[store]\nlisting_dir = "l"\n[store.locales]\nen = ["en-US"]\nde = ["de-DE"]\n'
                           '[store.details]\ncontactEmail = "a@b.c"\n',
                 {'l/en.md': LISTING, 'l/de.md': LISTING})
    staged = store.plan(_Edit(), p, 'flutter', with_images=False, only={'de-DE'})
    assert [c['locale'] for c in staged['text']] == ['de-DE']
    # The contact details are app-wide: not part of a per-locale rollout.
    assert staged['details'] == {}
    everything = store.plan(_Edit(), p, 'flutter', with_images=False)
    assert {c['locale'] for c in everything['text']} == {'en-US', 'de-DE'}


def test_a_staged_rollout_refuses_a_locale_it_does_not_know(tmp_path):
    p = _project(tmp_path, '[store]\nlisting_dir = "l"\n[store.locales]\nen = ["en-US"]\n',
                 {'l/en.md': LISTING})
    with pytest.raises(Exception) as e:
        store.plan(_Edit(), p, 'flutter', only={'de'})
    assert e.value.code == 'UNKNOWN_LOCALE'
