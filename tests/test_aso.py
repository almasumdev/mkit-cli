"""Keyword research and listing impact, with Play faked: nothing here is fetched."""
import json

from mkit import aso, config


def _project(tmp_path, keywords):
    root = tmp_path / 'p'
    root.mkdir()
    (root / 'k.toml').write_text(keywords, encoding='utf-8')
    (root / 'mkit.toml').write_text('[app]\nname = "X"\nkind = "flutter"\npackage = "com.x"\n'
                                    '[aso]\nkeywords = "k.toml"\n', encoding='utf-8')
    return config.load(project=root)


def test_markets_take_seeds_and_topic_or_fall_back_to_the_keywords(tmp_path):
    p = _project(tmp_path, '[[market]]\nhl = "en_US"\ngl = "US"\nkeywords = ["grocery list"]\n'
                           '[[market]]\nlang = "de"\nhl = "de"\ngl = "DE"\nkeywords = ["einkaufsliste"]\n'
                           'seeds = ["einkaufsliste", "einkaufszettel"]\ntopic = ["einkauf"]\n')
    markets, _ = aso.load_markets(p)
    us, de = markets
    assert us['seeds'] == ['grocery list'] and us['topic'] == ['grocery', 'list']
    assert de['seeds'] == ['einkaufsliste', 'einkaufszettel'] and de['topic'] == ['einkauf']


def _suggest(table):
    """Autocomplete that offers each phrase once its first `n` letters are typed."""
    def suggest(q, hl, gl):
        return [phrase for phrase, n in table.items() if phrase.startswith(q) and len(q) >= n]
    return suggest


def test_demand_is_higher_the_fewer_letters_autocomplete_needs():
    s = _suggest({'family grocery list': 2, 'grocery list for roommates': 14})
    early, letters = aso.demand('family grocery list', 'en', 'US', s)
    late, _ = aso.demand('grocery list for roommates', 'en', 'US', s)
    never, none = aso.demand('nobody types this', 'en', 'US', s)
    assert early == 1.0 and letters == 2
    assert 0 < late < early
    assert never == 0.0 and none is None


def test_opportunity_prefers_a_weak_page_one():
    assert aso.opportunity(1.0, 5_000, 0) > aso.opportunity(1.0, 10_000_000, 0)
    assert aso.opportunity(1.0, 5_000, 0) > aso.opportunity(1.0, 5_000, 4)
    assert aso.opportunity(0.0, 5_000, 0) == 0


def test_research_finds_long_tail_phrases_and_scores_them():
    suggest = _suggest({'shared grocery list': 2, 'shared grocery list app': 4, 'shared drive': 2,
                        'grocery': 2})
    apps = {'shared grocery list': ['big.app', 'com.x'], 'shared grocery list app': ['big.app', 'small.app']}
    details = {'big.app': {'installs': 10_000_000, 'label': '10M+', 'title': 'Shared Grocery List'},
               'small.app': {'installs': 1_000, 'label': '1K+', 'title': 'Lists'},
               'com.x': {'installs': 100, 'label': '100+', 'title': 'Family Grocery List: X'}}
    markets = [{'lang': 'en', 'hl': 'en_US', 'gl': 'US', 'seeds': ['shared'], 'topic': ['grocery', 'list'],
                'keywords': ['family grocery list']}]
    rows = aso.research('com.x', markets, 1, suggest_fn=suggest,
                        search_fn=lambda w, hl, gl: apps.get(w, []), details_fn=details.__getitem__)
    by_kw = {r['kw']: r for r in rows}
    # Off-topic and one-word phrases are dropped; the tracked keyword is kept.
    assert set(by_kw) == {'shared grocery list', 'shared grocery list app', 'family grocery list'}
    assert by_kw['shared grocery list']['pos'] == 2
    assert by_kw['shared grocery list']['in_title'] == 1
    assert by_kw['family grocery list']['tracked'] and by_kw['family grocery list']['demand'] == 0
    assert [r['score'] for r in rows] == sorted((r['score'] for r in rows), reverse=True)


def test_impact_compares_visitors_and_keywords_either_side_of_the_change():
    daily = {'2026-09-28': (10, 1), '2026-09-30': (12, 1), '2026-10-02': (6, 0), '2026-10-03': (8, 1)}
    before = {('family list', 'DE'): 11, ('ai list', 'NO'): None, ('lista', 'BR'): 31}
    after = {('family list', 'DE'): None, ('ai list', 'NO'): 1, ('lista', 'BR'): 24}
    r = aso.impact(daily, '2026-10-02', 4, before, after)
    assert r['before'] == {'days': 4, 'visitors': 22, 'acquisitions': 2, 'visitors_per_day': 5.5,
                           'conversion': 9.1}
    # Only the days Play has reported so far count after the change.
    assert r['after']['days'] == 2 and r['after']['visitors'] == 14
    assert r['gained'] == [{'kw': 'ai list', 'gl': 'NO', 'pos': 1}]
    assert r['lost'] == [{'kw': 'family list', 'gl': 'DE', 'was': 11}]
    assert r['moved'] == [{'kw': 'lista', 'gl': 'BR', 'from': 31, 'to': 24}]


def test_scan_around_picks_the_scans_either_side_of_the_date(tmp_path):
    for day, pos in (('20260923', 5), ('20261001', 7), ('20261018', 3)):
        (tmp_path / f'results-{day}.json').write_text(json.dumps([{'kw': 'k', 'gl': 'US', 'pos': pos}]))
    b_file, b, a_file, a = aso.scan_around(tmp_path, 'results', '2026-10-02')
    assert b_file.name == 'results-20261001.json' and b == {('k', 'US'): 7}
    assert a_file.name == 'results-20261018.json' and a == {('k', 'US'): 3}
