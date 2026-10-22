"""Store art: Play screenshots and the feature graphic, built from real phone
captures and a words file per language (docs/store-art.md).

Everything that is the same for every app lives here: the page templates (a
landscape hero, portrait slides, the feature graphic) in two layouts (classic
and pop; art.toml `layout`), the phone frame, the
clean status bar, right-to-left mirroring, fonts for each script, and the
line-count check. An app keeps only what makes its art its own, in its art
folder (`[art] dir`, default store/art):

    shots/<name>.png           raw captures, 1080x2340, as `adb exec-out screencap -p` gives them
    shots/<code>/<name>.png    optional: a capture of the app in that language
    captions/<code>.json       the words, keyed by slide id; one file per listing code
    art.toml                   slides, erase boxes, colours, font and mascot

Pages are HTML drawn by a headless Chromium browser (Edge or Chrome), so the
text is real type in the app's own font. Images go where `mkit listing` reads
them: <[store] art_dir>/screenshots/<code>/ and <art_dir>/feature/<code>.png.
"""
import html
import json
import math
import os
import random
import shutil
import subprocess
import tempfile
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from .errors import NotFound, UsageError

PORTRAIT = (1080, 1920)
LANDSCAPE = (1920, 1080)
FEATURE = (1024, 500)
SHOT_W, SHOT_H = 1080, 2340
TEMPLATES = Path(__file__).parent / 'data' / 'art'

# Backdrops a page can draw behind its copy and phones (art.toml `decoration`).
DECORATIONS = ('contour', 'leaves', 'none')

# Page designs (art.toml `layout`). classic: words over phones on a soft
# gradient. pop: a vivid ground, short bold titles with an underlined word,
# big phones and floating pills and pictures the app places itself.
LAYOUTS = ('classic', 'pop')

# What the pop ground grows behind the phones (art.toml `ornament`), and how the title's [word]
# is marked (`underline_style`). The defaults are the pop look as it first shipped.
ORNAMENTS = ('sprigs', 'scatter', 'none')

# `scatter`: soft glass shapes over the whole ground, as an app might draw behind its own screens.
# (x, y) as fractions of the page, width as a fraction of its shorter side, tilt in degrees, and
# kind: 0 a rounded square, 1 a circle, 2 a pill.
SCATTER = (
    (.06, .08, .16, -19, 0), (.59, .035, .10, 0, 1), (.86, .20, .22, 24, 0), (.37, .24, .13, -32, 2),
    (-.07, .36, .21, 0, 1), (.64, .43, .18, 17, 0), (.18, .54, .12, 34, 0), (.91, .59, .15, -28, 2),
    (.43, .69, .09, 0, 1), (-.04, .78, .18, -12, 0), (.74, .84, .20, 29, 0), (.29, .94, .16, -23, 2),
)
UNDERLINES = ('swoosh', 'colour', 'none')

# What happens to a capture's status bar ([status_bar] mode). redraw: its
# icons are erased and a 9:41 bar is drawn over it on the page. clean: the
# capture keeps its own bar, painted over in its own colour, with a neat 9:41,
# signal and battery drawn into the capture.
BAR_MODES = ('redraw', 'clean')

# Characters a caption may not use: dashes, arrows, bullets, invisible joiners.
BANNED = {'\u2014': 'em dash', '\u2013': 'en dash', '\u2192': 'arrow', '\u2190': 'arrow',
          '\u2022': 'bullet', '\u00b7': 'middle dot', '\u2060': 'word joiner'}

THEME = {
    'light': dict(bg1='#F4F7EF', bg2='#DCEAD4', line='#4E9150', line_op=0.20, ink='#1F2A21',
                  sub='#4D5C50', accent='#2F7A3E', tile='#E3EFDD', chip_border='rgba(78,145,80,.28)',
                  phone_shadow='0 50px 90px rgba(20,40,25,.30),0 12px 28px rgba(20,40,25,.20),'
                               'inset 0 0 0 3px #2B302D'),
    'dark': dict(bg1='#0E1210', bg2='#16261A', line='#A5D69B', line_op=0.13, ink='#F3F6F1',
                 sub='#A9B5AB', accent='#A5D69B', tile='#E3EFDD', chip_border='rgba(78,145,80,.28)',
                 phone_shadow='0 0 0 3px #3C4A40,0 40px 120px rgba(120,190,110,.22),'
                              'inset 0 0 0 3px #2B302D'),
}

# The pop layout's colours (art.toml [theme.light] / [theme.dark] override any).
_POP_LIGHT = dict(
    bg1='#55D27E', bg2='#26AC52', bg3='#168A3E', bg_mid=48,   # ground: a radial glow from the top
    blob_dark='#0F7A34', blob_light='#7BE39B',                 # soft shade bottom left, light top right
    glow='#FFFFFF',                                            # halo and ring behind the phones, sprigs, dots, chips
    ink='#FFFFFF', title_shadow='0 4px 18px rgba(5,60,25,.25)',
    underline='#FFD95A',                                       # the hand-drawn line under the [word]
    accent='#1E9E4A',                                          # ticks, the go pill, the notification tile
    pill='#FFFFFF', pill_ink='#1B2A1F',
    shade='#043214',                                           # every shadow, at its own strength
    phone='#141816')
POP_THEME = {
    'light': _POP_LIGHT,
    'dark': {**_POP_LIGHT, 'bg1': '#1F3D29', 'bg2': '#122419', 'bg3': '#0B140E', 'bg_mid': 50,
             'title_shadow': 'none'},
}

# The app's font draws Latin; other scripts fall back, glyph by glyph, to the
# system font closest to it (Windows names; art.toml [script_fonts] overrides).
SCRIPT_FONTS = {
    **dict.fromkeys(['be', 'bg', 'ru', 'sr', 'uk', 'el', 'kk', 'mk', 'mn'], 'Bahnschrift'),
    **dict.fromkeys(['ar', 'fa', 'ur', 'he', 'iw', 'ka', 'hy'], 'Segoe UI'),
    **dict.fromkeys(['hi', 'bn', 'mr', 'ne', 'ta', 'te', 'kn', 'ml', 'gu', 'pa', 'si'], 'Nirmala UI'),
    'th': 'Leelawadee UI', 'lo': 'Leelawadee UI', 'km': 'Leelawadee UI',
    'ja': 'Yu Gothic UI', 'ko': 'Malgun Gothic',
    'zh-CN': 'Microsoft YaHei UI', 'zh-TW': 'Microsoft JhengHei UI', 'zh-HK': 'Microsoft JhengHei UI',
}
RTL = {'ar', 'fa', 'ur', 'he', 'iw'}

# What a script needs beyond its font: Korean breaks only between words;
# Arabic's tall letters and marks need more room between lines.
LANG_CSS = {
    'ko': 'body{word-break:keep-all}',
    'ar': 'html[lang] h1{line-height:1.3}html[lang] p{line-height:1.45}',
    'fa': 'html[lang] h1{line-height:1.3}html[lang] p{line-height:1.45}',
    'ur': 'html[lang] h1{line-height:1.3}html[lang] p{line-height:1.45}',
    'he': 'html[lang] h1{line-height:1.12}',
}


# ---------------------------------------------------------------- the app's design

