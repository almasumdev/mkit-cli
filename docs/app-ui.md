# App UI foundations

This decides how an app is organised, never how it looks: where colours
live, how Pro is marked, what a picker does, how Settings is put together. No
colour value (except Pro's gold) and no size of the app's look is set here;
each app keeps its own palette, type, shapes and components. A studio whose
apps share one look keeps that look in its own rules beside this guide.

Read this before adding a colour, a Pro mark, a settings row or a picker to
any app. Read it with `mkit guide ui`.

## Colours from one place

Every colour an app draws is defined in its theme folder and nowhere else.

| Kind | Where |
|---|---|
| Follows the theme and palette | the palette file: one complete set per palette, light and dark |
| Never changes with the theme | `fixed_colors.dart` (or the native app's equivalent) |
| The framework's own (Material `ColorScheme`, Compose `ColorScheme`) | mapped from the palette set by the theme builder |

Widgets read colours through the app's token accessor (a context extension in
Flutter, a `CompositionLocal` in Compose) and the framework's widgets get them
through the colour scheme the builder maps them into. A widget never writes a
colour literal: in Flutter no `Color(0x…)`, `Color.fromRGBO`, `Color.fromARGB`
or `Colors.<name>` (only `Colors.transparent`); in Compose no `Color(0x…)`.

**The rule is a test, not a convention.** Each app carries one that walks its
source, skips the theme folder, generated files and comment lines, and fails
on any colour literal, naming the file and line. Write it once and copy it to
each app, changing only the folder name.

**One complete set per palette.** Every palette, in light and in dark, is one
full colour set: the ground, the inks from strongest to faintest, the card,
the lines, the primary fill and the ink on it, the icon tile and its glyph,
the accent and its soft wash, danger, the warning colour, and whatever else
the app draws with (a receipt's paper, a panel's gradient). The theme builder
and the token class only map that set; neither writes a colour of its own. An
app with one palette has one set per brightness, and the same rule.

**Two inks for the primary colour.** A primary colour dark enough to carry
white text as a button is often too dark to read as text on a dark ground.
So a set carries an ink for the primary colour used as text or an icon (a
price, a check, a cursor, a focused field, a text button), and one for the
glyph on an icon tile, separate from the fill. Fills (buttons, switches, a
selected dot) keep the primary. Where the two are the same colour, the set
simply says so twice.

What goes in `fixed_colors.dart`, and nothing else: the brand (a mascot, the
intro slides), Pro's gold, other companies' marks in their own colours,
shadows and scrims, and colours fixed by what they sit on (white on a red
swipe, ink on a photo). A colour that ought to change with the palette is in
the palette set, even if today it happens to be the same in every palette.

## Pro's mark

Pro is the studio's product, so its mark is the same in every app: **one
crown, drawn, in one gold.**

- **The shape** is one crown, drawn in code on a 24-unit
  grid, never an icon font's crown (`workspace_premium` and the like): three
  points with round tips over a band, solid, one colour, the jewel and the gap
  above the band cut through it (even-odd).

  ```text
  body (even-odd):  M3.6 8.2 7.7 11.7 12 5.4 16.3 11.7 20.4 8.2 18.7 16.2H5.3Z
                    M12 11.2 13.6 13 12 14.8 10.4 13Z
  tips:             circles r1.6 at (3.6, 6.9) and (20.4, 6.9), r1.7 at (12, 3.9)
  band:             rounded rect 4.8,18 → 19.2,20.8, corner 1.4
  ```

  One component per app draws it: an icon widget in Flutter, a composable in
  Compose.
- **The colour** is Pro gold — this guide uses `#E3A93C` — a fixed colour, the same in light
  and dark and in every palette: a mark of the product that changed with the
  theme would read as two marks.
- **The tag** beside anything the free plan lacks is an outline, never a
  fill: the crown and the word `PRO` in gold inside a gold-outlined pill, in
  the app's own type. Shown only while Pro is not owned.
- **Where the crown stands alone:** a locked colour theme's swatch, a locked
  action's icon, the Pro screen's header, in gold. Inside a filled button it
  takes the button's own ink instead. On a row whose other rows have icon
  tiles, it sits on the row's usual tile in the tile's glyph colour, so it
  lines up with the rest.

## Settings

- **Groups under section headers.** Rows that belong together form a group;
  groups sit under short section headers in the app's own style.
- **The Pro row** comes first, on its own, with the crown as its icon.
- **The rating, share and feedback rows** are those of `mkit guide review`;
  the update row and the version line at the very foot are those of
  `mkit guide update`.
- **An app with colour themes** puts the light/dark choice and the colour
  choice together, one after the other in the same place. A locked colour can
  be tried on before buying; leaving Settings ends the try-on.

## Picker sheets

A choice from a list (a language, a currency, a list to move to) is a
**bottom sheet**; a question with a few answers is a dialog
(`mkit guide review`).

- **One frame** for every sheet in the app: its handle, its title, its body.
  One component, not one per sheet.
- **A long list has search.** Any picker with more than about a dozen
  choices (languages, currencies) opens with a search field and stays clear of
  the keyboard. Matching: a language by its own name, its English name or a
  code prefix; a currency by code, sign, name or country. Nothing found is one
  plain line saying so, not an empty sheet.
- **The chosen row is marked one way in every picker** of the app, in its own
  colours (a wash, a check, a bolder title: whichever the app chose, the same
  everywhere). Two pickers that mark it two ways is the bug.
- Tapping a row applies it and closes the sheet; there is no Done button.

## Checklist, every app

1. No colour literal outside the theme folder, and the test that proves it.
2. One complete colour set per palette and brightness; the builder only maps.
3. Pro gold in `fixed_colors.dart`, the drawn crown everywhere Pro is marked,
   no icon-font crown left, and the Pro tag an outline.
4. Language and currency pickers search, and every picker marks the choice
   the same way.
