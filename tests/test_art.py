import json

import pytest
from PIL import Image

from mkit import art, config
from mkit.errors import UsageError
from mkit.cloud import store

ART_TOML = '''reference = "en"
mascot = "logo.svg"

[shots.home]
erase = [[10, 10, 20, 20]]

[[slide]]
id = "hero"
kind = "landscape"
shots = ["home", "home", "home"]

[[slide]]
id = "home"
shot = "home"

[[slide]]
id = "alerts"
shot = "home"
notify = true

[feature]
shot = "home"
'''

EN = {
    'locale': 'en-US', 'dir': 'ltr',
    'hero': {'name': 'Demo', 'title': 'The app for [you]', 'sub': 'Sub', 'chips': ['A', 'B']},
    'home': {'title': 'Home [page]', 'sub': 'Sub'},
    'alerts': {'title': 'Never [miss]', 'sub': 'Sub',
               'notify': {'app': 'Demo', 'when': 'now', 'title': 'T', 'body': 'B'}},
    'feature': {'name': 'Demo', 'title': 'Never [lose]', 'sub': 'Sub', 'chips': ['A']},
}


def _app(tmp_path, captions=None, toml_extra='[store.locales]\nen = ["en-US"]\nar = ["ar"]\n'):
    root = tmp_path / 'app'
    (root / 'store' / 'art' / 'shots').mkdir(parents=True)
    (root / 'store' / 'art' / 'captions').mkdir()
    (root / 'mkit.toml').write_text('[app]\nname = "Demo"\nkind = "flutter"\npackage = "com.x"\n'
                                    '[store]\n' + toml_extra + '[art]\n', encoding='utf-8')
    (root / 'store' / 'art' / 'art.toml').write_text(ART_TOML, encoding='utf-8')
    (root / 'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding='utf-8')
    Image.new('RGB', (1080, 2340), (240, 244, 236)).save(root / 'store' / 'art' / 'shots' / 'home.png')
    for code, words in (captions or {'en': EN}).items():
        (root / 'store' / 'art' / 'captions' / f'{code}.json').write_text(json.dumps(words), encoding='utf-8')
    return config.load(project=root)


def test_init_sets_up_an_app_once(tmp_path):
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'mkit.toml').write_text('[app]\nname = "Demo"\nkind = "flutter"\npackage = "com.x"\n',
                                    encoding='utf-8')
    (root / '.gitignore').write_text('build/\n', encoding='utf-8')
    done = art.init(config.load(project=root))
    assert (root / 'store/art/art.toml').is_file()
    assert (root / 'store/art/captions/en.json').is_file()
    assert (root / 'store/art/shots').is_dir()
    assert '[art]' in (root / 'mkit.toml').read_text(encoding='utf-8')
    ignore = (root / '.gitignore').read_text(encoding='utf-8').splitlines()
    assert ignore[0] == 'build/' and '/store/screenshots/' in ignore and '/store/feature/' in ignore
    assert done[:2] == ['wrote store/art/art.toml', 'wrote store/art/captions/en.json'] and len(done) == 4
    assert art.init(config.load(project=root)) == []


def test_init_follows_the_store_art_dir(tmp_path):
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'mkit.toml').write_text('[app]\nname = "D"\nkind = "flutter"\npackage = "com.x"\n'
                                    '[store]\nart_dir = "console/assets"\n', encoding='utf-8')
    art.init(config.load(project=root))
    ignore = (root / '.gitignore').read_text(encoding='utf-8')
    assert '/console/assets/screenshots/' in ignore and '/console/assets/feature/' in ignore


def test_pages_go_where_listing_reads_them(tmp_path):
    p = _app(tmp_path)
    jobs = art.Pages(art.Design(p), 'en', tmp_path / 'work').all()
    names = [(stem, size, target.relative_to(p.root).as_posix()) for stem, _, size, target in jobs]
    assert names == [
        ('01_hero', (1920, 1080), 'store/screenshots/en/01_hero.png'),
        ('02_home', (1080, 1920), 'store/screenshots/en/02_home.png'),
        ('03_alerts', (1080, 1920), 'store/screenshots/en/03_alerts.png'),
        ('feature', (1024, 500), 'store/feature/en.png'),
    ]
    alerts = jobs[2][1]
    assert 'class="notify"' in alerts and 'lang="en"' in alerts and '<span class="hl">miss</span>' in alerts


