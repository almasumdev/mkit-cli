# The store folder

Every app keeps everything Google Play shows in one folder, `store/`, and mkit
reads it from there. The layout is the same in every app, so anyone, person
or agent, knows where each thing is and what to update when the app changes.

## Layout

```
store/
  README.md                    the app's own store guide: facts, keyword strategy, languages
  listing/<code>.md            title, short and full description, one file per language
  art/shots/*.png              raw phone captures for the screenshots
  art/captions/<code>.json     screenshot and feature graphic words, one file per language
  art/art.toml                 slides, captures, what to erase, colours (docs/store-art.md)
  whatsnew/whatsnew-<locale>   the release note for the next release, per Play locale
  products.toml                in-app products and subscriptions
  datasafety.csv               the data safety form, built from [datasafety]
  screenshots/<code>/          built by `mkit art build` (not in git)
  feature/<code>.png           built by `mkit art build` (not in git)
```

In `mkit.toml`:

```toml
[store]
listing_dir  = "store/listing"
whatsnew_dir = "store/whatsnew"
products     = "store/products.toml"
datasafety   = "store/datasafety.csv"
icon         = "android/app/src/main/ic_launcher-playstore.png"   # the launcher set's 512x512

[store.locales]                  # listing code -> Play locale(s); every per-language file follows it
en = ["en-US"]
de = ["de-DE"]

[art]                            # mkit art init adds it
```

The Play icon stays with the launcher icons it is generated with; `icon`
points at it rather than keeping a copy.

## Git

Commit the sources; ignore what mkit builds. `mkit art init` adds the ignore
lines itself:

```gitignore
# Store art built by `mkit art build` (sources: store/art)
/store/screenshots/
/store/feature/
```

The leading `/` ties each line to the repo root. Everything else in `store/`
is committed.

## Every language, every time

Each per-language part follows `[store.locales]`, so a language the listing
has also gets screenshots, a feature graphic and a release note:

| Part | One per | Checked by |
|---|---|---|
| Listing text | listing code | `mkit listing plan --text-only` |
| Screenshots, feature graphic | listing code | `mkit art check` (lists codes with no captions) |
| Release note | Play locale | `mkit whatsnew check` (lists locales with no note) |

A language without its own file is shown the default one (English) by Play.
English is written first and is the master; the other languages follow its
facts and order, in each market's own words and the app's own terms for its
features (the app's translation files). No dashes, arrows, bullets or emoji.

### Release notes

Play shows the note as plain text under its own "What's new" heading, so a
note is only its changes:

- One change per line, as a plain sentence, the one people will notice most
  first. Say what the person can now do, in the app's own names for its tabs
  and features.
- No heading line ("What's new"), bullets, list markers, dashes, arrows or
  emoji. A line break already makes it a list.
- An optional last line for the rest: "Small fixes and polish throughout."
- At most 500 characters, and written for this release: a note left as it was
  at the last release describes that one.

```
A new look for Circle, Crew, Ranks, My apps and You.
Pick light, dark or your phone's theme on the You page.
Small fixes and polish throughout.
```

`mkit whatsnew check` shows the length, every style problem and whether the
note is unchanged since the last release. `mkit deploy` refuses a note that
breaks the style, and one unchanged since its last version bump unless
`--same-notes` says that is on purpose.

## Keeping it current

When the app changes, the store changes with it, in the same piece of work:

| The app... | Update |
|---|---|
| gets any change people will notice (every release) | `whatsnew/` for every locale, before `mkit deploy`: English first (plain lines, at most 500 characters), then every other locale; `mkit whatsnew check` shows none missing |
| gains, loses or moves a feature to or from the paid version | `listing/` in every language (English first), the facts in `art/captions/`, and `products.toml` if a product changes |
| looks different on a screen the screenshots show | a new capture in `art/shots/`, then `mkit art build` |
| gets a new language | a listing file, a `[store.locales]` entry, a captions file, a release note |
| collects different data | `[datasafety]` in `mkit.toml`, `mkit datasafety build`, and the privacy page |
| gets a new icon | regenerate the launcher set; `icon` already points at it |

A release note written for one release is replaced for the next; Play keeps
the old ones with their releases.

## Publishing

Looking is always safe; anything that changes what people see on Play needs
an explicit go:

| Look | Publish |
|---|---|
| `mkit listing plan --text-only` | `mkit listing apply --text-only` |
| `mkit art check`, `mkit art build`, `mkit listing plan --images-only` | `mkit listing apply --images-only` |
| `mkit whatsnew check` | sent with `mkit deploy` |
| `mkit products plan` | `mkit products apply` |
| `mkit datasafety check` | `mkit datasafety apply` |

## The app's own guide

`store/README.md` holds what is particular to the app: the facts its listing
may claim, its keyword strategy, its languages and titles, what each
screenshot shows. Keep it current with the rest of the folder. Value Guard's
is the reference.

## Moving an app over

Move the listing folder to `store/listing` (`git mv`) and the release notes to
`store/whatsnew`, point `[store]` at them, point `icon` at the launcher set's
Play icon, run `mkit art init`, and write `store/README.md`. Nothing about the
files changes, only where they live.
