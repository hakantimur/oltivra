# iOS release (TestFlight via Codemagic)

There is no Mac in the workflow: Codemagic builds the app on a cloud Mac (free plan: 500 macOS minutes a month)
and uploads it to TestFlight. The workflow is `ios-testflight` in `codemagic.yaml` and only runs when started by hand.

## Identifiers

| Item | Value |
| --- | --- |
| Bundle ID | `com.noriloop.oltivra` |
| Firebase iOS app | `1:269747180478:ios:e939b331d301df5e8a1fef` (project `synova-36a5f`) |
| Google iOS OAuth client | `269747180478-n3318o2626nr61h27dupp91jsa1l2b6l.apps.googleusercontent.com` |

`firebase apps:sdkconfig IOS <app id>` prints the full `GoogleService-Info.plist`. The app does not bundle that file:
Firebase options come from `--dart-define`, like on Android.

## One-time setup

1. **Apple Developer → Identifiers → `com.noriloop.oltivra`:** enable *Push Notifications*, *Sign in with Apple*
   and *App Attest*. `ios/Runner/Runner.entitlements` asks for all three, so signing fails without them.
2. **App Store Connect:** create the app with that bundle ID. Under *Users and Access → Integrations → App Store
   Connect API*, create a key with the *App Manager* role and download the `.p8` file (it can be downloaded once).
3. **Codemagic** (sign in with GitHub, add `hakantimur/oltivra`):
   - *Team integrations → Developer Portal*: add the API key (issuer ID, key ID, `.p8`) and name it `Oltivra ASC`.
   - *Environment variables*: group `oltivra_ios`, variable `FIREBASE_API_KEY_IOS` = `API_KEY` from the Oltivra iOS
     `GoogleService-Info.plist`, marked secure.
4. **Firebase console (synova-36a5f):**
   - *Authentication → Sign-in method*: enable **Apple** (native iOS sign-in needs no extra fields).
   - *Cloud Messaging → Apple app configuration*: upload an APNs auth key (`.p8` from Apple Developer → Keys).
   - *App Check → Apps → Oltivra iOS*: register **App Attest** (and DeviceCheck as the fallback).

## Build

Codemagic → Oltivra → *Start new build* → workflow **iOS TestFlight**. The build number is Codemagic's
`$BUILD_NUMBER`, so every run is a new TestFlight build. The version name comes from `pubspec.yaml`.

## Still on test values

- AdMob: `GAD_APPLICATION_ID` in `ios/Flutter/*.xcconfig` is Google's sample app ID and no `ADMOB_*_IOS` units are
  passed, so iOS shows test ads. Create an iOS app in AdMob, then set the real app ID and pass
  `--dart-define=ADMOB_INTERSTITIAL_IOS=…` / `ADMOB_REWARDED_IOS=…` before the App Store release.