class Design:
    """One app's art settings: its folder, art.toml and where images go."""

    def __init__(self, project):
        self.project = project
        self.root = project.root
        self.dir = project.path('art.dir', 'store/art')
        self.out = project.path('art.out') or project.path('store.art_dir', 'store')
        file = self.dir / 'art.toml'
        if not file.is_file():
            raise NotFound(f'no {file.relative_to(self.root)}',
                           hint='Run `mkit art init` to set up the art folder.', code='NO_ART')
        with open(file, 'rb') as f:
            try:
                self.data = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise UsageError(f'{file} is not valid TOML: {e}', code='BAD_ART') from e
        self.slides = self.data.get('slide') or []
        if not self.slides:
            raise UsageError(f'{file}: no [[slide]] entries', code='BAD_ART')
        self.reference = self.data.get('reference', 'en')
        self.layout = self._choice(file, 'layout', self.data.get('layout', 'classic'), LAYOUTS)
        self.decoration = self._choice(file, 'decoration', self.data.get('decoration', 'contour'), DECORATIONS)
        self.ornament = self._choice(file, 'ornament', self.data.get('ornament', 'sprigs'), ORNAMENTS)
        self.underline_style = self._choice(file, 'underline_style',
                                            self.data.get('underline_style', 'swoosh'), UNDERLINES)
        bar = self.data.get('status_bar') or {}
        self.bar_mode = self._choice(file, '[status_bar] mode',
                                     bar.get('mode', 'clean' if self.layout == 'pop' else 'redraw'), BAR_MODES)
        base = POP_THEME if self.layout == 'pop' else THEME
        self.theme = {k: {**base[k], **(self.data.get('theme', {}).get(k) or {})} for k in base}
        self.font = self.data.get('font', 'Barlow')
        self.font_dir = self._path(self.data.get('font_dir'))
        self.mascot = self._path(self.data.get('mascot'))
        self.script_fonts = {**SCRIPT_FONTS, **(self.data.get('script_fonts') or {})}

    @staticmethod
    def _choice(file, name, value, allowed):
        if value not in allowed:
            raise UsageError(f'{file}: {name} must be one of {", ".join(allowed)}, not {value!r}',
                             code='BAD_ART')
        return value

    def _path(self, rel):
        return (self.root / rel) if rel else None

    def font_file(self, *styles):
        """The first of the app font's files in these styles, or None."""
        for style in styles:
            file = self.font_dir / f'{self.font}-{style}.ttf' if self.font_dir else None
            if file and file.is_file():
                return file
        return None

    def asset(self, rel):
        """A picture a page places (art.toml `src`), relative to the app folder."""
        path = self.root / rel
        if not path.is_file():
            raise NotFound(f'no {rel} (an art `src` in {self.dir.relative_to(self.root).as_posix()}/art.toml)',
                           code='NO_ART_ASSET')
        return path

    def codes(self):
        return sorted(p.stem for p in (self.dir / 'captions').glob('*.json'))

    def words(self, code):
        file = self.dir / 'captions' / f'{code}.json'
        if not file.is_file():
            raise NotFound(f'no captions for {code}: {file.relative_to(self.root)}', code='NO_CAPTIONS')
        try:
            return json.loads(file.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            raise UsageError(f'{file}: {e}', code='BAD_CAPTIONS') from e

    def shot(self, name, code):
        own = self.dir / 'shots' / code / f'{name}.png'
        path = own if own.is_file() else self.dir / 'shots' / f'{name}.png'
        if not path.is_file():
            raise NotFound(f'no capture {path.relative_to(self.root)}', code='NO_SHOT')
        return path

    def screenshot_dir(self, code):
        return self.out / 'screenshots' / code

    def feature_file(self, code):
        return self.out / 'feature' / f'{code}.png'


# ---------------------------------------------------------------- captures

class Shots:
    """Cleans each capture once per build: erases anything private, each
    erased row blended from its left edge to its right, and tidies the
    status bar. In redraw mode its icons are erased the same way and the
    bar's ink (light or dark) is remembered for the 9:41 drawn over it; in
    clean mode the bar is painted over in its own colour and a 9:41 drawn
    into the capture."""

    def __init__(self, design, code, work):
        self.design = design
        self.code = code
        self.work = work / 'shots' / code
        self.work.mkdir(parents=True, exist_ok=True)
        self.ink = {}
        bar = design.data.get('status_bar') or {}
        self.mode = design.bar_mode
        self.clean = self.mode == 'clean'
        self.bar_height = bar.get('height', 96 if self.clean else 100)
        self.bar_erase = bar.get('erase', [[36, 8, 250, 96], [760, 8, 1048, 96]])
        self.sample = tuple(bar.get('sample', [540, 60]))

    def get(self, name):
        out = self.work / f'{name}.png'
        if name not in self.ink:
            src = self.design.shot(name, self.code)
            im = Image.open(src).convert('RGB')
            if im.size != (SHOT_W, SHOT_H):
                raise UsageError(f'{src.name}: expected {SHOT_W}x{SHOT_H}, got {im.size[0]}x{im.size[1]}',
                                 code='BAD_SHOT')
            extra = (self.design.data.get('shots', {}).get(name) or {}).get('erase', [])
            if self.clean:
                for box in extra:
                    blend_out(im, *box)
                self.ink[name] = clean_bar(im, self.bar_height, self.sample,
                                           self.design.font_file('SemiBold', 'Medium', 'Bold', 'Regular'))
            else:
                for box in self.bar_erase + extra:
                    blend_out(im, *box)
                self.ink[name] = ink_for(im, self.bar_height)
            im.save(out)
        return out, self.ink[name]


def blend_out(im, x0, y0, x1, y1):
    """Replace a box with, row by row, a blend from its left edge to its right."""
    px = im.load()
    for y in range(y0, y1):
        a, b = px[x0 - 1, y], px[x1, y]
        for x in range(x0, x1):
            t = (x - x0 + 1) / (x1 - x0 + 1)
            px[x, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ink_for(im, height):
    """Dark icons on a light status bar, light ones on a dark one."""
    r, g, b = im.crop((0, 0, im.width, height)).resize((1, 1), Image.BOX).getpixel((0, 0))
    return '#1F2A21' if 0.2126 * r + 0.7152 * g + 0.0722 * b > 128 else '#F3F6F1'


def clean_bar(im, height, sample, font_file=None):
    """Keep the capture's own status bar but paint out what is on it (the
    real time, notification icons, battery) in the colour at [sample], then
    draw a neat 9:41, signal and battery in an ink that reads on it: dark on
    a light bar, light on a dark one. Returns the ink."""
    from PIL import ImageDraw, ImageFont
    bg = im.getpixel(sample)
    light = 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2] > 128
    ink = (31, 42, 33) if light else (236, 242, 236)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, im.width, height), fill=bg)
    font = ImageFont.truetype(str(font_file), 40) if font_file else ImageFont.load_default(40)
    d.text((70, 26), '9:41', font=font, fill=ink)
    for i, h in enumerate((14, 20, 26, 32)):
        d.rounded_rectangle((880 + i * 14, 66 - h, 889 + i * 14, 66), 3, fill=ink)
    d.rounded_rectangle((950, 40, 1006, 66), 6, outline=ink, width=3)
    d.rounded_rectangle((955, 45, 990, 61), 3, fill=ink)
    return '#%02X%02X%02X' % ink


# ---------------------------------------------------------------- caption rules

def lint(words, reference, slides):
    """Problems a captions file has on its own: keys that differ from the
    reference language, titles without exactly one [accent], banned characters."""
    problems = []

    def keys(node, prefix=''):
        if isinstance(node, dict):
            out = set()
            for k, v in node.items():
                if k in ('locale', 'dir', 'font'):
                    continue
                out |= {f'{prefix}{k}'} | keys(v, f'{prefix}{k}.')
            return out
        return set()

    have, want = keys(words), keys(reference)
    for k in sorted(want - have):
        problems.append(f'missing {k}')
    for k in sorted(have - want):
        problems.append(f'not in the reference: {k}')
    for sid in [s['id'] for s in slides] + ['feature']:
        title = (words.get(sid) or {}).get('title', '')
        if title and (title.count('[') != 1 or title.count(']') != 1):
            problems.append(f'{sid}.title: needs exactly one [accent]')

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f'{where}{k}.')
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f'{where}{i}.')
        elif isinstance(node, str):
            for ch, name in BANNED.items():
                if ch in node:
                    problems.append(f'{where[:-1]}: {name}')

    walk(words, '')
    return problems


