# Being found on Play

Everything in the store listing that decides whether anybody ever sees the app.
The files it lives in are `store-listing` territory; this is what to *put* in
them, and how to tell whether it worked.

Two searches matter and they are not the same thing:

```text
Play Store search  ─►  decided by four text fields, then by how the app performs
Google web search  ─►  automatic; the big card is a brand-name result, not a setting
```

## What Play indexes

Four fields, and no others. There is no keyword field — Apple has one, Play
does not, and everything you want found has to live in text a reader also sees.

| Field | Limit | Weight |
|---|---|---|
| Title | 30 characters | heaviest |
| Short description | 80 characters | strong |
| Long description | 4000 characters | moderate, and stuffing is penalised |
| Developer name | — | counts as a match |

**Text only decides eligibility.** Which of the eligible apps ranks above the
others comes from install volume and velocity, retention, rating and review
count, uninstalls, and Android vitals. An app can match a query perfectly and
sit on page four.

That is the join between this guide and `mkit guide review`: a rating and a
review count are search inputs, not vanity. Twenty-three reviews at 4.7 is what
makes an unknown app look installable.

**Every locale is its own index.** An app listed in 17 languages has 17 separate
search surfaces. A title translated for *meaning* rather than for what people type in
that language throws the locale away — the German listing should carry the words
Germans search, not a faithful rendering of the English one.

## The title decision, per app

The one real choice, and it is worth making deliberately rather than drifting
into it:

| Title | Wins | Loses |
|---|---|---|
| Keyword — `Tally: Shared Shopping List` | Play search for the category | nothing, until the brand is worth searching |
| Brand — `Tally` | Google's app card, once people know the name | every query that is not the name |

Google's big card — the rich result with screenshots and an Install button —
appears when a search matches **one app** with confidence. That means it is a
brand-name result: it follows people knowing the name, it does not create them.
Nothing there is configurable, no markup applies, and it cannot be bought.

So the move worth copying from apps that have both is **a name whose words are
also the keywords**: distinctive enough to be an entity, ordinary enough to be
searched. Prefer that to picking a side.

What genuinely helps the web side: the same name used everywhere — the listing,
the studio's site, GitHub, socials — and a page per app on the site that links the
Play listing, so Google can tie a name to a thing.

## Choosing keywords: what is winnable, not what is wanted

The instinct is to rank for the biggest term. The useful question is which page
one is weak enough to break into, which is exactly what `mkit aso score`
answers: it reads the **weakest of the top five apps' install counts** for each
keyword.

```
mkit aso score    # weakest top-5 installs per keyword; counts how many are under 10k
mkit aso rank     # where this app sits now, and which way it moved since last run
```

A keyword whose fifth-place app has 10 million installs is not a target, however
well it describes the app. One whose top five includes something under 10k is a
page you can take with a better listing alone.

Keywords live in `console/aso/keywords.toml` (`[aso] keywords` in `mkit.toml`),
grouped by market, because a term's difficulty is not the same in two countries:

```toml
[[market]]
lang = "en"
hl   = "en_US"
gl   = "US"
keywords = [
  "shared shopping list",
  "family grocery list",
  "shopping list with prices",
]
```

Results save beside the file, which is what makes `aso rank` able to show the
move rather than only the position.

## Finding phrases: `aso research`

The tracked list only holds what someone thought of. `mkit aso research`
finds what people actually type, per market, and scores each phrase:

```
mkit aso research               # every [[market]] in the keywords file
mkit aso research --market DE   # one country
```

- **Found through autocomplete.** Each market's `seeds` are typed into Play's
  own search box, alone and followed by every letter ("grocery list a",
  "grocery list b", ...), which is how the long tail shows itself. Phrases of
  one word, or with none of the market's `topic` words, are dropped. The
  tracked `keywords` are always scored too.
- **demand** (0 to 1): how few letters autocomplete needs before it offers
  the phrase. 1.0 is offered after two letters; 0 is never offered, which
  means few people type it, not none.
- **median top 5**: installs of the middle of the five apps Play shows for
  it. **in titles**: how many of those five carry the phrase in their title.
- **score**: demand a new app can reach, discounted by both. Sort by it.

It is slow on purpose (thousands of requests, paced), and saves
`research-YYYYMMDD.json` beside the rank scans.

```toml
[[market]]
lang = "de"
hl = "de"
gl = "DE"
seeds = ["einkaufsliste", "einkaufszettel", "gemeinsame"]   # default: the keywords
topic = ["einkauf", "liste", "zettel"]                     # default: the seeds' words
keywords = ["familien einkaufsliste", "gemeinsame einkaufsliste"]
```

## The ladder

How a new app climbs, one rung at a time. Text decides which searches the app
is eligible for; installs from those searches are what lift it for the next.

1. **Rung one: long-tail phrases it can be top three for.** High score in
   `aso research`: real demand, a page one of small apps, few exact titles.
   "family grocery list", not "grocery list". Position 40 on a big term is
   worth nothing; nobody scrolls there.
2. **Place them** (below): the best phrase in the title, a second in the
   short description, each three to five times in the long description.
3. **Stage it.** Apply to a few markets first and leave the rest as they are,
   so the rest are the comparison:
   `mkit listing apply --locales de-DE,es-ES` (after `listing plan --locales`).
   For descriptions, a store listing experiment in Play Console splits real
   visitors 50/50; titles cannot be tested that way.
4. **Measure** after two weeks or more: `mkit aso rank`, then
   `mkit aso impact --since <the day it went live>` for store visitors and
   acquisitions per day either side, and the keywords gained and lost.
5. **Keep what won, roll it out, climb.** Once the app is top three on its
   rung and installs rise, the next rung is the mid-tail ("shared shopping
   list"); the head terms come last, months later, with ratings behind them.

One change per round. A title, short and long description changed together
in every market at once can only say that something happened.

## Placing them

- **Title**: the two or three words people type, plus the name. Thirty
  characters, so every word has to earn its place.
- **Short description**: the sentence that appears under the title in search
  results. One more keyword phrase, in a sentence a person would say.
- **Long description**: written for a reader, with the terms appearing naturally
  two or three times. Not a keyword list — Play demotes those, and the first two
  lines are all most people read.
- **Not in the title**: "free", "best", "#1", "no ads" and anything comparative.
  Play's policy on misleading listings is enforced, and a suspension costs more
  than a keyword is worth.

## Judging it

One change at a time, and wait. Play re-indexes in days, but rank moves on
install behaviour that takes longer, so a title changed on Monday tells you
nothing by Wednesday. Two changes at once tell you nothing ever.

```
mkit aso rank                          # before the change, and again a fortnight after
mkit aso impact --since 2026-10-02     # visitors, acquisitions and keywords either side
```

A title change also resets whatever recognition the old one had, so it is a
thing to do rarely and on purpose.

## The checklist

1. `[aso] keywords` set, with a `[[market]]` per country that matters.
2. `mkit aso research` run, and the targets picked from the top of its
   score rather than the ones that sound best (`aso score` for a quick check
   of the tracked list alone).
3. Title: name plus the two or three words that were chosen, inside 30
   characters, no superlatives.
4. Short description: one sentence, one more phrase, written for a person.
5. Long description: natural repetition, the first two lines doing the work.
6. Every locale's text written for what that language searches, not translated
   from English.
7. Staged: `listing apply --locales` for a few markets first.
8. `mkit aso rank` run before the change, again a fortnight later, and
   `mkit aso impact --since` to read the result.
