"""The guides: how an app should do the things every app has to do.

Each guide is a markdown file in docs/ that ships inside the package (as
mkit/_guides/), so
`mkit guide about` works offline on any machine. A guide is written once, for
everyone, and a studio's own details are filled in from its settings:

    {{studio.name}}                 a value, from [studio] in mkit.toml or
                                    ~/.mkit/config.toml
    {{about.rating_heading}}        a value with a default in DEFAULTS, or
    {{studio.tagline|...}}          after the bar (never inside a table)
    {{app.name|<App>}}              the app, inside a project; <App> outside

A value that is not set renders as ‹studio.name›, visible, so a guide never
quietly prints a blank where a fact should be - and `unset` names every one.

Parts a studio can leave out are marked, and dropped when [about] parts does
not list them:

    <!-- part:ask -->            on its own line: up to <!-- /part:ask -->
    | 7 | ... | <!-- part:ask --> at the end of a line: that line only

A studio may keep rules of its own beside a guide - decisions that are true
for it and nobody else - in a house folder: the file of the same name, which is
appended after the guide under a heading saying it overrides what it
contradicts. By default that folder is docs/house in the engine's own git
checkout; [guide] house_dir points anywhere else.
"""
import os
import re
from pathlib import Path

from . import config

# name -> (file, one-line description)
GUIDES = {
    'about': ('about-screen.md', 'the About screen: its parts, words, marks and behaviour'),
    'review': ('in-app-review.md', 'asking for a rating: when, where, and the rules Play enforces'),
    'update': ('in-app-update.md', 'checking for updates: Play decides, your policy says how hard to ask'),
    'aso': ('aso.md', 'being found on Play: the indexed fields, winnable keywords, the title'),
    'support': ('support-replies.md', 'answering users by email: plain text, every point, the sign-off'),
    'ui': ('app-ui.md', 'how an app is organised: colours, Pro, pickers, Settings'),
    'store': ('store.md', 'the store/ folder: what lives where, in every language'),
    'art': ('store-art.md', 'screenshots and the feature graphic, from real captures'),
    'news': ('news-topics.md', 'news and offer notifications over FCM topics'),
}

ABOUT_PARTS = ('mark', 'name', 'version', 'what', 'rating', 'maker', 'ask', 'more_apps', 'footer')

# The words a guide uses when [about] does not reword them. Kept here rather
# than after a bar in the guide, because a bar inside a markdown table ends the
# cell and the guide would not read on GitHub.
DEFAULTS = {
    'about.rating_heading': 'Enjoying <App>?',
    'about.rating_line': 'Rate it on Google Play and support our work.',
    'about.maker_heading': 'Meet the developer',
    'about.ask': 'We design and build mobile apps. <App> is one of ours. If you have one in mind, '
                 'tell us about it.',
    'about.email_button': 'Start a project',
    'about.website_button': 'Website',
    'about.more_heading': 'More from us',
    'about.more_line': 'Everything we have on the store, in one place.',
    'support.signoff': 'The <App> team',
}

_PLACEHOLDER = re.compile(r'\{\{\s*([a-z_]+(?:\.[a-z0-9_]+)+)\s*(?:\|([^}]*))?\}\}')
_BLOCK_OPEN = re.compile(r'^\s*<!--\s*part:([a-z_]+)\s*-->\s*$')
_BLOCK_CLOSE = re.compile(r'^\s*<!--\s*/part:([a-z_]+)\s*-->\s*$')
_LINE_PART = re.compile(r'<!--\s*part:([a-z_]+)\s*-->\s*$')

_ENGINE = Path(__file__).resolve().parent


def _locate(filename):
    """The guide inside the package (an install), else in the checkout's docs/."""
    for candidate in (_ENGINE / '_guides' / filename, _ENGINE.parents[1] / 'docs' / filename):
        if candidate.is_file():
            return candidate
    return None


def settings(project):
    """A get(dotted, default) over env, the project, then ~/.mkit/config.toml."""
    if project is not None:
        return project.get
    user_file = config.home() / 'config.toml'
    user = config._read_toml(user_file) if user_file.is_file() else {}

    def get(dotted, default=None):
        env = os.environ.get('MKIT_' + dotted.replace('.', '_').upper())
        if env is not None:
            return env
        value = config._dig(user, dotted)
        return default if value is None else value
    return get


def house_file(filename, get):
    explicit = get('guide.house_dir')
    folder = Path(explicit).expanduser() if explicit else _ENGINE.parents[1] / 'docs' / 'house'
    found = folder / filename
    return found if found.is_file() else None


def _keep_parts(text, enabled):
    """Drop the parts not in `enabled` (None keeps every one) and every marker."""
    def keep(part):
        return enabled is None or part in enabled
    out, skipping = [], None
    for line in text.split('\n'):
        opened = _BLOCK_OPEN.match(line)
        if opened:
            if not keep(opened.group(1)):
                skipping = opened.group(1)
            continue
        closed = _BLOCK_CLOSE.match(line)
        if closed:
            if skipping == closed.group(1):
                skipping = None
            continue
        if skipping:
            continue
        inline = _LINE_PART.search(line)
        if inline:
            if not keep(inline.group(1)):
                continue
            line = _LINE_PART.sub('', line).rstrip()
        out.append(line)
    return '\n'.join(out)


def render(name, project=None, raw=False):
    """The guide as text, filled in for this studio. Returns (text, info)."""
    filename, _ = GUIDES[name]
    path = _locate(filename)
    if path is None:
        raise FileNotFoundError(filename)
    text = path.read_text(encoding='utf-8')
    get = settings(project)
    house = house_file(filename, get)
    if house:
        text = (text.rstrip('\n') + '\n\n---\n\n## This studio\'s own rules\n\n'
                '*Kept by this studio, beside the guide above. Where the two disagree, '
                'these win.*\n\n' + house.read_text(encoding='utf-8').strip() + '\n')
    info = {'guide': name, 'file': str(path), 'house': str(house) if house else None, 'unset': []}
    if raw:
        return text, info

    parts = get('about.parts') if name == 'about' else None
    text = _keep_parts(text, set(parts) if parts is not None else None)

    unset = []

    def fill(match):
        key, default = match.group(1), match.group(2)
        if default is None:
            default = DEFAULTS.get(key)
        value = get(key)
        if value not in (None, ''):
            return str(value)
        if default is not None:
            return default
        if key not in unset:
            unset.append(key)
        return f'‹{key}›'

    info['unset'] = unset
    return _PLACEHOLDER.sub(fill, text), info
