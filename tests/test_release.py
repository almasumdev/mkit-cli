import base64
import json
import subprocess
from types import SimpleNamespace

import pytest

from mkit import cli, config, kinds, secrets
from mkit.cloud import auth, play
from mkit.errors import NotFound
from mkit.output import Output

from fakeplay import FakePlay


# ------------------------------------------------------------------ kinds

def _project(tmp_path, kind, files, extra=''):
    root = tmp_path / 'p'
    root.mkdir()
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    (root / 'mkit.toml').write_text(f'[app]\nname = "X"\nkind = "{kind}"\npackage = "com.x"\n{extra}')
    return config.load(project=root)


def test_pubspec_bump_keeps_crlf(tmp_path):
    p = _project(tmp_path, 'flutter', {'pubspec.yaml': 'name: x\r\nversion: 1.2.3+9  \r\nfoo: 1\r\n'})
    k = kinds.for_project(p)
    assert k.bump('minor') == ('1.2.3', 9, '1.3.0', 10)
    assert (p.root / 'pubspec.yaml').read_bytes() == b'name: x\r\nversion: 1.3.0+10  \r\nfoo: 1\r\n'


def test_gradle_kts_bump_keeps_crlf_and_ignores_suffix(tmp_path):
    gradle = ('android {\r\n    defaultConfig {\r\n        versionCode = 20\r\n'
              '        versionName = "1.0.19"\r\n    }\r\n    debug { versionNameSuffix = "-debug" }\r\n}\r\n')
    p = _project(tmp_path, 'android', {'app/build.gradle.kts': gradle})
    k = kinds.for_project(p)
    assert k.bump('patch')[2:] == ('1.0.20', 21)
    text = (p.root / 'app/build.gradle.kts').read_bytes()
    assert b'versionCode = 21\r\n' in text and b'versionName = "1.0.20"\r\n' in text
    assert text.count(b'\r\n') == gradle.count('\r\n') and b'"-debug"' in text


def test_groovy_gradle_and_major(tmp_path):
    p = _project(tmp_path, 'android', {'app/build.gradle': 'versionCode 19\nversionName "1.0.18"\n'})
    assert kinds.for_project(p).bump('major')[2:] == ('2.0.0', 20)


def test_debug_package_read_from_the_debug_build_type(tmp_path):
    groovy = ("android {\n  buildTypes {\n    release { applicationIdSuffix '.rel' }\n"
              "    debug {\n      signingConfig signingConfigs.debug\n"
              "      applicationIdSuffix '.debug'\n    }\n  }\n}\n")
    p = _project(tmp_path, 'flutter', {'pubspec.yaml': 'version: 1.0.0+1\n',
                                       'android/app/build.gradle': groovy})
    k = kinds.for_project(p)
    assert k.debug_package() == 'com.x.debug'
    assert k.installed_package(release=True) == 'com.x'


def test_debug_package_kotlin_dsl(tmp_path):
    kts = 'android { buildTypes { getByName("debug") { applicationIdSuffix = ".dev" } } }\n'
    p = _project(tmp_path, 'android', {'app/build.gradle.kts': kts})
    assert kinds.for_project(p).debug_package() == 'com.x.dev'


def test_no_debug_suffix_means_the_store_package(tmp_path):
    # Used to be assumed ".debug": run -c then cleaned a package that did not
    # exist, and the debug build went on to replace the store install.
    kts = 'android { buildTypes { release { applicationIdSuffix = ".r" } } }\n'
    p = _project(tmp_path, 'android', {'app/build.gradle.kts': kts})
    assert kinds.for_project(p).debug_package() == 'com.x'


def test_promote_names_the_version_as_deploy_does(tmp_path):
    from mkit.commands.release import version_label
    p = _project(tmp_path, 'flutter', {'pubspec.yaml': 'version: 1.3.0+9\n'})
    k = kinds.for_project(p)
    # The release name deploy sets is the version name.
    assert version_label(k, [{'versionCodes': ['8'], 'name': '1.2.2'}]) == '1.2.2 (8)'
    # Play's own default for a release uploaded some other way.
    assert version_label(k, [{'versionCodes': ['8'], 'name': '8 (1.2.2)'}]) == '1.2.2 (8)'
    # No name on Play: this checkout's, but only when its code is what moved.
    assert version_label(k, [{'versionCodes': ['9'], 'name': None}]) == '1.3.0 (9)'
    assert version_label(k, [{'versionCodes': ['7'], 'name': None}]) == 'versionCode 7'
    # Phone and watch: one name, both codes.
    assert version_label(k, [{'versionCodes': ['8'], 'name': '1.2.2'},
                             {'versionCodes': ['1008'], 'name': '1.2.2'}]) == '1.2.2 (8, 1008)'


