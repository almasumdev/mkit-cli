import csv
import io

import pytest

from mkit import datasafety
from mkit.cloud import store

from test_store import _project

ANSWERS = '''[store]
datasafety = "docs/ds.csv"

[datasafety]
collects = true
encrypted_in_transit = true
deletion = "no"
account_creation = "none"

[datasafety.collected]
crash_logs = ["app_functionality", "analytics"]
diagnostics = ["app_functionality", "analytics"]
app_interactions = ["analytics"]
device_ids = ["app_functionality", "analytics"]
'''


def _dir(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return path


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def _value(rows, question, response=''):
    for row in rows:
        if (row['Question ID (machine readable)'] == question
                and row['Response ID (machine readable)'] == response):
            return row['Response value']
    raise AssertionError(f'no row for {question} / {response}')


def test_the_shipped_question_set_carries_no_answers():
    """It is the question set, not somebody's declaration."""
    rows = datasafety.question_rows()
    assert len(rows) > 700
    assert not any(r['Response value'].strip() for r in rows)


def test_builds_the_four_firebase_answers(tmp_path):
    p = _project(tmp_path, ANSWERS)
    text, info = datasafety.build(p.section('datasafety'))
    rows = _rows(text)

    assert info['data_types'] == ['App interactions', 'Crash logs', 'Device or other IDs',
                                  'Diagnostics']
    assert _value(rows, datasafety.COLLECTS) == 'TRUE'
    assert _value(rows, datasafety.ENCRYPTED) == 'TRUE'
    assert _value(rows, 'PSL_DATA_TYPES_APP_PERFORMANCE', 'PSL_CRASH_LOGS') == 'TRUE'
    assert _value(rows, 'PSL_DATA_TYPES_IDENTIFIERS', 'PSL_DEVICE_ID') == 'TRUE'
    # Everything not listed is declared as not collected, never left blank.
    assert _value(rows, 'PSL_DATA_TYPES_LOCATION', 'PSL_PRECISE_LOCATION') == 'FALSE'
    assert _value(rows, 'PSL_DATA_TYPES_PERSONAL', 'PSL_EMAIL') == 'FALSE'


def test_purposes_and_sharing_follow_the_type(tmp_path):
    p = _project(tmp_path, ANSWERS)
    text, _ = datasafety.build(p.section('datasafety'))
    rows = _rows(text)
    usage = 'PSL_DATA_USAGE_RESPONSES:PSL_USER_INTERACTION:'

    assert _value(rows, usage + 'DATA_USAGE_COLLECTION_PURPOSE', 'PSL_ANALYTICS') == 'TRUE'
    assert _value(rows, usage + 'DATA_USAGE_COLLECTION_PURPOSE', 'PSL_ADVERTISING') == 'FALSE'
    # Collected, not shared: Google processes it as the developer's service provider.
    assert _value(rows, usage + 'PSL_DATA_USAGE_COLLECTION_AND_SHARING',
                  'PSL_DATA_USAGE_ONLY_COLLECTED') == 'TRUE'
    assert _value(rows, usage + 'DATA_USAGE_SHARING_PURPOSE', 'PSL_ANALYTICS') == 'FALSE'
    # No in-app opt-out.
    assert _value(rows, usage + 'DATA_USAGE_USER_CONTROL',
                  'PSL_DATA_USAGE_USER_CONTROL_REQUIRED') == 'TRUE'
    # A type that is not collected answers nothing further.
    assert _value(rows, 'PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_COLLECTION_PURPOSE',
                  'PSL_ANALYTICS') == ''


def test_the_long_form_carries_sharing_and_controls(tmp_path):
    p = _project(tmp_path, '''[store]
datasafety = "docs/ds.csv"
[datasafety]
[datasafety.collected.photos]
purposes = ["app_functionality"]
shared = ["analytics"]
ephemeral = true
optional = true
''')
    text, _ = datasafety.build(p.section('datasafety'))
    rows = _rows(text)
    usage = 'PSL_DATA_USAGE_RESPONSES:PSL_PHOTOS:'

    assert _value(rows, 'PSL_DATA_TYPES_PHOTOS_AND_VIDEOS', 'PSL_PHOTOS') == 'TRUE'
    assert _value(rows, usage + 'PSL_DATA_USAGE_COLLECTION_AND_SHARING',
                  'PSL_DATA_USAGE_ONLY_SHARED') == 'TRUE'
    assert _value(rows, usage + 'DATA_USAGE_SHARING_PURPOSE', 'PSL_ANALYTICS') == 'TRUE'
    assert _value(rows, usage + 'PSL_DATA_USAGE_EPHEMERAL') == 'TRUE'
    assert _value(rows, usage + 'DATA_USAGE_USER_CONTROL',
                  'PSL_DATA_USAGE_USER_CONTROL_OPTIONAL') == 'TRUE'


def test_an_app_that_collects_nothing(tmp_path):
    p = _project(tmp_path, '[store]\ndatasafety = "docs/ds.csv"\n[datasafety]\ncollects = false\n')
    text, info = datasafety.build(p.section('datasafety'))
    rows = _rows(text)
    assert info['data_types'] == []
    assert _value(rows, datasafety.COLLECTS) == 'FALSE'
    assert _value(rows, 'PSL_DATA_TYPES_APP_PERFORMANCE', 'PSL_CRASH_LOGS') == 'FALSE'


def test_what_is_built_passes_the_check(tmp_path):
    """build -> check is the path every app takes; nothing REQUIRED may be left blank."""
    p = _project(tmp_path, ANSWERS)
    text, _ = datasafety.build(p.section('datasafety'))
    path = p.path('store.datasafety')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='')

    info = store.read_datasafety(p)
    assert info['required_blank'] == []
    assert info['collects_data'] == 'TRUE'
    assert info['data_types'] == ['App interactions', 'Crash logs', 'Device or other IDs',
                                  'Diagnostics']


