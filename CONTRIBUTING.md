# Contributing

Issues and pull requests are welcome. mkit drives real releases to the Play
Store, so the bar is less about style than about never surprising someone on
release day.

## Getting set up

```bash
git clone https://github.com/almasumdev/mkit-android
cd mkit-android
uv sync                 # or: pip install -e ".[dev]"
uv run pytest           # the whole suite, against a fake Play service
```

Nothing in the tests touches a real Google account. Play is faked by
`tests/fakeplay.py`, and it stays that way: a test that could publish is not a
test.

## The checklist for a change

1. Make the change. Keep anything app-specific out of the code.
2. Add or update tests in `tests/`.
3. `uv run python scripts/gen_docs.py` if a command, flag or summary changed —
   `docs/commands.md` is generated from the command registry, and
   `tests/test_docs.py` fails while it is stale.
4. `uv run pytest` — everything passes.
5. Describe the change under `## Unreleased` in `CHANGELOG.md`, in words
   somebody using the command would understand.

## Rules that must hold

- **A command that changes what users, testers or Play review see is
  `risk='publish'`** and calls `safety.confirm` before changing anything.
  `tests/test_docs.py` pins the list, so adding one is a deliberate act.
- **Nothing publishes in a test.** Use `tests/fakeplay.py` or `--dry-run`.
- **Secrets never reach output.** Read them through `secrets.Secrets`, which
  registers each one for masking.
- **JSON output and exit codes are a contract.** Agents and scripts branch on
  them; changing a shape or a code is a major version.
- **A per-app difference becomes an `mkit.toml` key**, documented in
  `docs/config.md` — never a branch in the code on an app's name.

## Versioning

Semantic versioning, in `src/mkit/__init__.py` only (`pyproject.toml` reads it
from there).

| Bump | When |
|---|---|
| patch | fixes; commands, flags, `mkit.toml` keys and JSON output unchanged |
| minor | new commands, flags, config keys or output fields; nothing existing breaks |
| major | anything an existing `mkit.toml`, script or agent would break on |

Releasing:

```bash
uv run python scripts/release.py minor      # shows the version and changelog entry
uv run python scripts/release.py minor go   # tests, bumps, dates the changelog, tags
git push --follow-tags
```

The script refuses with uncommitted changes, failing tests, or an empty
`## Unreleased` section, so every tag is a tested, described state.

## Reporting a bug

Say which app kind (Flutter, native, Wear), the command you ran, and the JSON
output — `mkit <command> --json`. Never paste a service account key, and note
that `mkit doctor --json` is safe to share: it names which credentials are
missing without printing any of them.
