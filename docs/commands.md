# mkit command reference

Generated from the command registry (mkit 0.5.x). Do not edit by hand: run `python scripts/gen_docs.py`.

Global options, accepted before or after any command: `--json`, `--human`, `--project PATH`, `--dry-run`, `--strict`, `--yes --confirm PACKAGE`, `--no-color`.

## Risk classes

| Class | Meaning |
|---|---|
| read | looks only, changes nothing |
| plan | reads remote state and shows a diff, changes nothing |
| write | changes local files/git or a non-user-facing remote thing |
| publish | changes what users, testers or Play review see; always confirmed |

## Develop

| Command | Risk | What |
|---|---|---|
| `bump` | write | Bump the version name and code (and commit it, unless --no-commit) |
| `devices` | read | List attached devices and emulators |
| `emu` | read | Start an Android emulator (cold boot) and wait for it |
| `gradle` | write | Run Gradle tasks with the right JDK and folder (lint, clean, test, profiles...) |
| `logs` | read | Follow the app's logcat (Shift+R restarts the app) |
| `run` | read | Build, install and launch the app on a device |
| `studio` | read | Open this app in Android Studio |
| `version` | read | Show this app's version, as the version file has it |

### mkit bump

`write`

Bump the version name and code (and commit it, unless --no-commit)

```
mkit bump [level] [--no-commit]
```

| Argument | What |
|---|---|
| `level` | which part of the name (one of major, minor, patch) (default patch) |
| `--no-commit` | change the file only |

Examples:

```
mkit bump
mkit bump minor
mkit bump --no-commit
mkit bump --dry-run
```

### mkit devices

`read`

List attached devices and emulators

```
mkit devices
```

### mkit emu

`read`

Start an Android emulator (cold boot) and wait for it

```
mkit emu [avd] [--list]
```

| Argument | What |
|---|---|
| `avd` | emulator name (default: ask, or the only one) |
| `--list` | only list the emulators |

Examples:

```
mkit emu
mkit emu Pixel_8_API_35
mkit emu --list
```

### mkit gradle

`write`

Anything a project did through Gradle before, with the JDK mkit picks and from the Gradle root (android/ for Flutter apps). Output streams as-is.

```
mkit gradle <tasks...>
```

| Argument | What |
|---|---|
| `tasks` | Gradle tasks and flags, passed through as-is |

Examples:

```
mkit gradle :app:lintDebug
mkit gradle clean
mkit gradle :app:testDebugUnitTest
mkit gradle :app:generateBaselineProfile
```

### mkit logs

`read`

Follows the debug install by default, the same one `mkit run` puts on the device; Shift+R restarts that app. -r switches to the release install.

```
mkit logs [--device DEVICE] [--all] [-r|--release]
```

| Argument | What |
|---|---|
| `--device` | adb serial to use when several are attached |
| `--all` | the whole device log, not just this app's |
| `-r, --release` | the release (Play) install instead of the debug one |

### mkit run

`read`

Flutter apps run through `flutter run`: r hot reload, R hot restart, q quit, logs in the same terminal. Native apps are built with Gradle, installed and opened; -l then follows logcat, where Shift+R builds and installs the current code and restarts the app.

```
mkit run [-p|--phone] [-e|--emulator] [-c|--clean] [-t|--test] [-r|--release] [-l|--logs] [--install] [--device DEVICE]
```

| Argument | What |
|---|---|
| `-p, --phone` | use a physical phone |
| `-e, --emulator` | use a running emulator |
| `-c, --clean` | first-install state: uninstall for every user and wipe backup first |
| `-t, --test` | run the project's tests on the device instead |
| `-r, --release` | build the release variant |
| `-l, --logs` | native apps: follow this app's logcat afterwards (Shift+R rebuilds, installs and restarts) |
| `--install` | Flutter apps: build, install and open without attaching (no hot reload); used automatically when not at a terminal |
| `--device` | adb serial to use when several are attached |

Examples:

```
mkit run
mkit run -p
mkit run -c -p
mkit run -r
mkit run -t
mkit run --install -l
```

### mkit studio

`read`

