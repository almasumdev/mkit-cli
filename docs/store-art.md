# Store art

Every app's Play screenshots and feature graphic are built the same way: real
phone captures, placed in phone frames on the app's own colours, with a
headline and a line of text in the app's own font, in every listing language.
`mkit art build` draws them; `mkit listing apply --images-only` uploads them.

Only what makes an app's art its own lives in the app. The templates, the
drawing and the checks live here, so a fix or a better layout reaches every
app at once.

## What is shared, what is the app's

| Shared (the engine, `mkit/art.py`) | Per app (committed in the app repo) |
|---|---|
| The page templates in two layouts (classic and pop, below): a 1920x1080 landscape hero, 1080x1920 slides with one phone, the 1024x500 feature graphic, and their backdrop | `store/art/shots/*.png`: the raw phone captures |
| The phone frame and a clean 9:41 status bar | `store/art/captions/<code>.json`: the words, one file per listing language |
| Right-to-left mirroring, fonts for every script, line-breaking rules | `store/art/art.toml`: the layout, which slides, which capture each shows, what to erase, colours, font, mascot, backdrop, and (pop) where each pill and picture goes, plus the pictures themselves |
| The line-count check and the caption rules | `[art]` in `mkit.toml` (switches the commands on) |

The built images are not committed. They are rebuilt from the files above in
a few minutes, on any computer, so git keeps only what is needed to make them.

## Setting an app up

```
mkit art init
```

It writes only what is missing:

- `store/art/shots/`, `store/art/captions/en.json` and `store/art/art.toml`
  from starter files, with every option explained in comments,
- `[art]` in `mkit.toml`,
- two lines in `.gitignore`, so the built images stay out of git:

```gitignore
# Store art built by `mkit art build` (sources: store/art)
/store/screenshots/
/store/feature/
```

The images go where `mkit listing` reads them, under `[store] art_dir`
(default `store`): `screenshots/<code>/01_<slide>.png ...` and
`feature/<code>.png`. If an app keeps its art elsewhere, set `art_dir` before
`init`, and the ignore lines follow it.

Then fill in `art.toml` (font, mascot, slides), add the captures and write
`captions/en.json`.

## Captures

Take them from the real app on a phone, never mock them up.

```
adb exec-out screencap -p > store/art/shots/home.png
```

- 1080x2340 PNG (a 19.5:9 phone at 1080 wide). Other sizes are refused.
- Use demo data that looks lived-in: real brand names, several states
  (active, expiring, expired), no test strings.
- Show the full app. If a feature is paid, turn the paid version on in the
  debug build so nothing shows a lock, crown or Pro badge. Screenshots show
  what the app does, not what it costs.
- Take everything in the light theme, plus one dark screen for a dark slide.
- The status bar is tidied by the build, so the notification shade needs no
  tidying. `[status_bar] mode = "redraw"` (the classic default) erases the
  phone's own icons and draws a 9:41 bar over the capture. `mode = "clean"`
  (the pop default) keeps the capture's own bar but paints out everything on
  it in the colour at `sample` (capture pixels, default `[540, 60]`) up to
  `height` (default 96), then draws a 9:41, signal and battery into it in the
  app font: dark ink on a light bar, light ink on a dark one.
- Anything private (an account name, an email address) is erased by listing
  its box under `[shots.<name>]` in `art.toml`, as `[left, top, right,
  bottom]` in capture pixels. Keep the capture itself unedited, so replacing
  it later is only a new capture.
- Put the phone's settings back afterwards: theme, demo data, the paid switch.

A capture of the app in another language goes in `shots/<code>/<name>.png`
and is used for that language instead of the English one.

## Slides

Play shows up to 8 phone screenshots. The usual set:

1. A landscape hero (`kind = "landscape"`): the app's name and mascot, the one
   line that says what it is, three short feature chips, and three phones.
   Play shows a landscape first image large, so it is the store's banner.