def test_built_images_are_what_listing_uploads(tmp_path, monkeypatch):
    p = _app(tmp_path)
    monkeypatch.setattr(art, 'browser', lambda project: 'chrome')

    def fake_png(self, page, target, size):
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', size, 'white').save(target)
    monkeypatch.setattr(art.Renderer, 'png', fake_png)
    written, kept = art.build(art.Design(p), ['en'])
    assert len(written['en']) == 4 and kept is None
    images = store.desired_images(p, 'flutter')['en-US']
    assert len(images['phoneScreenshots']) == 3
    assert len(images['featureGraphic']) == 1


def test_right_to_left_pages_are_mirrored(tmp_path):
    ar = json.loads(json.dumps(EN))
    ar['dir'] = 'rtl'
    p = _app(tmp_path, {'en': EN, 'ar': ar})
    jobs = art.Pages(art.Design(p), 'ar', tmp_path / 'work').all()
    hero, feature = jobs[0][1], jobs[-1][1]
    assert '.copy{left:auto;right:120px}' in hero
    assert '.guard{left:auto;right:34px}' in feature
    assert 'class="notify" dir="rtl"' in jobs[2][1]
    assert "'Segoe UI'" in hero


def test_captures_are_cleaned_and_checked(tmp_path):
    p = _app(tmp_path)
    shots = art.Shots(art.Design(p), 'en', tmp_path / 'work')
    path, ink = shots.get('home')
    assert ink == '#1F2A21'
    Image.new('RGB', (100, 100)).save(p.root / 'store/art/shots/small.png')
    with pytest.raises(art.UsageError):
        shots.get('small')


def test_blend_out_fills_a_box_from_its_edges():
    im = Image.new('RGB', (10, 1), (0, 0, 0))
    im.putpixel((1, 0), (0, 0, 0))
    im.putpixel((8, 0), (90, 90, 90))
    im.putpixel((4, 0), (255, 0, 0))
    art.blend_out(im, 2, 0, 8, 1)
    row = [im.getpixel((x, 0))[0] for x in range(2, 8)]
    assert row == sorted(row) and row[-1] < 90 and im.getpixel((4, 0)) != (255, 0, 0)


def test_lint_finds_what_breaks_a_captions_file():
    bad = json.loads(json.dumps(EN))
    del bad['home']['sub']
    bad['alerts']['title'] = 'Never miss'
    bad['hero']['sub'] = 'Fast — simple'
    bad['extra'] = {'x': 'y'}
    problems = art.lint(bad, EN, [{'id': 'hero'}, {'id': 'home'}, {'id': 'alerts'}])
    assert 'missing home.sub' in problems
    assert 'alerts.title: needs exactly one [accent]' in problems
    assert 'hero.sub: em dash' in problems
    assert any(x.startswith('not in the reference: extra') for x in problems)
    assert art.lint(EN, EN, [{'id': 'hero'}]) == []


def test_compare_reports_lines_and_overflow_but_not_a_cut_notification_title():
    ref = {'02_home': {'title': {'lines': 2, 'over': False}, 'notify.title': {'lines': 1, 'over': False}}}
    got = {'02_home': {'title': {'lines': 3, 'over': True}, 'notify.title': {'lines': 1, 'over': True}}}
    assert art.compare(got, ref) == ['02_home title: runs past its box', '02_home title: 3 lines, reference has 2']


def test_a_missing_art_file_says_how_to_start(tmp_path):
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'mkit.toml').write_text('[app]\nname = "D"\nkind = "flutter"\npackage = "com.x"\n[art]\n',
                                    encoding='utf-8')
    with pytest.raises(art.NotFound) as e:
        art.Design(config.load(project=root))
    assert 'mkit art init' in e.value.hint


def test_browser_skips_one_that_does_not_answer(tmp_path, monkeypatch):
    shell = tmp_path / 'chrome-headless-shell.exe'
    shell.write_bytes(b'')
    monkeypatch.setattr(art, '_playwright', lambda pattern: [str(shell)] if 'headless' in pattern else [])
    monkeypatch.setattr(art, '_answers', lambda exe: exe == str(shell))
    monkeypatch.setattr(art.shutil, 'which', lambda name: None)
    project = type('P', (), {'get': lambda self, key: None})()
    assert art.browser(project) == shell


