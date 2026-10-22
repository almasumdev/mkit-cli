from pathlib import Path

from mkit import commands  # noqa: F401
from mkit.docgen import render
from mkit.registry import REGISTRY

DOC = Path(__file__).resolve().parents[1] / 'docs' / 'commands.md'


def test_command_reference_is_current():
    assert DOC.read_text(encoding='utf-8') == render(), \
        'docs/commands.md is stale: run `uv run python scripts/gen_docs.py`'


def test_every_command_is_documented_and_classified():
    text = render()
    for name, cmd in REGISTRY.items():
        assert f'### mkit {name}' in text
        assert cmd.summary and cmd.risk


def test_every_publish_command_supports_a_dry_run():
    """The policy the CLI guard leans on: publish-class means previewable.

    Checked in the handler's source as well as the flag, so declaring support
    without implementing it fails here rather than in somebody's release.
    """
    import inspect
    for name, cmd in REGISTRY.items():
        if cmd.risk == 'publish':
            assert cmd.dry_run, name
            assert 'dry_run' in inspect.getsource(cmd.handler), name


def test_a_command_claiming_a_dry_run_reads_the_flag():
    import inspect
    for name, cmd in REGISTRY.items():
        if cmd.dry_run:
            assert 'dry_run' in inspect.getsource(cmd.handler), name


def test_release_commands_are_publish_class():
    # The skill promises agents never release without being asked; that rests
    # on every command that changes Play or Firebase being publish-class.
    for name in ('deploy', 'promote', 'rollout', 'rules', 'config set', 'listing apply',
                 'datasafety apply', 'products apply', 'remoteconfig apply',
                 'remoteconfig rollback', 'reviews reply', 'testers set'):
        assert REGISTRY[name].risk == 'publish', name
