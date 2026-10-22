import json

import pytest

from mkit import cli, guides


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def no_house(monkeypatch, tmp_path):
    """This checkout's own house rules stay out of what the tests read."""
    empty = tmp_path / 'no-house'
    empty.mkdir()
    monkeypatch.setenv('MKIT_GUIDE_HOUSE_DIR', str(empty))
    return empty


def user_config(isolated, text):
    (isolated / 'config.toml').write_text(text, encoding='utf-8')


@pytest.mark.parametrize('name', sorted(guides.GUIDES))
def test_every_guide_renders_with_nothing_left_unfilled(name, no_house):
    text, info = guides.render(name)
    assert '{{' not in text and '<!-- part:' not in text
    assert info['house'] is None


def test_studio_details_fill_the_guide(isolated, no_house):
    user_config(isolated, '[studio]\nemail = "hi@acme.dev"\nplay_developer_id = "42"\n')
    text, info = guides.render('about')
    assert 'mailto:hi@acme.dev' in text
    assert 'market://dev?id=42' in text
    assert 'studio.email' not in info['unset']


def test_an_unset_detail_is_shown_and_named(no_house):
    text, info = guides.render('about')
    assert '‹studio.email›' in text
    assert 'studio.email' in info['unset']


def test_about_words_have_defaults_and_can_be_reworded(isolated, no_house):
    text, _ = guides.render('about')
    assert 'Enjoying <App>?' in text
    user_config(isolated, '[about]\nrating_heading = "Like <App>?"\n')
    text, info = guides.render('about')
    assert '`Like <App>?`' in text and '`Enjoying <App>?`' not in text
    assert not any(k.startswith('about.') for k in info['unset'])


def test_about_parts_left_out_are_dropped(isolated, no_house):
    user_config(isolated, '[about]\nparts = ["mark", "name", "version", "what", "footer"]\n')
    text, info = guides.render('about')
    assert '**Rating**' not in text and '`Enjoying <App>?`' not in text
    assert 'mailto:' not in text and 'market://dev' not in text
    assert '**Footer**' in text and '**Mark**' in text
    assert 'studio.email' not in info['unset']


def test_raw_keeps_placeholders_and_parts(no_house):
    text, _ = guides.render('about', raw=True)
    assert '{{studio.email}}' in text and '<!-- part:ask -->' in text


def test_house_rules_are_appended_and_win(monkeypatch, tmp_path):
    house = tmp_path / 'house'
    house.mkdir()
    (house / 'about-screen.md').write_text('Stars route by number here.\n', encoding='utf-8')
    monkeypatch.setenv('MKIT_GUIDE_HOUSE_DIR', str(house))
    text, info = guides.render('about')
    assert info['house'] == str(house / 'about-screen.md')
    assert text.rstrip().endswith('Stars route by number here.')
    assert "## This studio's own rules" in text


def test_guide_command_lists_and_renders(capsys, isolated, no_house):
    code, env = run(capsys, 'guide')
    assert code == 0
    assert {g['name'] for g in env['result']['guides']} == set(guides.GUIDES)
    assert all(g['available'] for g in env['result']['guides'])

    user_config(isolated, '[support]\nsignoff = "The <App> team at Acme"\n')
    code, env = run(capsys, 'guide', 'support')
    assert code == 0
    assert 'The <App> team at Acme' in env['result']['text']


def test_a_project_setting_beats_the_user_one(capsys, isolated, no_house, project, monkeypatch):
    user_config(isolated, '[studio]\nemail = "all@acme.dev"\n')
    with open(project / 'mkit.toml', 'a', encoding='utf-8') as f:
        f.write('[studio]\nemail = "demo@acme.dev"\n')
    monkeypatch.chdir(project)
    code, env = run(capsys, 'guide', 'about')
    assert code == 0
    assert 'mailto:demo@acme.dev' in env['result']['text']


def test_the_wheel_packs_every_guide():
    """Where the build lists the guides, it lists all of them (the public pyproject)."""
    from pathlib import Path
    pyproject = Path(__file__).resolve().parents[1] / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8') if pyproject.is_file() else ''
    if 'mkit/_guides/' not in text:
        pytest.skip('this build does not package the guides')
    for filename, _ in guides.GUIDES.values():
        assert f'"docs/{filename}" = "mkit/_guides/{filename}"' in text, filename


def test_an_app_adds_its_own_rules_last(capsys, isolated, project, monkeypatch, tmp_path):
    house = tmp_path / 'house'
    house.mkdir()
    (house / 'app-ui.md').write_text('Studio look.\n', encoding='utf-8')
    monkeypatch.setenv('MKIT_GUIDE_HOUSE_DIR', str(house))
    (project / 'docs' / 'guides').mkdir(parents=True)
    (project / 'docs' / 'guides' / 'app-ui.md').write_text('Cards everywhere in {{app.name}}.\n',
                                                           encoding='utf-8')
    monkeypatch.chdir(project)
    code, env = run(capsys, 'guide', 'ui')
    text = env['result']['text']
    assert code == 0 and env['result']['app'] and not env['result']['replaced']
    assert '## Colours from one place' in text
    assert text.index('Studio look.') < text.index("## This app's own rules")
    assert text.rstrip().endswith('Cards everywhere in Demo.')


def test_an_app_can_replace_a_guide_outright(capsys, isolated, no_house, project, monkeypatch):
    with open(project / 'mkit.toml', 'a', encoding='utf-8') as f:
        f.write('[guide]\napp_dir = "design"\nreplace = ["about"]\n')
    (project / 'design').mkdir()
    (project / 'design' / 'about-screen.md').write_text('# Our About page\n\nOne line.\n',
                                                        encoding='utf-8')
    monkeypatch.chdir(project)
    code, env = run(capsys, 'guide', 'about')
    assert code == 0 and env['result']['replaced']
    assert env['result']['text'].strip() == '# Our About page\n\nOne line.'
    code, env = run(capsys, 'guide', 'ui')
    assert env['result']['app'] is None and '## Colours from one place' in env['result']['text']
