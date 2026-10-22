# News and offers

The occasional notification to a group of users (a new feature, an offer, a
note to everyone on an old version) is sent from the Firebase console
(Messaging, "New campaign" > "Notifications") to FCM topics. No backend and no
per-user data: the phone joins topics, the console picks them. Value Guard
and ListKin do it this way; every app should, so a campaign is aimed the same
way everywhere.

## Fixed in every app

**Topics.** A phone with news on is in exactly these:

| Topic | Who |
|---|---|
| `news_all` | everyone |
| `news_free` / `news_pro` | by whether it has Pro (an app without Pro: `news_all` and the language only) |
| `news_lang_<code>` | the app's own language code, anything outside `[a-zA-Z0-9_]` turned to `_`: `news_lang_en`, `news_lang_bn`, `news_lang_zh_CN` |

The console sends to one topic per campaign. To combine them, e.g. free users
who read English (`'news_free' in topics && 'news_lang_en' in topics`), send
through the FCM HTTP v1 API with a `condition`. Write each language's message
to its own language topic; there is no translation on the phone.

**Keeping them right.** The phone works out the topics it should be in, keeps
the ones it joined in its preferences, and joins or leaves only the
difference, again whenever something they depend on changes (the switches, Pro,
the app language, signing in or out where the app needs an account). A topic
it could not join or leave (offline, no Play services) is tried on the next
change or start. A run while one is going makes it look again once done.

**The switch.** "News and offers" in Settings, on by default, as its own row
beside the app's other notification setting. Off, or the app's notifications
off, leaves every topic. Other notifications (reminders, household alerts)
never use topics and are never affected by it.

**The channel.** `news_offers`, created by the app with a name and description
in the app's language, and set as FCM's default channel in AndroidManifest.xml
(`com.google.firebase.messaging.default_notification_channel_id`), so a
console message, which names no channel, never lands among the app's own
alerts. Default importance.

**Showing it.** Android shows a console message itself while the app is in the
background; one that arrives while the app is open is shown by the app, on the
same channel. A background message handler returns at once for a message with
a `notification`: there is nothing to draw or sync for news.

**Tapping it.** The custom data key `open` says where a tap leads. `open = pro`
opens the app's Pro screen; anything else, or none, just opens the app. A tap
that starts the app waits until the home screen is up before opening anything.

**Privacy.** The app's privacy policy says it: the phone joins a few
notification groups (everyone, free or Pro, the app's language) when News and
offers is on, no other data is used, and turning it off leaves them.

## Per app

Only the code in its own stack (where the switch lives, how Pro and the
language are read, how Pro opens) and the wording of the switch in its
catalogs.

| App | Where |
|---|---|
| Value Guard | `lib/data/news_topics.dart`, `lib/data/notification_service.dart` |
| ListKin | `lib/services/news_topics.dart`, `lib/services/notification_service.dart` |