def test_a_page_draws_the_backdrop_the_app_chose(tmp_path):
    p = _app(tmp_path)
    toml = p.root / 'store' / 'art' / 'art.toml'
    hero = art.Pages(art.Design(p), 'en', tmp_path / 'work').all()[0][1]
    assert '<polyline' in hero
    toml.write_text('decoration = "leaves"\n' + toml.read_text(encoding='utf-8'), encoding='utf-8')
    hero = art.Pages(art.Design(p), 'en', tmp_path / 'work').all()[0][1]
    assert '<polyline' not in hero and 'fill-opacity' in hero
    toml.write_text(toml.read_text(encoding='utf-8').replace('"leaves"', '"vines"'), encoding='utf-8')
    with pytest.raises(UsageError):
        art.Design(p)


# ---------------------------------------------------------------- layouts

def _page_digest(tmp_path, p, code):
    """A page set's HTML with the temp folder taken out, hashed."""
    import hashlib
    jobs = art.Pages(art.Design(p), code, tmp_path / 'work').all()
    text = '\n'.join(doc for _, doc, _, _ in jobs).replace(tmp_path.as_uri(), 'file:///TMP')
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize('decoration, en, ar', [
    ('contour', 'b93ebfc38ee19420fbebcfb329404d57ca5619ec17543c3d9ba640b836a2cd2a',
     '862eeff46e1cd0aa9d8f9db93a9e388590fba43530eec87cfaf9aad6189f5e59'),
    ('leaves', '871e3c781b3a96facd2a3e404a0860bd269e91c9a01f5ca98eee22597b7e0455',
     '21c40107db38125e17420e390851e5128db5e7b38c6d4fb320a1cedcf73e9261'),
])
def test_classic_pages_are_unchanged(tmp_path, decoration, en, ar):
    """The classic layout draws exactly the pages it drew before pop existed."""
    rtl = json.loads(json.dumps(EN))
    rtl['dir'] = 'rtl'
    p = _app(tmp_path, {'en': EN, 'ar': rtl})
    toml = p.root / 'store' / 'art' / 'art.toml'
    toml.write_text(f'decoration = "{decoration}"\n' + toml.read_text(encoding='utf-8'), encoding='utf-8')
    assert art.Design(p).layout == 'classic' and art.Design(p).bar_mode == 'redraw'
    assert (_page_digest(tmp_path, p, 'en'), _page_digest(tmp_path, p, 'ar')) == (en, ar)


def test_layout_and_status_bar_mode_must_be_known(tmp_path):
    p = _app(tmp_path)
    toml = p.root / 'store' / 'art' / 'art.toml'
    base = toml.read_text(encoding='utf-8')
    toml.write_text('layout = "fancy"\n' + base, encoding='utf-8')
    with pytest.raises(UsageError, match='layout must be one of classic, pop'):
        art.Design(p)
    toml.write_text('layout = "pop"\n' + base, encoding='utf-8')
    assert art.Design(p).bar_mode == 'clean'          # pop keeps the capture's own bar
    toml.write_text('layout = "pop"\n' + base + '\n[status_bar]\nmode = "paint"\n', encoding='utf-8')
    with pytest.raises(UsageError, match='mode must be one of redraw, clean'):
        art.Design(p)
    toml.write_text(base + '\n[status_bar]\nmode = "clean"\n', encoding='utf-8')
    d = art.Design(p)
    assert d.layout == 'classic' and d.bar_mode == 'clean'
    classic = art.Pages(d, 'en', tmp_path / 'work').all()[1][1]
    assert 'class="bar"' not in classic                # the capture carries its own 9:41