# ---------------------------------------------------------------- page pieces

def rich(text):
    """Escape a caption and turn [words] into the accent span."""
    return html.escape(text).replace('[', '<span class="hl">').replace(']', '</span>')


def contour(cx, cy, r0, rings, seed, colour, opacity, step=34):
    """Wobbly concentric rings, a topographic backdrop."""
    rnd = random.Random(seed)
    p1, p2 = rnd.uniform(0, 6), rnd.uniform(0, 6)
    paths = []
    for i in range(rings):
        r = r0 + i * step
        pts = []
        for k in range(97):
            a = k / 96 * 2 * math.pi
            w = 1 + 0.07 * math.sin(3 * a + p1 + i * 0.25) + 0.04 * math.sin(5 * a + p2)
            pts.append(f'{cx + r * w * math.cos(a):.1f},{cy + r * w * 0.86 * math.sin(a):.1f}')
        paths.append(f'<polyline points="{" ".join(pts)}"/>')
    return (f'<g fill="none" stroke="{colour}" stroke-width="2.4" '
            f'stroke-opacity="{opacity}">{"".join(paths)}</g>')


def ornament(kind, x, y, angle, length, seed, colour):
    """One spot of the pop ground's ornament (art.toml `ornament`), growing in from (x, y)."""
    if kind == 'sprigs':
        return sprig(x, y, angle, length, seed, colour, .10, count=7, curl_by=.2, start=.16,
                     span=.76, shrink=.35, pulse=1.3, stem=1, width=6)
    return ''


def scatter(w, h, colour, rtl=False):
    """The `scatter` ornament: SCATTER's glass shapes, each a faint fill with a lighter rim."""
    unit = min(w, h)
    out = []
    for fx, fy, fw, tilt, kind in SCATTER:
        sw = fw * unit
        sh = sw * .38 if kind == 2 else sw
        r = sw * .25 if kind == 0 else sw / 2
        x = (1 - fx) * w - sw if rtl else fx * w
        y = fy * h
        turn = -tilt if rtl else tilt
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{sw:.1f}" height="{sh:.1f}" rx="{r:.1f}" '
                   f'fill="{colour}" fill-opacity=".09" stroke="{colour}" stroke-opacity=".20" stroke-width="2" '
                   f'transform="rotate({turn} {x + sw / 2:.1f} {y + sh / 2:.1f})"/>')
    return ''.join(out)


def sprig(x, y, angle, length, seed, colour, opacity,
          count=6, curl_by=0.18, start=.2, span=.72, shrink=.4, pulse=1.25, stem=1.2, width=5):
    """A stem with leaves along it, growing from (x, y) toward [angle]: a
    garden backdrop, for apps whose look is leaves rather than contours.
    The defaults are the classic sprig; the pop ground grows a fuller one."""
    rnd = random.Random(seed)
    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx
    curl = rnd.choice([-1, 1]) * length * curl_by
    ex, ey = x + dx * length, y + dy * length
    cx, cy = x + dx * length * 0.5 + nx * curl, y + dy * length * 0.5 + ny * curl

    def at(t):
        u = 1 - t
        return (x * u * u + cx * 2 * u * t + ex * t * t, y * u * u + cy * 2 * u * t + ey * t * t)

    def tangent(t):
        tx = (cx - x) * 2 * (1 - t) + (ex - cx) * 2 * t
        ty = (cy - y) * 2 * (1 - t) + (ey - cy) * 2 * t
        m = math.hypot(tx, ty) or 1
        return tx / m, ty / m

    def leaf(bx, by, a, ln, op):
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        w = ln * 0.42

        def p(t, s):
            return f'{bx + ux * ln * t + vx * w * s:.1f},{by + uy * ln * t + vy * w * s:.1f}'
        return (f'<path d="M{bx:.1f},{by:.1f} C{p(.25, 1)} {p(.75, .6)} {p(1, 0)} '
                f'C{p(.75, -.6)} {p(.25, -1)} {bx:.1f},{by:.1f}Z" fill-opacity="{op:.3f}"/>')

    leaves = []
    for i in range(count):
        t = start + span * i / (count - 1)
        side = 1 if i % 2 == 0 else -1
        tx, ty = tangent(t)
        a = math.atan2(ty, tx) + side * .8
        bx, by = at(t)
        leaves.append(leaf(bx, by, a, length * .3 * (1 - shrink * i / count), opacity * (pulse if i % 2 else 1)))
    tx, ty = tangent(1)
    leaves.append(leaf(ex, ey, math.atan2(ty, tx), length * .2, opacity * pulse))
    return (f'<g fill="{colour}"><path d="M{x:.1f},{y:.1f} Q{cx:.1f},{cy:.1f} {ex:.1f},{ey:.1f}" fill="none" '
            f'stroke="{colour}" stroke-opacity="{opacity * stem:.3f}" stroke-width="{width}" stroke-linecap="round"/>'
            f'{"".join(leaves)}</g>')


def backdrop(style, size, theme, spots):
    """The page's decoration. Each spot is (x, y, size, rings, seed, step): a
    set of contour rings there, or a sprig growing in from there."""
    if style == 'none':
        return ''
    w, h = size
    out = []
    for x, y, r0, rings, seed, step in spots:
        if style == 'leaves':
            bx, by = min(max(x, 0), w), min(max(y, 0), h)
            angle = math.atan2(h / 2 - by, w / 2 - bx) + random.Random(seed).uniform(-.5, .5)
            out.append(sprig(bx, by, angle, (r0 + rings * step) * .62, seed,
                             theme['line'], theme['line_op'] * 1.6))
        else:
            out.append(contour(x, y, r0, rings, seed, theme['line'], theme['line_op'], step=step))
    return ''.join(out)


def status_icons(ink):
    return f'''
<div class="time" style="color:{ink}">9:41</div>
<svg class="icons" viewBox="0 0 120 30" fill="{ink}">
  <rect x="0" y="18" width="5" height="8" rx="1.5"/><rect x="8" y="13" width="5" height="13" rx="1.5"/>
  <rect x="16" y="8" width="5" height="18" rx="1.5"/><rect x="24" y="3" width="5" height="23" rx="1.5"/>
  <path d="M47 25l-4.2-4.6a6.2 6.2 0 0 1 8.4 0z"/>
  <path d="M38.6 15.8a12.4 12.4 0 0 1 16.8 0l-2.4 2.6a8.8 8.8 0 0 0-12 0z"/>
  <path d="M34.4 11.2a18.6 18.6 0 0 1 25.2 0l-2.4 2.6a15 15 0 0 0-20.4 0z"/>
  <rect x="72" y="6" width="38" height="19" rx="5" fill="none" stroke="{ink}" stroke-width="2.4"/>
  <rect x="75.5" y="9.5" width="28" height="12" rx="2.5"/>
  <rect x="112" y="12" width="3" height="7" rx="1.2"/>
</svg>'''


def mirror(rtl, width):
    """For right-to-left pages: flip an x position (and a tilt) across the page."""
    def x(pos, w=0):
        return width - pos - w if rtl else pos

    def turn(deg):
        return -deg if rtl else deg
    return x, turn


# The 9:41 bar drawn over a capture in redraw mode.
BAR_CSS = '''.bar{position:absolute;left:0;top:0;right:0;display:flex;align-items:center;justify-content:space-between;
  padding:0 calc(46px * var(--s)) 0 calc(56px * var(--s))}
.time{font:600 calc(34px * var(--s))/1 var(--ff);letter-spacing:.3px}
.icons{width:calc(106px * var(--s));height:calc(27px * var(--s))}
.cam{position:absolute;left:50%%;top:50%%;width:calc(30px * var(--s));height:calc(30px * var(--s));
  margin:calc(-15px * var(--s)) 0 0 calc(-15px * var(--s));border-radius:50%%;background:#050605;
  box-shadow:inset 0 0 0 calc(5px * var(--s)) #1A1D1B}
'''

