# mkit for AI agents

Read this before running mkit in any app.

## The release rule

**Never run a release or publish command unless the user asked for that
exact action in this conversation.** Not to test, not to verify a change,
not as a "safe" dry run.

Release and publish commands:

| Command | Changes |
|---|---|
| `deploy` (including `deploy --dry-run`) | builds, bumps and commits the version, uploads to Play |
| `promote`, `rollout` | what users on a track get |
| `listing apply`, `datasafety apply`, `testers set` | the store listing and testing setup |
| `products apply` | in-app products and prices |
| `rules`, `config set`, `remoteconfig apply`, `remoteconfig rollback` | the live Firebase project |
| `reviews reply` | a public reply |
| `bump`, `share` | the app's version commit; a build handed to testers |

`deploy --dry-run` is on the list because it bumps and builds, uploads a
full bundle to Play and takes minutes; it is still release work.

When the user does ask:

1. Say exactly what will happen (app, version, track, what changes).
2. Run the plan form first where there is one (`listing plan`,
   `products plan`, `remoteconfig plan`) and show the result.
3. Run it with `--yes --confirm <package>`. The engine refuses without both
   when it is not at a terminal (exit 6). `safety.no_prompt` does not change
   this: it only spares a person at a terminal the typed confirmation. Approval covers that one action;
   the next publish needs a new one.

## Free to run

Everything else, when it helps the task: `doctor`, `status`, `version`,
`commands`, `schema`, `manual`, `self status`, `devices`, `listing plan`,
`products plan`, `remoteconfig plan`, `whatsnew check`, `datasafety check`,
`stats`, `vitals`, `crashes`, `reviews list`, `aso rank`, `aso score`,
`config show`, `testers show`, `products list`, `prices convert`,
`firebase sha`, `remoteconfig versions`.

`run` builds and installs on a device: only when the user wants the app on a
device, and only on the device they mean.

`studio` opens a window on the user's screen: only when they ask for it.

## Discover, don't guess

- `mkit commands --json`: every command with its risk class, needed
  features, and a JSON Schema of its input.
- `mkit schema <command> --json`: one command in detail.
- `mkit doctor --json`: which features this app uses and what is broken.
- `mkit manual`: what only Play Console can do. Tell the user; don't look for
  a workaround.
- Reference: `docs/commands.md`, `docs/config.md`.

## Output contract

Off a terminal mkit prints JSON on its own. stdout is exactly one envelope:

```json
{"ok": true, "command": "...", "exit": 0, "result": {}, "warnings": [], "skipped": []}
{"ok": false, "command": "...", "exit": 3, "error": {"code": "...", "message": "...", "hint": "...", "retryable": false}}
```

stderr has one JSON event per line (`step`, `done`, `detail`, `warn`,
`skipped`, `upload`, `log`). Branch on `exit`; follow `error.hint`.

| exit | meaning | what to do |
|---|---|---|
| 0 | ok | |
| 1 | failed | read `error`, report it |
| 2 | usage | fix the arguments |
| 3 | credential missing | tell the user which key `hint` names; never ask for the secret itself |
| 4 | not found | |
| 5 | conflict: remote changed, edit expired, already in review | re-run the plan, then ask again |
| 6 | needs confirmation | stop and ask the user |
| 7 | done, with skipped steps | report what `skipped` lists |
| 10 | plan found differences | show the diff |

## Changing mkit itself

Changes go in the engine, never in an app's copy; follow
CONTRIBUTING.md (tests, regenerated docs, changelog, version).

Never read, print or copy `.env` files or credentials. Never commit them.
