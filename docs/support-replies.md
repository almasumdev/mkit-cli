# Support replies

How an app answers its users by email, from
`{{studio.email}}`. The shape is fixed so every reply reads as one studio,
whichever app and whoever writes it. Read this before drafting any reply to a
user's mail, review or feedback.

## The rules

- **Plain text.** No bold, no headings, no emoji, no HTML, no tables. Mail
  clients and phones show plain text the same everywhere. A list is lines
  starting with `- `; steps are `1.`, `2.`.
- **One paragraph per line.** Do not wrap lines by hand; the mail app wraps
  them for the reader's screen.
- **The user's language.** Reply in the language they wrote in. If they mixed
  two, use the one their question is in.
- **In the same thread.** Reply to their mail, so the subject stays
  `Re: ...` and they see the history. A new subject only for a mail we start.
- **Answer every point, in their order.** Each point gets its own line or
  paragraph: what they asked, then what is true now. Nothing they raised is
  skipped.
- **Only what is true.** "Available now" only once it is in production on
  Play. Before that: "in the next update, coming in the next days". Never a
  date that is not certain, and never a feature that is not planned; for those,
  "noted for a future update".
- **The app's own words.** Feature names as the app shows them in that
  language (the app's translation files), never internal terms: no schema,
  manifest, sync pass, track, build number.
- **Warm and short.** Plain sentences, at most one exclamation mark, under
  about 200 words unless they need steps. No "we apologise for any
  inconvenience" or "your feedback is important to us"; say the specific
  thing instead.
- **House punctuation.** No em or en dashes as punctuation, no arrows, no
  decorative characters.
- **Privacy.** Never ask for a password or a code. Ask for the app version or
  phone only when it is not already in their mail (the app's feedback mail
  adds both). Never repeat their personal data back to them.
- **A bug.** Say what is wrong in their terms, what happens next and when it
  is fixed. Ask at most one specific question, if one is needed to fix it.

## Asking for a rating

Only when their problem is solved and they are happy, and never as a
condition: no "if you rate us", no reward, no asking for a particular star
count in exchange for anything (Play's policy on manipulated ratings, the same
line `mkit guide review` draws in the app). One sentence,
with the app's Play link, after the answers:

```text
If everything works well for you, a 5-star rating on Google Play would mean a lot to us and helps other people find the app: https://play.google.com/store/apps/details?id=<package>
```

Never ask someone who is still having a problem, or who is unhappy.

## The shape

```text
Hello <first name, as they signed>,

Thank you for <the specific thing they did: your detailed feedback, the clear steps, your patience>.

<One line or paragraph per point they raised, in their order. A list when there are several:>
- <their point, in their words>: <what is true now, or what happens next>.
- ...

<Only when solved and they are happy:> If everything works well for you, a 5-star rating on Google Play would mean a lot to us and helps other people find the app: <Play link>

Any more feedback is always welcome. Just reply to this mail; every message is read.

Kind regards,
{{support.signoff}}
{{studio.email}}
```

The sign-off is the same for every app: the app's name, the studio, and the
address — set once as `[support] signoff`. The closing words ("Kind regards",
"Viele Grüße", "Cordialement") follow the reply's language.
