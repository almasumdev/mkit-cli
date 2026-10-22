# Changelog

Every change is described here before it is released. Versions follow semantic
versioning (see CONTRIBUTING.md). An app states the oldest engine it works with
in `mkit.toml` (`requires = ">=0.3"`), and an older engine refuses to run for
it rather than doing the wrong thing.

## Unreleased

- `mkit doctor` names each missing `[store]` key with the command it blocks,
  instead of reporting the feature on while `listing`, `art`, `datasafety`
  or `products` have nowhere to read from.
- `mkit manual` lists two more Console-only steps: production access for a new
  personal developer account (12 testers opted in for 14 days of closed
  testing), and App access test credentials for an app behind a sign-in.
- `mkit init` writes a commented `.env` naming every credential, where it
  comes from and how to encode it. An existing `.env` is never replaced, not
  even with `--force`.
- Tests run on GitHub Actions: Linux, macOS and Windows, Python 3.11 and 3.13,
  with a check that the generated command reference is current.

## 0.3.1 — first public release

mkit shipped a small studio's Android apps for a year before this; this is that
tool, with the studio's own house style and private services taken out. What is
here is the engine.

- **Release.** `mkit deploy` in one command: preflight, a commit for whatever
  was already uncommitted, the version bump in its own commit, Firestore rules,
  the release build, the upload with mapping and release notes, the in-app
  update document, a Telegram message, and a push. A failure before Play
  accepts the build undoes the bump commit — and only if it is still at HEAD,
  so it can never drop someone else's work. `promote`, `rollout` and `share`
  move a build on from there.
- **Store.** The listing, what's new, screenshots, the feature graphic, data
  safety and in-app products all live in the repo, in every language, with
  `plan` showing the difference against Play before `apply` sends it. `mkit art
  build` draws the screenshots from real device captures.
- **Insight.** `stats`, `vitals`, `crashes`, `reviews`, and `aso rank` /
  `aso score` for where an app sits in Play search.
- **Firebase.** Firestore rules, Remote Config (`plan`, `apply`, `pull`,
  `rollback`), and an in-app update document the app reads at startup.
- **Devices.** `run` builds and installs on a phone or emulator, `logs`
  follows just that app, `studio` opens the project in Android Studio.
- **For agents.** JSON output off a terminal, one envelope per run, an exit
  code per outcome, a risk class per command, and a confirmation that
  publish-class commands will not run without.
