# In-app updates

Every EazyVerse app checks for updates the same way and shows them the same
way. The decision logic, the Firebase document `mkit config set` writes, and
what the user sees are settled here; each app only writes the code in its own
stack (Flutter or native). Read this before adding or changing update code in
any app. Where it says a thing is fixed, it is fixed in every app.

The core rule is simple:

```text
Google Play decides whether this device can install an update.
Firebase decides how strongly the app should ask for that update.
```

Never reverse that order.

## Why This Order

Google Play knows things the app and Firebase do not:

- which track installed this app: internal, closed, open, production
- whether the user is allowed into that track
- whether the rollout has reached this user
- whether the device can install the new build
- whether Play has finished processing the release

Firebase does not know those things. Firebase is only policy.

If Firebase alone says "latest version is 2.0.0", a production user could be
blocked while 2.0.0 is still only on internal testing. That user would have no
way to update. This is the bug this design avoids.

## Runtime Flow

Use this exact flow:

```text
1. App starts.
2. App asks Google Play for update availability.
3. If Play says no update:
   - do not read Firebase update policy
   - show no update UI
   - clear the local cached update policy
4. If Play says update available:
   - read Firebase config/app once
   - combine Play availability + Firebase policy + current app version
   - show the quiet update icon, the forced update screen, or nothing
5. If Play cannot answer:
   - do not read Firebase
   - replay the last proven cached update decision, if the current app is still
     older than the cached Play-available build
```

## Firebase Document

Firestore document:

```text
config/app
```

Fields:

```text
latestBuild        int     newest published versionCode/build number
latestVersionName  string  newest version name, e.g. "2.0.0"
minSupportedBuild  int     manual floor; 0 means block nobody
nudgeAfterDays     int     wait this many Play staleness days before the update icon appears
```

