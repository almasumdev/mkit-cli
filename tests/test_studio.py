"""`mkit studio`: which folder is handed to Android Studio, and how it starts."""
import json

import pytest

from mkit import cli, proc, toolchain


@pytest.fixture
def opened(monkeypatch):
    """Records what would have been launched; nothing is started."""
    calls = []

    def fake_detach(argv, cwd=None, env=None):
        calls.append({'argv': [str(a) for a in argv], 'cwd': str(cwd)})
        return 4242

    monkeypatch.setattr(proc, 'detach', fake_detach)
    monkeypatch.setattr(toolchain, 'studio', lambda project=None: 'C:/studio/bin/studio64.exe')
    return calls


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def native(tmp_path):
    root = tmp_path / 'native'
    root.mkdir()
    (root / 'mkit.toml').write_text(
        'requires = ">=0.1"\n[app]\nname = "Native"\nkind = "android"\n'
        'package = "com.example.native"\nmodule = "app"\n', encoding='utf-8')
    return root


def test_a_flutter_app_opens_at_the_repo_root(project, opened, capsys):
    # Not android/: the root is the Flutter project, and Studio indexes
    # android/ underneath it while keeping Dart analysis and hot reload.
    code, envelope = run(capsys, 'studio', '--project', str(project))
    assert code == 0
    assert envelope['result']['folder'] == str(project)
    assert opened[0]['argv'] == ['C:/studio/bin/studio64.exe', str(project)]


def test_dash_a_opens_the_gradle_project_of_a_flutter_app(project, opened, capsys):
    code, envelope = run(capsys, 'studio', '-a', '--project', str(project))
    assert code == 0
    assert envelope['result']['folder'] == str(project / 'android')


def test_the_flag_is_spelled_only_dash_a(project, opened, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(['studio', '--android', '--project', str(project)])
    assert e.value.code == 2


def test_a_native_app_opens_at_its_gradle_root_either_way(tmp_path, opened, capsys):
    root = native(tmp_path)
    for argv in (('studio',), ('studio', '-a')):
        code, envelope = run(capsys, *argv, '--project', str(root))
        assert code == 0
        assert envelope['result']['folder'] == str(root)


def test_dry_run_names_the_folder_without_opening_anything(project, opened, capsys):
    code, envelope = run(capsys, 'studio', '--dry-run', '--project', str(project))
    assert code == 0
    assert envelope['result'] == {'folder': str(project), 'studio': 'C:/studio/bin/studio64.exe',
                                  'pid': None, 'dry_run': True}
    assert opened == []


def test_the_pid_is_reported_and_studio_outlives_mkit(project, opened, capsys):
    _, envelope = run(capsys, 'studio', '--project', str(project))
    assert envelope['result']['pid'] == 4242
    assert envelope['result']['studio'] == 'C:/studio/bin/studio64.exe'


# ------------------------------------------------------------ finding Studio

def test_a_pinned_launcher_is_taken_as_given(monkeypatch, tmp_path):
    exe = tmp_path / 'studio64.exe'
    exe.write_text('')
    monkeypatch.setenv('MKIT_STUDIO', str(exe))
    assert toolchain.studio() == str(exe)


def test_a_pinned_install_folder_is_looked_inside(monkeypatch, tmp_path):
    binary = tmp_path / 'Android Studio' / 'bin' / toolchain.STUDIO_EXES[0]
    binary.parent.mkdir(parents=True)
    binary.write_text('')
    monkeypatch.setenv('MKIT_STUDIO', str(tmp_path / 'Android Studio'))
    assert toolchain.studio() == str(binary)


def test_a_pinned_path_that_is_not_studio_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv('MKIT_STUDIO', str(tmp_path / 'nowhere'))
    with pytest.raises(Exception) as e:
        toolchain.studio()
    assert e.value.code == 'TOOL_MISSING'


def test_no_studio_anywhere_names_the_setting(monkeypatch):
    monkeypatch.setattr(toolchain, 'STUDIO_CANDIDATES', ())
    monkeypatch.setattr(toolchain.shutil, 'which', lambda name: None)
    with pytest.raises(Exception) as e:
        toolchain.studio()
    assert e.value.code == 'TOOL_MISSING'
    assert 'mkit.toml' in e.value.hint
