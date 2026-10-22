# mkit.toml reference

One file per app, at the app's root, committed. It says what the app is and
which features it uses. Secrets never go here.

A table switches a feature on. Leave it out and every step that uses it is
skipped without a word, because the app does not use it. If a table is there
but its credential is missing, a pipeline skips the step with a warning
(`--strict` makes that a failure) and a command asking for it directly exits
3 with the key to add.

Settings are layered, first match wins: command flags, `MKIT_*` environment
variables (`MKIT_APP_PACKAGE` for `app.package`), this file,
`~/.mkit/config.toml`, built-in defaults.

```toml
requires = ">=0.2"            # oldest engine this app works with

[app]
name = "Tally"                # used in output and Telegram messages
kind = "flutter"              # flutter | android | android-wear
package = "com.example.app"
activity = ".MainActivity"    # optional
module = "app"                # native: Gradle module of the phone app
wear_module = "wear"          # android-wear: Gradle module of the watch app
version_file = "..."          # override: pubspec.yaml / version.properties / build.gradle(.kts)
signing = "key.properties"    # override where the release signing config is
java_home = "..."             # pin a JDK (default: first JDK 17-24 found)
studio = "..."                # pin Android Studio (default: the usual install paths)
debug_suffix = ".debug"       # optional: where debug builds install; read from Gradle when unset
log_tags = ["flutter:V"]      # logcat filter for run -l and logs; empty = whole logcat
push_after_deploy = true      # push the release commits when deploy finishes (default true)

[play]                        # Google Play: upload, tracks, listing, products, reviews, vitals
internal_testing_url = "..."  # shown in the deploy message
upload_timeout = 600          # seconds per upload request
upload_chunk_mb = 4
reports_bucket = "..."        # override MKIT_PLAY_REPORTS_BUCKET for this app

[store]                       # store files kept in the repo
listing_dir = "store/listing"       # <code>.md: three fenced blocks (title, short, full); default docs/store-listing
art_dir = "store"                     # feature/<code>.png, screenshots/<code>/, wear/<code>/
icon = "store/icon.png"               # 512x512 PNG (default art_dir/icon.png); may point at android/app/src/main/ic_launcher-playstore.png
whatsnew_dir = "distribution/whatsnew" # whatsnew-<play-locale>, 500 characters max
datasafety = "store/datasafety.csv"   # built by `datasafety build`, see below
products = "store/products.toml"      # in-app products and subscriptions
backup_dir = "console"                # where `listing pull` writes backups
# Optional, for apps that keep one set of art rather than one per language:
feature = "console/assets/feature-1024x500.png"   # one feature graphic for every language
screenshots = "console/assets/screenshots/phone"  # one screenshots folder for every language
wear_screenshots = "console/assets/screenshots/wear"
art_locales = ["en-US"]               # only these listings get art; the others inherit it

[store.locales]               # listing file code -> Play locale(s)
en = ["en-US"]
es = ["es-419", "es-ES"]      # one text, two listings

[store.details]               # optional: contactEmail, contactWebsite, contactPhone, defaultLanguage

[firebase]                    # this app's Firebase project
project = "my-project"        # must match the Firebase service account's project
rules = true                  # deploy firestore.rules / indexes before each build
update_doc = "config/app"     # the in-app update document written after each release
remote_config = "remoteconfig.template.json"
deploy = ["firestore:rules"]  # override what `rules` deploys

[notify.telegram]             # Telegram message after deploy and promote

[aso]
keywords = "console/aso/keywords.toml"
results_dir = "console/aso"   # default: next to the keywords file

[art]                         # store art: mkit art init / check / build (docs/store-art.md)
dir = "store/art"             # default: shots/, captions/<code>.json, art.toml
out = "store"                 # default: [store] art_dir, where mkit listing reads images
browser = "..."               # override: a Chromium to draw with (default: Edge or Chrome)

[hooks]                       # this app's own scripts, run at fixed points
pre_deploy = "python console/check.py"
post_build = "..."
post_deploy = "..."
post_promote = "..."

[safety]                      # usually in ~/.mkit/config.toml, for every app
no_prompt = ["deploy", "promote"]  # a person at a terminal is not asked to type the name
```

`safety.no_prompt` only drops the typed confirmation for a person at a
terminal; the command still prints what it is about to change. Off a terminal
(an agent, a script) those commands still refuse without `--yes --confirm`.

## Studio details (mkit guide)

`mkit guide <name>` fills its guides in from these. They are the same for every
app, so they usually live in `~/.mkit/config.toml`; an app's `mkit.toml` wins
where it differs. Anything a guide needs and you have not set shows as ‹key›,
and the command lists them.

