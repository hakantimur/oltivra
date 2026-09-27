import 'package:flutter/widgets.dart';

import 'tables/common.dart';
import 'tables/home.dart';
import 'tables/match.dart';
import 'tables/onboarding.dart';
import 'tables/progress.dart';
import 'tables/settings.dart';
import 'tables/social.dart';
import 'tables/store.dart';

/// UI languages shipped in the app (spec §8: English + Turkish UI).
const supportedLanguages = ['en', 'tr'];

typedef StringTable = Map<String, Map<String, String>>;

/// Flat key → text lookup merged from per-feature tables (`lib/l10n/tables/*.dart`).
/// Every table provides `en`; a missing `tr` entry falls back to English, a missing key shows the key.
abstract final class Strings {
  static final Map<String, Map<String, String>> _merged = _merge([
    commonStrings,
    onboardingStrings,
    homeStrings,
    matchStrings,
    socialStrings,
    progressStrings,
    settingsStrings,
    storeStrings,
  ]);

  static Map<String, Map<String, String>> _merge(List<StringTable> tables) {
    final out = <String, Map<String, String>>{for (final l in supportedLanguages) l: {}};
    for (final table in tables) {
      table.forEach((lang, entries) => (out[lang] ??= {}).addAll(entries));
    }
    return out;
  }

  static String lookup(String language, String key, [Map<String, Object?>? args]) {
    var text = _merged[language]?[key] ?? _merged['en']?[key] ?? key;
    args?.forEach((name, value) => text = text.replaceAll('{$name}', '${value ?? ''}'));
    return text;
  }

  static bool has(String key) => _merged['en']!.containsKey(key);
}

extension StringsContext on BuildContext {
  String get lang {
    final code = Localizations.maybeLocaleOf(this)?.languageCode ?? 'en';
    return supportedLanguages.contains(code) ? code : 'en';
  }

  /// Localised text for [key]; `{name}` placeholders are filled from [args].
  String t(String key, [Map<String, Object?>? args]) => Strings.lookup(lang, key, args);

  /// Picks the current language from a server-provided `{"en": ..., "tr": ...}` map.
  String pick(Map? names, {String fallback = ''}) {
    if (names == null) return fallback;
    return (names[lang] ?? names['en'] ?? fallback).toString();
  }
}
