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


def test_release_commands_are_publish_class():
    # The skill promises agents never release without being asked; that rests
    # on every command that changes Play or Firebase being publish-class.
    for name in ('deploy', 'promote', 'rollout', 'rules', 'config set', 'listing apply',
                 'datasafety apply', 'products apply', 'remoteconfig apply',
                 'remoteconfig rollback', 'reviews reply', 'testers set'):
        assert REGISTRY[name].risk == 'publish', name
