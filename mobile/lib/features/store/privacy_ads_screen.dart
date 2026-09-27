import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/env.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import '../settings/settings_widgets.dart';
import 'store_services.dart';

/// P08 · Privacy & ad preferences: an app-owned overview. Where Google UMP requires a privacy-options form
/// (EEA/UK/CH, spec §30.2) "Manage ad preferences" opens that platform form; elsewhere a local
/// personalised-ads preference is stored on the device and applied to ad requests.
class PrivacyAdsScreen extends ConsumerStatefulWidget {
  const PrivacyAdsScreen({super.key});

  @override
  ConsumerState<PrivacyAdsScreen> createState() => _PrivacyAdsScreenState();
}

class _PrivacyAdsScreenState extends ConsumerState<PrivacyAdsScreen> {
  AdConsentState? _consent;
  bool _checking = true;
  bool _opening = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() => _checking = true);
    try {
      final state = await ref.read(adConsentGatewayProvider).refresh();
      if (mounted) setState(() => _consent = state);
    } catch (_) {
      // Consent service unreachable (offline / not configured): fall back to the local preference.
      if (mounted) setState(() => _consent = null);
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _manage() async {
    setState(() => _opening = true);
    try {
      await ref.read(adConsentGatewayProvider).showPrivacyOptions();
      await _refresh();
    } catch (_) {
      if (mounted) showMessage(context, context.t('store.privacy.form_failed'));
    } finally {
      if (mounted) setState(() => _opening = false);
    }
  }

  Future<void> _setPersonalized(bool value) async {
    await ref.read(sharedPrefsProvider).setBool(personalizedAdsPrefKey, value);
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final usesForm = _consent?.privacyOptionsRequired == true;
    final personalized = ref.read(sharedPrefsProvider).getBool(personalizedAdsPrefKey) ?? true;
    return OPage(
      title: context.t('store.privacy.title'),
      children: [
        Container(
          padding: const EdgeInsets.all(OSpace.xl),
          decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.md)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 52,
                    height: 52,
                    decoration: const BoxDecoration(color: OColors.mint, shape: BoxShape.circle),
                    child: const Icon(Icons.verified_user_outlined, color: OColors.primary),
                  ),
                  const SizedBox(width: OSpace.lg),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(context.t('store.privacy.kicker').toUpperCase(),
                            style: OText.labelSm.copyWith(color: OColors.primary)),
                        const SizedBox(height: 2),
                        Text(context.t('store.privacy.heading'), style: OText.headlineSm),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: OSpace.lg),
              Text(context.t('store.privacy.body'), style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
            ],
          ),
        ),
        SettingsCaption(context.t('store.privacy.section.choices')),
        SettingsGroup(children: [
          if (_checking)
            const Padding(padding: EdgeInsets.all(OSpace.lg), child: LinearProgressIndicator())
          else if (usesForm)
            SettingsTile(
              key: const ValueKey('privacy_manage'),
              icon: Icons.tune_rounded,
              iconBackground: OColors.rose,
              iconColor: OColors.secondary,
              title: context.t('store.privacy.manage'),
              subtitle: context.t('store.privacy.manage.sub'),
              onTap: _opening ? null : _manage,
              trailing: _opening
                  ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : null,
            )
          else
            SettingsTile(
              key: const ValueKey('privacy_personalized'),
              icon: Icons.tune_rounded,
              iconBackground: OColors.rose,
              iconColor: OColors.secondary,
              title: context.t('store.privacy.personalized'),
              subtitle: context.t('store.privacy.personalized.sub'),
              trailing: Switch(value: personalized, onChanged: _setPersonalized),
            ),
        ]),
        if (!_checking && !usesForm)
          Padding(
            padding: const EdgeInsets.fromLTRB(OSpace.xs, OSpace.sm, OSpace.xs, 0),
            child: Text(context.t('store.privacy.local_note'),
                style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
          ),
        SettingsCaption(context.t('store.privacy.section.how')),
        _ExplainCard(
          icon: Icons.timer_off_outlined,
          color: OColors.sun,
          iconColor: OColors.tertiary,
          title: context.t('store.privacy.interstitial.title'),
          body: context.t('store.privacy.interstitial.body'),
        ),
        const SizedBox(height: OSpace.md),
        _ExplainCard(
          icon: Icons.military_tech_outlined,
          color: OColors.mint,
          iconColor: OColors.primary,
          title: context.t('store.privacy.rewarded.title'),
          body: context.t('store.privacy.rewarded.body'),
        ),
        const SizedBox(height: OSpace.lg),
        InfoBanner(
          icon: Icons.policy_outlined,
          title: context.t('store.privacy.more.title'),
          body: context.t('store.privacy.more.body'),
          iconBackground: OColors.white,
          iconColor: OColors.onSurfaceVariant,
        ),
        const SizedBox(height: OSpace.sm),
        TextButton.icon(
          onPressed: () async {
            final ok = await launchUrl(Uri.parse(Env.accountDeletionUrl), mode: LaunchMode.externalApplication);
            if (!ok && context.mounted) showMessage(context, context.t('settings.link_failed'));
          },
          icon: const Icon(Icons.open_in_new_rounded, size: 18),
          label: Text(context.t('settings.web_deletion')),
        ),
      ],
    );
  }
}

class _ExplainCard extends StatelessWidget {
  const _ExplainCard({required this.icon, required this.color, required this.iconColor, required this.title,
      required this.body});

  final IconData icon;
  final Color color;
  final Color iconColor;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) => OCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                  child: Icon(icon, size: 20, color: iconColor),
                ),
                const SizedBox(width: OSpace.md),
                Expanded(child: Text(title, style: OText.labelLg)),
              ],
            ),
            const SizedBox(height: OSpace.md),
            Text(body, style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
          ],
        ),
      );
}