BASE_CSS = '''
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:%(w)dpx;height:%(h)dpx;overflow:hidden}
body{font-family:var(--ff);position:relative;background:linear-gradient(170deg,%(bg1)s 0%%,%(bg2)s 100%%)}
.deco{position:absolute;inset:0}
.hl{color:%(accent)s}
.phone{position:absolute;background:#0B0D0C;box-shadow:%(phone_shadow)s}
.screen{position:relative;overflow:hidden;background:#fff}
.screen img{display:block}
''' + BAR_CSS + '''.chips{display:flex;flex-wrap:wrap;gap:12px}
.chips span{font-weight:600;color:%(ink)s;background:rgba(255,255,255,.72);
  border:2px solid %(chip_border)s;border-radius:99px}
.mascot{display:block}
'''

PORTRAIT_CSS = '''
.head{position:absolute;left:70px;right:70px;top:40px;height:480px;display:flex;flex-direction:column;
  justify-content:center;text-align:center}
h1{font-weight:700;font-size:88px;line-height:1.04;letter-spacing:-1px;color:%(ink)s;text-wrap:balance}
p{margin-top:26px;font-weight:500;font-size:40px;line-height:1.28;color:%(sub)s;text-wrap:balance}
.notify{position:absolute;left:62px;right:62px;top:634px;display:flex;gap:26px;align-items:flex-start;
  padding:30px 34px;border-radius:40px;background:#FFFFFF;
  box-shadow:0 30px 60px rgba(20,40,25,.28),0 6px 16px rgba(20,40,25,.14)}
.nicon{flex:none;width:92px;height:92px;border-radius:26px;background:%(tile)s;display:grid;place-items:center}
.nicon .mascot{width:96px;height:96px}
.ntext{min-width:0}
.nhead{font:600 28px/1.2 var(--ff);color:%(accent)s}
.nhead span{color:#7A857C;font-weight:500}
.ntitle{margin-top:6px;font:700 36px/1.2 var(--ff);color:#1F2A21;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nbody{margin-top:4px;font:500 31px/1.3 var(--ff);color:#4D5C50}
'''

LANDSCAPE_CSS = '''
.copy{position:absolute;left:120px;top:0;bottom:0;width:780px;display:flex;flex-direction:column;justify-content:center}
.brand{display:flex;align-items:center;gap:20px}
.brand .mascot{width:104px;height:104px;margin:-10px}
.brand b{font:600 34px/1 var(--ff);letter-spacing:4px;text-transform:uppercase;color:%(accent)s}
h1{margin-top:34px;font:700 92px/1.02 var(--ff);letter-spacing:-1.2px;color:%(ink)s;text-wrap:balance}
p{margin-top:28px;font:500 40px/1.3 var(--ff);color:%(sub)s;text-wrap:balance}
.chips{margin-top:40px}
.chips span{font-size:28px;padding:14px 24px}
'''

FEATURE_CSS = '''
.guard{position:absolute;left:34px;top:118px;width:250px;height:250px;
  filter:drop-shadow(0 16px 22px rgba(31,74,42,.22))}
.guard .mascot{width:100%%;height:100%%}
.copy{position:absolute;left:286px;top:0;bottom:0;width:440px;display:flex;flex-direction:column;justify-content:center}
.name{font:600 26px/1 var(--ff);letter-spacing:3px;text-transform:uppercase;color:%(accent)s}
.copy h1{margin-top:14px;font:700 58px/1.02 var(--ff);letter-spacing:-.6px;color:%(ink)s;text-wrap:balance}
.copy p{margin-top:14px;font:500 25px/1.25 var(--ff);color:%(sub)s}
.chips{margin-top:20px;gap:9px}
.chips span{font-size:18px;padding:8px 14px}
'''

# ---- the pop layout. Colours come from pop_vals(theme); positions the app
# chooses (pills, pictures) are written on each element.

POP_CSS = '''
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:%(w)dpx;height:%(h)dpx;overflow:hidden}
body{font-family:var(--ff);position:relative;background:%(ground)s}
.blob{position:absolute;border-radius:50%%}
.leaves{position:absolute;inset:0}
.dots{position:absolute;inset:0;background-image:radial-gradient(%(dots)s 2px,transparent 2.5px);
  background-size:46px 46px;-webkit-mask-image:linear-gradient(#000,transparent 55%%);
  mask-image:linear-gradient(#000,transparent 55%%)}
.t{color:%(ink)s;font-weight:700;letter-spacing:-.01em;text-shadow:%(title_shadow)s}
.u{position:relative;display:inline-block}
.u svg{position:absolute;left:-2%%;width:104%%;bottom:-.42em;height:.3em;overflow:visible}
.u path{fill:none;stroke:%(underline)s;stroke-width:7;stroke-linecap:round}
.u.u-colour{color:%(underline)s}
.sub{color:%(ink)s;font-weight:500;text-shadow:%(title_shadow)s}
.mascot{display:block}
.phone{position:absolute;background:%(phone)s;border-radius:var(--r);padding:var(--b);
  box-shadow:0 50px 90px %(shade40)s,0 12px 26px %(shade25)s}
.screen{position:relative;border-radius:calc(var(--r) - var(--b));overflow:hidden;background:#F3F8F2}
.screen img{display:block;width:100%%}
''' + BAR_CSS + '''.pill{position:absolute;display:flex;align-items:center;gap:.5em;background:%(pill)s;border-radius:999px;
  padding-block:.42em;padding-inline:.42em .9em;font-weight:600;line-height:1.2;color:%(pill_ink)s;
  white-space:nowrap;z-index:5;box-shadow:0 16px 30px %(shade30)s,0 0 0 3px %(ring)s}
.pill.go{background:%(accent)s;color:%(pill)s;padding-block:.5em;padding-inline:.6em 1.1em;
  box-shadow:0 16px 30px %(shade35)s,0 0 0 4px %(pill)s}
.ck{width:1.5em;height:1.5em;border-radius:50%%;background:%(accent)s;display:grid;place-items:center;flex:none}
.go .ck{background:%(pill)s}
.ck:after{content:"";width:28%%;height:52%%;border:solid %(pill)s;border-width:0 .16em .16em 0;
  transform:translateY(-12%%) rotate(45deg)}
.go .ck:after{border-color:%(accent)s}
.art{position:absolute;filter:drop-shadow(0 14px 18px %(shade35)s)}
.chips{display:flex;flex-wrap:wrap;gap:12px}
.chip{color:%(ink)s;font-weight:600;line-height:1.2;border-radius:999px;background:%(glass)s;
  border:2px solid %(glass_line)s}
.copy{position:absolute;top:0;bottom:0;display:flex;flex-direction:column;justify-content:center}
.brand{display:flex;align-items:center}
.brand .mascot{filter:drop-shadow(0 8px 14px %(shade35)s)}
.name{line-height:1.2}
.copy h1{line-height:1.02}
.notify{position:absolute;z-index:6;background:%(pill)s;border-radius:34px;padding:28px 30px;display:flex;
  gap:24px;align-items:center;box-shadow:0 26px 50px %(shade35)s}
.nicon{width:88px;height:88px;border-radius:24px;background:%(accent)s;display:grid;place-items:center;flex:none}
.nicon .mascot{height:60px}
.ntext{min-width:0}
.nhead{font-size:28px;line-height:1.2;color:#6B7A6E;font-weight:500}
.ntitle{margin-top:4px;font-size:38px;line-height:1.2;font-weight:700;color:%(pill_ink)s;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nbody{margin-top:2px;font-size:34px;line-height:1.2;font-weight:500;color:#3B4A3F}
'''