```toml
[studio]
name = "Acme Apps"
tagline = "Small tools, done properly."
email = "hello@acme.dev"            # users and clients write here
website = "https://acme.dev"
privacy_url = "https://acme.dev/privacy"
terms_url = "https://acme.dev/terms"
play_developer_id = "1234567890123456789"   # the id in your Play developer page URL
developer = "Ada Example"
developer_role = "Mobile app developer at Acme Apps"
portfolio = "https://ada.example"
photo = "https://github.com/ada-example.png?size=460"

[about]                       # the About screen (mkit guide about)
# The parts it has, in this order; leave one out to drop it. Default: all nine.
parts = ["mark", "name", "version", "what", "rating", "maker", "ask", "more_apps", "footer"]
# Its words; <App> stands for the app's name. Each has a default.
rating_heading = "Enjoying <App>?"
rating_line = "Rate it on Google Play and support our work."
maker_heading = "Meet the developer"
ask = "We design and build mobile apps. <App> is one of ours. If you have one in mind, tell us about it."
email_button = "Start a project"
website_button = "Website"
more_heading = "More from us"
more_line = "Everything we have on the store, in one place."

[support]                     # replies to users (mkit guide support)
signoff = "The <App> team"    # the line above the email address

[guide]
house_dir = "~/studio/house"  # this studio's own rules, one file per guide
```

A studio's own decisions beside a guide — its worked examples, a look its apps
share, a rule it chose differently — go in `house_dir`, in a file named like the
guide's (`about-screen.md`, `in-app-review.md`, ...). `mkit guide` appends it
under *This studio's own rules*, which win where the two disagree. Without
`house_dir`, mkit looks in `docs/house/` beside its own source checkout.

## Store listing file

`listing_dir/<code>.md`, any text around three fenced blocks:

````markdown
## Title
```
Tally: Family Shopping List
```
## Short description
```
One shared list for the whole family, synced as you shop.
```
## Full description
```
...
```
````

## Data safety

Play's data safety form is 782 questions, and the API takes the same CSV the
Console's import accepts. There is no API that reads the current answers back -
`applications.dataSafety` is POST only - so the declaration lives in the repo,
next to the code it describes.

The question set ships with the engine. An app declares only its answers:

```toml
[store]
datasafety = "docs/data-safety/myapp.csv"   # where `datasafety build` writes it

[datasafety]
collects             = true    # does the app collect or share any of the types below
encrypted_in_transit = true    # default true
deletion             = "no"    # "yes" | "no" | "auto"; how a user can ask for deletion
account_creation     = "none"  # "none" | "password" | "other_auth" |
                               # "password_other_auth" | "oauth" | "other"; a list is fine
outside_app_accounts = false   # default false; only asked when account_creation = "none"
account_deletion_url = ""      # a page for deleting an account: Play requires it
                               # whenever account_creation is not "none"
deletion_url         = ""      # a page for deleting data: required with deletion = "yes"

[datasafety.collected]
# data type = the purposes it is collected for. A type left out is declared
# as NOT collected - the file says what the app does, nothing is true by omission.
crash_logs       = ["app_functionality", "analytics"]
diagnostics      = ["app_functionality", "analytics"]
app_interactions = ["analytics"]
device_ids       = ["app_functionality", "analytics"]
```

Purposes: `app_functionality`, `analytics`, `developer_communications`,
`fraud_prevention`, `advertising`, `personalization`, `account_management`.

`mkit datasafety types` lists every data type with the names it answers to - a
short alias, the name from Play's own label, and the raw `PSL_` id all work, so
there is nothing to guess.

A type that is shared, ephemeral, or that the user can turn off takes the long
form instead of a bare list:

```toml
[datasafety.collected.photos]
purposes  = ["app_functionality"]
shared    = ["analytics"]   # also shared with others, for these purposes
collected = false           # only shared (straight from the device to a third
                            # party); default true: sent off the device is collected
ephemeral = true            # processed in memory, never stored; default false
optional  = true            # the user can opt out in the app; default false
```

Then:

```
mkit datasafety build     # write the CSV from the answers above
mkit datasafety check     # nothing REQUIRED left blank
mkit datasafety apply     # upload it (replaces what Play holds; asks first)
```

Google handles some things the app never sees, and those are not declared:
purchases made through Play Billing, and the platform's own backup. A
permission is not collection either - an app that asks for location to scan for
Bluetooth devices, and never reads a location, does not declare location.

**The declaration is what Play publishes and holds the developer to**, so it
follows the code: an SDK added is a line added here. To see what Play holds
right now, export it from the Console (`mkit manual` names the page) - nothing
else can read it back.

## products.toml

```toml
regions_version = "2022/02"

[pricing]
pin_nominal = ["USD", "EUR", "GBP"]   # 4.99 stays 4.99 in these currencies
whole_unit = ["INR", "BDT"]           # prices like 499, not 4.99
[pricing.rates]                        # units per USD; refresh by hand
INR = 94.79
[pricing.regions]                      # currency -> regions priced explicitly
INR = ["IN"]

[[product]]
id = "pro_lifetime"
usd = 4.99
title = "Pro"
description = "One payment, Pro forever."

[[product.offer]]                      # a discount offer on the product above
id           = "launch"                # offerId: a-z, 0-9, hyphens; starts with a letter or digit
discount_pct = 50                      # 1..99 percent off, in every region the product sells in
start        = "2026-11-01"            # optional; UTC midnight (a full ISO datetime also works)
end          = "2026-12-31"            # required; after start
tags         = ["launch"]              # optional offer tags the billing library returns
# purchase_option = "buy"              # optional; default below

[[subscription]]
id = "pro_monthly"
base_plan = "monthly"
period = "P1M"
usd = 0.99
grace = "P7D"
account_hold = "P30D"
title = "Pro, monthly"
description = "Cancel any time."
benefits = ["Unlimited layouts"]
trial = "P3D"                         # optional: free for 3 days first (P7D, P1W, P1M ...)
trial_id = "free-trial"               # optional offer id, default free-trial
```

