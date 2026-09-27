import 'package:flutter/material.dart';

import '../../../l10n/strings.dart';
import '../../../live/match_snapshot.dart';
import '../../../theme/app_theme.dart';
import '../../../theme/tokens.dart';
import '../../../widgets/o_avatar.dart';
import '../../../widgets/o_widgets.dart';

/// Compact Survival roster: alive players, lock marks (no answer or correctness), eliminated players greyed.
/// After resolution, [survived]/[eliminatedNow] mark this round's outcome from the server reveal.
class SurvivalRoster extends StatelessWidget {
  const SurvivalRoster({super.key, required this.snapshot, this.survived = const {}, this.eliminatedNow = const {},
      this.reactions = const {}, this.trailing});

  final MatchSnapshot snapshot;
  final Set<String> survived;
  final Set<String> eliminatedNow;
  final Map<String, String> reactions;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final s = snapshot;
    final players = s.bySlot;
    final eliminated = players.where((p) => p.eliminated).length;
    return OCard(
      padding: const EdgeInsets.fromLTRB(OSpace.lg, OSpace.md, OSpace.lg, OSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(child: Text(context.t('match.contenders'), style: OText.labelLg)),
              if (eliminated > 0)
                Text(context.t('match.eliminated_count', {'n': eliminated}),
                    style: OText.labelMd.copyWith(color: OColors.secondary)),
              if (trailing != null) ...[const SizedBox(width: OSpace.sm), trailing!],
            ],
          ),
          const SizedBox(height: OSpace.md),
          Wrap(
            spacing: OSpace.sm,
            runSpacing: OSpace.md,
            children: [
              for (final p in players)
                _RosterMark(
                  participant: p,
                  isMe: p.pid == s.myPid,
                  survived: survived.contains(p.pid),
                  outNow: eliminatedNow.contains(p.pid),
                  reaction: reactions[p.pid],
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RosterMark extends StatelessWidget {
  const _RosterMark({required this.participant, required this.isMe, required this.survived, required this.outNow,
      this.reaction});

  final Participant participant;
  final bool isMe;
  final bool survived;
  final bool outNow;
  final String? reaction;

  @override
  Widget build(BuildContext context) {
    final p = participant;
    final out = p.eliminated;
    final status = out
        ? context.t('match.status_eliminated')
        : survived
            ? context.t('match.status_survived')
            : p.answerLocked
                ? context.t('match.answer_locked')
                : null;
    Widget? badge;
    if (outNow || (out && !survived)) {
      badge = _badge(Icons.close_rounded, OColors.inkSubtle);
    } else if (survived) {
      badge = _badge(Icons.check_rounded, OColors.primary);
    } else if (p.answerLocked) {
      badge = _badge(Icons.lock_rounded, OColors.ink);
    }
    return Semantics(
      label: [isMe ? context.t('match.you_name', {'name': p.name}) : p.name, ?status].join(', '),
      excludeSemantics: true,
      child: SizedBox(
        width: 52,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Column(
              children: [
                Opacity(
                  opacity: out ? 0.35 : 1,
                  child: Container(
                    padding: const EdgeInsets.all(2),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: isMe ? OColors.turquoise : Colors.transparent, width: 2),
                    ),
                    child: OAvatar(avatarId: p.avatarId, frameId: p.frameId, size: 40, badge: badge),
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  isMe ? context.t('match.you') : p.name,
                  style: OText.labelSm.copyWith(
                    color: out ? OColors.inkSubtle : OColors.ink,
                    decoration: out ? TextDecoration.lineThrough : null,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
            if (reaction != null)
              Positioned(top: -12, left: -8, right: -8, child: Center(child: _Bubble(reaction!))),
          ],
        ),
      ),
    );
  }

  Widget _badge(IconData icon, Color color) => Container(
        padding: const EdgeInsets.all(2),
        decoration: BoxDecoration(color: color, shape: BoxShape.circle,
            border: Border.all(color: OColors.white, width: 1.5)),
        child: Icon(icon, size: 10, color: OColors.white),
      );
}

class _Bubble extends StatelessWidget {
  const _Bubble(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(color: OColors.white, borderRadius: BorderRadius.circular(ORadius.pill),
            boxShadow: OShadow.floating),
        child: Text(text, style: OText.labelSm, maxLines: 1),
      );
}
