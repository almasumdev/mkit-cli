"""Build Play's data safety CSV from a few lines of `mkit.toml`.

Play's Data safety form is 782 questions. The API takes the same CSV the
Console's import accepts, and there is no API that hands the current answers
back - `applications.dataSafety` is POST only - so the declaration has to be
kept in the repo, next to the code it describes.

Every app was doing that by hand: one wrote a script to fill Google's sample
CSV, two others carry a byte-identical copy of the result. That is the
duplication the engine exists to remove, so the question set ships here
(`data/datasafety-questions.csv`, answers stripped) and an app declares only
what it collects:

    [datasafety]
    collects             = true
    encrypted_in_transit = true
    deletion             = "no"
    account_creation     = "none"

    [datasafety.collected]
    crash_logs       = ["app_functionality", "analytics"]
    diagnostics      = ["app_functionality", "analytics"]
    app_interactions = ["analytics"]
    device_ids       = ["app_functionality", "analytics"]

`mkit datasafety build` turns that into the CSV at the `datasafety` path under
`[store]`; `check` validates it and `apply` uploads it. A data type left out of
[datasafety.collected] is declared as not collected, which is the whole point:
the file says what the app does, and nothing is true by omission.

**This is a declaration, not a description.** Whatever is written here is what
Play publishes on the store page and holds the developer to, so it follows the
code: an SDK added is a line added.
"""
import csv
import io
from pathlib import Path

from .errors import UsageError

QUESTIONS = Path(__file__).parent / 'data' / 'datasafety-questions.csv'

COLUMNS = (
    'Question ID (machine readable)',
    'Response ID (machine readable)',
    'Response value',
    'Answer requirement',
    'Human-friendly question label',
)

# The questions that are answered once for the whole app rather than per data type.
COLLECTS = 'PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA'
ENCRYPTED = 'PSL_DATA_COLLECTION_ENCRYPTED_IN_TRANSIT'
ACCOUNT_CREATION = 'PSL_SUPPORTED_ACCOUNT_CREATION_METHODS'
DELETION = 'PSL_SUPPORT_DATA_DELETION_BY_USER'
OUTSIDE_ACCOUNTS = 'PSL_HAS_OUTSIDE_APP_ACCOUNTS'
DELETION_URL = 'PSL_DATA_DELETION_URL'
ACCOUNT_DELETION_URL = 'PSL_ACCOUNT_DELETION_URL'
USAGE = 'PSL_DATA_USAGE_RESPONSES'

# How a purpose is spelled in mkit.toml, and the response id it answers.
PURPOSES = {
    'app_functionality': 'PSL_APP_FUNCTIONALITY',
    'analytics': 'PSL_ANALYTICS',
    'developer_communications': 'PSL_DEVELOPER_COMMUNICATIONS',
    'fraud_prevention': 'PSL_FRAUD_PREVENTION_SECURITY',
    'advertising': 'PSL_ADVERTISING',
    'personalization': 'PSL_PERSONALIZATION',
    'account_management': 'PSL_ACCOUNT_MANAGEMENT',
}

ACCOUNT_METHODS = {
    'none': 'PSL_ACM_NONE',
    'password': 'PSL_ACM_USER_ID_PASSWORD',
    'other_auth': 'PSL_ACM_USER_ID_OTHER_AUTH',
    'password_other_auth': 'PSL_ACM_USER_ID_PASSWORD_OTHER_AUTH',
    'oauth': 'PSL_ACM_OAUTH',
    'other': 'PSL_ACM_OTHER',
}

DELETION_CHOICES = {
    'yes': 'DATA_DELETION_YES',
    'no': 'DATA_DELETION_NO',
    'auto': 'DATA_DELETION_NO_AUTO_DELETED',
}

# Short spellings for types whose own label is a mouthful or repeats itself.
# Every type also answers to the name derived from its label, and to its raw
# PSL id, so nobody has to guess which of the three was meant.
ALIASES = {
    'device_ids': 'PSL_DEVICE_ID',
    'diagnostics': 'PSL_PERFORMANCE_DIAGNOSTICS',
    'app_interactions': 'PSL_USER_INTERACTION',
    'user_ids': 'PSL_USER_ACCOUNT',
    'installed_apps': 'PSL_APPS_ON_DEVICE',
    'payment_info': 'PSL_CREDIT_DEBIT_BANK_ACCOUNT_NUMBER',
    'user_generated_content': 'PSL_USER_GENERATED_CONTENT',
}