POP_TOML = '''layout = "pop"
reference = "en"
mascot = "logo.svg"

[theme.light]
underline = "#123456"

[[slide]]
id = "hero"
kind = "landscape"
shots = ["home", "home"]

[[slide.pill]]
text = "Avocados"
x = 260
y = 640
size = 36
rotate = -5

[[slide]]
id = "home"
shot = "home"

[[slide.art]]
src = "logo.svg"
x = 790
y = 380
height = 210
rotate = 10
z = 6

[[slide.pill]]
text = "Lemons"
x = 40
y = 1130

[[slide.pill]]
key = "add"
go = true
x = 380
y = 1740
size = 54
rotate = -2

[[slide]]
id = "alerts"
shot = "home"
notify = true
notify_y = 640

[[slide]]
id = "night"
shot = "home"
dark = true

[feature]
shots = ["home", "home"]

[[feature.pill]]
key = "add"
x = 600
y = 360
size = 24
'''

POP_EN = {
    'locale': 'en-US', 'dir': 'ltr',
    'hero': {'name': 'Demo', 'title': 'The list for [families]', 'chips': ['A', 'B']},
    'home': {'title': 'One list,\n[whole family]', 'pills': {'add': 'Add 5 items'}},
    'alerts': {'title': 'Live\n[updates]',
               'notify': {'app': 'Demo', 'when': 'now', 'title': 'Our family', 'body': 'Sam added'}},
    'night': {'title': 'Dark\n[mode]', 'sub': 'Easy on the eyes'},
    'feature': {'name': 'Demo', 'title': 'The list for [families]', 'pills': {'add': 'Add it'}},
}


def _pop(tmp_path, captions=None):
    p = _app(tmp_path, captions or {'en': POP_EN})
    (p.root / 'store' / 'art' / 'art.toml').write_text(POP_TOML, encoding='utf-8')
    return p


def test_pop_pages_carry_pills_art_and_the_notification(tmp_path):
    p = _pop(tmp_path)
    jobs = art.Pages(art.Design(p), 'en', tmp_path / 'work').all()
    assert [(stem, size) for stem, _, size, _ in jobs] == [
        ('01_hero', (1920, 1080)), ('02_home', (1080, 1920)), ('03_alerts', (1080, 1920)),
        ('04_night', (1080, 1920)), ('feature', (1024, 500))]
    hero, home, alerts, night, feature = (doc for _, doc, _, _ in jobs)
    assert hero.count('class="phone"') == 2 and 'class="chips" data-m="chips"' in hero
    assert 'data-m="pill.1"' in hero and '>Avocados</span>' in hero
    # A literal pill as written, a keyed one from the captions, the go pill green.
    assert '<span class="pt">Lemons</span>' in home and 'style="left:40px;top:1130px;font-size:44px' in home
    assert 'class="pill go"' in home and 'data-m="pill.add"' in home and '>Add 5 items</span>' in home
    assert 'class="art"' in home and 'left:790px;top:380px;height:210px;transform:rotate(10deg);z-index:6' in home
    # Title: the [word] underlined, the newline a break, at most two lines; no sub when there is none.
    assert 'One list,<br><span class="u">whole family<svg' in home and 'data-max="2"' in home
    assert 'data-m="sub"' not in home and 'data-m="sub"' in night
    assert 'class="notify"' in alerts and 'top:640px' in alerts and 'data-m="notify.title">Our family<' in alerts
    assert 'class="notify"' not in home
    assert 'stroke:#123456' in home                    # the app's underline colour
    assert '#1F3D29' in night and '#1F3D29' not in home   # dark slides stand on the dark ground
    assert feature.count('class="phone"') == 2 and '>Add it</span>' in feature
    assert 'class="bar"' not in home                   # clean mode: no bar drawn over the capture


def test_pop_scatter_ground_and_a_coloured_word(tmp_path):
    p = _pop(tmp_path)
    toml = p.root / 'store' / 'art' / 'art.toml'
    toml.write_text(POP_TOML.replace('layout = "pop"', 'layout = "pop"\nornament = "scatter"\n'
                                     'underline_style = "colour"', 1), encoding='utf-8')
    jobs = art.Pages(art.Design(p), 'en', tmp_path / 'work').all()
    home = next(doc for stem, doc, _, _ in jobs if stem == '02_home')
    # The glass shapes instead of sprigs, and no dot texture over them.
    assert home.count('<rect ') == len(art.SCATTER) and 'class="dots"' not in home
    # The word takes the underline colour, with no line drawn under it.
    assert '<span class="u u-colour">whole family</span>' in home and '.u.u-colour{color:#123456}' in home