POP_PORTRAIT_CSS = '''
.head{position:absolute;left:40px;right:40px;top:120px;height:380px;text-align:center}
.head h1{font-size:124px;line-height:1.02}
.head p{margin-top:24px;font-size:44px;line-height:1.2}
'''

POP_LANDSCAPE_CSS = '''
.brand{gap:18px}
.brand .mascot{height:87px}
.name{font-size:60px}
.copy h1{font-size:100px;margin-top:46px}
.copy p{margin-top:28px;font-size:40px;line-height:1.25}
.chips{margin-top:52px}
.chip{font-size:27px;padding:10px 22px}
'''

POP_FEATURE_CSS = '''
.brand{gap:10px}
.brand .mascot{height:49px}
.name{font-size:34px}
.copy h1{font-size:52px;margin-top:24px}
.copy p{margin-top:14px;font-size:24px;line-height:1.25}
.chips{margin-top:20px;gap:9px}
.chip{font-size:18px;padding:7px 14px}
'''

# The hand-drawn line under a title's [word].
SWOOSH = '<svg viewBox="0 0 200 20" preserveAspectRatio="none"><path d="M3 13 C 50 4, 120 3, 197 9"/></svg>'

# The mark on a pop title's [word], per `underline_style`: the swoosh, drawn clear of the
# descenders, or `colour`, no line and the word itself in the underline colour.
UNDERLINE_SVG = {
    'swoosh': SWOOSH,
    'colour': '',
    'none': '',
}

# Where the pop pages put their phones: (left, top, width, tilt, z) for 1, 2
# or 3 captures, and the halo (x, y, radius) and sprigs (x, y, angle, length,
# seed) of the ground. All left-to-right; right-to-left pages mirror them.
POP_HERO_PHONES = {2: [(150, 260, 390, -9, 1), (470, 150, 450, 5, 2)],
                   3: [(90, 300, 360, -10, 1), (310, 150, 440, 0, 2), (580, 300, 360, 10, 1)]}
POP_FEATURE_PHONES = {1: [(700, 50, 250, 6, 2)],
                      2: [(560, 90, 220, -8, 1), (740, 50, 240, 6, 2)]}
POP_GROUND = {
    'portrait': ((540, 1150, 560), [(1080, 520, 160, 300, 3), (0, 1920, -50, 360, 5)]),
    'landscape': ((560, 560, 500), [(0, 1080, -60, 330, 2), (980, 0, 110, 230, 7), (1920, 1080, 210, 280, 4)]),
    'feature': ((780, 260, 290), [(0, 500, -40, 200, 6)]),
}


def rgba(colour, alpha):
    """'#RRGGBB' (or '#RGB') at an opacity."""
    c = str(colour).lstrip('#')
    if len(c) == 3:
        c = ''.join(ch * 2 for ch in c)
    try:
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise UsageError(f'art.toml: {colour!r} is not a #RRGGBB colour', code='BAD_ART') from None
    return f'rgba({r},{g},{b},{alpha:g})'


def pop_vals(theme):
    """A pop theme plus the values its CSS derives from it."""
    s, g = theme['shade'], theme['glow']
    return dict(theme,
                ground=(f"radial-gradient(130% 80% at 50% 0%,{theme['bg1']} 0%,{theme['bg2']} "
                        f"{theme['bg_mid']}%,{theme['bg3']} 100%)"),
                ring=rgba(theme['accent'], .9), dots=rgba(g, .10), glass=rgba(g, .16), glass_line=rgba(g, .55),
                **{f'shade{n}': rgba(s, n / 100) for n in (25, 30, 35, 40)})


def pop_rich(text, style='swoosh'):
    """Escape a pop title: [word] gets its underline, a newline breaks the line."""
    return (html.escape(text).replace('\n', '<br>')
            .replace('[', '<span class="u">' if style == 'swoosh' else f'<span class="u u-{style}">')
            .replace(']', UNDERLINE_SVG[style] + '</span>'))