def _slug(text):
    """A label's last segment as a mkit.toml name: 'App activity / App interactions'."""
    tail = (text or '').replace('\n', ' / ').split(' / ')[-1].strip().lower()
    return ''.join(c if c.isalnum() else '_' for c in tail).strip('_')


def question_rows():
    """The shipped question set, as dicts. Read once per call; it is 782 rows."""
    text = QUESTIONS.read_text(encoding='utf-8-sig')
    return list(csv.DictReader(io.StringIO(text)))


def data_types(rows=None):
    """Every data type: its PSL id, the names it answers to, and its label."""
    types = {}
    for row in rows or question_rows():
        if not row[COLUMNS[0]].startswith('PSL_DATA_TYPES_'):
            continue
        psl = row[COLUMNS[1]]
        label = (row[COLUMNS[4]] or '').replace('\n', ' / ')
        names = {psl, _slug(label)}
        names |= {alias for alias, target in ALIASES.items() if target == psl}
        types[psl] = {'id': psl, 'names': sorted(n for n in names if n), 'label': label}
    return types


def _resolve(name, types):
    """The PSL id a mkit.toml name means, or a UsageError naming the near misses."""
    wanted = str(name).strip()
    for psl, info in types.items():
        if wanted == psl or wanted.lower() in info['names']:
            return psl
    close = sorted(n for info in types.values() for n in info['names']
                   if wanted.lower()[:4] and wanted.lower()[:4] in n)
    raise UsageError(f'unknown data type "{name}" in [datasafety.collected]',
                     hint=('Did you mean: ' + ', '.join(close[:5]) + '?') if close
                          else 'Run `mkit datasafety types` for every name.',
                     code='DATASAFETY_UNKNOWN_TYPE')


def _purposes(values, where):
    out = set()
    for value in values:
        key = str(value).strip().lower()
        if key not in PURPOSES:
            raise UsageError(f'unknown purpose "{value}" in {where}',
                             hint='One of: ' + ', '.join(sorted(PURPOSES)),
                             code='DATASAFETY_UNKNOWN_PURPOSE')
        out.add(PURPOSES[key])
    return out


def _collected(config, types):
    """[datasafety.collected] as {psl id: {purposes, collected, shared, ephemeral, optional}}."""
    collected = {}
    for name, value in (config.get('collected') or {}).items():
        psl = _resolve(name, types)
        # Two spellings, because most types only ever need the short one:
        #   crash_logs = ["analytics"]           purposes, collected, not shared
        #   [datasafety.collected.photos]        the same plus sharing and controls
        #   purposes = [...]
        if isinstance(value, dict):
            entry = value
        elif isinstance(value, (list, tuple)):
            entry = {'purposes': list(value)}
        else:
            raise UsageError(f'[datasafety.collected] {name} must be a list of purposes '
                             f'or a table, not {type(value).__name__}',
                             code='DATASAFETY_BAD_TYPE')
        purposes = _purposes(entry.get('purposes') or [], f'[datasafety.collected] {name}')
        if not purposes:
            raise UsageError(f'[datasafety.collected] {name} lists no purpose',
                             hint='Play requires at least one: ' + ', '.join(sorted(PURPOSES)),
                             code='DATASAFETY_NO_PURPOSE')
        shared = _purposes(entry.get('shared') or [], f'[datasafety.collected] {name} shared')
        # Play's "collected, shared, or both" is two checkboxes. Data the app
        # sends off the device is collected; sharing it on is on top of that,
        # so only a type that goes to a third party straight from the device
        # (an SDK the app never sees the data from) sets collected = false.
        is_collected = bool(entry.get('collected', True))
        if not is_collected and not shared:
            raise UsageError(f'[datasafety.collected] {name} is neither collected nor shared',
                             hint='Leave the type out instead, or set shared.',
                             code='DATASAFETY_NOT_COLLECTED')
        collected[psl] = {
            'purposes': purposes,
            'collected': is_collected,
            'shared': shared,
            'ephemeral': bool(entry.get('ephemeral', False)),
            'optional': bool(entry.get('optional', False)),
        }
    return collected


def _flag(value):
    return 'TRUE' if value else 'FALSE'


