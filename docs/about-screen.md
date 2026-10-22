# The About screen

Every app needs an About screen, and every app that solves it on its own ends
up with a different one. This guide is a spine that works: which parts, in what
order, what each says and does, and what it must never claim. **Only the theme
changes between apps** — colours, type, and the app's own row and button
components.

Read it with `mkit guide about`. Your studio's details are filled in from
`[studio]`, and which parts you use and what they say from `[about]` — in
`~/.mkit/config.toml` for every app, or an app's own `mkit.toml` to differ.
Anything you have not set shows as ‹key›.

## Make it yours

```toml
[studio]
name             = "Acme Apps"
tagline          = "Small tools, done properly."
email            = "hello@acme.dev"          # where users and clients write
website          = "https://acme.dev"
privacy_url      = "https://acme.dev/privacy"
terms_url        = "https://acme.dev/terms"
play_developer_id = "1234567890123456789"    # from your Play developer page URL
developer        = "Ada Example"
developer_role   = "Mobile app developer at Acme Apps"
portfolio        = "https://ada.example"
photo            = "https://github.com/ada-example.png?size=460"

[about]
# Leave out a part to drop it - its row, its words and its behaviour.
parts = ["mark", "name", "version", "what", "rating", "maker", "ask", "more_apps", "footer"]
# Every line below can be reworded; these are the defaults.
rating_heading = "Enjoying <App>?"
ask            = "We design and build mobile apps. <App> is one of ours. If you have one in mind, tell us about it."
```

`<App>` stands for the app's name, translated with the rest of the line.

## The spine

Top to bottom, in this order. A studio leaves out what it does not want;
nothing is reordered.

| # | Part | What it holds |
|---|---|---|
| 1 | **Mark** | the app's own launcher icon, centred, nothing behind it | <!-- part:mark -->
| 2 | **Name** | the app name, the largest type on the page | <!-- part:name -->
| 3 | **Version** | `v1.2.3` — the short form, bare, no tag or box, no build number | <!-- part:version -->
| 4 | **What it is** | one sentence, centred, the app's own words; never marketing | <!-- part:what -->
| 5 | **Rating** | a heading, one line, five stars → the Play listing | <!-- part:rating -->
| 6 | **The maker** | photo, name, role → the portfolio | <!-- part:maker -->
| 7 | **The ask** | a few lines about the studio, then two actions: email, website | <!-- part:ask -->
| 8 | **More apps** | a heading, one line, one Play button → the developer page | <!-- part:more_apps -->
| 9 | **Footer** | Privacy · Terms, then `© <year> {{studio.name}}` | <!-- part:footer -->

The first four are one block, centred. The middle parts are banks, each with a
heading and left-aligned text. The footer is centred and quiet. That single
change of alignment is what tells the eye where the reading starts.

**No cards.** Not for the rating, not for the maker, not for the Play button —
even in an app whose other screens are made of cards. Groups are made by space
alone: a heading sits close to what it names and far from what it does not, and
that asymmetry is the whole of the grouping. Roughly 10dp under a heading
against 26dp under a bank; wider — about 34dp — above the first bank and below
the last, where the page changes subject rather than section. An About page is
a few short things in a column, and a container round each is how it turns into
a filing cabinet.

## The words

English below; translate them into each of the app's locales. Every line is an
`[about]` key, so a studio rewords it once for all its apps.

| String | Key | Text |
|---|---|---|
| What it is | — | the app's own one sentence — the only line it writes itself | <!-- part:what -->
| Rating heading | `rating_heading` | `{{about.rating_heading}}` | <!-- part:rating -->
| Rating line | `rating_line` | `{{about.rating_line}}` | <!-- part:rating -->
| Maker heading | `maker_heading` | `{{about.maker_heading}}` | <!-- part:maker -->
| Maker name / role | `[studio]` | `{{studio.developer}}` / `{{studio.developer_role}}` | <!-- part:maker -->
| The ask | `ask` | `{{about.ask}}` | <!-- part:ask -->
| Email button | `email_button` | `{{about.email_button}}` | <!-- part:ask -->
| Website button | `website_button` | `{{about.website_button}}` | <!-- part:ask -->
| More heading | `more_heading` | `{{about.more_heading}}` | <!-- part:more_apps -->
| More line | `more_line` | `{{about.more_line}}` | <!-- part:more_apps -->
| Play button | — | `Google Play` | <!-- part:more_apps -->
| Footer | — | `Privacy` · `Terms` · `© <year> {{studio.name}}` | <!-- part:footer -->

The buttons **name their destination and nothing else**. The sentence saying
what is over there goes above them. A button carrying the whole explanation is
a sentence with a button drawn round it.

An app's own heading style still applies: if its section headers are uppercased
by its own component, these are too. The words are shared; the case is the
app's.

## What it never does

- **No rating it does not have.** The stars carry no number and show nothing
  back. They are a link to the listing, not a score.
- **No install counts, no review counts, no awards, no "loved by N users".**
- **No "All rights reserved."** It has carried no legal weight since the Berne
  Convention. The bare `© <year> {{studio.name}}` stays, and the year is read
  from the clock so the line cannot rot.
- **No list of the studio's other apps inside the app.** A hard-coded list
  cannot know what shipped after the build, what was renamed or what was
  pulled, and each of those becomes a false line on a page whose whole claim is
  that it states facts. The Play developer page is the same information, kept
  by the shop that sells it.