Every local price is the smallest amount ending in 99 worth at least the USD
anchor. Regions not listed get Play's own conversion. `products apply` never
deletes anything: not products, not offers.

### Free trials

`trial` on a `[[subscription]]` puts a free-trial offer on its base plan: free
for that long, then the base plan's price. It is sold in every region the base
plan is, and only to someone who has never subscribed to any of the app's
subscriptions, so a trial on monthly and on yearly is still one trial per
person. `plan` shows it as `create`, a changed length as `update`, a draft as
`activate`; apply creates or updates it, then activates it. The app has to buy
with the trial's offer token to start it (Play only returns the offer to
people it applies to).

### Discount offers

A `[[product.offer]]` under a `[[product]]` is a limited-time discount on that
product's purchase option (Play's one-time product offers).

- **Regions**: the offer is sold in every region the purchase option is
  available in on Play, plus any the file prices, at the same relative
  discount (`discount_pct = 50` is half price, rounded by Play to the local
  billable unit).
- **Purchase option**: `purchase_option` if set; otherwise the product's own
  option (`option`, default `buy`) when Play has it or is about to; otherwise
  the product's only option on Play, or its legacy-compatible buy option.
- **plan** diffs by offer id: discount, missing regions, start/end, tags and
  state. `create` and `update` are followed by activation (Play stores new
  offers as DRAFT); an offer that only needs switching on shows as `activate`.
  `start` is compared only when the file sets it.
- **apply** creates or updates, then activates. It never deletes or
  deactivates: taking an offer out of the file leaves it on Play (end it
  in Play Console, or let `end` pass).
- A change to a live offer is sent as an update. If Play refuses to edit an
  active offer, apply stops with exit 5 (`OFFER_ACTIVE`): deactivate it in
  Play Console and use a new offer id, or put the file back to the live terms.
- A new or changed offer whose `end` has already passed is refused (exit 2,
  `OFFER_ENDED`); a malformed offer is refused before Play is called (exit 2,
  `BAD_PRODUCTS`).
- Offers reach only apps on Play Billing Library 8 or later, through
  `ProductDetails.getOneTimePurchaseOfferDetailsList()`. An app on an older
  library still sells at the full price.
- An engine older than the one that added offers ignores `[[product.offer]]`,
  so an app that uses them should raise `requires` in `mkit.toml`.

## Store art (art.toml)

`<[art] dir>/art.toml` holds an app's slides, the boxes to erase from its
captures, its font, mascot and colours. `mkit art init` writes a starter with
every key explained; [store-art.md](store-art.md) is the full recipe.

| Key | What |
|---|---|
| `reference` | captions file every language is measured against (default `en`) |
| `font_dir`, `font` | folder with `<font>-Regular/-Medium/-SemiBold/-Bold.ttf`, and the family name |
| `mascot` | SVG or PNG for the hero, the feature graphic and the notification icon |
| `[status_bar]` | `height` and `erase` boxes of the phone's own status bar, in capture pixels |
| `[shots.<name>]` | `erase` boxes for anything private in one capture |
| `[theme.light]`, `[theme.dark]` | colours (`bg1`, `bg2`, `line`, `ink`, `sub`, `accent`, `tile`, ...); default green |
| `[script_fonts]` | fallback font by listing code |
| `[[slide]]` | `id`, `shot` (or `shots` = three for `kind = "landscape"`), `notify`, `dark`, `offset` |
| `[feature]` | `shot` for the feature graphic |

## Keywords file (ASO)

```toml
[[market]]
lang = "en"
hl = "en_US"      # Play UI language
gl = "US"         # country
keywords = ["shopping list", "grocery list"]   # tracked by `aso rank` / `aso score`
seeds = ["grocery list", "shared list"]         # optional: what `aso research` types (default: keywords)
topic = ["grocery", "list", "shopping"]         # optional: a found phrase must hold one (default: the seeds' words)
```

## Secrets

| Key | File | What |
|---|---|---|
| `MKIT_PLAY_SERVICE_ACCOUNT_JSON_BASE64` | `~/.mkit/.env` | Play service account (all apps) |
| `MKIT_TELEGRAM_JSON_BASE64` | `~/.mkit/.env` | `{"bot_token", "chat_id"}` |
| `MKIT_PLAY_REPORTS_BUCKET` | `~/.mkit/.env` | Play bulk reports bucket |
| `MKIT_FIREBASE_SERVICE_ACCOUNT_JSON_BASE64` | `<app>/.env` | this app's Firebase project |

Any `*_JSON_BASE64` key also works as `*_FILE=path`. The shell environment
beats the app's `.env`, which beats `~/.mkit/.env`.
