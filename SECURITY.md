# Security

mkit handles credentials that can publish to Google Play and write to Firebase,
so a bug here can be worth more than the tool is.

## Reporting

Use GitHub's private advisory form:
[Report a vulnerability](https://github.com/almasumdev/mkit-cli/security/advisories/new).
Please do not open a public issue for anything that exposes a secret or lets a
command publish without confirmation.

Expect a first reply within a week.

## What counts

- A credential reaching output, a log, an error message or a crash trace.
  Secrets are read through `secrets.Secrets`, which registers each one for
  masking; anything that escapes that is a bug of this kind.
- A `publish`-class command running without `safety.confirm`, or confirmation
  being bypassable. Those commands change what users and Play reviewers see.
- A path taken from `mkit.toml`, a listing file or a Play response being used to
  write outside the project.
- Anything that uploads a build, changes a listing or alters Remote Config
  without the operator asking for it.

## What does not

- `mkit doctor` naming which credential is missing. That is deliberate: it
  prints the key's name and never its value.
- Anything requiring an attacker to already have your service account JSON.
- The Play Console steps mkit cannot do (`mkit manual`) — those are Google's
  surface, not this tool's.

## For users of mkit

Credentials belong in `.env` (per app) or `~/.mkit/.env`, both gitignored —
`mkit init` sets that up and never overwrites an existing `.env`. Nothing
sensitive should ever reach `mkit.toml`, which is committed.
