import 'package:flutter/material.dart';

import '../../l10n/strings.dart';
import '../../live/match_snapshot.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'match_view_data.dart';
import 'survival/survival_roster.dart';
import 'widgets/match_widgets.dart';

/// Automatic between-round transition (P03 screen 4): shown during NEXT_ROUND and while a published round
/// has not reached `starts_at_ms` yet. The question itself stays hidden until it opens. No actions.
class RoundTransitionView extends StatelessWidget {
  const RoundTransitionView({super.key, required this.data});

  final MatchViewData data;

  @override
  Widget build(BuildContext context) {
    final s = data.s;
    final hasRound = s.roundId != null && data.beforeStart;
    String? roundLabel;
    if (hasRound && s.roundNumber > 0) {
      final base = s.isSurvival
          ? context.t('match.survival_round', {'n': s.roundNumber})
          : s.isSuddenDeath
              ? context.t('match.sd_question', {'n': s.roundNumber})
              : context.t('match.round_of', {'n': s.roundNumber, 'total': s.totalNormalRounds});
      roundLabel = s.difficulty == null ? base : '$base · ${context.t('difficulty.${s.difficulty}')}';
    }
    final startsIn = hasRound ? secondsLeft(data.nowMs, s.startsAtMs) : null;
    return Column(
      children: [
        MatchTopBar(
          overline: context.t('mode.${s.mode}'),
          title: context.t('match.intermission'),
          onClose: data.onLeave,
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
            children: [
              if (roundLabel != null)
                Center(child: OPill(roundLabel, dot: true, background: OColors.surfaceContainer)),
              const SizedBox(height: OSpace.md),
              Text(context.t('match.get_ready'), style: OText.headlineXlMobile, textAlign: TextAlign.center),
              if (s.isSuddenDeath && !s.isSurvival) ...[
                const SizedBox(height: OSpace.sm),
                Text(context.t('match.sd_banner'),
                    style: OText.bodyMd.copyWith(color: OColors.secondary), textAlign: TextAlign.center),
              ],
              if (hasRound && s.categoryId != null) ...[
                const SizedBox(height: OSpace.lg),
                OCard(
                  radius: ORadius.md,
                  padding: const EdgeInsets.all(OSpace.xl),
                  child: Column(
                    children: [
                      Container(
                        width: 64,
                        height: 64,
                        decoration: const BoxDecoration(color: OColors.surfaceContainer, shape: BoxShape.circle),
                        child: Icon(categoryIcon(s.categoryId), color: OColors.primary, size: 30),
                      ),
                      const SizedBox(height: OSpace.md),
                      OPill(context.t('match.next_category')),
                      const SizedBox(height: OSpace.sm),
                      Text(context.t('category.${s.categoryId}'), style: OText.headlineLg,
                          textAlign: TextAlign.center),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: OSpace.xl),
              if (s.isSurvival) SurvivalRoster(snapshot: s) else _Standings(snapshot: s),
              const SizedBox(height: OSpace.xl),
              OCard(
                child: Column(
                  children: [
                    Text(
                      startsIn == null
                          ? context.t('match.next_question_incoming')
                          : context.t('match.next_question_in', {'n': startsIn}),
                      style: OText.labelLg,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: OSpace.md),
                    const ClipRRect(
                      borderRadius: BorderRadius.all(Radius.circular(ORadius.pill)),
                      child: LinearProgressIndicator(
                          minHeight: 6, color: OColors.turquoise, backgroundColor: OColors.surfaceContainer),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Current Quick Battle positions from server scores.
class _Standings extends StatelessWidget {
  const _Standings({required this.snapshot});

  final MatchSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final s = snapshot;
    final rows = s.byScore;
    final active = rows.where((p) => !p.left).length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Icon(Icons.leaderboard_rounded, size: 18, color: OColors.inkSubtle),
            const SizedBox(width: OSpace.sm),
            Expanded(
              child: Text(context.t('match.live_standings').toUpperCase(),
                  style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
            ),
            Text(context.t('match.active_players', {'n': active}),
                style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
          ],
        ),
        const SizedBox(height: OSpace.sm),
        for (var i = 0; i < rows.length; i++)
          _StandingRow(
            position: _position(rows, i),
            participant: rows[i],
            isMe: rows[i].pid == s.myPid,
          ),
      ],
    );
  }

  /// Players with equal server scores share a position.
  static int _position(List<Participant> rows, int index) {
    var i = index;
    while (i > 0 && rows[i - 1].score == rows[index].score) {
      i--;
    }
    return i + 1;
  }
}

class _StandingRow extends StatelessWidget {
  const _StandingRow({required this.position, required this.participant, required this.isMe});

  final int position;
  final Participant participant;
  final bool isMe;

  @override
  Widget build(BuildContext context) {
    final p = participant;
    return Opacity(
      opacity: p.left ? 0.5 : 1,
      child: Container(
        margin: const EdgeInsets.only(bottom: OSpace.sm),
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
        decoration: BoxDecoration(
          color: isMe ? OColors.mint : OColors.white,
          borderRadius: BorderRadius.circular(ORadius.card),
        ),
        child: Row(
          children: [
            Container(
              width: 32,
              height: 32,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: position == 1 ? OColors.sun : OColors.surfaceContainer,
                shape: BoxShape.circle,
              ),
              child: Text('$position', style: OText.labelMd),
            ),
            const SizedBox(width: OSpace.md),
            OAvatar(avatarId: p.avatarId, frameId: p.frameId, size: 40),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(p.name, style: OText.labelLg.copyWith(color: isMe ? OColors.primary : OColors.ink),
                      overflow: TextOverflow.ellipsis),
                  if (isMe || p.left)
                    Text(context.t(p.left ? 'match.player_left' : 'match.you'),
                        style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                ],
              ),
            ),
            Text(context.t('match.points', {'n': p.score}), style: OText.tabular(OText.labelLg)),
          ],
        ),
      ),
    );
  }
}