Opens the folder Android Studio should have: the repo root for a Flutter app, where the Flutter plugin gives Dart analysis, hot reload and the device list, with android/ indexed underneath. -a opens android/ on its own instead, a plain Gradle project for native work (manifests, AGP, Gradle plugins) with no Dart support. Native apps open at their Gradle root either way. Studio is left running when mkit exits.

```
mkit studio [-a]
```

| Argument | What |
|---|---|
| `-a` | Flutter apps: open the android/ Gradle project instead |

Examples:

```
mkit studio
mkit studio -a
```

### mkit version

`read`

Show this app's version, as the version file has it

```
mkit version
```

## Release

| Command | Risk | What |
|---|---|---|
| `deploy` | publish | Bump, build and release to a Play track (internal by default) |
| `promote` | publish | Move a tested release to another track, keeping its notes and name |
| `rollout` | publish | Change a staged production rollout: a percentage, halt, resume or complete |
| `share` | write | Build the release bundle and get an internal app sharing link |
| `status` | read | What every Play track holds (versions, rollout, notes) |

### mkit deploy

`publish`, needs `[play]` in mkit.toml

Bump, build and release to a Play track (internal by default)

```
mkit deploy [level] [--track TRACK] [--rollout ROLLOUT] [--same-notes]
```

| Argument | What |
|---|---|
| `level` | version bump (one of major, minor, patch) (default patch) |
| `--track` | track to release to (one of internal, closed, open, prod) (default internal) |
| `--rollout` | production only: staged rollout percentage, e.g. 20 |
| `--same-notes` | ship the release note unchanged from the last release |

Examples:

```
mkit deploy
mkit deploy minor
mkit deploy --dry-run
mkit deploy --yes --confirm com.example.app
```

### mkit promote

`publish`, needs `[play]` in mkit.toml

Move a tested release to another track, keeping its notes and name

```
mkit promote [to] [--from FROM] [--rollout ROLLOUT]
```

| Argument | What |
|---|---|
| `to` | destination track (one of internal, closed, open, prod) (default prod) |
| `--from` | source track (one of internal, closed, open, prod) (default internal) |
| `--rollout` | production only: staged rollout percentage, e.g. 20 |

Examples:

```
mkit promote
mkit promote closed
mkit promote prod --from closed --rollout 20
```

### mkit rollout

`publish`, needs `[play]` in mkit.toml

Change a staged production rollout: a percentage, halt, resume or complete

```
mkit rollout <action> [--track TRACK]
```

| Argument | What |
|---|---|
| `action` | a percentage like 50, or halt | resume | complete |
| `--track` | track with the staged release (default prod) |

Examples:

```
mkit rollout 50
mkit rollout halt
mkit rollout complete
```

### mkit share

`write`, needs `[play]` in mkit.toml

Build the release bundle and get an internal app sharing link

```
mkit share [--no-build]
```

| Argument | What |
|---|---|
| `--no-build` | upload the bundle already built |

### mkit status

`read`, needs `[play]` in mkit.toml

What every Play track holds (versions, rollout, notes)

```
mkit status
```

## Store

| Command | Risk | What |
|---|---|---|
| `datasafety apply` | publish | Upload the data safety declaration (replaces the one on Play) |
| `datasafety build` | write | Write the data safety CSV from [datasafety] in mkit.toml |
| `datasafety check` | read | Check the data safety CSV (no upload) |
| `datasafety types` | read | Every data type a declaration can name |
| `listing apply` | publish | Push listing changes (only what differs) to Play |
| `listing plan` | plan | Show how the listing files differ from Play (changes nothing) |
| `listing pull` | read | Save the live listing (all locales) to a JSON backup |
| `testers set` | publish | Set the Google Groups on a testing track |
| `testers show` | read | Google Groups on each testing track |
| `whatsnew check` | read | Check the what's new files: lengths and locales |

### mkit datasafety apply

`publish`, needs `[play]`, `[store]` in mkit.toml

Upload the data safety declaration (replaces the one on Play)

```
mkit datasafety apply
```

### mkit datasafety build

`write`, needs `[store]` in mkit.toml

The 782 questions are the same for every app; only the answers differ.

