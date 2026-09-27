# oltivra

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## Android release (Google Play)

Package name: `com.noriloop.oltivra` (must match the Play Console app).

1. Signing: `android/key.properties` (git-ignored) points at the upload keystore:
   ```
   storeFile=C:/Users/<you>/.oltivra-signing/upload-keystore.jks
   storePassword=...
   keyAlias=upload
   keyPassword=...
   ```
   Keep the keystore and its passwords backed up; enrol in Play App Signing so Google holds the app signing key.
2. Bump `version:` in `pubspec.yaml` (`name+code`; the code must increase for every upload).
3. Build with production values:
   ```
   flutter build appbundle --release \
     -PadmobAppId=ca-app-pub-XXXX~YYYY \
     --dart-define=API_BASE_URL=https://api.example.com \
     --dart-define=AUTH_MODE=firebase --dart-define=LIVE_MODE=rtdb --dart-define=USE_EMULATORS=false \
     --dart-define=FIREBASE_PROJECT_ID=... --dart-define=FIREBASE_API_KEY=... --dart-define=FIREBASE_APP_ID=... \
     --dart-define=ADMOB_REWARDED_ANDROID=ca-app-pub-XXXX/AAAA \
     --dart-define=ADMOB_INTERSTITIAL_ANDROID=ca-app-pub-XXXX/BBBB
   ```
   Output: `build/app/outputs/bundle/release/app-release.aab`.
4. Backend: `OLTIVRA_GOOGLE_PLAY_PACKAGE` defaults to `com.noriloop.oltivra` (purchase verification).