2. The main screen: what the app is for, at a glance.
3. The reminder or notification, if the app has one (`notify = true` puts a
   notification card, with the app's real notification text, over the phone).
4. to 7. One job each: the detail page, the thing only this app does,
   settings that make it personal.
8. One dark slide (`dark = true`) with a dark capture.

`offset = <pixels>` on a slide scrolls its capture up, for a screen whose
point is low down. The feature graphic (`[feature]`) shows one capture beside
the mascot, the name, a headline and chips; keep it calm, it is shown small.

## Layouts

`layout` at the top of `art.toml` picks the page design. Every app gets the
same choice; nothing about one app's look is in the engine.

**classic** (the default): a soft gradient, the headline and a line of text
over one phone, contour rings or leaf sprigs behind (`decoration`). The hero
has three phones (`shots = [left, front, right]`), the feature graphic one
(`[feature] shot`).

**pop**: a vivid ground (a radial glow, soft light and dark blobs, a halo and
ring behind the phones, faint sprigs, a dot texture fading down the page),
short bold titles with a hand-drawn underline under the `[bracketed]` word,
big phones, and pills and pictures the app places itself.

- Portrait slides: the title alone at the top (two lines at most in the
  reference; a `\n` in the title breaks the line where you want it), one big
  phone cropped at the bottom of the page. A `sub` is optional; leave it out
  for the plain look.
- The hero: two or three phones fanned on the left (`shots`), the mascot, the
  name, the title and the chips on the right.
- The feature graphic: the mascot, the name and the title on the left, two
  phones on the right (`[feature] shots = [back, front]`, or one `shot`).
- `dark = true` slides stand on the dark ground (`[theme.dark]`).
- `notify = true` puts the notification card (captions `notify`, the mascot on
  an accent tile) over the phone at `notify_y` (page pixels, default 600).
- `decoration` does nothing in pop; it has its own ground.

Pills and pictures are placed in page pixels (left, top), so the app decides
exactly where they go. Right-to-left pages mirror them: the distance from the
left becomes the distance from the right, and the tilt turns the other way.

```toml
[[slide]]
id = "helper"
shot = "helper"

[[slide.pill]]          # a white pill with a tick
text = "Lemons"         # literal, never translated: it names an item on the capture
x = 40
y = 1130
size = 50               # font size in px (default 44)
rotate = -5             # degrees (default 0)

[[slide.pill]]
key = "add"             # captions: helper.pills.add, so it is translated
go = true               # the green action pill
x = 380
y = 1740
size = 54

[[slide.art]]           # a picture from the app repo, PNG or SVG
src = "store/art/helper.svg"
x = 760
y = 360
height = 240            # px; the width follows
rotate = 10
z = 6                   # stacking (default 4; phones are 1 and 2, pills 5)
```

The hero slide takes the same `[[slide.pill]]` and `[[slide.art]]`; the
feature graphic takes `[[feature.pill]]` and `[[feature.art]]` (keys from
captions `feature.pills`).

Pop colours are keys under `[theme.light]` and `[theme.dark]`, all optional:
`bg1`, `bg2`, `bg3` (the ground, top to bottom) and `bg_mid` (where `bg2`
sits, in percent), `blob_dark`, `blob_light`, `glow` (halo, ring, sprigs,
dots, chip glass), `ink` (titles, name, chips), `title_shadow`, `underline`,
`accent` (ticks, go pill, notification tile), `pill`, `pill_ink`, `shade`
(every shadow, at its own strength) and `phone` (the frame). The starter
`art.toml` lists them with their defaults.

## Captions

`captions/<code>.json` has a block per slide id, plus `feature`. The codes are
the listing codes in `[store.locales]`, so each file reaches every Play locale
its listing does.

- A headline is a benefit, not a feature name, in a few words. Put the key
  words in `[square brackets]`: they are drawn in the accent colour (pop:
  underlined). Exactly one bracketed span per headline.
- The line under it (`sub`) backs the headline up in about ten words. Pop
  pages may leave it out.
- Pop pills that are translated live in the slide's block under `pills`
  (`"pills": {"add": "Add 5 items"}`); literal pills in `art.toml` are not.
- Plain punctuation only: no dashes, arrows, bullets or emoji. The check
  refuses them.
- Every claim true of the app as it is; the app's own words for its features.
- The notification uses the app's real notification title and text. A title
  too long for one line ends in "..." as it does on a phone.
- `"dir": "rtl"` for Arabic, Hebrew, Persian and Urdu. The page is mirrored:
  art on the left, words on the right.

## Other languages

Translations are fitted without looking at images:

```
mkit art check            # every language against the reference (en)
mkit art check de ar ja   # some
```

The check lays every page out in the browser and reports each block that
wraps to a different number of lines than the reference, or runs past its box,
and each file whose keys differ from the reference's. Titles, subs, the brand
name, chips, the notification and every pill are measured; a pill that runs
off the page counts as past its box, and a pop portrait title may not pass two
lines. Naming the reference (`mkit art check en`) holds it to its own boxes
and caps. It makes no images and takes a few seconds a language. Write, check, reword until it says OK, then
build. It also lists listing codes that have no captions (they get no art)
and captions no listing uses.

Scripts other than Latin fall back to the system font closest to the app's
(Windows: Bahnschrift for Cyrillic and Greek, Segoe UI for Arabic, Hebrew and
Georgian, Nirmala UI for Indic scripts, Leelawadee UI for Thai, Yu Gothic UI,
Malgun Gothic and Microsoft YaHei/JhengHei UI for CJK). `[script_fonts]` in
`art.toml` or `"font"` in a captions file changes one. Korean breaks only
between words. Chinese and Japanese get their own glyphs from the page's
language. Measure and build on the same kind of computer, since the fonts are
the system's.

## Building and uploading

```
mkit art build            # every language
mkit art build en ar      # some
mkit art build en --keep-pages   # keep the HTML pages to inspect one
```

It needs Microsoft Edge, Google Chrome or a Playwright Chromium
(`uvx playwright install chromium-headless-shell`); it uses the first that
draws a test page, so an Edge waiting for an update restart is passed over.
`browser = "<path>"` under `[art]` names one outright. Then, when the images
should go live:

```
mkit listing plan --images-only
mkit listing apply --images-only    # publish: only on an explicit go
```

## Moving an app over

An app with hand-made art (a storeshot export, a design tool) moves over when
its art next changes: `mkit art init`, captures into `shots/`, slides into
`art.toml`, the words into `captions/`. Delete the old image files from the
repo once the built ones are in place, and any app-local art script.