class Pages:
    """Every page for one language: (file stem, html, size, target file)."""

    def __init__(self, design, code, work):
        self.d = design
        self.code = code
        self.words = design.words(code)
        self.rtl = self.words.get('dir') == 'rtl' or code.split('-')[0] in RTL and 'dir' not in self.words
        self.dir = 'rtl' if self.rtl else 'ltr'
        self.shots = Shots(design, code, work)

    def font_stack(self):
        extra = self.words.get('font') or self.d.script_fonts.get(self.code) \
            or self.d.script_fonts.get(self.code.split('-')[0])
        return f"'{self.d.font}', " + (f"'{extra}', " if extra else '') + 'sans-serif'

    def font_faces(self):
        if not self.d.font_dir:
            return ''
        faces = []
        for weight, style in [(400, 'Regular'), (500, 'Medium'), (600, 'SemiBold'), (700, 'Bold')]:
            file = self.d.font_dir / f'{self.d.font}-{style}.ttf'
            if file.is_file():
                faces.append(f"@font-face{{font-family:'{self.d.font}';font-weight:{weight};"
                             f"src:url('{file.as_uri()}')}}")
        return '\n'.join(faces)

    def mascot(self):
        if not self.d.mascot or not self.d.mascot.is_file():
            return ''
        return f'<img class="mascot" src="{self.d.mascot.as_uri()}" alt="">'

    def page(self, css, body, size, theme, base=BASE_CSS):
        vals = dict(theme, w=size[0], h=size[1])
        return (f'<!doctype html><html lang="{self.code}"><head><meta charset="utf-8"><style>\n'
                f'{self.font_faces()}\n:root{{--ff:{self.font_stack()}}}\n{base % vals}\n{css % vals}\n'
                f'{LANG_CSS.get(self.code) or LANG_CSS.get(self.code.split("-")[0], "")}'
                f'</style></head><body>{body}</body></html>')

    def phone(self, name, x, y, width, bezel=16, offset=0, rotate=0, extra=''):
        path, ink = self.shots.get(name)
        screen_w = width - 2 * bezel
        screen_h = round(screen_w * SHOT_H / SHOT_W)
        scale = screen_w / SHOT_W
        bar_h = round(self.shots.bar_height * scale)
        turn = f'transform:rotate({rotate}deg);' if rotate else ''
        bar = '' if self.shots.clean else f'''
    <div class="bar" style="height:{bar_h}px;--s:{screen_w / 808:.3f}">
      {status_icons(ink)}
      <div class="cam"></div>
    </div>'''
        return f'''
<div class="phone" style="left:{x}px;top:{y}px;width:{width}px;height:{screen_h + 2 * bezel}px;
     padding:{bezel}px;border-radius:{round(width * .105)}px;{turn}{extra}">
  <div class="screen" style="width:{screen_w}px;height:{screen_h}px;border-radius:{round(width * .085)}px">
    <img src="{path.as_uri()}" style="width:{screen_w}px;height:{screen_h}px;margin-top:-{round(offset * scale)}px">{bar}
  </div>
</div>'''

    def chips(self, words):
        return ''.join(f'<span>{html.escape(c)}</span>' for c in words)

    def notification(self, n):
        return f'''
<div class="notify" dir="{self.dir}">
  <div class="nicon">{self.mascot()}</div>
  <div class="ntext">
    <div class="nhead">{html.escape(n['app'])} <span>&#8226; {html.escape(n['when'])}</span></div>
    <div class="ntitle" data-m="notify.title">{html.escape(n['title'])}</div>
    <div class="nbody" data-m="notify.body">{html.escape(n['body'])}</div>
  </div>
</div>'''

    def portrait(self, i, slide, words):
        theme = self.d.theme['dark' if slide.get('dark') else 'light']
        w, h = PORTRAIT
        rnd = random.Random(i * 7 + 3)
        deco = backdrop(self.d.decoration, (w, h), theme, [
            (rnd.choice([-40, w + 40]), rnd.uniform(200, 700), 60, 9, i, 34),
            (rnd.choice([-60, w + 60]), rnd.uniform(1300, 1800), 80, 10, i + 11, 34)])
        notify = self.notification(words['notify']) if slide.get('notify') else ''
        body = f'''
<svg class="deco" viewBox="0 0 {w} {h}">{deco}</svg>
<div class="head" dir="{self.dir}"><h1 data-m="title">{rich(words['title'])}</h1><p data-m="sub">{rich(words['sub'])}</p></div>
{self.phone(slide['shot'], 118, 540, 844, offset=slide.get('offset', 0))}
{notify}'''
        return self.page(PORTRAIT_CSS, body, PORTRAIT, theme)

    def landscape(self, slide, words):
        theme = self.d.theme['light']
        w, h = LANDSCAPE
        x, turn = mirror(self.rtl, w)
        left, mid, right = slide['shots']
        deco = backdrop(self.d.decoration, (w, h), theme, [
            (x(1500), 560, 120, 13, 4, 40), (x(-40), 1040, 60, 8, 8, 34)])
        body = f'''
<svg class="deco" viewBox="0 0 {w} {h}">{deco}</svg>
<div class="copy" dir="{self.dir}">
  <div class="brand">{self.mascot()}<b data-m="name">{html.escape(words['name'])}</b></div>
  <h1 data-m="title">{rich(words['title'])}</h1>
  <p data-m="sub">{rich(words['sub'])}</p>
  <div class="chips" data-m="chips">{self.chips(words.get('chips', []))}</div>
</div>
{self.phone(left, x(1010, 400), 230, 400, bezel=11, rotate=turn(-7))}
{self.phone(right, x(1445, 400), 230, 400, bezel=11, rotate=turn(7))}
{self.phone(mid, x(1215, 450), 110, 450, bezel=12, extra="z-index:2")}'''
        css = LANDSCAPE_CSS + ('.copy{left:auto;right:120px}' if self.rtl else '')
        return self.page(css, body, LANDSCAPE, theme)

    def feature(self, slide, words):
        theme = self.d.theme['light']
        w, h = FEATURE
        x, turn = mirror(self.rtl, w)
        deco = backdrop(self.d.decoration, (w, h), theme, [
            (x(930), 70, 40, 10, 5, 34), (x(40), 480, 50, 8, 9, 34)])
        body = f'''
<svg class="deco" viewBox="0 0 {w} {h}">{deco}</svg>
<div class="guard">{self.mascot()}</div>
<div class="copy" dir="{self.dir}">
  <div class="name" data-m="name">{html.escape(words['name'])}</div>
  <h1 data-m="title">{rich(words['title'])}</h1>
  <p data-m="sub">{rich(words['sub'])}</p>
  <div class="chips" data-m="chips">{self.chips(words.get('chips', []))}</div>
</div>
{self.phone(slide['shot'], x(740, 230), 58, 230, bezel=7, rotate=turn(5))}'''
        css = FEATURE_CSS + ('.guard{left:auto;right:34px}.copy{left:auto;right:286px}' if self.rtl else '')
        return self.page(css, body, FEATURE, theme)

    # ------------------------------------------------ the pop layout

    def pop_ground(self, kind, size, theme):
        """Depth behind everything: a soft dark and a soft light blob, a halo
        and ring where the phones stand, faint sprigs, and a dot texture that
        fades out down the page."""
        w, h = size
        (hx, hy, hr), sprigs = POP_GROUND[kind]
        if self.rtl:
            hx = w - hx
            sprigs = [(w - x, y, 180 - a, ln, seed) for x, y, a, ln, seed in sprigs]
        g = theme['glow']
        blob = ('<div class="blob" style="left:{:.0f}px;top:{:.0f}px;width:{:.0f}px;height:{:.0f}px;'
                'background:radial-gradient({},transparent {}%);opacity:{}"></div>')
        if self.d.ornament == 'scatter':
            leaves = scatter(w, h, g, self.rtl)
        else:
            leaves = ''.join(ornament(self.d.ornament, x, y, math.radians(a), ln, seed, g)
                             for x, y, a, ln, seed in sprigs)
        dots = '' if self.d.ornament == 'scatter' else '<div class="dots"></div>'
        return (blob.format(-w * .15, h * .55, w * .6, w * .6, theme['blob_dark'], 68, .55)
                + blob.format(w * .55, -h * .35, w * .6, w * .6, theme['blob_light'], 66, .45)
                + f'<div class="blob" style="left:{hx - hr}px;top:{hy - hr}px;width:{2 * hr}px;height:{2 * hr}px;'
                  f'background:radial-gradient({rgba(g, .32)},{rgba(g, .10)} 45%,transparent 70%)"></div>'
                + f'<div class="blob" style="left:{hx - hr * .78:.0f}px;top:{hy - hr * .78:.0f}px;'
                  f'width:{hr * 1.56:.0f}px;height:{hr * 1.56:.0f}px;border:3px solid {rgba(g, .16)}"></div>'
                + f'<svg class="leaves" viewBox="0 0 {w} {h}">{leaves}</svg>{dots}')

    def pop_phone(self, name, x, y, width, rotate=0, z=1, offset=0):
        path, ink = self.shots.get(name)
        b, r = width * .02, width * .12
        screen_w = width - 2 * b
        scale = screen_w / SHOT_W
        bar = '' if self.shots.clean else (
            f'<div class="bar" style="height:{round(self.shots.bar_height * scale)}px;--s:{screen_w / 808:.3f}">'
            f'{status_icons(ink)}<div class="cam"></div></div>')
        shift = f' style="margin-top:-{offset * scale:.1f}px"' if offset else ''
        return (f'<div class="phone" style="left:{x}px;top:{y}px;width:{width}px;--r:{r:.0f}px;--b:{b:.1f}px;'
                f'transform:rotate({rotate}deg);z-index:{z}"><div class="screen" style="height:'
                f'{screen_w * SHOT_H / SHOT_W:.1f}px"><img src="{path.as_uri()}"{shift}>{bar}</div></div>')

    def pop_phones(self, names, spots, size):
        x, turn = mirror(self.rtl, size[0])
        if len(names) not in spots:
            raise UsageError(f'art.toml: this page takes {" or ".join(map(str, spots))} shots, '
                             f'not {len(names)}', code='BAD_ART')
        return ''.join(self.pop_phone(n, x(px, pw), py, pw, turn(rot), z)
                       for n, (px, py, pw, rot, z) in zip(names, spots[len(names)]))

    def pop_extras(self, place, words, where, size):
        """The app's own pictures ([[...art]]) and pills ([[...pill]]) on a
        page, at the page pixels it gave; mirrored on right-to-left pages."""
        _, turn = mirror(self.rtl, size[0])
        side = 'right' if self.rtl else 'left'
        out = []
        for a in place.get('art') or []:
            out.append(f'<img class="art" src="{self.d.asset(a["src"]).as_uri()}" alt="" style="{side}:{a["x"]}px;'
                       f'top:{a["y"]}px;height:{a["height"]}px;transform:rotate({turn(a.get("rotate", 0))}deg);'
                       f'z-index:{a.get("z", 4)}">')
        for i, p in enumerate(place.get('pill') or []):
            if 'text' in p:
                text, mark = str(p['text']), f'pill.{i + 1}'
            elif 'key' in p:
                try:
                    text = words['pills'][p['key']]
                except (KeyError, TypeError):
                    raise UsageError(f'captions/{self.code}.json has no {where}.pills.{p["key"]}',
                                     code='BAD_CAPTIONS') from None
                mark = f'pill.{p["key"]}'
            else:
                raise UsageError(f'art.toml: a pill on {where} needs key or text', code='BAD_ART')
            out.append(f'<div class="pill{" go" if p.get("go") else ""}" dir="{self.dir}" data-m="{html.escape(mark)}" '
                       f'style="{side}:{p["x"]}px;top:{p["y"]}px;font-size:{p.get("size", 44)}px;'
                       f'transform:rotate({turn(p.get("rotate", 0))}deg)"><span class="ck"></span>'
                       f'<span class="pt">{html.escape(text)}</span></div>')
        return '\n'.join(out)

    def pop_copy(self, words, left, width, size):
        """Brand (mascot and name), title, an optional line and chips."""
        x, _ = mirror(self.rtl, size[0])
        mark = self.d.underline_style
        sub = f'<p class="sub" data-m="sub">{pop_rich(words["sub"], mark)}</p>' if words.get('sub') else ''
        chips = ''.join(f'<span class="chip">{html.escape(c)}</span>' for c in words.get('chips') or [])
        chips = f'<div class="chips" data-m="chips">{chips}</div>' if chips else ''
        return (f'<div class="copy" dir="{self.dir}" style="left:{x(left, width)}px;width:{width}px">'
                f'<div class="brand">{self.mascot()}<span class="t name" data-m="name">'
                f'{html.escape(words["name"])}</span></div>'
                f'<h1 class="t" data-m="title">{pop_rich(words["title"], mark)}</h1>{sub}{chips}</div>')

    def pop_notification(self, n, y, width):
        _, turn = mirror(self.rtl, width)
        return f'''
<div class="notify" dir="{self.dir}" style="left:70px;top:{y}px;width:{width - 140}px;transform:rotate({turn(-2)}deg)">
  <div class="nicon">{self.mascot()}</div>
  <div class="ntext">
    <div class="nhead">{html.escape(n['app'])} &nbsp;&#183;&nbsp; {html.escape(n['when'])}</div>
    <div class="ntitle" data-m="notify.title">{html.escape(n['title'])}</div>
    <div class="nbody" data-m="notify.body">{html.escape(n['body'])}</div>
  </div>
</div>'''

    def pop_portrait(self, slide, words):
        theme = self.d.theme['dark' if slide.get('dark') else 'light']
        w = PORTRAIT[0]
        x, _ = mirror(self.rtl, w)
        mark = self.d.underline_style
        sub = f'<p class="sub" data-m="sub">{pop_rich(words["sub"], mark)}</p>' if words.get('sub') else ''
        notify = self.pop_notification(words['notify'], slide.get('notify_y', 600), w) if slide.get('notify') else ''
        body = f'''{self.pop_ground('portrait', PORTRAIT, theme)}
<div class="head" dir="{self.dir}"><h1 class="t" data-m="title" data-max="2">{pop_rich(words['title'], mark)}</h1>{sub}</div>
{self.pop_phone(slide['shot'], x(160, 760), 520, 760, offset=slide.get('offset', 0))}
{self.pop_extras(slide, words, slide['id'], PORTRAIT)}
{notify}'''
        return self.page(POP_PORTRAIT_CSS, body, PORTRAIT, pop_vals(theme), base=POP_CSS)

    def pop_landscape(self, slide, words):
        theme = self.d.theme['dark' if slide.get('dark') else 'light']
        body = f'''{self.pop_ground('landscape', LANDSCAPE, theme)}
{self.pop_phones(slide['shots'], POP_HERO_PHONES, LANDSCAPE)}
{self.pop_extras(slide, words, slide['id'], LANDSCAPE)}
{self.pop_copy(words, 1030, 780, LANDSCAPE)}'''
        return self.page(POP_LANDSCAPE_CSS, body, LANDSCAPE, pop_vals(theme), base=POP_CSS)

    def pop_feature(self, feature, words):
        theme = self.d.theme['light']
        shots = feature.get('shots') or [feature['shot']]
        body = f'''{self.pop_ground('feature', FEATURE, theme)}
{self.pop_phones(shots, POP_FEATURE_PHONES, FEATURE)}
{self.pop_extras(feature, words, 'feature', FEATURE)}
{self.pop_copy(words, 60, 470, FEATURE)}'''
        return self.page(POP_FEATURE_CSS, body, FEATURE, pop_vals(theme), base=POP_CSS)

    def all(self):
        jobs = []
        shots_dir = self.d.screenshot_dir(self.code)
        pop = self.d.layout == 'pop'
        for i, slide in enumerate(self.d.slides):
            try:
                text = self.words[slide['id']]
            except KeyError:
                raise UsageError(f'captions/{self.code}.json has no "{slide["id"]}"', code='BAD_CAPTIONS')
            stem = f'{i + 1:02d}_{slide["id"]}'
            if slide.get('kind') == 'landscape':
                doc = self.pop_landscape(slide, text) if pop else self.landscape(slide, text)
                size = LANDSCAPE
            else:
                doc = self.pop_portrait(slide, text) if pop else self.portrait(i, slide, text)
                size = PORTRAIT
            jobs.append((stem, doc, size, shots_dir / f'{stem}.png'))
        feature = self.d.data.get('feature') or {'shot': self.d.slides[0].get('shot', 'home')}
        draw = self.pop_feature if pop else self.feature
        jobs.append(('feature', draw(feature, self.words['feature']), FEATURE,
                     self.d.feature_file(self.code)))
        return jobs


