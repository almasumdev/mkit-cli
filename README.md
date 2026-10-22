# mkit

One command-line tool for everything around an Android app that is not writing
it: build and install on a device, release to Google Play, keep the store
listing, screenshots, data safety and in-app products in your repo, read
installs, vitals, crashes and reviews, check search rank, and drive the
Firebase side (Firestore rules, Remote Config, an in-app update document).

Flutter and native Kotlin apps, including apps with a Wear OS module.

```bash
mkit deploy          # bump, build, upload to Play, publish, notify, push
mkit run -p          # build and install on the phone
mkit status          # what every track holds right now
mkit crashes         # what is breaking in production
```

A release is one command. `mkit deploy` bumps the version, commits it, builds
the bundle, uploads it with its mapping file and release notes, stages it on a
track, writes the update document, sends a message, and pushes — and if
anything fails before Play accepts the build, the version bump undoes itself so
the repo never claims a release that did not happen.

## Why it exists

Shipping an Android app means a dozen small jobs that live in different places:
a Gradle command, the Play Console, the Firebase console, a screenshot folder
somebody renamed, a changelog nobody updated. Each is easy; together they are a
release day. mkit puts them behind one tool, with the app's settings in one
file, so the same release happens the same way every time — and so an AI agent
can run the safe parts without being handed your Play Console password.

It was built to ship a small studio's apps and has been doing that for a while.
It is opinionated where opinions save time and configurable where apps really
differ.

## Install

Requires Python 3.11+ and git. [uv](https://docs.astral.sh/uv/) is the easiest
way in:

```bash
uv tool install git+https://github.com/almasumdev/mkit-android
mkit --version
```

Or with pipx: `pipx install git+https://github.com/almasumdev/mkit-android`.

## Getting started

In an app's folder:

```bash
mkit init            # writes mkit.toml, asking what it cannot work out
mkit doctor          # what is configured, what is missing, and what to add
```

`mkit.toml` is the whole of an app's configuration:

```toml
[app]
name    = "My App"
kind    = "flutter"          # flutter | android | android-wear
package = "com.example.app"

[play]                       # switches Play features on

[store]                      # store listing, art and data safety in the repo
listing_dir = "store/listing"
```

Credentials never live in that file. A Google Play service account goes in
`.env` (per app) or `~/.mkit/.env` (shared); `mkit doctor` names the exact key
when one is missing, and never prints a secret. Every setting is documented in
[docs/config.md](docs/config.md).

## What it does

| | |
|---|---|
| **Develop** | `run`, `devices`, `logs`, `emu`, `studio`, `gradle`, `version`, `bump` |
| **Release** | `deploy`, `status`, `promote`, `rollout`, `share` |
| **Store** | `listing`, `whatsnew`, `datasafety`, `testers`, `art` |
| **Money** | `products`, `prices` |
| **Insight** | `stats`, `vitals`, `crashes`, `reviews`, `aso` |
| **Firebase** | `rules`, `config`, `remoteconfig`, `firebase` |

Every command, flag and example: [docs/commands.md](docs/commands.md),
generated from the code so it cannot describe a flag that does not exist.

Commands are classed by what they can change — `read`, `plan`, `write`,
`publish` — and anything in the `publish` class refuses to run without an
explicit confirmation naming the package.

Some things have no API and must be done in the Play Console. `mkit manual`
lists them, so you know what is left rather than discovering it at release
time.

## Working with AI agents

mkit answers in JSON whenever it is not attached to a terminal, with one
envelope on stdout and a documented exit code per outcome, so an agent can
branch on a result instead of reading prose. [AGENTS.md](AGENTS.md) is the
contract: which commands are safe to run unasked, which need a human to say so,
and what an agent must never do.

## Documentation

| | |
|---|---|
| [docs/commands.md](docs/commands.md) | every command and flag |
| [docs/config.md](docs/config.md) | `mkit.toml`, the store and keyword files, credentials |
| [docs/store.md](docs/store.md) | the `store/` folder: what lives where, in every language |
| [docs/store-art.md](docs/store-art.md) | screenshots and the feature graphic, built from real captures |
| [docs/in-app-update.md](docs/in-app-update.md) | how an app should check for updates: Play first, your policy second |
| [docs/news-topics.md](docs/news-topics.md) | news and offer notifications over FCM topics |
| [AGENTS.md](AGENTS.md) | the agent contract |
| [CONTRIBUTING.md](CONTRIBUTING.md) | changing mkit, tests, versioning |

## Status and scope

Developed on Windows against real apps on Google Play; the code paths for
macOS and Linux exist but are less travelled, and there is no CI yet. The test
suite runs against a fake Play service — nothing in the tests touches a real
account.

It does not: create an app in the Play Console, answer content rating or target
audience questionnaires, manage tester email lists (the API only takes Google
Groups), or publish for you when managed publishing is on. `mkit manual` is the
full list.

Issues and pull requests are welcome. If you use it for your own apps, I would
like to hear what broke.

## Licence

MIT. See [LICENSE](LICENSE).