```
mkit datasafety build [--show]
```

| Argument | What |
|---|---|
| `--show` | print the answers without writing the file |

Examples:

```
mkit datasafety build
mkit datasafety build --show
```

### mkit datasafety check

`read`, needs `[store]` in mkit.toml

Check the data safety CSV (no upload)

```
mkit datasafety check
```

### mkit datasafety types

`read`

What [datasafety.collected] accepts, so nobody has to guess a spelling.

```
mkit datasafety types
```

### mkit listing apply

`publish`, needs `[play]`, `[store]` in mkit.toml

Push listing changes (only what differs) to Play

```
mkit listing apply [--text-only] [--images-only] [--locales LOCALES] [--resubmit]
```

| Argument | What |
|---|---|
| `--text-only` | only the text |
| `--images-only` | only the images |
| `--locales` | only these Play locales, comma separated, e.g. de-DE,es-ES (a staged rollout) |
| `--resubmit` | cancel a review already running and resubmit everything |

Examples:

```
mkit listing apply
mkit listing apply --text-only --dry-run
mkit listing apply --locales de-DE,es-ES,es-419,pt-BR
```

### mkit listing plan

`plan`, needs `[play]`, `[store]` in mkit.toml

Show how the listing files differ from Play (changes nothing)

```
mkit listing plan [--text-only] [--images-only] [--locales LOCALES]
```

| Argument | What |
|---|---|
| `--text-only` | only the text |
| `--images-only` | only the images |
| `--locales` | only these Play locales, comma separated, e.g. de-DE,es-ES (a staged rollout) |

Examples:

```
mkit listing plan
mkit listing plan --text-only
mkit listing plan --locales de-DE,es-ES
```

### mkit listing pull

`read`, needs `[play]` in mkit.toml

Save the live listing (all locales) to a JSON backup

```
mkit listing pull [--out OUT]
```

| Argument | What |
|---|---|
| `--out` | file to write (default: a timestamped backup) |

### mkit testers set

`publish`, needs `[play]` in mkit.toml

Set the Google Groups on a testing track

```
mkit testers set <track> <groups>
```

| Argument | What |
|---|---|
| `track` | testing track |
| `groups` | group emails |

### mkit testers show

`read`, needs `[play]` in mkit.toml

Google Groups on each testing track

```
mkit testers show
```

### mkit whatsnew check

`read`, needs `[store]` in mkit.toml

Check the what's new files: lengths and locales

```
mkit whatsnew check
```

## Money

| Command | Risk | What |
|---|---|---|
| `prices convert` | read | Google Play's own local price for every region, from one price |
| `products apply` | publish | Create or update products, their offers and subscriptions to match the file, and activate them |
| `products list` | read | What Play holds: every one-time product and subscription |
| `products plan` | plan | Compare the products file with Play (changes nothing) |

### mkit prices convert

`read`, needs `[play]` in mkit.toml

Google Play's own local price for every region, from one price

```
mkit prices convert <amount> [--currency CURRENCY]
```

| Argument | What |
|---|---|
| `amount` | price, tax exclusive, e.g. 4.99 |
| `--currency` | currency of the amount (default USD) |

Examples:

```
mkit prices convert 4.99
```

### mkit products apply

`publish`, needs `[play]`, `[store]` in mkit.toml

Create or update products, their offers and subscriptions to match the file, and activate them

```
mkit products apply
```

### mkit products list

`read`, needs `[play]` in mkit.toml

What Play holds: every one-time product and subscription

```
mkit products list
```

### mkit products plan

`plan`, needs `[play]`, `[store]` in mkit.toml

Compare the products file with Play (changes nothing)

```
mkit products plan
```

## Insight

| Command | Risk | What |
|---|---|---|
| `aso impact` | read | What a listing change did: store visitors and keywords before vs after a date |
| `aso rank` | read | Where the app ranks in Play search for each keyword, vs the last run |
| `aso research` | read | Find phrases people type and score which are worth targeting (mkit guide aso) |
| `aso score` | read | How beatable page one is for each keyword (weakest top-5 install count) |
| `crashes` | read | Top crash and ANR clusters with where they happen |
| `reviews list` | read | Reviews with text from the last 7 days (the API limit) |
| `reviews reply` | publish | Reply to a review (public, 350 characters) |
| `stats` | read | Installs, uninstalls, active devices, store conversion, ratings, countries |
| `vitals` | read | Crash and ANR rates per version (Play Developer Reporting API) |