def test_debug_suffix_setting_wins_over_gradle(tmp_path):
    p = _project(tmp_path, 'flutter',
                 {'pubspec.yaml': 'version: 1.0.0+1\n',
                  'android/app/build.gradle': 'debug { applicationIdSuffix ".debug" }'},
                 extra='debug_suffix = ".qa"\n')
    assert kinds.for_project(p).debug_package() == 'com.x.qa'


def test_version_properties_preferred_for_wear(tmp_path):
    p = _project(tmp_path, 'android-wear', {'version.properties': '# x\nversionName=1.0.7\nversionCode=8\n',
                                            'app/build.gradle.kts': 'versionCode = appVersionCode\n'})
    k = kinds.for_project(p)
    assert k.current_version() == ('1.0.7', 8)
    assert [m.factor for m in k.modules()] == ['phone', 'wear']
    k.bump('patch')
    assert 'versionName=1.0.8\nversionCode=9' in (p.root / 'version.properties').read_text()


# ------------------------------------------------------------------ tracks + notes

def test_resolve_wear_tracks():
    available = ['internal', 'alpha', 'production', 'wear:internal', 'wear:production']
    assert play.resolve_track(available, 'phone', 'closed') == 'alpha'
    assert play.resolve_track(available, 'wear', 'internal') == 'wear:internal'
    assert play.resolve_track(available, 'wear', 'prod') == 'wear:production'
    assert play.resolve_track(available, 'wear', 'open') is None
    assert play.resolve_track(['internal'], 'wear', 'internal') is None


def test_release_notes_limit(tmp_path):
    p = _project(tmp_path, 'flutter', {'pubspec.yaml': 'version: 1.0.0+1\n',
                                       'wn/whatsnew-en-US': 'Hello', 'wn/whatsnew-de-DE': ' ',
                                       'wn/README.md': 'ignored'},
                 extra='[store]\nwhatsnew_dir = "wn"\n')
    assert play.release_notes(p) == [{'language': 'en-US', 'text': 'Hello'}]
    (p.root / 'wn/whatsnew-fr-FR').write_text('x' * 501)
    with pytest.raises(Exception) as e:
        play.release_notes(p)
    assert e.value.code == 'WHATSNEW_TOO_LONG'


# ------------------------------------------------------------------ fake Play

def _ctx(tmp_path, fake, monkeypatch, kind='flutter', files=None):
    p = _project(tmp_path, kind, files or {'pubspec.yaml': 'version: 1.0.0+1\n'})
    monkeypatch.setattr(auth, 'play', lambda ctx, timeout=None: fake)
    out = Output(mode='json')
    from mkit import output
    monkeypatch.setattr(output, 'out', out)
    return SimpleNamespace(project=p, out=out, dry_run=False, secrets=None), p


def test_promote_keeps_notes_and_name(tmp_path, monkeypatch):
    notes = [{'language': 'en-US', 'text': 'New'}]
    fake = FakePlay({'internal': [{'versionCodes': ['7'], 'status': 'completed', 'name': '1.0.6',
                                   'releaseNotes': notes}], 'production': []})
    ctx, p = _ctx(tmp_path, fake, monkeypatch)
    moved = play.promote(ctx, kinds.for_project(p), 'internal', 'prod')
    assert moved[0]['versionCodes'] == ['7']
    prod = fake.tracks_state['production'][0]
    assert prod['releaseNotes'] == notes and prod['name'] == '1.0.6' and prod['status'] == 'completed'


def test_promote_with_rollout_and_dry_run(tmp_path, monkeypatch):
    fake = FakePlay({'internal': [{'versionCodes': ['7'], 'status': 'completed'}], 'production': []})
    ctx, p = _ctx(tmp_path, fake, monkeypatch)
    play.promote(ctx, kinds.for_project(p), 'internal', 'prod', rollout=0.2, dry_run=True)
    assert fake.committed == [] and fake.deleted == 1
    play.promote(ctx, kinds.for_project(p), 'internal', 'prod', rollout=0.2)
    assert fake.tracks_state['production'][0] == {'versionCodes': ['7'], 'status': 'inProgress',
                                                  'userFraction': 0.2}


