import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'settings_screen.dart' show languageName;
import 'settings_widgets.dart';

/// P07 · Language: the app (UI) language and the competitive question language are separate settings
/// (spec §8). UI language is local + synced to the profile; the question language is whatever the server
/// lists as competitive (`question_languages` in bootstrap) — there is no silent fallback.
class LanguageScreen extends ConsumerStatefulWidget {
  const LanguageScreen({super.key});

  @override
  ConsumerState<LanguageScreen> createState() => _LanguageScreenState();
}

class _LanguageScreenState extends ConsumerState<LanguageScreen> {
  String? _busy; // 'ui:<code>' | 'q:<code>'

  Future<void> _setUi(String code) async {
    setState(() => _busy = 'ui:$code');
    await ref.read(localeProvider.notifier).set(code);
    try {
      final res = await ref.read(apiClientProvider).patch('/v1/profile/preferences', {'ui_language': code});
      _apply(res);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _setQuestion(String code) async {
    setState(() => _busy = 'q:$code');
    try {
      final res = await ref.read(apiClientProvider).patch('/v1/profile/preferences', {'question_language': code});
      _apply(res);
      if (mounted) showMessage(context, context.t('settings.language.question_saved'));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  void _apply(Map<String, dynamic> res) {
    final profile = res['profile'];
    if (profile is Map) ref.read(sessionProvider.notifier).applyProfile(profile.cast<String, dynamic>());
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider).value;
    final locale = ref.watch(localeProvider);
    final currentUi = locale?.languageCode ?? context.lang;
    final serverUi = ((session?.raw['ui_languages'] as List?) ?? supportedLanguages).cast<String>();
    // The app can only render languages it ships tables for.
    final uiLanguages = [for (final l in supportedLanguages) if (serverUi.contains(l)) l];
    final questionLanguages = ((session?.raw['question_languages'] as List?) ?? const []).cast<String>();
    final currentQuestion = session?.questionLanguage;
    final unavailable = [for (final l in supportedLanguages) if (!questionLanguages.contains(l)) l];

    return OPage(
      title: context.t('settings.language'),
      children: [
        InfoBanner(
          icon: Icons.balance_rounded,
          title: context.t('settings.language.integrity.title'),
          body: context.t('settings.language.integrity.body'),
        ),
        SettingsCaption(context.t('settings.language.app'),
            trailing: Text(context.t('settings.language.app.tag'),
                style: OText.labelSm.copyWith(color: OColors.primary))),
        Padding(
          padding: const EdgeInsets.only(bottom: OSpace.sm, left: OSpace.xs),
          child: Text(context.t('settings.language.app.help'),
              style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
        ),
        SettingsGroup(children: [
          for (final code in uiLanguages)
            _LanguageTile(
              code: code,
              title: languageName(code),
              subtitle: context.t('settings.language.app.option'),
              selected: code == currentUi,
              busy: _busy == 'ui:$code',
              onTap: _busy != null || code == currentUi ? null : () => _setUi(code),
            ),
        ]),
        SettingsCaption(context.t('settings.language.question'),
            trailing: Text(context.t('settings.language.question.tag'),
                style: OText.labelSm.copyWith(color: OColors.secondary))),
        Padding(
          padding: const EdgeInsets.only(bottom: OSpace.sm, left: OSpace.xs),
          child: Text(context.t('settings.language.question.help'),
              style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
        ),
        if (questionLanguages.isEmpty)
          OEmptyState(icon: Icons.quiz_outlined, title: context.t('settings.language.question.none'))
        else
          SettingsGroup(children: [
            for (final code in questionLanguages)
              _LanguageTile(
                code: code,
                title: languageName(code),
                subtitle: context.t('settings.language.question.available'),
                selected: code == currentQuestion,
                busy: _busy == 'q:$code',
                onTap: _busy != null || code == currentQuestion ? null : () => _setQuestion(code),
              ),
            for (final code in unavailable)
              _LanguageTile(
                code: code,
                title: languageName(code),
                subtitle: context.t('settings.language.question.unavailable'),
                selected: false,
                disabled: true,
              ),
          ]),
      ],
    );
  }
}

class _LanguageTile extends StatelessWidget {
  const _LanguageTile({
    required this.code,
    required this.title,
    required this.subtitle,
    required this.selected,
    this.onTap,
    this.busy = false,
    this.disabled = false,
  });

  final String code;
  final String title;
  final String subtitle;
  final bool selected;
  final bool busy;
  final bool disabled;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final Widget trailing;
    if (busy) {
      trailing = const SizedBox.square(dimension: 24, child: CircularProgressIndicator(strokeWidth: 2));
    } else if (disabled) {
      trailing = const Icon(Icons.block_rounded, color: OColors.outlineVariant);
    } else if (selected) {
      trailing = Container(
        width: 28,
        height: 28,
        decoration: const BoxDecoration(color: OColors.turquoise, shape: BoxShape.circle),
        child: const Icon(Icons.check_rounded, size: 18, color: OColors.white),
      );
    } else {
      trailing = Container(
        width: 28,
        height: 28,
        decoration: const BoxDecoration(color: OColors.surfaceContainer, shape: BoxShape.circle),
      );
    }
    return Semantics(
      selected: selected,
      enabled: !disabled,
      child: Opacity(
        opacity: disabled ? 0.55 : 1,
        child: SettingsTile(
          icon: disabled ? Icons.lock_outline_rounded : Icons.translate_rounded,
          iconBackground: selected ? OColors.mint : null,
          iconColor: selected ? OColors.primary : null,
          title: title,
          subtitle: subtitle,
          onTap: onTap,
          trailing: trailing,
        ),
      ),
    );
  }
}
