import base64
import json

import pytest

from mkit import cli, config, secrets
from mkit.errors import AUTH, NEEDS_CONFIRM, CredentialMissing, NeedsConfirm, NotFound


def b64(obj):
    return base64.b64encode(json.dumps(obj).encode()).decode()


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out)


# ------------------------------------------------------------------ config

def test_finds_project_from_subfolder(project):
    sub = project / 'lib' / 'deep'
    sub.mkdir(parents=True)
    assert config.find_root(sub) == project


def test_missing_project_is_not_found(tmp_path):
    with pytest.raises(NotFound):
        config.load(project=tmp_path)


def test_feature_switch_and_env_override(project, monkeypatch):
    p = config.load(project=project)
    assert p.has('play') and p.has('firebase') and not p.has('aso')
    assert p.package == 'com.example.demo'
    monkeypatch.setenv('MKIT_APP_PACKAGE', 'com.override')
    assert p.package == 'com.override'


def test_requires_newer_engine_refuses(project):
    (project / 'mkit.toml').write_text('requires = ">=99.0"\n', encoding='utf-8')
    with pytest.raises(Exception) as e:
        config.load(project=project)
    assert e.value.code == 'ENGINE_TOO_OLD'


# ------------------------------------------------------------------ secrets

def test_project_env_beats_user_env(project, isolated):
    (isolated / '.env').write_text(f'MKIT_TELEGRAM_JSON_BASE64={b64({"bot_token": "user-token-123", "chat_id": 1})}\n')
    (project / '.env').write_text(f'MKIT_TELEGRAM_JSON_BASE64={b64({"bot_token": "project-token-123", "chat_id": 2})}\n')
    s = secrets.Secrets(project)
    assert s.json('TELEGRAM')['chat_id'] == 2


def test_unprefixed_alias_and_file_form(project, tmp_path):
    key = tmp_path / 'sa.json'
    key.write_text(json.dumps({'client_email': 'a@b', 'private_key': 'PRIVATE-KEY-VALUE'}))
    (project / '.env').write_text(f'FIREBASE_SERVICE_ACCOUNT_FILE={key}\n')
    s = secrets.Secrets(project)
    assert s.json('FIREBASE_SERVICE_ACCOUNT')['client_email'] == 'a@b'


def test_missing_credential_names_the_key(project):
    with pytest.raises(CredentialMissing) as e:
        secrets.Secrets(project).json('PLAY_SERVICE_ACCOUNT')
    assert 'MKIT_PLAY_SERVICE_ACCOUNT_JSON_BASE64' in e.value.hint
    assert e.value.exit_code == AUTH


def test_secret_values_are_redacted(project):
    (project / '.env').write_text(
        f'MKIT_PLAY_SERVICE_ACCOUNT_JSON_BASE64={b64({"private_key": "SUPER-SECRET-KEY", "client_email": "x@y"})}\n')
    secrets.Secrets(project).json('PLAY_SERVICE_ACCOUNT')
    assert 'SUPER-SECRET-KEY' not in secrets.redact('leaked SUPER-SECRET-KEY here')


# ------------------------------------------------------------------ cli contract

def test_commands_json_lists_risk_and_schema(capsys):
    code, data = run(capsys, 'commands', '--json')
    assert code == 0 and data['ok']
    names = {c['name']: c for c in data['result']['commands']}
    assert names['init']['risk'] == 'write'
    assert 'properties' in names['init']['input']


def test_doctor_reports_missing_credentials(capsys, project):
    code, data = run(capsys, '--project', str(project), 'doctor')
    features = {f['feature']: f['status'] for f in data['result']['features']}
    assert features['play'] == 'broken' and features['aso'] == 'off'
    assert code == 1


def test_unknown_schema_is_exit_4(capsys):
    code, data = run(capsys, 'schema', 'no-such-thing')
    assert code == 4 and data['error']['code'] == 'NOT_FOUND'