def test_edit_play_will_not_send_for_review_is_saved_for_console(tmp_path, monkeypatch):
    fake = FakePlay({'internal': [{'versionCodes': ['7'], 'status': 'completed'}], 'production': []},
                    manual_review=True)
    ctx, p = _ctx(tmp_path, fake, monkeypatch)
    play.promote(ctx, kinds.for_project(p), 'internal', 'prod')
    assert fake.commit_kwargs == {'changesNotSentForReview': True}
    assert fake.tracks_state['production'][0]['versionCodes'] == ['7']
    assert any('Send changes for review' in w for w in ctx.out.warnings)


def test_edit_keeps_in_review_guard_when_saved_for_console(tmp_path, monkeypatch):
    fake = FakePlay(manual_review=True)
    ctx, _ = _ctx(tmp_path, fake, monkeypatch)
    with play.Edit(ctx) as edit:
        edit.finish(False, in_review='error')
    assert fake.commit_kwargs == {'changesInReviewBehavior': 'ERROR_IF_IN_REVIEW',
                                  'changesNotSentForReview': True}


def test_promote_nothing_is_not_found(tmp_path, monkeypatch):
    ctx, p = _ctx(tmp_path, FakePlay(), monkeypatch)
    with pytest.raises(NotFound):
        play.promote(ctx, kinds.for_project(p), 'internal', 'prod')


def test_rollout_steps_keep_completed_release(tmp_path, monkeypatch):
    fake = FakePlay({'production': [{'versionCodes': ['6'], 'status': 'completed'},
                                    {'versionCodes': ['7'], 'status': 'inProgress', 'userFraction': 0.1}]})
    ctx, _ = _ctx(tmp_path, fake, monkeypatch)
    play.rollout(ctx, 'prod', 'set', 0.5)
    assert fake.tracks_state['production'][1]['userFraction'] == 0.5
    assert fake.tracks_state['production'][0]['versionCodes'] == ['6']
    play.rollout(ctx, 'prod', 'halt')
    assert fake.tracks_state['production'][1]['status'] == 'halted'
    play.rollout(ctx, 'prod', 'complete')
    assert fake.tracks_state['production'] == [{'versionCodes': ['7'], 'status': 'completed'}]


def test_upload_wear_without_wear_track_skips_watch(tmp_path, monkeypatch):
    files = {'version.properties': 'versionName=1.0.0\nversionCode=1\n',
             'app/build/outputs/bundle/release/app-release.aab': 'x',
             'wear/build/outputs/bundle/release/wear-release.aab': 'y'}
    fake = FakePlay({'internal': []})
    ctx, p = _ctx(tmp_path, fake, monkeypatch, kind='android-wear', files=files)
    results = play.upload_release(ctx, kinds.for_project(p), 'internal', notes=[])
    assert [r['module'] for r in results] == ['phone']
    assert fake.tracks_state['internal'][0]['versionCodes'] == ['101']
    assert any('Wear OS track' in w for w in ctx.out.warnings)


# ------------------------------------------------------------------ deploy pipeline

def _git(root, *args):
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)


def _deploy_project(tmp_path, isolated):
    root = tmp_path / 'app'
    (root / 'android').mkdir(parents=True)
    (root / 'android' / 'key.properties').write_text('storeFile=x\n')
    (root / 'pubspec.yaml').write_bytes(b'name: app\r\nversion: 1.0.0+1\r\n')
    (root / 'mkit.toml').write_text('[app]\nname = "App"\nkind = "flutter"\npackage = "com.app"\n'
                                    '[play]\n[notify.telegram]\n')
    _git(root, 'init', '-q')
    _git(root, '-c', 'user.email=t@t', '-c', 'user.name=t', 'add', '-A')
    _git(root, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'init')
    key = base64.b64encode(json.dumps({'client_email': 'a@b', 'private_key': 'k' * 20}).encode()).decode()
    (isolated / '.env').write_text(f'MKIT_PLAY_SERVICE_ACCOUNT_JSON_BASE64={key}\n')
    return root


@pytest.fixture
def deploy_env(tmp_path, isolated, monkeypatch):
    root = _deploy_project(tmp_path, isolated)
    monkeypatch.setenv('GIT_AUTHOR_NAME', 't')
    monkeypatch.setenv('GIT_AUTHOR_EMAIL', 't@t')
    monkeypatch.setenv('GIT_COMMITTER_NAME', 't')
    monkeypatch.setenv('GIT_COMMITTER_EMAIL', 't@t')
    from mkit import toolchain
    monkeypatch.setattr(toolchain, 'find_jdk', lambda project=None: 'JDK')
    monkeypatch.setattr(toolchain, 'java_major', lambda home: 17)
    monkeypatch.setattr(toolchain, 'tool', lambda name: name)
    monkeypatch.setattr(kinds.Flutter, 'bundle', lambda self, env: [])
    return root


