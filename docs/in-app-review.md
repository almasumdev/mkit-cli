# In-app reviews

How an app asks for a rating: at what kind of moment, with what limits, and the
rules Google Play enforces around its own card. The decision logic and the
limits are the same for every app; each app writes the code in its own stack
and names its own value moment. Read it with `mkit guide review`.

The core rule:

```text
Google Play decides whether this user sees a rating card, and whether it counts.
Your policy decides only when it is worth spending the one chance you get.
```

Never reverse that order, and never try to decide who is allowed to rate.

## The rule that binds the card

The obvious design — five stars in the app, 5 goes to Play, fewer opens a
feedback form — is **prohibited**. Google's In-App Review guidelines:

> "Your app shouldn't ask the user any questions before or while presenting the
> rating button or card, including questions about their opinion (such as 'Do
> you like the app?') or predictive questions (such as 'Would you rate this app
> 5 stars')."

And the ratings policy forbids influencing which ratings get left, which is
what sending only the happy users to the store does. So:

- **The card is never preceded by a question**, a star widget or a condition of
  any kind. Nothing is gained by trying: the card reports nothing back, so
  gating it cannot even be measured. The usual punishment is not a takedown —
  the card quietly stops appearing.
- **No star control of the app's own routes by the star pressed.** Every star
  goes to the same place. Apple bans the pattern outright, so a gated screen
  also blocks the iOS release of it.

Three more things the API will not do, so no design may assume them:

- **No prefill.** The star rating and the review text cannot be set. The card
  is drawn by Play and must be surfaced "as-is, without tampering or modifying
  the existing design in any way".
- **No result.** "The API does not indicate whether the user reviewed or not,
  or even whether the review dialog was shown."
- **No lookup.** Nothing tells the app whether this user has already reviewed.
  The Play Developer API's review list (`mkit reviews list`) carries author
  display names that cannot be matched to an install.

Play itself handles repetition: it enforces a per-user quota and knows who has
already reviewed, and for those users the card shows their existing review or
does not appear. So asking again never pesters anyone — it wastes the one slot
you had. **Your limits exist to spend that slot well, not to protect the user.**

**Everything the app shows here is a dialog, not a bottom sheet.** A sheet is a
surface you drag, park half-open and dismiss by flinging — right for choosing a
thing from a list, wrong for a question with a few answers, where a
half-dismissed panel leaves the question unanswered and the state ambiguous. A
dialog is modal, centred, and gone the moment one of its buttons is pressed.

## Where this lives: four surfaces, and no others

| Surface | Trigger | Goes to |
|---|---|---|
| **The card** | a value moment with every threshold met | Play's card. Nothing asked before it, ever, and never fired from a button |
| **Settings row** | the whole row, one tap | the Play listing |
| **About stars** | any star | the Play listing (see `mkit guide about`) |
| **`Send feedback` row** | one tap, always available in Settings | the mail composer, directly |

Three of those carry a rating; the fourth is the way to tell you something is
wrong, and it is listed here because it sits in the same bank and gets
forgotten otherwise. Nothing else in the app offers to rate.

**The Settings row**, replacing any "Rate us" row:

| | |
|---|---|
| Title | `{{about.rating_heading}}` |
| Subtitle | `Rate us ★★★★★ on Google Play` |
| The stars | drawn **inside that sentence**, between "Rate us" and "on", in the app's gold, at the line's own size. Filled, and **not tappable** |
| Tap | the whole row, one target → the Play listing |

The stars sit in the sentence rather than beside it. Off to one side they read
as a control somebody is meant to press; in the line they read as the word they
replace. They are a picture of what the row is for, the way an envelope beside
*Send feedback* is a picture. A row that is both a link and a rating widget has
two answers to one press, and a thumb finds the wrong one.

**Drawn, never written.** `Rate us 5 stars on Google Play` in words is the
phrasing Google's own guidance quotes back as the thing not to say. Nowhere in
this flow does any string contain the number.

**The Share row** goes with it, since it sits in the same bank:

| | |
|---|---|
| Title | `Recommend <App>` |
| Subtitle | `Send it to someone who'd use it` |
| Tap | the platform's share sheet, unchanged |

**The `Send feedback` row** is always visible and opens the mail composer
described below. It is not optional: it is the only way to report a problem
that does not go through a rating. It is separate from the About page's
`{{about.email_button}}`, which reads as commercial rather than as "something
is wrong".

## The feedback mail

One composer, identical from wherever it is reached:

```text
To:       {{studio.email}}
Subject:  <App> feedback
Body:     <blank line for the user to write in>
          ---
          <App> 1.0.21 (22)
          Android 15 (API 35)
          <manufacturer> <model>
```

The lines under the rule are the ones you would otherwise have to ask for.
Nothing else goes in: no logs, no identifiers, no account details.

### Let them pick the mail app

Always show the chooser. `ACTION_SENDTO` with a `mailto:` URI, handed straight
to `startActivity`, goes wherever the phone's saved default points — usually
Gmail, and usually not the account somebody wants to write from. Wrapping it
takes one call and asks every time:

```kotlin
val mail = Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:$STUDIO_EMAIL")).apply {
    putExtra(Intent.EXTRA_SUBJECT, subject)
    putExtra(Intent.EXTRA_TEXT, body)
}
leaveTo(Intent.createChooser(mail, chooserTitle))
```

The `mailto:` filter still does the filtering, so the sheet holds mail apps and
nothing else, and the extras survive it. On a phone with exactly one mail app
the sheet has one row in it; that extra tap is the price of never guessing
wrong.

**Declare the query, and hide the row without one.** From Android 11 the app
cannot see which apps handle `mailto:` unless the manifest says it may:

```xml
<queries>
    <intent>
        <action android:name="android.intent.action.SENDTO" />
        <data android:scheme="mailto" />
    </intent>
</queries>
```

With that, `resolveActivity` answers honestly and a device with no mail app can
have the `Send feedback` row left out. Without it the chooser opens onto "No
apps can perform this action" — a dead end shown to somebody who was trying to
help.

**Flutter needs a plugin for this.** `url_launcher` hands the `mailto:` URI to
the platform default and offers no chooser: use `android_intent_plus` with
`ACTION_SENDTO` and `createChooser`, or a small platform channel. Do not reach
for `ACTION_SEND` with `message/rfc822` to get a sheet — it pulls in Drive,
Bluetooth and whatever else claims the type.

## When to ask

**Only at a value moment** — the app's own definition of the user having got
what they came for. One per app, named in code, never "on launch". Some shapes
it takes:

| Kind of app | Value moment |
|---|---|
| a list or planner | a list actually used: a trip finished, the last item ticked |
| a scheduler | a schedule the app really fired |
| a player | a session played through |
| a remote or controller | a device connected and driven |
| a tracker | a record saved complete, with its dates |

**Never ask when** any of these is true:

- first session, or onboarding not finished
- fewer than `review_min_days_installed` days since install
- an error, crash or failed operation happened this session
- any dialog, sheet or keyboard of the app's own is open, or a task is mid-flight
- the app updated in the last 24 hours
- the user already rated, opted out, or was sent to the listing by a Rate row

**Thresholds**, all tunable from Remote Config, all with compiled defaults:

| Key | Default | Why |
|---|---|---|
| `review_enabled` | `true` | a kill switch that needs no release |
| `review_min_sessions` | `5` | three is eager; the app should be a habit |
| `review_min_days_installed` | `3` | a day-one rating is a guess |
| `review_min_value_events` | `2` | once could be an accident |
| `review_cooldown_days` | `120` | Play's own quota is roughly monthly and undocumented |
| `review_max_per_year` | `2` | a ceiling regardless of everything above |

Remote Config is free at small-studio scale: 100,000 fetches per day per
project on the no-cost plan, against six parameters and a 12-hour client fetch
interval. The defaults are compiled in, so a cold start with no network behaves
correctly.

The thresholds do **not** go in the Firestore `config/app` document: that one is
only read when Play says an update exists (see `mkit guide update`), and these
are needed on sessions where it does not.

## State the app keeps

In backed-up preferences, so Android Auto Backup carries them across a
reinstall and a returning user is not asked from zero:

| Key | Holds |
|---|---|
| `review_session_count` | sessions since install, incremented once per process start |
| `review_value_events` | value moments reached |
| `review_last_asked_at` | when the flow was last launched cleanly |
| `review_asks_this_year` | asks in the trailing year |
| `review_opted_out` | the user pressed `Never` in the fallback dialog. Nothing automatic asks again |

A clean `launchReviewFlow` counts as **asked** — it is the only signal there is.
So does every manual path: the Settings row, the About stars, and the feedback
mail. Somebody who has just written to complain must not meet a rating card a
week later. An app with accounts may keep this state on the user's document
instead, which survives device changes; an app without accounts should not
build that.

## Fallback, when there is no card

No Play Services, a sideloaded build, an old device: the request fails. Then,
and only then, the app shows its own **dialog** — the About page's rating bank
in a dialog: the same heading, the same line, the same five stars, and every
star goes to the listing.

What it adds is **two ways out**: `Not now` and `Never`. The About page is a
page somebody chose to open, so ignoring it costs nothing; this arrives
unbidden after a value moment, and a rating prompt with no way to decline is the
"forced prompt" the ratings policy names outright — and one that can only be
declined *this time* is a promise to come back. `Not now` starts the cooldown;
`Never` sets `review_opted_out` and ends it for good. Both count as asked. The
manual routes stay: somebody who pressed `Never` can still rate from Settings
or the About page, because those are theirs to press, not yours to show.

Nothing is asked before the stars, here or anywhere: no "how are we doing", no
thumbs, no question at all.

Errors are never shown to the user and never change the app's flow. The card
failing to appear is normal.

## Per stack

| Stack | Use |
|---|---|
| Flutter | `in_app_review` — `isAvailable()`, then `requestReview()` |
| Native | `com.google.android.play:review:2.0.2` (+ `review-ktx`) |

Request `ReviewInfo` only once the app is certain it will launch the flow: it
is valid for a limited time. Launch it from a resumed Activity, never from a
background task.

## Testing

- **Internal test track** is the only real test: a tester account, primary on
  the device, app installed from Play, no existing review. Quota is not
  enforced there. After the first install from the track, local builds work.
- **Internal app sharing disables review submission** — the button is greyed.
  Fine for checking that the card appears, useless for the rest.
- **`FakeReviewManager`** fakes the API with no UI, for tests only.

## Measuring it

Completion cannot be measured, so do not try. Log `review_flow_requested`,
`review_flow_launched` and `review_flow_unavailable` to Analytics, and read the
outcome in aggregate: `mkit stats` and `mkit reviews list` against the dates the
thresholds changed. One threshold change at a time, or the numbers say nothing.

## How an app adapts this

Three layers, and only the first is the app's own invention.

### 1. The value moment — code, one call, per app

Nothing outside the app knows that a schedule fired or a list got finished, so
this layer cannot be configured from anywhere. The app calls one function from
the places it names as its value moment:

```text
onValueMoment()   ← called where the user got what they came for
```

One function, however many call sites. It increments the counter and, when
every threshold passes, asks for the card. Nothing else in the app knows about
reviews. A moment that fires on launch, on a screen opening, or after an error
is not a value moment, whatever it is called.

### 2. The thresholds — `remoteconfig.template.json`, per app repo

Named by `remote_config` in the app's `mkit.toml`. The six keys carry **the same
names in every app** and whatever values suit that app:

```json
{
  "parameters": {
    "review_enabled":            { "defaultValue": { "value": "true" } },
    "review_min_sessions":       { "defaultValue": { "value": "5" } },
    "review_min_days_installed": { "defaultValue": { "value": "3" } },
    "review_min_value_events":   { "defaultValue": { "value": "2" } },
    "review_cooldown_days":      { "defaultValue": { "value": "120" } },
    "review_max_per_year":       { "defaultValue": { "value": "2" } }
  }
}
```

`mkit remoteconfig plan` shows the drift between that file and what is live;
`mkit remoteconfig apply` publishes it; `mkit remoteconfig pull` brings a
console edit back into the repo. The file is versioned with the app, so the
thresholds a build shipped under are in its history.

**Different values per app are expected.** An app opened daily earns its ask
sooner than one opened when a warranty expires: five sessions is a week in one
and might be a year in the other. Tune the values, never the key names — a key
spelled differently in one app is a key nobody will remember to change.

**An app with no Firebase** ships the compiled defaults and nothing else. That
is a working app, not a broken one; it just cannot be retuned without a release.

### 3. Everything else — copied, not decided

The surfaces, the fallback dialog and its actions, the Settings rows, the mail
and its chooser, the strings. None of it is per app, and an app that has
"adapted" any of it has drifted rather than adapted. What an app changes is what
`mkit guide about` lists: colours, type, and the row and button it already has.

## The checklist

An app has finished this work when all six are true.

1. **The card** fires at a value moment, behind the thresholds, asking nothing
   first, never from a button.
2. **The Settings rating row** reads `{{about.rating_heading}}` / `Rate us ★★★★★
   on Google Play`, the stars drawn inside that sentence and not tappable. The
   whole row is one tap to the listing.
3. **A `Send feedback` row** sits in the same bank, always visible, opening the
   mail composer directly — its own row, with its own words.
4. **Every star the app draws goes to the listing** — the About page and the
   fallback dialog alike. No star routes by its number.
5. **The fallback dialog** appears only when the card cannot, offers `Not now`
   and `Never`, and is a dialog. Nothing in this flow is a bottom sheet.
6. **The mail** carries the app version, Android version and device, and opens
   through a chooser.