@pytest.mark.parametrize('name', ('device_ids', 'device_or_other_ids', 'PSL_DEVICE_ID'))
def test_a_type_answers_to_its_alias_its_label_and_its_id(tmp_path, name):
    """Three spellings, one type: nobody has to guess which the engine wanted."""
    p = _project(tmp_path, f'[store]\ndatasafety = "d.csv"\n[datasafety]\n'
                           f'[datasafety.collected]\n"{name}" = ["analytics"]\n')
    _, info = datasafety.build(p.section('datasafety'))
    assert info['data_types'] == ['Device or other IDs']


def test_a_misspelled_type_says_what_was_meant(tmp_path):
    p = _project(tmp_path, '[store]\ndatasafety = "d.csv"\n[datasafety]\n'
                           '[datasafety.collected]\ncrash_log = ["analytics"]\n')
    with pytest.raises(Exception) as e:
        datasafety.build(p.section('datasafety'))
    assert e.value.code == 'DATASAFETY_UNKNOWN_TYPE'
    assert 'crash_logs' in e.value.hint


def test_a_misspelled_purpose_is_refused(tmp_path):
    p = _project(tmp_path, '[store]\ndatasafety = "d.csv"\n[datasafety]\n'
                           '[datasafety.collected]\ncrash_logs = ["analytic"]\n')
    with pytest.raises(Exception) as e:
        datasafety.build(p.section('datasafety'))
    assert e.value.code == 'DATASAFETY_UNKNOWN_PURPOSE'


def test_collecting_with_no_types_listed_is_refused(tmp_path):
    p = _project(tmp_path, '[store]\ndatasafety = "d.csv"\n[datasafety]\ncollects = true\n')
    with pytest.raises(Exception) as e:
        datasafety.build(p.section('datasafety'))
    assert e.value.code == 'DATASAFETY_NO_TYPES'


def test_no_section_at_all_points_at_the_docs(tmp_path):
    p = _project(tmp_path, '[store]\ndatasafety = "d.csv"\n')
    with pytest.raises(Exception) as e:
        datasafety.build(p.section('datasafety'))
    assert e.value.code == 'NO_DATASAFETY_CONFIG'


