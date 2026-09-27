import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'widgets.dart';

/// P01 · 13+ declaration (spec §2.1). A single neutral confirmation; no birthdate or other personal data is
/// collected. The answer stays on the device until it is posted with the consent after sign-in.
class AgeGateScreen extends ConsumerStatefulWidget {
  const AgeGateScreen({super.key});

  @override
  ConsumerState<AgeGateScreen> createState() => _AgeGateScreenState();
}

class _AgeGateScreenState extends ConsumerState<AgeGateScreen> {
  bool _confirmed = false;
  bool _underAge = false;
  bool _saving = false;

  Future<void> _continue() async {
    setState(() => _saving = true);
    await ref.read(localOnboardingProvider.notifier).confirmAge();
    if (!mounted) return;
    setState(() => _saving = false);
    context.go(Routes.terms);
  }

  @override
  Widget build(BuildContext context) {
    final signedOut = ref.watch(authStateProvider).value == null;
    return Scaffold(
      appBar: onboardingAppBar(
        context,
        title: context.t('onboarding.age.title'),
        onBack: _underAge
            ? () => setState(() => _underAge = false)
            : signedOut
                ? () => context.go(Routes.launch)
                : null,
      ),
      body: SafeArea(
        top: false,
        child: AnimatedSwitcher(
          duration: ODuration.medium,
          child: _underAge ? _blocked(context) : _form(context),
        ),
      ),
    );
  }

  Widget _form(BuildContext context) => ListView(
        key: const ValueKey('form'),
        padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
        children: [
          const OnboardingStepBar(step: 1),
          const SizedBox(height: OSpace.xl),
          const _AgeHeroCard(),
          const SizedBox(height: OSpace.xl),
          Semantics(header: true, child: Text(context.t('onboarding.age.heading'), style: OText.headlineXlMobile)),
          const SizedBox(height: OSpace.sm),
          Text(context.t('onboarding.age.body'), style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant)),
          const SizedBox(height: OSpace.xl),
          OCheckTile(
            key: const Key('age-confirm'),
            value: _confirmed,
            onChanged: (v) => setState(() => _confirmed = v),
            title: context.t('onboarding.age.confirm'),
            subtitle: context.t('onboarding.age.confirm_hint'),
          ),
          const SizedBox(height: OSpace.md),
          Container(
            padding: const EdgeInsets.all(OSpace.md),
            decoration: BoxDecoration(
              color: OColors.surfaceContainer,
              borderRadius: BorderRadius.circular(ORadius.card),
            ),
            child: Row(
              children: [
                const Icon(Icons.shield_outlined, color: OColors.primary, size: 22),
                const SizedBox(width: OSpace.sm),
                Expanded(
                  child: Text(context.t('onboarding.age.privacy'),
                      style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                ),
              ],
            ),
          ),
          const SizedBox(height: OSpace.xxl),
          OButton(
            key: const Key('age-continue'),
            label: context.t('action.continue'),
            trailingIcon: Icons.arrow_forward_rounded,
            loading: _saving,
            onPressed: _confirmed ? _continue : null,
          ),
          const SizedBox(height: OSpace.md),
          const OnboardingStepCaption(step: 1),
          const SizedBox(height: OSpace.lg),
          Center(
            child: TextButton(
              key: const Key('age-under-13'),
              onPressed: () => setState(() => _underAge = true),
              child: Text(context.t('onboarding.age.under_13'),
                  style: OText.labelMd.copyWith(color: OColors.inkSubtle, decoration: TextDecoration.underline)),
            ),
          ),
        ],
      );

  Widget _blocked(BuildContext context) => Center(
        key: const ValueKey('blocked'),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(OSpace.margin),
          child: OEmptyState(
            icon: Icons.waving_hand_rounded,
            title: context.t('onboarding.age.blocked_title'),
            body: context.t('onboarding.age.blocked_body'),
            action: SizedBox(
              width: 220,
              child: OButton(
                label: context.t('onboarding.age.blocked_back'),
                style: OButtonStyle.secondary,
                onPressed: () => setState(() {
                  _underAge = false;
                  _confirmed = false;
                }),
              ),
            ),
          ),
        ),
      );
}

class _AgeHeroCard extends StatelessWidget {
  const _AgeHeroCard();

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(OSpace.xl),
        decoration: BoxDecoration(
          color: const Color(0xFFF2F3FF),
          borderRadius: BorderRadius.circular(ORadius.lg),
          boxShadow: OShadow.card,
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  OPill(
                    context.t('onboarding.age.badge'),
                    icon: Icons.verified_user_rounded,
                    background: const Color(0xFFDDE2F7),
                    foreground: OColors.onSurfaceVariant,
                  ),
                  const SizedBox(height: OSpace.sm),
                  Text(context.t('onboarding.age.hero_title'), style: OText.headlineSm),
                  const SizedBox(height: OSpace.xs),
                  Text(context.t('onboarding.age.hero_body'),
                      style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                ],
              ),
            ),
            const SizedBox(width: OSpace.md),
            ExcludeSemantics(
              child: SizedBox.square(
                dimension: 84,
                child: Stack(
                  clipBehavior: Clip.none,
                  alignment: Alignment.center,
                  children: [
                    Container(
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: OColors.turquoise.withValues(alpha: 0.2),
                      ),
                    ),
                    Container(
                      width: 66,
                      height: 66,
                      alignment: Alignment.center,
                      decoration: const BoxDecoration(shape: BoxShape.circle, color: OColors.turquoise),
                      child: Text('13+', style: OText.headlineLg.copyWith(color: OColors.white)),
                    ),
                    Positioned(
                      right: -2,
                      bottom: -2,
                      child: Container(
                        width: 28,
                        height: 28,
                        decoration: const BoxDecoration(shape: BoxShape.circle, color: OColors.tertiaryFixed),
                        child: const Icon(Icons.bolt_rounded, size: 18, color: Color(0xFF4C3700)),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      );
}
