import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/legal.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'widgets.dart';

/// P01 · Terms and privacy acceptance. Both documents must be accepted. Signed-out players continue to sign-in
/// (the consent is posted right after it); a signed-in player whose server consent is missing re-bootstraps so
/// `SessionController` posts it now.
class TermsScreen extends ConsumerStatefulWidget {
  const TermsScreen({super.key});

  @override
  ConsumerState<TermsScreen> createState() => _TermsScreenState();
}

class _TermsScreenState extends ConsumerState<TermsScreen> {
  bool _tos = false;
  bool _privacy = false;
  bool _saving = false;

  Future<void> _accept() async {
    setState(() => _saving = true);
    try {
      await ref.read(localOnboardingProvider.notifier).acceptTerms();
      final signedIn = ref.read(authStateProvider).value != null;
      if (signedIn) {
        ref.invalidate(sessionProvider);
        await ref.read(sessionProvider.future); // redirect moves on once the consent is recorded
      } else if (mounted) {
        context.go(Routes.signIn);
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final signedOut = ref.watch(authStateProvider).value == null;
    return Scaffold(
      appBar: onboardingAppBar(
        context,
        title: context.t('onboarding.terms.title'),
        onBack: signedOut ? () => context.go(Routes.ageGate) : null,
      ),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
          children: [
            const OnboardingStepBar(step: 2),
            const SizedBox(height: OSpace.xl),
            const Center(child: OnboardingHeroIcon(icon: Icons.verified_user_outlined, badgeIcon: Icons.lock_rounded)),
            const SizedBox(height: OSpace.lg),
            Semantics(
              header: true,
              child: Text(context.t('onboarding.terms.heading'),
                  textAlign: TextAlign.center, style: OText.headlineXlMobile),
            ),
            const SizedBox(height: OSpace.sm),
            Text(
              context.t('onboarding.terms.body'),
              textAlign: TextAlign.center,
              style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant),
            ),
            const SizedBox(height: OSpace.xl),
            _DocumentRow(
              key: const Key('terms-tos'),
              icon: Icons.description_outlined,
              title: context.t('onboarding.terms.tos'),
              subtitle: context.t('onboarding.terms.tos_sub'),
              agreeLabel: context.t('onboarding.terms.agree_tos'),
              value: _tos,
              onChanged: (v) => setState(() => _tos = v),
              onOpen: () => showLegalDocument(context, 'terms'),
            ),
            const SizedBox(height: OSpace.md),
            _DocumentRow(
              key: const Key('terms-privacy'),
              icon: Icons.admin_panel_settings_outlined,
              title: context.t('onboarding.terms.privacy'),
              subtitle: context.t('onboarding.terms.privacy_sub'),
              agreeLabel: context.t('onboarding.terms.agree_privacy'),
              value: _privacy,
              onChanged: (v) => setState(() => _privacy = v),
              onOpen: () => showLegalDocument(context, 'privacy'),
            ),
            const SizedBox(height: OSpace.md),
            Text(
              context.t('onboarding.terms.required'),
              textAlign: TextAlign.center,
              style: OText.bodySm.copyWith(color: OColors.inkSubtle),
            ),
            const SizedBox(height: OSpace.xl),
            OButton(
              key: const Key('terms-continue'),
              label: context.t('onboarding.terms.continue'),
              trailingIcon: Icons.arrow_forward_rounded,
              loading: _saving,
              onPressed: _tos && _privacy ? _accept : null,
            ),
            const SizedBox(height: OSpace.md),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.shield_outlined, size: 16, color: OColors.primary),
                const SizedBox(width: OSpace.xs),
                Flexible(
                  child: Text(context.t('onboarding.terms.footer'),
                      style: OText.labelMd.copyWith(color: OColors.onSurfaceVariant)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// One legal document: tap the header to read it, tap the agreement line to toggle acceptance.
class _DocumentRow extends StatelessWidget {
  const _DocumentRow({super.key, required this.icon, required this.title, required this.subtitle,
      required this.agreeLabel, required this.value, required this.onChanged, required this.onOpen});

  final IconData icon;
  final String title;
  final String subtitle;
  final String agreeLabel;
  final bool value;
  final ValueChanged<bool> onChanged;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) => AnimatedContainer(
        duration: ODuration.fast,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: OColors.white,
          borderRadius: BorderRadius.circular(ORadius.card),
          boxShadow: OShadow.card,
          border: Border.all(color: value ? OColors.turquoise : Colors.transparent, width: 1.5),
        ),
        child: Material(
          type: MaterialType.transparency,
          child: Column(
            children: [
              Semantics(
                button: true,
                label: context.t('onboarding.terms.read', {'doc': title}),
                excludeSemantics: true,
                child: InkWell(
                  onTap: onOpen,
                  child: Padding(
                    padding: const EdgeInsets.all(OSpace.lg),
                    child: Row(
                      children: [
                        Container(
                          width: 48,
                          height: 48,
                          decoration: const BoxDecoration(color: OColors.surfaceContainer, shape: BoxShape.circle),
                          child: Icon(icon, color: OColors.primary),
                        ),
                        const SizedBox(width: OSpace.md),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(title, style: OText.headlineSm),
                              Text(subtitle, style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                            ],
                          ),
                        ),
                        const Icon(Icons.chevron_right_rounded, color: OColors.ink),
                      ],
                    ),
                  ),
                ),
              ),
              const Divider(height: 1, color: OColors.divider),
              Semantics(
                checked: value,
                button: true,
                label: agreeLabel,
                excludeSemantics: true,
                child: InkWell(
                  onTap: () => onChanged(!value),
                  child: Container(
                    color: value ? OColors.mint : null,
                    constraints: const BoxConstraints(minHeight: 52),
                    padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
                    child: Row(
                      children: [
                        OCheckBox(value: value),
                        const SizedBox(width: OSpace.md),
                        Expanded(child: Text(agreeLabel, style: OText.labelLg)),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}
