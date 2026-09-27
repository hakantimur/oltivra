/// Build-time configuration (`--dart-define`). Defaults target the local stack on an Android emulator,
/// where the host machine is reachable at 10.0.2.2.
abstract final class Env {
  /// Backend API origin (docker compose publishes the API on :8000).
  static const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'http://10.0.2.2:8000');

  /// `fake`: the dev backend accepts `test:<uid>` tokens (no Firebase project needed).
  /// `firebase`: Firebase Auth (emulator when [useEmulators]).
  static const authMode = String.fromEnvironment('AUTH_MODE', defaultValue: 'fake');

  /// `poll`: match state via `GET /v1/matches/{id}` + sync; `rtdb`: Realtime Database listeners.
  static const liveMode = String.fromEnvironment('LIVE_MODE', defaultValue: 'poll');

  static const useEmulators = bool.fromEnvironment('USE_EMULATORS', defaultValue: true);
  static const emulatorHost = String.fromEnvironment('EMULATOR_HOST', defaultValue: '10.0.2.2');
  static const firebaseProjectId = String.fromEnvironment('FIREBASE_PROJECT_ID', defaultValue: 'demo-oltivra');
  static const firebaseApiKey = String.fromEnvironment('FIREBASE_API_KEY', defaultValue: 'demo-api-key');
  static const firebaseAppId = String.fromEnvironment('FIREBASE_APP_ID', defaultValue: '1:000000000000:android:0000');
  static const firebaseSenderId = String.fromEnvironment('FIREBASE_SENDER_ID', defaultValue: '0');

  /// OAuth *web* client id of the Firebase project; Android Google Sign-In needs it to mint an ID token.
  static const googleServerClientId = String.fromEnvironment('GOOGLE_SERVER_CLIENT_ID');

  /// Firebase App Check (spec §15.2): Play Integrity in release builds. A debug token registered in the Firebase
  /// console switches to the debug provider (emulators, sideloaded dev builds).
  static const appCheckDebugToken = String.fromEnvironment('APP_CHECK_DEBUG_TOKEN');

  /// Public web page for account deletion (spec §30.2), served by the backend.
  static String get accountDeletionUrl => '$apiBaseUrl/account/delete';

  static bool get fakeAuth => authMode == 'fake';
  static bool get pollLive => liveMode != 'rtdb';
}