def _log(root):
    return subprocess.run(['git', 'log', '--format=%s'], cwd=root, capture_output=True, text=True).stdout.split('\n')


def test_deploy_success_commits_bump_and_skips_missing_telegram(capsys, deploy_env, monkeypatch):
    monkeypatch.setattr(play, 'upload_release', lambda ctx, kind, track, **kw:
                        [{'module': 'phone', 'track': 'internal', 'versionCode': '2', 'status': 'completed'}])
    code = cli.main(['--project', str(deploy_env), 'deploy', '--yes', '--confirm', 'com.app'])
    data = json.loads(capsys.readouterr().out)
    assert data['ok'] and data['result']['versionCode'] == 2
    assert code == 7  # telegram on but no credential: skipped, so partial
    assert data['skipped'][0]['step'] == 'Notify'
    assert _log(deploy_env)[0] == 'chore: bump version to 1.0.1 (versionCode 2)'
    assert b'version: 1.0.1+2\r\n' in (deploy_env / 'pubspec.yaml').read_bytes()


def _remote_head(remote):
    return subprocess.run(['git', 'log', '--format=%s', '-1'], cwd=remote,
                          capture_output=True, text=True).stdout.strip()


def test_deploy_pushes_the_release_commits(capsys, deploy_env, monkeypatch, tmp_path):
    """The commits that made the release end up on the remote by themselves.

    A bump commit that exists on one machine is a version on Play that nothing
    else can reproduce, which is the whole reason deploy stopped telling people
    to remember `git push`.
    """
    remote = tmp_path / 'remote.git'
    _git(tmp_path, 'init', '--bare', '-q', str(remote))
    _git(deploy_env, 'remote', 'add', 'origin', str(remote))
    _git(deploy_env, 'push', '-q', '-u', 'origin', 'HEAD')
    monkeypatch.setattr(play, 'upload_release', lambda ctx, kind, track, **kw:
                        [{'module': 'phone', 'track': 'internal', 'versionCode': '2', 'status': 'completed'}])
    cli.main(['--project', str(deploy_env), 'deploy', '--yes', '--confirm', 'com.app'])
    data = json.loads(capsys.readouterr().out)
    assert data['result']['pushed']
    assert _remote_head(remote) == 'chore: bump version to 1.0.1 (versionCode 2)'


def test_deploy_without_an_upstream_still_succeeds(capsys, deploy_env, monkeypatch):
    """No remote is a warning, never a failure: the build is already on Play."""
    monkeypatch.setattr(play, 'upload_release', lambda ctx, kind, track, **kw:
                        [{'module': 'phone', 'track': 'internal', 'versionCode': '2', 'status': 'completed'}])
    code = cli.main(['--project', str(deploy_env), 'deploy', '--yes', '--confirm', 'com.app'])
    data = json.loads(capsys.readouterr().out)
    assert data['ok'] and data['result']['versionCode'] == 2
    assert code == 7  # partial: released, not pushed
    assert not data['result'].get('pushed')
    assert _log(deploy_env)[0] == 'chore: bump version to 1.0.1 (versionCode 2)'