- **No second button saying what the first one does.** A "Rate on Google Play"
  button under five stars that do exactly that asks twice.

## The marks

One shape per job, at one weight. Take them from the app's own outline icon set.

| Where | Mark |
|---|---|
| A row that navigates | chevron pointing forward |
| Email button | envelope | <!-- part:ask -->
| Website button | globe | <!-- part:ask -->
| Google Play button | Google Play's own four-colour mark, from Google's brand resources — never redrawn | <!-- part:more_apps -->
| Rating | five hollow stars | <!-- part:rating -->

Outline weight throughout, one family throughout. A filled glyph beside a hollow
one is the fastest way to make a page look assembled from whatever was to hand.
The Play mark is the single exception to the app's palette and is **never
tinted**: it is a trademark, and an icon slot that paints its content with the
surface's colour would flatten all four of its colours into one.

## What changes per app

A short list on purpose. Read the app's design doc, or its theme file, and take
four things from it:

1. **Every colour** — the ground, the ink, and a warm tone for the stars.
2. **The type scale**, and which style is a heading.
3. **The row it already uses** for "tap to go somewhere".
4. **The button it already uses** for a primary action.

Two rules hold whatever those are:

1. **Reuse the app's own components.** If its settings list has a row, the
   About page uses that row; a page built from new one-off widgets is how two
   screens in one app stop looking related. Reuse the *component*, not a
   container: a card the app has is still a card and still does not belong here.
2. **Keep the app's colour discipline.** Where an app gives colours meanings,
   this page obeys them and adds no new accent. If its palette has no gold for
   the stars, take the nearest warm tone it already has.

## The two assets that fool you

**The app icon.** An adaptive icon is drawn on a canvas bigger than the mark on
it — the safe-zone margin a launcher masks away. Drawn plainly it arrives with a
ring of transparent air that reads as a hole, and no spacer around it fixes that,
because the air is inside the picture. Measure the mark in the vector's own path
data, then draw the canvas at `mark_size × viewport / mark_height` inside a box
the size of the mark, and let the margin overflow. A mark running 21→87 of a 108
viewport, wanted at 72dp, needs a 118dp canvas. In Compose that overflow needs
`requiredSize`, not `size`, or the box's constraints shrink it back.

**No tile behind it** — not the icon's own background layer, not a rounded plate.
A filled tile is a card. That leaves two layers, and which one is a contrast
question, not a matter of taste:

1. **The foreground alone**, where its artwork carries its own colour and that
   colour reads on both of the app's grounds.
2. **The monochrome layer, tinted with the page's ink**, where the foreground
   was drawn for the icon's own background and disappears without it — a
   near-black foreground on a dark theme is the same colour twice. The
   monochrome layer is that shape with the colour taken out, so it takes the
   page's ink and reads on both themes.

Check the foreground against the app's darkest **and** lightest surface before
choosing. Both layers carry the same margin, so size either off the mark.

**The photo.** One square image, centre-cropped to a circle, never letterboxed
into it. 256px is enough for a 46–52dp avatar. Take it from `{{studio.photo}}`
and store it density-independent (`drawable-nodpi` on Android, a single asset in
Flutter).

## Behaviour

| Control | Does |
|---|---|
| Any star | the app's own Play listing: `market://details?id=<package>`, then `https://play.google.com/store/apps/details?id=<package>` | <!-- part:rating -->
| Maker row | `{{studio.portfolio}}` | <!-- part:maker -->
| Email button | `mailto:{{studio.email}}`, with a subject naming the app | <!-- part:ask -->
| Website button | `{{studio.website}}` | <!-- part:ask -->
| Google Play button | `market://dev?id={{studio.play_developer_id}}`, then `https://play.google.com/store/apps/dev?id={{studio.play_developer_id}}` | <!-- part:more_apps -->
| Privacy, Terms | `{{studio.privacy_url}}`, `{{studio.terms_url}}` | <!-- part:footer -->

Every one of these hands the user to something the app does not own, so every
one can fail: no mail app, no browser, no Play. Fail in silence — there is no
second way to do any of them, and a toast saying the phone has no email client
helps nobody.

For when a rating is *asked for* rather than offered here — the prompt at a
good moment, and what happens after a low score — see `mkit guide review`.

## Strings

Every line except the studio's own names is translated into all of the app's
locales in the same change that adds it. An About page that is half English is
worse than one that is plainly smaller. These stay untranslated
(`translatable="false"` on Android): the developer's name, the studio name, the
website's address, and `Google Play` — a product name Google requires to be left
in English.

## In Flutter

The same spine maps onto the app's own widgets: `package_info_plus` for the
version, `url_launcher` for every row in the behaviour table, the launcher icon
from the app's own asset, and the app's existing section header, list row and
button widgets for everything below the centred block.

## Checklist for a new app

1. Set `[studio]` and `[about]` once; check them with `mkit guide about`.
2. Read the app's design doc and take the four things above from it.
3. Build the spine with that app's components — no new widgets unless the app
   genuinely lacks one, and no cards.
4. App icon sized off its own artwork; photo cropped to a circle.
5. All strings in every locale the app ships.
6. Wire the behaviours; let each fail silently.
7. Check it in the app's light and dark themes, and in its right-to-left locale
   if it has one.