### mkit aso impact

`read`, needs `[aso]`, `[play]` in mkit.toml

What a listing change did: store visitors and keywords before vs after a date

```
mkit aso impact [--since SINCE] [--days DAYS]
```

| Argument | What |
|---|---|
| `--since` | the day the change went live, YYYY-MM-DD |
| `--days` | days to compare on each side (default 14) |

Examples:

```
mkit aso impact --since 2026-10-02
```

### mkit aso rank

`read`, needs `[aso]` in mkit.toml

Where the app ranks in Play search for each keyword, vs the last run

```
mkit aso rank [--workers WORKERS]
```

| Argument | What |
|---|---|
| `--workers` | parallel requests (default 6) |

### mkit aso research

`read`, needs `[aso]` in mkit.toml

Find phrases people type and score which are worth targeting (mkit guide aso)

```
mkit aso research [--market MARKET] [--top TOP] [--workers WORKERS]
```

| Argument | What |
|---|---|
| `--market` | only this country (gl), e.g. DE |
| `--top` | phrases to show per market (human output) (default 15) |
| `--workers` | parallel requests (default 3) |

Examples:

```
mkit aso research
mkit aso research --market DE
```

### mkit aso score

`read`, needs `[aso]` in mkit.toml

How beatable page one is for each keyword (weakest top-5 install count)

```
mkit aso score [--workers WORKERS]
```

| Argument | What |
|---|---|
| `--workers` | parallel requests (default 6) |

### mkit crashes

`read`, needs `[play]` in mkit.toml

Top crash and ANR clusters with where they happen

```
mkit crashes [--limit LIMIT]
```

| Argument | What |
|---|---|
| `--limit` | how many (default 10) |

### mkit reviews list

`read`, needs `[play]` in mkit.toml

Reviews with text from the last 7 days (the API limit)

```
mkit reviews list [--limit LIMIT] [--translate TRANSLATE] [--unanswered]
```

| Argument | What |
|---|---|
| `--limit` | how many (default 50) |
| `--translate` | translate into this language, e.g. en |
| `--unanswered` | only reviews without a reply |

### mkit reviews reply

`publish`, needs `[play]` in mkit.toml

Reply to a review (public, 350 characters)

```
mkit reviews reply <id> <text>
```

| Argument | What |
|---|---|
| `id` | review id from `mkit reviews list` |
| `text` | the reply |

### mkit stats

`read`, needs `[play]` in mkit.toml

Installs, uninstalls, active devices, store conversion, ratings, countries

```
mkit stats [--days DAYS]
```

| Argument | What |
|---|---|
| `--days` | daily rows to show (human output) (default 14) |

### mkit vitals

`read`, needs `[play]` in mkit.toml

Crash and ANR rates per version (Play Developer Reporting API)

```
mkit vitals [--days DAYS]
```

| Argument | What |
|---|---|
| `--days` | window in days (default 28) |

## Firebase

| Command | Risk | What |
|---|---|---|
| `config set` | publish | Write the in-app update document: latest version, block old builds, nudge delay |
| `config show` | read | Show the in-app update document |
| `firebase config` | write | Download google-services.json for this app |
| `firebase debug-app` | write | Register the debug build's package with Firebase, then pull the config |
| `firebase sha` | read | SHA fingerprints registered for this app in Firebase |
| `firebase sha-add` | write | Register a signing SHA-1/SHA-256 with Firebase (then pull the config) |
| `remoteconfig apply` | publish | Publish the template file as the live Remote Config |
| `remoteconfig plan` | plan | Compare the template file with the live Remote Config |
| `remoteconfig pull` | write | Save the live Remote Config template to the template file |
| `remoteconfig rollback` | publish | Make an earlier Remote Config version live again |
| `remoteconfig versions` | read | Recent Remote Config versions |
| `rules` | publish | Deploy Firestore rules and indexes |

