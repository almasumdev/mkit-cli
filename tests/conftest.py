import pytest


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """No test reads the real ~/.mkit or a shell-level MKIT_* setting."""
    import os
    for key in list(os.environ):
        if key.startswith('MKIT_') or key.endswith('_JSON_BASE64'):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('MKIT_HOME', str(home))
    monkeypatch.setenv('MKIT_OUTPUT', 'json')
    return home


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'mkit.toml').write_text(
        'requires = ">=0.1"\n[app]\nname = "Demo"\nkind = "flutter"\n'
        'package = "com.example.demo"\n[play]\n[firebase]\nrules = true\n',
        encoding='utf-8')
    return root
