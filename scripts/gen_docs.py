"""Regenerate docs/commands.md from the command registry.

    uv run python scripts/gen_docs.py

tests/test_docs.py fails while the committed file is out of date.
"""
from pathlib import Path

from mkit import commands  # noqa: F401  (registers every command)
from mkit.docgen import render

target = Path(__file__).resolve().parents[1] / 'docs' / 'commands.md'
target.write_text(render(), encoding='utf-8', newline='\n')
print(f'wrote {target}')