### mkit config set

`publish`, needs `[firebase]` in mkit.toml

Write the in-app update document: latest version, block old builds, nudge delay

```
mkit config set [--latest] [--latest-build LATEST_BUILD] [--latest-version-name LATEST_VERSION_NAME] [--min-supported-build MIN_SUPPORTED_BUILD] [--nudge-after-days NUDGE_AFTER_DAYS]
```

| Argument | What |
|---|---|
| `--latest` | publish the current version as the latest |
| `--latest-build` | set latestBuild explicitly (e.g. what Play already has) |
| `--latest-version-name` | set latestVersionName explicitly, with --latest-build |
| `--min-supported-build` | block every build below this versionCode (0 = none) |
| `--nudge-after-days` | days an update must be known before the app mentions it |

Examples:

```
mkit config set --latest
mkit config set --latest-build 12 --latest-version-name 1.2.0
mkit config set --min-supported-build 42
mkit config set --min-supported-build 0
```

### mkit config show

`read`, needs `[firebase]` in mkit.toml

Show the in-app update document

```
mkit config show
```

### mkit firebase config

`write`, needs `[firebase]` in mkit.toml

Download google-services.json for this app

```
mkit firebase config [--out OUT]
```

| Argument | What |
|---|---|
| `--out` | where to write it (default: the Android app module) |

### mkit firebase debug-app

`write`, needs `[firebase]` in mkit.toml

For a debug build type with an applicationIdSuffix: Firebase, and the google-services Gradle plugin, only accept packages registered in the project. Registers it when missing, adds this computer's debug key (SHA-1 and SHA-256, for Google sign-in) and writes google-services.json. Safe to run again.

```
mkit firebase debug-app
```

### mkit firebase sha

`read`, needs `[firebase]` in mkit.toml

SHA fingerprints registered for this app in Firebase

```
mkit firebase sha
```

### mkit firebase sha-add

`write`, needs `[firebase]` in mkit.toml

Register a signing SHA-1/SHA-256 with Firebase (then pull the config)

```
mkit firebase sha-add <sha>
```

| Argument | What |
|---|---|
| `sha` | fingerprint, with or without colons |

### mkit remoteconfig apply

`publish`, needs `[firebase]` in mkit.toml

Publish the template file as the live Remote Config

```
mkit remoteconfig apply
```

### mkit remoteconfig plan

`plan`, needs `[firebase]` in mkit.toml

Compare the template file with the live Remote Config

```
mkit remoteconfig plan
```

### mkit remoteconfig pull

`write`, needs `[firebase]` in mkit.toml

Save the live Remote Config template to the template file

```
mkit remoteconfig pull
```

### mkit remoteconfig rollback

`publish`, needs `[firebase]` in mkit.toml

Make an earlier Remote Config version live again

```
mkit remoteconfig rollback <version>
```

| Argument | What |
|---|---|
| `version` | version number |

### mkit remoteconfig versions

`read`, needs `[firebase]` in mkit.toml

Recent Remote Config versions

```
mkit remoteconfig versions [--limit LIMIT]
```

| Argument | What |
|---|---|
| `--limit` | how many (default 10) |

### mkit rules

`publish`, needs `[firebase]` in mkit.toml

Deploy Firestore rules and indexes

```
mkit rules
```

## About mkit

| Command | Risk | What |
|---|---|---|
| `commands` | read | List every command with its risk class and what it needs |
| `doctor` | read | Check tools, settings and credentials for this project |
| `guide` | read | How an app should do what every app has to do, filled in with your studio's details |
| `init` | write | Link this app folder to mkit (mkit.toml + launchers) |
| `manual` | read | What only Play Console can do (no API), as a checklist |
| `schema` | read | Input schema and details of one command |
| `self status` | read | The engine's version, how it was installed, and whether a newer one exists |
| `self update` | write | Update mkit: pull an editable checkout, or name the upgrade command |

### mkit commands

`read`

Every registered command. In JSON mode each entry carries a JSON Schema of its input, so an agent can build a valid call without reading help text.

```
mkit commands
```

Examples:

```
mkit commands
mkit commands --json
```