# ---------------------------------------------------------------- the browser

def _playwright(pattern):
    """Browsers Playwright downloaded, newest first."""
    root = Path(os.path.expandvars(r'%LOCALAPPDATA%\ms-playwright'))
    return [str(p) for p in sorted(root.glob(pattern), reverse=True)] if root.is_dir() else []


def _answers(exe):
    """Whether a browser draws a page and hands back its DOM before it exits.
    Some launchers return at once and leave the work to a process they start
    (Edge does while an update waits for a restart); those cannot be used."""
    profile = tempfile.mkdtemp(prefix='mkit-art-browser-')
    try:
        dom = subprocess.run(
            [str(exe), '--headless=new', '--disable-gpu', f'--user-data-dir={profile}',
             '--dump-dom', 'data:text/html,<p>@@ready@@</p>'],
            capture_output=True, timeout=60, text=True, encoding='utf-8', errors='replace').stdout
        return '@@ready@@' in dom
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def browser(project):
    """A Chromium-based browser to draw pages: [art] browser, else the first of
    Edge, Chrome or a Playwright Chromium that answers."""
    named = project.get('art.browser')
    if named:
        if Path(named).is_file():
            return Path(named)
        raise NotFound(f'[art] browser not found: {named}', code='NO_BROWSER')
    exe = '.exe' if os.name == 'nt' else ''
    candidates = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        *(shutil.which(n) or '' for n in ('msedge', 'microsoft-edge', 'google-chrome', 'chromium',
                                          'chromium-browser', 'chrome')),
        *_playwright('chromium_headless_shell-*/*/chrome-headless-shell' + exe),
        *_playwright('chromium-*/*/chrome' + exe),
    ]
    found = list(dict.fromkeys(c for c in candidates if c and Path(c).is_file()))
    for c in found:
        if _answers(c):
            return Path(c)
    if found:
        raise NotFound('no browser answered: ' + ', '.join(found),
                       hint='Restart Edge if it has an update waiting, install Chrome, run '
                            '`uvx playwright install chromium-headless-shell`, or set '
                            'browser = "<path>" under [art].', code='NO_BROWSER')
    raise NotFound('no Chromium browser found to draw the art (Edge or Chrome)',
                   hint='Install Edge or Chrome, or set browser = "<path>" under [art].',
                   code='NO_BROWSER')