def test_a_shared_type_is_collected_too_and_keeps_ephemeral(tmp_path):
    """Sent off the device and passed on: both checkboxes, and the ephemeral
    question still answered (Play rejects it only for a type that is shared
    alone)."""
    p = _project(tmp_path, '''[store]
datasafety = "docs/ds.csv"
[datasafety]
[datasafety.collected.other_in_app_messages]
purposes = ["app_functionality"]
shared = ["app_functionality"]
optional = true
[datasafety.collected.photos]
purposes = ["app_functionality"]
shared = ["app_functionality"]
collected = false
''')
    rows = _rows(datasafety.build(p.section('datasafety'))[0])
    messages = 'PSL_DATA_USAGE_RESPONSES:PSL_OTHER_MESSAGES:'
    assert _value(rows, messages + 'PSL_DATA_USAGE_COLLECTION_AND_SHARING',
                  'PSL_DATA_USAGE_ONLY_COLLECTED') == 'TRUE'
    assert _value(rows, messages + 'PSL_DATA_USAGE_COLLECTION_AND_SHARING',
                  'PSL_DATA_USAGE_ONLY_SHARED') == 'TRUE'
    assert _value(rows, messages + 'PSL_DATA_USAGE_EPHEMERAL') == 'FALSE'

    photos = 'PSL_DATA_USAGE_RESPONSES:PSL_PHOTOS:'
    assert _value(rows, photos + 'PSL_DATA_USAGE_COLLECTION_AND_SHARING',
                  'PSL_DATA_USAGE_ONLY_COLLECTED') == 'FALSE'
    assert _value(rows, photos + 'PSL_DATA_USAGE_COLLECTION_AND_SHARING',
                  'PSL_DATA_USAGE_ONLY_SHARED') == 'TRUE'
    assert _value(rows, photos + 'PSL_DATA_USAGE_EPHEMERAL') == ''


def test_a_type_neither_collected_nor_shared_is_refused(tmp_path):
    p = _project(tmp_path, '''[store]
datasafety = "docs/ds.csv"
[datasafety]
[datasafety.collected.photos]
purposes = ["app_functionality"]
collected = false
''')
    with pytest.raises(Exception) as err:
        datasafety.build(p.section('datasafety'))
    assert getattr(err.value, 'code', '') == 'DATASAFETY_NOT_COLLECTED'


def test_outside_accounts_is_asked_only_without_own_accounts(tmp_path):
    none = _project(_dir(tmp_path, 'none'), ANSWERS)
    rows = _rows(datasafety.build(none.section('datasafety'))[0])
    assert _value(rows, datasafety.OUTSIDE_ACCOUNTS) == 'FALSE'

    own = _project(_dir(tmp_path, 'own'), ANSWERS.replace('account_creation = "none"',
                                                     'account_creation = ["password", "oauth"]'))
    rows = _rows(datasafety.build(own.section('datasafety'))[0])
    assert _value(rows, datasafety.OUTSIDE_ACCOUNTS) == ''
    assert _value(rows, datasafety.ACCOUNT_CREATION, 'PSL_ACM_OAUTH') == 'TRUE'


def test_accounts_and_deletion_need_their_links(tmp_path):
    """Play rejects an app with accounts, or with deletion, that links no page."""
    text = ANSWERS.replace('account_creation = "none"', 'account_creation = "oauth"')
    text = text.replace('deletion = "no"', 'deletion = "yes"')
    p = _project(_dir(tmp_path, 'bare'), text)
    path = p.path('store.datasafety')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datasafety.build(p.section('datasafety'))[0], encoding='utf-8', newline='')
    blank = store.read_datasafety(p)['required_blank']
    assert 'PSL_ACCOUNT_DELETION_URL' in blank
    assert 'PSL_DATA_DELETION_URL' in blank

    linked = text.replace('deletion = "yes"', 'deletion = "yes"\n'
                          'account_deletion_url = "https://example.com/delete-account"\n'
                          'deletion_url = "https://example.com/delete-data"')
    p = _project(_dir(tmp_path, 'linked'), linked)
    path = p.path('store.datasafety')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datasafety.build(p.section('datasafety'))[0], encoding='utf-8', newline='')
    assert store.read_datasafety(p)['required_blank'] == []

