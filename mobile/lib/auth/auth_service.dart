import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:firebase_auth/firebase_auth.dart' as fb;
import 'package:google_sign_in/google_sign_in.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart';

import '../api/api_client.dart';

class AuthUser {
  const AuthUser({required this.uid, required this.provider, this.email});

  final String uid;
  final String provider;
  final String? email;
}

/// Sign-in providers (spec §2.1): Google, Apple and email. The backend only ever sees the ID token.
abstract class AuthService implements TokenSource {
  Stream<AuthUser?> get changes;
  AuthUser? get current;

  Future<void> signInWithGoogle();
  Future<void> signInWithApple();
  Future<void> signInWithEmail(String email, String password, {required bool create});
  Future<void> signOut();

  /// Marks the ID token as needing a refresh (fresh sign-in required for account deletion, spec §30.1).
  Future<void> reauthenticate();
}

class AuthCancelled implements Exception {
  const AuthCancelled();
}

/// Dev/test auth: the dev backend accepts `test:<uid>[:fresh]` bearer tokens, so the whole app can run on an
/// emulator against the local API without a Firebase project. Each provider maps to a stable local uid.
class FakeAuthService implements AuthService {
  FakeAuthService(this._prefs) {
    final uid = _prefs.getString(_key);
    if (uid != null) _current = AuthUser(uid: uid, provider: _prefs.getString('$_key.provider') ?? 'google');
  }

  static const _key = 'dev_auth_uid';
  final SharedPreferences _prefs;
  final _controller = StreamController<AuthUser?>.broadcast();
  AuthUser? _current;
  DateTime _freshUntil = DateTime.fromMillisecondsSinceEpoch(0);

  @override
  Stream<AuthUser?> get changes => _controller.stream;

  @override
  AuthUser? get current => _current;

  Future<void> _signIn(String uid, String provider, {String? email}) async {
    await _prefs.setString(_key, uid);
    await _prefs.setString('$_key.provider', provider);
    _current = AuthUser(uid: uid, provider: provider, email: email);
    _freshUntil = DateTime.now().add(const Duration(minutes: 5));
    _controller.add(_current);
  }

  String _newUid(String prefix) => '${prefix}_${Random().nextInt(1 << 32).toRadixString(36)}';

  @override
  Future<void> signInWithGoogle() => _signIn(_newUid('g'), 'google');

  @override
  Future<void> signInWithApple() => _signIn(_newUid('a'), 'apple');

  @override
  Future<void> signInWithEmail(String email, String password, {required bool create}) {
    final digest = sha256.convert(utf8.encode(email.trim().toLowerCase())).toString().substring(0, 16);
    return _signIn('e_$digest', 'email', email: email);
  }

  @override
  Future<void> signOut() async {
    await _prefs.remove(_key);
    _current = null;
    _controller.add(null);
  }

  @override
  Future<void> reauthenticate() async => _freshUntil = DateTime.now().add(const Duration(minutes: 5));

  @override
  Future<String?> idToken({bool forceRefresh = false}) async {
    final user = _current;
    if (user == null) return null;
    return DateTime.now().isBefore(_freshUntil) ? 'test:${user.uid}:fresh' : 'test:${user.uid}';
  }

  @override
  Future<String?> appCheckToken() async => null;
}

class FirebaseAuthService implements AuthService {
  FirebaseAuthService({fb.FirebaseAuth? auth, Future<String?> Function()? appCheck})
      : _auth = auth ?? fb.FirebaseAuth.instance,
        _appCheck = appCheck; // ignore: prefer_initializing_formals

  final fb.FirebaseAuth _auth;
  final Future<String?> Function()? _appCheck;
  bool _googleReady = false;

  AuthUser? _map(fb.User? user) => user == null
      ? null
      : AuthUser(
          uid: user.uid,
          email: user.email,
          provider: user.providerData.isEmpty ? 'unknown' : user.providerData.first.providerId,
        );

  @override
  Stream<AuthUser?> get changes => _auth.authStateChanges().map(_map);

  @override
  AuthUser? get current => _map(_auth.currentUser);

  @override
  Future<void> signInWithGoogle() async {
    final google = GoogleSignIn.instance;
    if (!_googleReady) {
      await google.initialize();
      _googleReady = true;
    }
    final GoogleSignInAccount account;
    try {
      account = await google.authenticate();
    } on GoogleSignInException catch (e) {
      if (e.code == GoogleSignInExceptionCode.canceled) throw const AuthCancelled();
      rethrow;
    }
    final credential = fb.GoogleAuthProvider.credential(idToken: account.authentication.idToken);
    await _auth.signInWithCredential(credential);
  }

  @override
  Future<void> signInWithApple() async {
    final rawNonce = _nonce();
    final AuthorizationCredentialAppleID apple;
    try {
      apple = await SignInWithApple.getAppleIDCredential(
        scopes: const [AppleIDAuthorizationScopes.email],
        nonce: sha256.convert(utf8.encode(rawNonce)).toString(),
      );
    } on SignInWithAppleAuthorizationException catch (e) {
      if (e.code == AuthorizationErrorCode.canceled) throw const AuthCancelled();
      rethrow;
    }
    final credential = fb.OAuthProvider('apple.com').credential(idToken: apple.identityToken, rawNonce: rawNonce);
    await _auth.signInWithCredential(credential);
  }

  @override
  Future<void> signInWithEmail(String email, String password, {required bool create}) async {
    if (create) {
      await _auth.createUserWithEmailAndPassword(email: email.trim(), password: password);
    } else {
      await _auth.signInWithEmailAndPassword(email: email.trim(), password: password);
    }
  }

  @override
  Future<void> signOut() async {
    await _auth.signOut();
    if (_googleReady) await GoogleSignIn.instance.signOut();
  }

  @override
  Future<void> reauthenticate() async {
    await _auth.currentUser?.getIdToken(true);
  }

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => _auth.currentUser?.getIdToken(forceRefresh);

  @override
  Future<String?> appCheckToken() async => _appCheck?.call();

  static String _nonce([int length = 32]) {
    const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._';
    final random = Random.secure();
    return List.generate(length, (_) => chars[random.nextInt(chars.length)]).join();
  }
}
