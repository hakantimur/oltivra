import 'package:flutter/material.dart';

import '../../../l10n/strings.dart';
import '../../../live/match_snapshot.dart';
import '../../../theme/app_theme.dart';
import '../../../theme/tokens.dart';
import '../../../widgets/o_avatar.dart';
import '../../../widgets/o_widgets.dart';
import '../widgets/match_widgets.dart';

/// P04 screen 4: a warm, respectful elimination state. The player cannot answer again; they can keep
/// watching as a spectator or leave (their result still arrives after the match).
class SurvivalEliminatedView extends StatelessWidget {
  const SurvivalEliminatedView({super.key, required this.snapshot, required this.onWatch, required this.onLeave});

  final MatchSnapshot snapshot;
  final VoidCallback onWatch;
  final VoidCallback onLeave;

  @override
  Widget build(BuildContext context) {
    final s = snapshot;
    final me = s.me;
    final alive = s.bySlot.where((p) => !p.eliminated).toList();
    return Column(
      children: [
        MatchTopBar(overline: context.t('mode.SURVIVAL'), title: context.t('match.eliminated_header'),
            onClose: onLeave),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
            children: [
              Center(
                child: Container(
                  width: 120,
                  height: 120,
                  decoration: const BoxDecoration(color: OColors.rose, shape: BoxShape.circle),
                  child: const Icon(Icons.sentiment_satisfied_alt_rounded, size: 56, color: OColors.secondary),
                ),
              ),
              const SizedBox(height: OSpace.lg),
              Text(context.t('match.eliminated_title'), style: OText.headlineXlMobile, textAlign: TextAlign.center),
              const SizedBox(height: OSpace.sm),
              Text(context.t('match.eliminated_body'),
                  style: OText.bodyLg.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
              const SizedBox(height: OSpace.xl),
              OCard(
                radius: ORadius.md,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (me != null) ...[
                      Text(context.t('match.rounds_cleared').toUpperCase(),
                          style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
                      const SizedBox(height: OSpace.xs),
                      Text('${me.score}', style: OText.displayStat),
                      const SizedBox(height: OSpace.md),
                    ],
                    InfoFooter(text: context.t('match.answer_closed_spectator'), icon: Icons.lock_outline_rounded),
                  ],
                ),
              ),
              const SizedBox(height: OSpace.lg),
              OCard(
                radius: ORadius.md,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(context.t('match.live_progress'), style: OText.labelLg)),
                        OPill(context.t('match.remaining', {'n': s.activeCount}), dot: true),
                      ],
                    ),
                    const SizedBox(height: OSpace.md),
                    for (final p in alive)
                      Padding(
                        padding: const EdgeInsets.only(bottom: OSpace.sm),
                        child: Row(
                          children: [
                            OAvatar(avatarId: p.avatarId, frameId: p.frameId, size: 36),
                            const SizedBox(width: OSpace.md),
                            Expanded(child: Text(p.name, style: OText.labelLg, overflow: TextOverflow.ellipsis)),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: OSpace.xl),
              OButton(label: context.t('match.watch_battle'), icon: Icons.visibility_rounded, onPressed: onWatch),
              const SizedBox(height: OSpace.sm),
              OButton(label: context.t('match.leave_after_match'), style: OButtonStyle.ghost, onPressed: onLeave),
            ],
          ),
        ),
      ],
    );
  }
}