def test_pop_rejects_an_unknown_ornament(tmp_path):
    p = _pop(tmp_path)
    (p.root / 'store' / 'art' / 'art.toml').write_text(
        POP_TOML.replace('layout = "pop"', 'layout = "pop"\nornament = "confetti"', 1), encoding='utf-8')
    with pytest.raises(art.UsageError):
        art.Design(p)


def test_pop_needs_its_pill_words_and_pictures(tmp_path):
    words = json.loads(json.dumps(POP_EN))
    del words['home']['pills']
    p = _pop(tmp_path, {'en': words})
    with pytest.raises(UsageError, match='home.pills.add'):
        art.Pages(art.Design(p), 'en', tmp_path / 'work').all()
    p = _pop(tmp_path / 'b')
    toml = p.root / 'store' / 'art' / 'art.toml'
    toml.write_text(toml.read_text(encoding='utf-8').replace('src = "logo.svg"', 'src = "gone.png"'),
                    encoding='utf-8')
    with pytest.raises(art.NotFound):
        art.Pages(art.Design(p), 'en', tmp_path / 'work').all()


def test_pop_right_to_left_pages_are_mirrored(tmp_path):
    ar = json.loads(json.dumps(POP_EN))
    ar['dir'] = 'rtl'
    p = _pop(tmp_path, {'en': POP_EN, 'ar': ar})
    hero, home, alerts, _, feature = (doc for _, doc, _, _ in art.Pages(art.Design(p), 'ar', tmp_path / 'w').all())
    # Pills and pictures keep their distance from the other edge, tilted the other way.
    assert 'style="right:40px;top:1130px' in home and 'dir="rtl"' in home
    assert 'right:380px;top:1740px;font-size:54px;transform:rotate(2deg)' in home
    assert 'right:790px;top:380px;height:210px;transform:rotate(-10deg)' in home
    # The phones swap sides with the words.
    assert 'left:1380px;top:260px;width:390px' in hero and 'transform:rotate(9deg)' in hero
    assert 'class="copy" dir="rtl" style="left:110px;width:780px"' in hero
    assert 'class="copy" dir="rtl" style="left:494px;width:470px"' in feature
    assert 'class="notify" dir="rtl"' in alerts and 'rotate(2deg)' in alerts
    assert "'Segoe UI'" in hero


def _capture(path, colour):
    im = Image.new('RGB', (1080, 2340), colour)
    for x in range(800, 1040):              # the phone's own icons, to be painted out
        for y in range(30, 70):
            im.putpixel((x, y), (255, 0, 0))
    im.save(path)


def test_clean_status_bar_picks_ink_by_the_bar_colour(tmp_path):
    p = _pop(tmp_path)
    shots_dir = p.root / 'store' / 'art' / 'shots'
    _capture(shots_dir / 'light.png', (241, 246, 240))
    _capture(shots_dir / 'dark.png', (17, 18, 19))
    shots = art.Shots(art.Design(p), 'en', tmp_path / 'work')
    light, ink = shots.get('light')
    assert ink == '#1F2A21'                 # dark ink on a light bar
    dark, ink = shots.get('dark')
    assert ink == '#ECF2EC'                 # light ink on a dark bar
    im = Image.open(light)
    assert im.getpixel((1030, 35)) == (241, 246, 240)    # the red icons are gone
    assert im.getpixel((885, 60)) == (31, 42, 33)        # a signal bar, in ink
    assert im.getpixel((540, 200)) == (241, 246, 240)    # below the bar, untouched
    assert Image.open(dark).getpixel((885, 60)) == (236, 242, 236)


def test_compare_holds_a_block_to_its_line_cap():
    got = {'02_home': {'title': {'lines': 3, 'over': False, 'max': 2},
                       'pill.add': {'lines': 1, 'over': True}}}
    assert art.compare(got, {}) == ['02_home title: 3 lines, at most 2', '02_home pill.add: runs past its box']
    ref = {'02_home': {'title': {'lines': 2}, 'pill.add': {'lines': 1}}}
    got['02_home']['title']['lines'] = 2
    got['02_home']['pill.add']['over'] = False
    assert art.compare(got, ref) == []
