import 'dart:io';

import 'package:firebase_app_check/firebase_app_check.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_database/firebase_database.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'auth/auth_service.dart';
import 'core/analytics.dart';
import 'core/env.dart';
import 'core/push.dart';
import 'core/providers.dart';
import 'l10n/strings.dart';
import 'router/app_router.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  final overrides = [
    sharedPrefsProvider.overrideWithValue(prefs),
    clientHeadersProvider.overrideWithValue(await _clientHeaders()),
  ];
  if (!Env.fakeAuth || !Env.pollLive) {
    await Firebase.initializeApp(
      options: const FirebaseOptions(
        apiKey: Env.firebaseApiKey,
        appId: Env.firebaseAppId,
        messagingSenderId: Env.firebaseSenderId,
        projectId: Env.firebaseProjectId,
      ),
    );
    if (Env.useEmulators) {
      await FirebaseAuth.instance.useAuthEmulator(Env.emulatorHost, 9099);
      FirebaseDatabase.instance.useDatabaseEmulator(Env.emulatorHost, 9000);
    }
    if (!Env.useEmulators) overrides.add(analyticsProvider.overrideWithValue(FirebaseAnalyticsService()));
    if (!Env.fakeAuth) {
      final appCheck = await _activateAppCheck();
      overrides.add(authServiceProvider.overrideWithValue(FirebaseAuthService(appCheck: appCheck)));
    }
  }
  runApp(ProviderScope(overrides: overrides, child: const OltivraApp()));
}

Future<Map<String, String>> _clientHeaders() async {
  try {
    final info = await PackageInfo.fromPlatform();
    return {'x-client-platform': Platform.operatingSystem, 'x-client-build': info.buildNumber};
  } catch (_) {
    return const {};
  }
}

/// Activates App Check and returns the token source for API calls. A missing token never blocks a request here;
/// the backend decides (monitor on stage, enforce in prod).
Future<Future<String?> Function()?> _activateAppCheck() async {
  if (Env.useEmulators) return null;
  try {
    await FirebaseAppCheck.instance.activate(
      providerAndroid: Env.appCheckDebugToken.isEmpty
          ? const AndroidPlayIntegrityProvider()
          : const AndroidDebugProvider(debugToken: Env.appCheckDebugToken),
      providerApple: Env.appCheckDebugToken.isEmpty
          ? const AppleAppAttestWithDeviceCheckFallbackProvider()
          : const AppleDebugProvider(debugToken: Env.appCheckDebugToken),
    );
  } catch (_) {
    return null;
  }
  return () async {
    try {
      return await FirebaseAppCheck.instance.getToken();
    } catch (_) {
      return null;
    }
  };
}

class OltivraApp extends ConsumerWidget {
  const OltivraApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(pushServiceProvider);
    return MaterialApp.router(
      title: 'Oltivra',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      routerConfig: ref.watch(routerProvider),
      locale: ref.watch(localeProvider),
      supportedLocales: [for (final l in supportedLanguages) Locale(l)],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
    );
  }
}