def _account_methods(config):
    """account_creation as the set of response ids it chooses."""
    methods = config.get('account_creation', 'none')
    methods = [methods] if isinstance(methods, str) else list(methods)
    chosen = set()
    for method in methods:
        key = str(method).strip().lower()
        if key not in ACCOUNT_METHODS:
            raise UsageError(f'unknown account_creation "{method}"',
                             hint='One of: ' + ', '.join(ACCOUNT_METHODS),
                             code='DATASAFETY_UNKNOWN_ACCOUNT')
        chosen.add(ACCOUNT_METHODS[key])
    return chosen


def _answer(row, config, collected):
    """One row's Response value: TRUE, FALSE, a string, or blank where it does not apply."""
    question, response = row[COLUMNS[0]], row[COLUMNS[1]]

    if question == COLLECTS:
        return _flag(config.get('collects', bool(collected)))
    if question == ENCRYPTED:
        return _flag(config.get('encrypted_in_transit', True))
    if question == OUTSIDE_ACCOUNTS:
        # Play only asks this of an app with no account creation of its own,
        # and rejects an answer from one that has it.
        if _account_methods(config) != {'PSL_ACM_NONE'}:
            return ''
        return _flag(config.get('outside_app_accounts', False))
    if question == ACCOUNT_CREATION:
        return _flag(response in _account_methods(config))
    if question == DELETION:
        key = str(config.get('deletion', 'no')).strip().lower()
        if key not in DELETION_CHOICES:
            raise UsageError(f'unknown deletion "{key}"',
                             hint='One of: ' + ', '.join(DELETION_CHOICES),
                             code='DATASAFETY_UNKNOWN_DELETION')
        return _flag(response == DELETION_CHOICES[key])
    if question in (DELETION_URL, ACCOUNT_DELETION_URL):
        key = 'deletion_url' if question == DELETION_URL else 'account_deletion_url'
        return str(config.get(key, '') or '')

    if question.startswith('PSL_DATA_TYPES_'):
        return _flag(response in collected)

    if not question.startswith(USAGE + ':'):
        # Everything else - family policy, independent validation, the account
        # types - is left as Play's own default rather than guessed at here.
        return ''

    _, data_type, part = question.split(':', 2)
    entry = collected.get(data_type)
    if entry is None:
        # A type that is not collected answers nothing further; the Console
        # greys these out for the same reason.
        return ''
    if part == 'PSL_DATA_USAGE_COLLECTION_AND_SHARING':
        if response == 'PSL_DATA_USAGE_ONLY_COLLECTED':
            return _flag(entry['collected'])
        if response == 'PSL_DATA_USAGE_ONLY_SHARED':
            return _flag(bool(entry['shared']))
        return ''
    if part == 'PSL_DATA_USAGE_EPHEMERAL':
        # Asked about collection only; Play rejects it for a type that is
        # only shared.
        return _flag(entry['ephemeral']) if entry['collected'] else ''
    if part == 'DATA_USAGE_USER_CONTROL':
        wanted = ('PSL_DATA_USAGE_USER_CONTROL_OPTIONAL' if entry['optional']
                  else 'PSL_DATA_USAGE_USER_CONTROL_REQUIRED')
        return _flag(response == wanted)
    if part == 'DATA_USAGE_COLLECTION_PURPOSE':
        return _flag(response in entry['purposes'])
    if part == 'DATA_USAGE_SHARING_PURPOSE':
        return _flag(response in entry['shared'])
    raise UsageError(f'unhandled data usage question {question}',
                     hint='The shipped question set is newer than this engine; '
                          'update mkit, or report it.',
                     code='DATASAFETY_UNHANDLED')


def build(config):
    """The whole CSV as text, from a [datasafety] section."""
    if not config:
        raise UsageError('no [datasafety] section in mkit.toml',
                         hint='See docs/config.md; `mkit datasafety types` lists the '
                              'data type names.',
                         code='NO_DATASAFETY_CONFIG')
    rows = question_rows()
    types = data_types(rows)
    collected = _collected(config, types)
    if config.get('collects', bool(collected)) and not collected:
        raise UsageError('[datasafety] says the app collects data but lists none',
                         hint='Add [datasafety.collected], or set collects = false.',
                         code='DATASAFETY_NO_TYPES')

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(COLUMNS), lineterminator='\r\n')
    writer.writeheader()
    for row in rows:
        row = dict(row)
        row[COLUMNS[2]] = _answer(row, config, collected)
        writer.writerow(row)
    labels = sorted(types[psl]['label'].split(' / ')[-1] for psl in collected)
    return out.getvalue(), {'rows': len(rows), 'data_types': labels}