def test_init_detects_flutter(capsys, tmp_path):
    root = tmp_path / 'my_app'
    (root / 'android' / 'app').mkdir(parents=True)
    (root / 'pubspec.yaml').write_text('name: my_app\nversion: 1.0.0+1\n')
    (root / 'android' / 'app' / 'build.gradle.kts').write_text('applicationId = "com.x.my_app"\n')
    code, data = run(capsys, 'init', str(root))
    assert code == 0
    assert data['result']['kind'] == 'flutter' and data['result']['package'] == 'com.x.my_app'
    assert (root / 'mkit.toml').is_file() and '.env' in (root / '.gitignore').read_text()
    assert b'\r\n' in (root / 'mkit.bat').read_bytes()


# ------------------------------------------------------------------ safety

class _Ctx:
    def __init__(self, project, **kw):
        from mkit.output import Output
        self.project = project
        self.out = kw.get('out') or Output(mode='json')
        self.command = kw.get('command', '')
        self.dry_run = kw.get('dry_run', False)
        self.yes = kw.get('yes', False)
        self.confirm = kw.get('confirm')


def test_publish_without_confirm_refuses_off_terminal(project):
    from mkit import safety
    p = config.load(project=project)
    with pytest.raises(NeedsConfirm) as e:
        safety.confirm(_Ctx(p), 'deploy')
    assert e.value.exit_code == NEEDS_CONFIRM


def test_no_prompt_skips_typing_only_at_a_terminal(project, isolated, monkeypatch):
    from mkit import safety
    from mkit.output import Output
    (isolated / 'config.toml').write_text('[safety]\nno_prompt = ["deploy"]\n', encoding='utf-8')
    p = config.load(project=project)
    asked = []
    monkeypatch.setattr('builtins.input', lambda prompt: asked.append(prompt) or 'Demo')

    # Off a terminal the setting changes nothing: still refused.
    with pytest.raises(NeedsConfirm):
        safety.confirm(_Ctx(p, command='deploy'), 'deploy')

    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('sys.stdout.isatty', lambda: True)
    human = Output(mode='human')
    safety.confirm(_Ctx(p, command='deploy', out=human), 'deploy')
    assert asked == []
    safety.confirm(_Ctx(p, command='promote', out=human), 'promote')
    assert len(asked) == 1


def test_confirm_must_name_this_package(project):
    from mkit import safety
    p = config.load(project=project)
    with pytest.raises(NeedsConfirm):
        safety.confirm(_Ctx(p, yes=True, confirm='com.other.app'), 'deploy')
    safety.confirm(_Ctx(p, yes=True, confirm='com.example.demo'), 'deploy')
    safety.confirm(_Ctx(p, dry_run=True), 'deploy')


# ------------------------------------------------------------------ proc.stream

def _echo_then_exit(lines, code):
    """A tool that prints [lines] and exits [code], so the exit path can be tested
    without a real firebase CLI."""
    import sys
    body = '; '.join(f'print({line!r})' for line in lines)
    return [sys.executable, '-c', f'{body}; raise SystemExit({code})']


def test_stream_raises_when_a_tool_fails(isolated):
    from mkit import proc
    from mkit.proc import ToolFailed
    with pytest.raises(ToolFailed):
        proc.stream(_echo_then_exit(['building', 'it broke'], 2), 'fake tool', quiet=True)


def test_stream_accepts_a_tool_that_finished_then_exited_nonzero(isolated):
    """firebase deploy posts an analytics event after the deploy and exits 2 when that
    call times out. The rules are live by then, so the exit code must not undo them."""
    from mkit import proc
    tail = proc.stream(
        _echo_then_exit(['Deploy complete!', 'Error: An unexpected error has occurred.'], 2),
        'firebase deploy', quiet=True, done_marker='Deploy complete!')
    assert 'Deploy complete!' in tail


def test_stream_still_fails_when_the_marker_never_appears(isolated):
    from mkit import proc
    from mkit.proc import ToolFailed
    with pytest.raises(ToolFailed):
        proc.stream(_echo_then_exit(['deploying', 'Error: permission denied'], 1),
                    'firebase deploy', quiet=True, done_marker='Deploy complete!')
