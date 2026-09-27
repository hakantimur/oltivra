import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';

/// P08 "Match safely unavailable": the match was stopped safely (CANCELLED / EXPIRED), or this device could
/// not reach it any more. Never blames the player, never exposes backend errors, never invents rewards.
class MatchUnavailableScreen extends StatelessWidget {
  const MatchUnavailableScreen({super.key, this.matchId, this.connectionLost = false, this.onRetry});

  final String? matchId;

  /// True when the live connection gave up (the match itself may still be running on the server).
  final bool connectionLost;

  /// Offered with [connectionLost] to try reattaching.
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final lost = connectionLost;
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.xxl, OSpace.margin, OSpace.xxl),
          children: [
            Center(
              child: Container(
                width: 120,
                height: 120,
                decoration: const BoxDecoration(color: OColors.rose, shape: BoxShape.circle),
                child: Icon(lost ? Icons.wifi_off_rounded : Icons.shield_rounded, size: 52,
                    color: OColors.secondary),
              ),
            ),
            const SizedBox(height: OSpace.xl),
            Text(context.t(lost ? 'match.lost_title' : 'match.unavailable_title'),
                style: OText.headlineXlMobile, textAlign: TextAlign.center),
            const SizedBox(height: OSpace.sm),
            Text(context.t(lost ? 'match.lost_body' : 'match.unavailable_body'),
                style: OText.bodyLg.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
            const SizedBox(height: OSpace.xl),
            if (!lost)
              OCard(
                radius: ORadius.md,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 48,
                      height: 48,
                      decoration: const BoxDecoration(color: OColors.mint, shape: BoxShape.circle),
                      child: const Icon(Icons.verified_user_rounded, color: OColors.primary),
                    ),
                    const SizedBox(width: OSpace.lg),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(context.t('match.fair_play_title'), style: OText.headlineSm),
                          const SizedBox(height: OSpace.xs),
                          Text(context.t('match.fair_play_body'),
                              style: OText.bodyMd.copyWith(color: OColors.inkSubtle)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: OSpace.xxl),
            if (lost && onRetry != null) ...[
              OButton(label: context.t('action.retry'), icon: Icons.refresh_rounded, onPressed: onRetry),
              const SizedBox(height: OSpace.md),
            ],
            OButton(
              label: context.t('match.back_home'),
              icon: Icons.home_rounded,
              style: lost && onRetry != null ? OButtonStyle.secondary : OButtonStyle.primary,
              onPressed: () => context.go(Routes.home),
            ),
            const SizedBox(height: OSpace.md),
            OButton(
              label: context.t('match.play_again'),
              icon: Icons.replay_rounded,
              style: OButtonStyle.ghost,
              onPressed: () => context.go(Routes.play),
            ),
          ],
        ),
      ),
    );
  }
}
