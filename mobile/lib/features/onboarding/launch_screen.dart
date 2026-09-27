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

/// P01 · Launch: brand splash while auth/session resolve. Signed-out players get the entry actions; a failed
/// session bootstrap shows a retry. Routing onwards is handled by `onboardingRedirect`.
class LaunchScreen extends ConsumerWidget {
  const LaunchScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authStateProvider);
    final session = ref.watch(sessionProvider);
    final local = ref.watch(localOnboardingProvider);
    final signedOut = auth.hasValue && auth.value == null;
    final signedIn = auth.value != null;
    // Riverpod keeps the error while it retries automatically, so the retry UI stays visible meanwhile.
    final failed = signedIn && session.hasError && !session.hasValue;

    final Widget bottom;
    if (failed) {
      bottom = Column(
        key: const ValueKey('error'),
        mainAxisSize: MainAxisSize.min,
        children: [
          OErrorView(error: session.error!, onRetry: () => ref.invalidate(sessionProvider)),
          TextButton(
            onPressed: () => ref.read(authServiceProvider).signOut(),
            child: Text(context.t('onboarding.launch.sign_out')),
          ),
        ],
      );
    } else if (signedOut) {
      bottom = Column(
        key: const ValueKey('actions'),
        mainAxisSize: MainAxisSize.min,
        children: [
          OButton(
            label: context.t('onboarding.launch.get_started'),
            trailingIcon: Icons.arrow_forward_rounded,
            onPressed: () => context.go(Routes.ageGate),
          ),
          const SizedBox(height: OSpace.md),
          OButton(
            label: context.t('onboarding.launch.have_account'),
            style: OButtonStyle.secondary,
            onPressed: () =>
                context.go(local.ageConfirmed && local.termsAccepted ? Routes.signIn : Routes.ageGate),
          ),
        ],
      );
    } else {
      bottom = const _LaunchFooter(key: ValueKey('footer'));
    }

    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0, -0.25),
            radius: 0.75,
            colors: [Color(0xFFE6F4F6), OColors.canvas],
          ),
        ),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: OSpace.margin),
            child: Column(
              children: [
                Expanded(
                  child: Center(
                    child: SingleChildScrollView(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const OltivraMark(),
                          const SizedBox(height: OSpace.xxl),
                          Semantics(
                            header: true,
                            child: Text(context.t('app.name'), style: OText.headlineXl.copyWith(fontSize: 48, height: 1.1)),
                          ),
                          const SizedBox(height: OSpace.md),
                          Text(
                            context.t('onboarding.launch.tagline'),
                            textAlign: TextAlign.center,
                            style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant, fontSize: 19),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
                AnimatedSwitcher(duration: ODuration.medium, child: bottom),
                const SizedBox(height: OSpace.xl),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _LaunchFooter extends StatelessWidget {
  const _LaunchFooter({super.key});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: OSpace.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _dot(OColors.turquoise.withValues(alpha: 0.6)),
                const SizedBox(width: OSpace.sm),
                Container(
                  width: 36,
                  height: 8,
                  decoration: BoxDecoration(
                    color: OColors.surfaceContainer,
                    borderRadius: BorderRadius.circular(ORadius.pill),
                  ),
                ),
                const SizedBox(width: OSpace.sm),
                _dot(OColors.pink.withValues(alpha: 0.6)),
              ],
            ),
            const SizedBox(height: OSpace.lg),
            Text(
              context.t('onboarding.launch.footer'),
              style: OText.labelMd.copyWith(color: OColors.inkSubtle.withValues(alpha: 0.8), letterSpacing: 0.6),
            ),
          ],
        ),
      );

  static Widget _dot(Color color) =>
      Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
}