# Added to a page for check: once the fonts are in, write each marked block's
# line count (chips: rows) and whether it runs past its box (a pill: past the
# page's edge), plus its line cap (data-max) when it has one.
MEASURE_JS = '''<script>
document.fonts.ready.then(() => {
  const r = {};
  const W = document.body.offsetWidth, H = document.body.offsetHeight;
  const count = e => Math.round(e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight));
  document.querySelectorAll('[data-m]').forEach(e => {
    let lines, over = e.scrollWidth > e.clientWidth + 1;
    if (e.classList.contains('chips')) {
      lines = new Set([...e.children].map(c => Math.round(c.getBoundingClientRect().top))).size;
    } else if (e.classList.contains('pill')) {
      const t = e.querySelector('.pt');  // its layout height: a tilt would inflate the box
      lines = Math.round(t.offsetHeight / parseFloat(getComputedStyle(t).lineHeight));
      const b = e.getBoundingClientRect();
      over = b.left < -1 || b.top < -1 || b.right > W + 1 || b.bottom > H + 1;
    } else {
      lines = count(e);
    }
    r[e.dataset.m] = {lines, over};
    if (e.dataset.max) r[e.dataset.m].max = +e.dataset.max;
  });
  const head = document.querySelector('.head');
  if (head) r['head'] = {lines: 0, over: head.scrollHeight > head.clientHeight + 1};
  const pre = document.createElement('pre');
  pre.textContent = '@@' + JSON.stringify(r) + '@@';
  document.body.appendChild(pre);
});
</script>'''


class Renderer:
    def __init__(self, exe):
        self.exe = exe

    def _run(self, args):
        profile = tempfile.mkdtemp(prefix='mkit-art-browser-')
        try:
            return subprocess.run(
                [str(self.exe), '--headless=new', '--disable-gpu', '--hide-scrollbars',
                 '--force-device-scale-factor=1', '--allow-file-access-from-files',
                 '--virtual-time-budget=3000', f'--user-data-dir={profile}', *args],
                check=True, capture_output=True, timeout=180, text=True, encoding='utf-8', errors='replace')
        finally:
            shutil.rmtree(profile, ignore_errors=True)

    def png(self, page, target, size):
        w, h = size
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix('.raw.png')
        self._run([f'--window-size={w},{h}', f'--screenshot={tmp}', page.as_uri()])
        for _ in range(100):  # a launcher can return just before the file lands
            if tmp.is_file():
                break
            time.sleep(0.1)
        im = Image.open(tmp).convert('RGB')
        if im.size != (w, h):
            im = im.crop((0, 0, w, h))
        im.save(target, optimize=True)
        tmp.unlink()

    def measure(self, page, size):
        w, h = size
        dom = self._run([f'--window-size={w},{h}', '--dump-dom', page.as_uri()]).stdout
        parts = dom.rsplit('@@', 2)
        if len(parts) < 3:
            raise UsageError(f'{page.name}: the page did not report its layout', code='MEASURE_FAILED')
        return json.loads(parts[1])


# ---------------------------------------------------------------- check and build

def compare(got, ref):
    """Where a language's line counts differ from the reference's, or pass a
    block's line cap. With an empty reference, only boxes and caps are checked
    (how the reference itself is checked)."""
    problems = []
    for stem, blocks in got.items():
        for key, m in blocks.items():
            want = ref.get(stem, {}).get(key, {}).get('lines')
            # A notification title ends in "..." when too long, as on a phone.
            if m['over'] and key != 'notify.title':
                problems.append(f'{stem} {key}: runs past its box')
            if m.get('max') and m['lines'] > m['max']:
                problems.append(f'{stem} {key}: {m["lines"]} lines, at most {m["max"]}')
            elif key != 'head' and want is not None and m['lines'] != want:
                problems.append(f'{stem} {key}: {m["lines"]} lines, reference has {want}')
    return problems


def _measure_all(design, code, work, renderer, pool):
    runs = {}
    for stem, doc, size, _ in Pages(design, code, work).all():
        page = work / code / f'{stem}.check.html'
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(doc.replace('</body>', MEASURE_JS + '</body>'), encoding='utf-8')
        runs[stem] = pool.submit(renderer.measure, page, size)
    return {stem: r.result() for stem, r in runs.items()}


def check(design, codes, workers=4, on_result=None):
    """{code: [problem, ...]} for each language; the reference is measured too."""
    renderer = Renderer(browser(design.project))
    work = Path(tempfile.mkdtemp(prefix='mkit-art-'))
    results = {}
    try:
        ref_words = design.words(design.reference)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            ref = _measure_all(design, design.reference, work, renderer, pool)
            results['_reference'] = ref
            for code in codes:
                if code == design.reference:
                    # The reference is measured against its own boxes and line caps.
                    problems = lint(ref_words, ref_words, design.slides) or compare(ref, {})
                    results[code] = problems
                    if on_result:
                        on_result(code, problems)
                    continue
                words = design.words(code)
                problems = lint(words, ref_words, design.slides)
                if not problems:
                    problems = compare(_measure_all(design, code, work, renderer, pool), ref)
                problems = [p.replace('reference has', f'{design.reference} has') for p in problems]
                results[code] = problems
                if on_result:
                    on_result(code, problems)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return results


def build(design, codes, workers=4, keep_pages=False, on_result=None):
    """Draw every image for each language; returns {code: [files]} and the
    folder the pages were kept in (or None)."""
    renderer = Renderer(browser(design.project))
    work = Path(tempfile.mkdtemp(prefix='mkit-art-'))
    written = {}
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for code in codes:
                shots_dir = design.screenshot_dir(code)
                shots_dir.mkdir(parents=True, exist_ok=True)
                for old in shots_dir.glob('*.png'):
                    old.unlink()
                runs = []
                for stem, doc, size, target in Pages(design, code, work).all():
                    page = work / code / f'{stem}.html'
                    page.parent.mkdir(parents=True, exist_ok=True)
                    page.write_text(doc, encoding='utf-8')
                    runs.append((target, pool.submit(renderer.png, page, target, size)))
                for target, r in runs:
                    r.result()
                written[code] = [str(t) for t, _ in runs]
                if on_result:
                    on_result(code, written[code])
    finally:
        if not keep_pages:
            shutil.rmtree(work, ignore_errors=True)
    return written, (work if keep_pages else None)


# ---------------------------------------------------------------- setting an app up

GITIGNORE_NOTE = '# Store art built by `mkit art build` (sources: {src})'


def init(project):
    """Create the art folder from the starter files, switch [art] on in
    mkit.toml and keep the built images out of git. Touches only what is
    missing; returns what it did."""
    done = []
    folder = project.path('art.dir', 'store/art')
    (folder / 'shots').mkdir(parents=True, exist_ok=True)
    (folder / 'captions').mkdir(parents=True, exist_ok=True)
    for src, dst in [(TEMPLATES / 'art.toml', folder / 'art.toml'),
                     (TEMPLATES / 'en.json', folder / 'captions' / 'en.json')]:
        if not dst.exists():
            shutil.copyfile(src, dst)
            done.append(f'wrote {dst.relative_to(project.root).as_posix()}')
    toml = project.root / 'mkit.toml'
    if not project.has('art'):
        text = toml.read_text(encoding='utf-8')
        text += ('' if text.endswith('\n') else '\n') + '\n[art]                         # store art: mkit art build\n'
        toml.write_text(text, encoding='utf-8')
        done.append('added [art] to mkit.toml')
    out = project.path('art.out') or project.path('store.art_dir', 'store')
    rel = out.relative_to(project.root).as_posix()
    rel = '' if rel == '.' else rel + '/'
    lines = [f'/{rel}screenshots/', f'/{rel}feature/']
    gi = project.root / '.gitignore'
    have = gi.read_text(encoding='utf-8').splitlines() if gi.is_file() else []
    missing = [line for line in lines if line not in have]
    if missing:
        note = GITIGNORE_NOTE.format(src=folder.relative_to(project.root).as_posix())
        block = '\n'.join([note, *missing]) + '\n'
        text = '\n'.join(have)
        gi.write_text((text + '\n\n' if text else '') + block, encoding='utf-8')
        done.append(f'.gitignore: {", ".join(missing)}')
    return done