def test_push_after_deploy_can_be_turned_off(capsys, deploy_env, monkeypatch, tmp_path):
    remote = tmp_path / 'off.git'
    _git(tmp_path, 'init', '--bare', '-q', str(remote))
    _git(deploy_env, 'remote', 'add', 'origin', str(remote))
    _git(deploy_env, 'push', '-q', '-u', 'origin', 'HEAD')
    toml = deploy_env / 'mkit.toml'
    toml.write_text(toml.read_text().replace('[app]' + chr(10), '[app]' + chr(10) + 'push_after_deploy = false' + chr(10)))
    _git(deploy_env, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qam', 'off')
    monkeypatch.setattr(play, 'upload_release', lambda ctx, kind, track, **kw:
                        [{'module': 'phone', 'track': 'internal', 'versionCode': '2', 'status': 'completed'}])
    cli.main(['--project', str(deploy_env), 'deploy', '--yes', '--confirm', 'com.app'])
    data = json.loads(capsys.readouterr().out)
    assert not data['result'].get('pushed')
    # The bump never left the machine: the remote is still on the commit that
    # was there before the release.
    assert _remote_head(remote) == 'init'


def test_deploy_failure_undoes_bump(capsys, deploy_env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('network down')
    monkeypatch.setattr(play, 'upload_release', boom)
    code = cli.main(['--project', str(deploy_env), 'deploy', '--yes', '--confirm', 'com.app'])
    data = json.loads(capsys.readouterr().out)
    assert code != 0 and not data['ok']
    assert _log(deploy_env)[0] == 'init'
    assert b'version: 1.0.0+1\r\n' in (deploy_env / 'pubspec.yaml').read_bytes()


def test_deploy_dry_run_leaves_repo_untouched(capsys, deploy_env, monkeypatch):
    seen = {}

    def fake_upload(ctx, kind, track, **kw):
        seen.update(kw)
        return [{'module': 'phone', 'track': 'internal', 'versionCode': '2', 'status': 'completed'}]
    monkeypatch.setattr(play, 'upload_release', fake_upload)
    (deploy_env / 'notes.txt').write_text('uncommitted work')
    code = cli.main(['--project', str(deploy_env), 'deploy', '--dry-run'])
    assert code == 0 and seen['dry_run'] is True
    assert _log(deploy_env)[0] == 'init'
    assert (deploy_env / 'notes.txt').read_text() == 'uncommitted work'
    assert b'version: 1.0.0+1\r\n' in (deploy_env / 'pubspec.yaml').read_bytes()


def test_deploy_needs_confirmation_off_terminal(capsys, deploy_env):
    code = cli.main(['--project', str(deploy_env), 'deploy'])
    data = json.loads(capsys.readouterr().out)
    assert code == 6 and data['error']['code'] == 'NEEDS_CONFIRM'
    assert _log(deploy_env)[0] == 'init'


# ------------------------------------------------------------------ release note style

def test_note_problems_flag_what_play_shows_badly():
    assert play.note_problems('A new look for Circle.\nRe-sign in works again.\nSmall fixes.') == []
    assert play.note_problems("What's new\nA new look.") == ['heading line (Play shows its own)']
    assert play.note_problems('• A new look\n• Faster') == ['bullet']
    assert play.note_problems('- A new look\n- Faster') == ['list marker']
    assert play.note_problems('Faster — much faster') == ['em dash']
    assert play.note_problems('Faster - much faster') == ['hyphen used as a dash']
    assert play.note_problems('Dark mode \U0001F319') == ['emoji']


def test_check_note_style_names_every_locale():
    with pytest.raises(Exception) as e:
        play.check_note_style([{'language': 'en-US', 'text': '• One'},
                               {'language': 'de-DE', 'text': 'Eins'},
                               {'language': 'fr-FR', 'text': 'Un – deux'}])
    assert e.value.code == 'WHATSNEW_STYLE'
    assert 'en-US: bullet' in e.value.message and 'fr-FR: en dash' in e.value.message
    assert 'de-DE' not in e.value.message


def _released_with_notes(root):
    """The app as it stands after a release: notes committed, then deploy's bump."""
    with open(root / 'mkit.toml', 'a') as f:
        f.write('[store]\nwhatsnew_dir = "wn"\n')
    (root / 'wn').mkdir()
    (root / 'wn' / 'whatsnew-en-US').write_text('A new look.\n')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '-m', 'chore: bump version to 1.0.0 (versionCode 1)')


def _upload_ok(monkeypatch):
    monkeypatch.setattr(play, 'upload_release', lambda ctx, kind, track, **kw:
                        [{'module': 'phone', 'track': 'internal', 'versionCode': '2', 'status': 'completed'}])


def test_deploy_refuses_the_last_releases_notes(capsys, deploy_env, monkeypatch):
    _released_with_notes(deploy_env)
    _upload_ok(monkeypatch)
    cli.main(['--project', str(deploy_env), 'deploy', '--yes', '--confirm', 'com.app'])
    data = json.loads(capsys.readouterr().out)
    assert not data['ok'] and data['error']['code'] == 'WHATSNEW_UNCHANGED'
    assert _log(deploy_env)[0] == 'chore: bump version to 1.0.0 (versionCode 1)'


def test_deploy_ships_the_same_notes_on_purpose(capsys, deploy_env, monkeypatch):
    _released_with_notes(deploy_env)
    _upload_ok(monkeypatch)
    cli.main(['--project', str(deploy_env), 'deploy', '--same-notes', '--yes', '--confirm', 'com.app'])
    assert json.loads(capsys.readouterr().out)['ok']


def test_deploy_takes_notes_written_since_the_last_release(capsys, deploy_env, monkeypatch):
    _released_with_notes(deploy_env)
    _upload_ok(monkeypatch)
    (deploy_env / 'wn' / 'whatsnew-en-US').write_text('Pick a theme on the You page.\n')
    cli.main(['--project', str(deploy_env), 'deploy', '--yes', '--confirm', 'com.app'])
    assert json.loads(capsys.readouterr().out)['ok']