`mkit config set` writes this document (`--latest` after a release Play has
accepted, `--min-supported-build` for an emergency floor, `--nudge-after-days`
for the icon's delay); `mkit config show` reads it. Release tooling updates
`latestBuild` and `latestVersionName` only after Play accepts the build.

Manual emergency control:

```text
minSupportedBuild = 0    no manual block
minSupportedBuild = 42   builds below 42 are retired, but only if Play can serve an update
```

## Decision Rules

Inputs from Play:

```text
updateAvailable
availableVersionCode
flexibleUpdateAllowed
clientVersionStalenessDays
installStatus
```

Inputs from Firebase:

```text
latestBuild
latestVersionName
minSupportedBuild
nudgeAfterDays
```

Decision:

```text
if Play does not say updateAvailable:
    NONE

if currentVersionCode <= 0:
    NONE

if minSupportedBuild > 0 and currentVersionCode < minSupportedBuild:
    BLOCKED

if Play availableVersionCode can reach latestBuild
and latestVersionName has a higher major than the current app:
    BLOCKED

if Play stalenessDays >= nudgeAfterDays:
    NUDGE

else:
    NONE
```

## Offline Protection Cache

When Play says an update is available and Firebase policy is successfully read,
cache the Play answer and Firebase policy inputs locally:

```text
cachedAvailableBuild
cachedStalenessDays
cachedLatestBuild
cachedLatestVersionName
cachedMinSupportedBuild
cachedNudgeAfterDays
```

Do not cache "blocked" or "nudge" as a verdict. Cache only the inputs.

Why: after the user installs the update, the same cached inputs should release
the prompt or block offline because the current app version now reaches the
cached Play-available build.

Offline decision when Play cannot answer:

```text
if cachedAvailableBuild <= 0:
    NONE

if currentVersionCode >= cachedAvailableBuild:
    clear cache
    NONE

recreate the last proven Play answer:
    updateAvailable = true
    availableVersionCode = cachedAvailableBuild
    stalenessDays = cachedStalenessDays

recreate the cached Firebase policy:
    latestBuild = cachedLatestBuild
    latestVersionName = cachedLatestVersionName
    minSupportedBuild = cachedMinSupportedBuild
    nudgeAfterDays = cachedNudgeAfterDays

run the same decision function used online
```

This means offline mode can show either a normal optional prompt or a forced
update screen, but only if that update was already detected online earlier on
this same device.

When Play successfully answers "no update available":

```text
clear the cached update policy
```

That prevents stale cached policy from prompting later when Play has already
said the device cannot install anything.

## Native Android Kotlin/Java

Use:

```text
com.google.android.play:app-update
com.google.android.play:app-update-ktx
Firebase Firestore
SharedPreferences
```

Kotlin shape:

```kotlin
appUpdateManager.appUpdateInfo
    .addOnSuccessListener { info ->
        if (info.updateAvailability() != UpdateAvailability.UPDATE_AVAILABLE) {
            clearCachedUpdatePolicy()
            tier.value = NONE
            return@addOnSuccessListener
        }

        firestore.collection("config").document("app").get()
            .addOnSuccessListener { doc ->
                val policy = readPolicy(doc)
                cachePolicyInputs(info, policy)
                tier.value = decide(info, policy, currentVersion)
            }
            .addOnFailureListener {
                tier.value = decideFromCachedPolicy()
            }
    }
    .addOnFailureListener {
        tier.value = decideFromCachedPolicy()
    }
```

Java uses the same shape with `addOnSuccessListener` / `addOnFailureListener`
and `SharedPreferences.Editor`.

## Flutter

Use:

```text
in_app_update
cloud_firestore
package_info_plus
shared_preferences or your app prefs wrapper
```

Dart shape:

```dart
Future<void> refreshUpdate() async {
  AppUpdateInfo info;
  try {
    info = await InAppUpdate.checkForUpdate();
  } catch (_) {
    tier.value = decideFromCachedPolicy();
    return;
  }

  if (info.updateAvailability != UpdateAvailability.updateAvailable) {
    clearCachedUpdatePolicy();
    tier.value = AppUpdateTier.none;
    return;
  }

  try {
    final doc = await FirebaseFirestore.instance
        .collection('config')
        .doc('app')
        .get();
    final policy = readPolicy(doc);
    cachePolicyInputs(info, policy);
    tier.value = decide(info, policy, currentVersion);
  } catch (_) {
    tier.value = decideFromCachedPolicy();
  }
}
```

## What Each Tier Shows

`NUDGE` (patch or minor) never interrupts. No dialog, no Play consent sheet,
nothing on launch. It shows only as an update icon in the main app bar and,
while it exists, as a row in Settings (see [The update row](#the-update-row)).
The user taps either when they choose to:

- Play allows a flexible update: start it. While it downloads the icon is a
  spinner, and a second tap says "Downloading…" instead of asking Play again.
  Once it has downloaded, offer the restart dialog. That dialog is fine
  because the user just asked for it.
- Play can't download in-app (offline replay, flexible not allowed): open the
  store listing.

Once a download is on disk, the icon itself changes to a restart icon (tooltip
"Update ready") and stays that way until the app restarts. The restart dialog
only opens by itself when the download lands while the user is on the main
screen and started it this session; anywhere else (another screen, a dialog
open, the controller rebuilt) that moment passes, and the changed icon is what
tells them. Tapping it opens the restart dialog.

A download left on disk from an earlier session does not pop up a dialog on
launch; the restart icon opens the dialog when tapped.

Only one restart dialog is ever open. The download worker and a tap on the
icon can both reach it in the same moment, so guard it with the app's own
flag: in Flutter, `Get.isDialogOpen` does not see a plain `showDialog`.

### The update row

Settings keeps its quiet version line at the very bottom ("v1.0.15"), always,
with nothing else beside it. Only while a newer version exists does a row of
its own appear, in the group with About; with no update, Settings looks as it
always did.

```text
Support
[icon]  FAQ                                                    >
[icon]  About                                                  >
[icon]  Version 1.0.16  NEW                          [ ⬆ Update ]   <- only
        Ready to download                                             while an
                                                                      update
[icon]  Version 1.0.16                                       62%     exists
        Downloading…                               ▓▓▓▓▓▓▓░░░░
[icon]  Version 1.0.16                              [ ↻ Restart ]
        Restart to finish updating
...
                         v1.0.15                                  <- always
```

| State | Title | Subtitle | Right side | Tap |
|---|---|---|---|---|
| No update (or not known) | no row | | | |
| `NUDGE`, waiting | "Version {new}", with a small **New** tag | "Ready to download" | small solid **Update** pill | the same action as the app-bar icon |
| Downloading | "Version {new}" | "Downloading…" | the percentage over a short bar; a spinner until Play gives sizes | says it is downloading, like the icon |
| Downloaded | "Version {new}" | "Restart to finish updating" | small solid **Restart** pill | opens the restart dialog |

- The title names the version that is coming. When its number isn't known
  for sure (below), it says "Update available" instead.
- The row goes when the app has restarted onto the new version; the footer
  then shows the new number.
- Nothing on this row starts itself or opens anything by itself. It follows
  the same rules as the icon: tap to download, tap to restart.
- It shows the same state as the app-bar icon, from the same controller, so
  the two never disagree.

**Which version is waiting.** Play's update info gives only the build number
(`availableVersionCode`). The name comes from `config/app`: show
`latestVersionName` only when `availableVersionCode == latestBuild`, because
only then is it the build Play is offering. Otherwise write "A new version is
ready to download" / "Downloading…" rather than guess a number. Cache the name
with the other policy inputs, so the offline replay shows it too.

**The download's progress.** Play reports it through the install state:
`bytesDownloaded()` and `totalBytesToDownload()` while the status is
`DOWNLOADING`. Show `floor(done / total * 100)%` and the bar; until the first
report with a total above zero, show a spinner.

- Native Kotlin/Java: register an `InstallStateUpdatedListener` on the app's
  `AppUpdateManager` for as long as the screen shows it, and unregister it
  after.
- Flutter: `in_app_update` passes on only the status, not the bytes. Add a
  small `EventChannel` in `MainActivity` that forwards Play's install state,
  plus the `app-update` library the plugin already brings, at the same
  version:

```kotlin
// build.gradle.kts: implementation("com.google.android.play:app-update:2.1.0")
EventChannel(messenger, "<app>/update_progress")
    .setStreamHandler(object : EventChannel.StreamHandler {
        private val updates = AppUpdateManagerFactory.create(applicationContext)
        private var listener: InstallStateUpdatedListener? = null

        override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
            val next = InstallStateUpdatedListener { state ->
                if (state.installStatus() == InstallStatus.DOWNLOADING) {
                    events.success(mapOf(
                        "downloaded" to state.bytesDownloaded(),
                        "total" to state.totalBytesToDownload(),
                    ))
                }
            }
            listener = next
            updates.registerListener(next)
        }

        override fun onCancel(arguments: Any?) {
            listener?.let { updates.unregisterListener(it) }
            listener = null
        }
    })
```

```dart
// In the update controller, next to the installUpdateListener.
const channel = EventChannel('<app>/update_progress');
channel.receiveBroadcastStream().listen((event) {
  if (event is! Map) return;
  final total = (event['total'] as num?)?.toDouble() ?? 0;
  if (total <= 0) return;
  final done = (event['downloaded'] as num?)?.toDouble() ?? 0;
  state = state.copyWith(downloading: true, progress: (done / total).clamp(0.0, 1.0));
}, onError: (_) {});
// Clear progress when the status turns DOWNLOADED, FAILED or CANCELED.
```

Guard the listen in a try/catch: the channel is missing in tests and on
anything but Android with Play, and a missing channel must only mean "no
percentage", never an error. Value Guard (`lib/ui/update/version_row.dart`,
`MainActivity.kt`) is the reference.

`BLOCKED` (major, or below `minSupportedBuild`) is the only full-screen UI: a
block over the whole app with the update button, and the restart button once
the update has downloaded. It can't be dismissed, and back does nothing
useful on it.

## What Not To Do

Do not read Firebase first and show update UI from `latestBuild` alone.

Do not force-update users because Firebase says a major version exists unless
Play says that same user can install that build.

Do not keep a permanent "blocked=true" or "nudge=true" cache. Cache Play and
Firebase inputs instead.

Do not show an offline prompt after the installed app version reaches the cached
available build. Clear that stale cache first.

Do not use Firebase Remote Config or Firestore as a replacement for Play update
availability. They answer different questions.

Do not block sideloaded/debug builds unless you are building a separate
enterprise distribution path. Play cannot update those installs.

Do not assume internal-track releases are visible to production users.

Do not show a dialog, a sheet or Play's consent flow on its own for an optional
update. The icon is the whole of the nudge.

Do not leave a finished download looking like an update that hasn't started.
The icon must say "restart", or the user never learns it is ready.

## Testing Checklist

Unit-test the pure decision function:

- Play says no update, Firebase says major/min floor: result is `NONE`
- Play says update, patch/minor: result is `NUDGE`
- Play says update, major and available build reaches policy: result is `BLOCKED`
- Play says update, available build cannot reach policy major: result is `NUDGE`
- Offline cache with cached optional update and old app: result is `NUDGE`
- Offline cache with cached major update and old app: result is `BLOCKED`
- Offline cache after app reaches cached available build: result is `NONE`
- Offline cache with no cached available build: result is `NONE`

Widget-test the icon: update available shows the update icon; downloading
shows the spinner; downloaded shows the restart icon.

Widget-test Settings: with no update there is no update row and the footer
shows "v" and the running version; waiting shows the row with the new
version, New and an Update pill; downloading with a known size shows the
percentage and bar, without one a spinner; downloaded shows Restart; the
footer is there in every state. Unit test that the new version is named only
when `availableVersionCode` equals `latestBuild`.

Manual-test on Play tracks:

- debug install: no update UI
- sideload install: no update UI unless a previously proven cached update still applies
- internal old build with internal new build: update UI appears
- production old build while new build is internal only: no update UI
- forced `minSupportedBuild`: block appears only when Play can serve an update
- tap the icon, accept Play's sheet, go to another screen while it downloads:
  back on the main screen the icon is the restart icon, and tapping it offers
  the restart
- double-tap the icon once the download is ready: one restart dialog, not two
- start the update from the update row: the row counts up while it downloads,
  the app-bar icon spins at the same time, both turn to restart together, and
  after the restart the row is gone and the footer shows the new version