### mkit doctor

`read`

Check tools, settings and credentials for this project

```
mkit doctor
```

Examples:

```
mkit doctor
mkit doctor --json
```

### mkit guide

`read`

How an app should do what every app has to do, filled in with your studio's details

```
mkit guide [name] [--raw]
```

| Argument | What |
|---|---|
| `name` | which guide; leave it out for the list (one of about, review, update, aso, support, ui, store, art, news) |
| `--raw` | the guide as written, placeholders and all |

Examples:

```
mkit guide
mkit guide about
mkit guide review --json
mkit guide about --raw
```

### mkit init

`write`

Link this app folder to mkit (mkit.toml + launchers)

```
mkit init [path] [--kind KIND] [--package PACKAGE] [--name NAME] [--force]
```

| Argument | What |
|---|---|
| `path` | app folder (default: current folder) |
| `--kind` | override the detected kind (one of flutter, android, android-wear) |
| `--package` | override the detected package id |
| `--name` | override the detected app name |
| `--force` | overwrite existing mkit.toml and launchers |

Examples:

```
mkit init
mkit init ../my_app --name MyApp
mkit init --dry-run
```

### mkit manual

`read`

What only Play Console can do (no API), as a checklist

```
mkit manual
```

Examples:

```
mkit manual
```

### mkit schema

`read`

Input schema and details of one command

```
mkit schema <name>
```

| Argument | What |
|---|---|
| `name` | command name, e.g. "deploy" or "listing plan" |

Examples:

```
mkit schema deploy --json
mkit schema listing plan
```

### mkit self status

`read`

The engine's version, how it was installed, and whether a newer one exists

```
mkit self status
```

### mkit self update

`write`

Update mkit: pull an editable checkout, or name the upgrade command

```
mkit self update
```

## Other

| Command | Risk | What |
|---|---|---|
| `art build` | write | Draw the screenshots and feature graphic for each language |
| `art check` | read | Line counts of every language against the reference (text only, no images) |
| `art init` | write | Set up store art: the art folder, [art] in mkit.toml, .gitignore lines |

### mkit art build

`write`, needs `[art]` in mkit.toml

Writes <art_dir>/screenshots/<code>/01_<slide>.png ... and <art_dir>/feature/<code>.png, the files `mkit listing plan --images-only` compares with Play. Nothing is uploaded.

```
mkit art build [codes] [--keep-pages]
```

| Argument | What |
|---|---|
| `codes` | listing codes (default: every captions file) |
| `--keep-pages` | keep the HTML pages and print where |

Examples:

```
mkit art build
mkit art build en ar
mkit art build en --keep-pages
```

### mkit art check

`read`, needs `[art]` in mkit.toml

Each caption block must wrap to as many lines as in the reference language and stay inside its box; each file must have the reference's keys, one [accent] per title and no dashes, arrows or bullets. The reference itself, when named, is held to its boxes and line caps (a pop title is at most two lines; a pill stays on the page). The pages are laid out in the browser but no image is made, so a translation can be fitted in seconds.

```
mkit art check [codes]
```

| Argument | What |
|---|---|
| `codes` | listing codes (default: every captions file) |

Examples:

```
mkit art check
mkit art check de ar ja
```

### mkit art init

`write`

Creates <dir>/shots/, <dir>/captions/en.json and <dir>/art.toml from the starter files, adds [art] to mkit.toml and keeps the built images out of git. Only what is missing is written.

```
mkit art init
```

Examples:

```
mkit art init
```

## Command groups

- `art`: store screenshots and feature graphic, built from captures and captions
- `aso`: search rank, keyword research and listing impact
- `config`: the in-app update document (config/app)
- `datasafety`: the data safety declaration
- `firebase`: Firebase app settings (SHA fingerprints, google-services.json)
- `listing`: store listing text, images and contact details
- `prices`: Google Play's regional prices
- `products`: one-time products, their offers, and subscriptions
- `remoteconfig`: Firebase Remote Config template
- `reviews`: Play reviews: read and reply
- `self`: the mkit engine itself: version, updates
- `testers`: Google Groups on testing tracks
- `whatsnew`: release notes (what's new) files
