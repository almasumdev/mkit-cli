# Changelog

Every change is described here before it is released. Versions follow semantic
versioning (see CONTRIBUTING.md). An app states the oldest engine it works with
in `mkit.toml` (`requires = ">=0.3"`), and an older engine refuses to run for
it rather than doing the wrong thing.

## Unreleased

## 0.5.0 — 2026-10-23

**An app can keep its own version of any guide.** A file named like the guide
in the app's repo — `docs/guides/about-screen.md`, `docs/guides/app-ui.md`, or
under `[guide] app_dir` — is added after the guide and the studio's own rules,
under *This app's own rules*, and wins over both. `[guide] replace = ["ui"]` in
the app's `mkit.toml` makes that file the whole guide. Placeholders work in it,
`{{app.name}}` included, and `mkit guide --json` reports `app` and `replaced`.

## 0.4.0 — 2026-10-23

**Guides.** `mkit guide` reads the guides every app follows — the About screen,
in-app review, in-app updates, ASO, support replies, app UI, the store folder,
store art, news notifications — filled in with your studio's details from
`[studio]`, `[about]` and `[support]` in `~/.mkit/config.toml` or an app's
`mkit.toml`. They ship inside the package, so they work offline. Anything not
set shows as ‹key› and is listed; `--raw` gives the guide as written.

- **The About screen is yours to shape.** `[about] parts` picks which of its
  nine parts an app has, and every line it says has an `[about]` key with a
  default.
- **Your own rules beside a guide.** A file of the same name in
  `[guide] house_dir` is appended under *This studio's own rules*, and wins
  where the two disagree.
- Five guides are new to this repo: about-screen, in-app-review, aso,
  support-replies and app-ui.

**`--dry-run` can no longer quietly make the change.** `mkit init --dry-run`
wrote every file it was meant to preview, and twelve other write-class commands
ignored the flag the same way: `bump` committed, `share` uploaded, `firebase
sha-add` changed the Firebase project. Commands now declare whether they
support a dry run, and the CLI refuses `--dry-run` for any that do not — exit 2,
`NO_DRY_RUN` — before anything runs. `init` and `bump` preview for real. Every
publish-class command already honoured it and still does.

- `mkit commands --json` reports `dry_run` per command, so an agent can tell in
  advance which commands it can rehearse.

## 0.3.1 — first public release

mkit shipped a small studio's Android apps for a year before this; this is that
tool, with the studio's own house style and private services taken out. What is
here is the engine.

**Release.** `mkit deploy` in one command: preflight, a commit for whatever was
already uncommitted, the version bump in its own commit, Firestore rules, the
release build, the upload with mapping and release notes, the in-app update
document, a Telegram message, and a push. A failure before Play accepts the
build undoes the bump commit — and only if it is still at HEAD, so it can never
drop someone else's work. `promote`, `rollout` and `share` move a build on from
there.

**Store.** The listing, what's new, screenshots, the feature graphic, data
safety and in-app products all live in the repo, in every language, with `plan`
showing the difference against Play before `apply` sends it. `mkit art build`
draws the screenshots from real device captures.

**Insight.** `stats`, `vitals`, `crashes`, `reviews`, and `aso rank` /
`aso score` for where an app sits in Play search.

**Firebase.** Firestore rules, Remote Config (`plan`, `apply`, `pull`,
`rollback`), and an in-app update document the app reads at startup.

**Devices.** `run` builds and installs on a phone or emulator, `logs` follows
just that app, `studio` opens the project in Android Studio.

**Getting started.** `mkit init` writes `mkit.toml` and a commented `.env`
naming every credential, where it comes from and how to encode it; an existing
`.env` is never replaced, not even with `--force`. `mkit doctor` says what is
configured, what is broken, and which store commands an app cannot run because
it has no file for them. `mkit manual` lists the Play Console steps that have no
API — including production access for a new personal account and App access
credentials for an app behind a sign-in.

**Staying current.** `mkit self status` says whether a newer release is on PyPI,
and `mkit self update` names the upgrade command for whichever of uv, pipx or
pip installed it.

**For agents.** JSON output off a terminal, one envelope per run, an exit code
per outcome, a risk class per command, and a confirmation that publish-class
commands will not run without.

**Built and tested** on Linux, macOS and Windows against Python 3.11 and 3.13,
with a check that the generated command reference matches the code on every
platform. Releases publish to PyPI from a version tag through trusted
publishing, with no token stored anywhere.
