import 'package:flutter/material.dart';

import '../../../l10n/strings.dart';
import '../../../live/match_snapshot.dart';
import '../../../theme/tokens.dart';
import '../../../widgets/o_widgets.dart';
import '../match_view_data.dart';
import '../widgets/match_widgets.dart';
import '../widgets/round_flash.dart';
import 'survival_roster.dart';

/// Survival live question (P04 screens 1, 2, 3 and 5): active question, answer locked with the outcome hidden,
/// round resolution (survived / protected / out), and the read-only spectator view.
class SurvivalQuestionView extends StatelessWidget {
  const SurvivalQuestionView({super.key, required this.data});

  final MatchViewData data;

  @override
  Widget build(BuildContext context) {
    final s = data.s;
    final ui = data.ui;
    final revealed = s.isRevealed;
    final myPid = s.myPid;
    final me = s.me;
    final status = s.ownAnswerStatus;
    final selected = ui.selectedFor(s);
    final readOnly = s.isSpectator || me == null || me.left || status == AnswerStatuses.ineligible;
    final canAnswer = data.questionOpen && !readOnly && s.eligibleToAnswer && selected == null &&
        status == AnswerStatuses.notAnswered;
    final reveal = s.reveal ?? const {};
    List<String> ids(String key) => ((reveal[key] as List?) ?? const []).map((e) => '$e').toList();
    final survivedIds = revealed ? ids('survived').toSet() : <String>{};
    final eliminatedIds = revealed ? ids('eliminated').toSet() : <String>{};
    final protectedIds = revealed ? ids('protected').toSet() : <String>{};
    final resolution = reveal['resolution'] as String?;

    final banners = <Widget>[];
    if (revealed && !readOnly && myPid != null) {
      if (survivedIds.contains(myPid)) {
        banners.add(StatusBanner(text: context.t('match.you_survived'), icon: Icons.shield_rounded));
      } else if (protectedIds.contains(myPid)) {
        banners.add(StatusBanner(
          text: context.t('match.you_protected'),
          icon: Icons.health_and_safety_rounded,
          background: OColors.sun,
          foreground: OColors.tertiary,
        ));
      } else if (eliminatedIds.contains(myPid)) {
        banners.add(StatusBanner(
          text: context.t('match.you_out_round'),
          icon: Icons.sentiment_neutral_rounded,
          background: OColors.rose,
          foreground: OColors.secondary,
        ));
      }
    } else if (!revealed && !readOnly && selected != null) {
      banners.add(StatusBanner(text: context.t('match.answer_locked_waiting'), icon: Icons.lock_rounded));
    } else if (readOnly) {
      banners.add(StatusBanner(
        text: context.t(s.isSpectator ? 'match.spectating_battle' : 'match.you_were_eliminated'),
        icon: Icons.visibility_rounded,
        background: OColors.surfaceContainer,
        foreground: OColors.ink,
      ));
    }
    if (revealed && eliminatedIds.isNotEmpty) {
      banners.add(StatusBanner(
        text: context.t('match.eliminated_this_round', {'n': eliminatedIds.length}),
        background: OColors.surfaceContainer,
        foreground: OColors.ink,
      ));
    }

    final options = <Widget>[];
    for (final entry in s.orderedOptions) {
      final concept = entry.value;
      var look = OptionLook.idle;
      String? caption;
      if (revealed) {
        if (concept == s.correctConceptId) {
          look = OptionLook.correct;
        } else if (concept == selected) {
          look = OptionLook.wrong;
        } else {
          look = OptionLook.dimmed;
        }
        if (concept == selected) caption = context.t('match.your_answer');
      } else if (selected != null) {
        if (concept == selected) {
          // Neutral lock: correctness stays hidden until the round resolves (spec §4.1).
          look = s.selectedConceptId != null || ui.resultFor(s) != null ? OptionLook.locked : OptionLook.pending;
          caption = context.t('match.your_answer');
        } else {
          look = OptionLook.dimmed;
        }
      }
      options.add(Padding(
        padding: const EdgeInsets.only(bottom: OSpace.md),
        child: AnswerOption(
          letter: entry.key,
          text: s.optionTexts[concept] ?? '',
          look: look,
          caption: caption,
          onTap: canAnswer ? () => data.onAnswer(concept) : null,
        ),
      ));
    }

    final phaseTag = switch (s.phase) {
      'SURVIVAL_RESCUE' => context.t('match.rescue_round'),
      'SURVIVAL_TIEBREAK' => context.t('match.final_tiebreak'),
      _ => null,
    };

    Widget? footer;
    if (revealed && resolution == 'ALL_WRONG') {
      footer = InfoFooter(text: context.t('match.rescue_all_wrong'));
    } else if (revealed && resolution == 'NO_ANSWERS') {
      footer = InfoFooter(text: context.t('match.rescue_no_answers'));
    } else if (revealed) {
      footer = InfoFooter(text: context.t('match.next_round_auto'), icon: Icons.schedule_rounded);
    } else if (!readOnly) {
      footer = InfoFooter(
        text: context.t('match.rules_survival'),
        icon: Icons.warning_amber_rounded,
        background: OColors.rose,
        foreground: OColors.secondary,
      );
    }

    // Centred own-outcome card (playtest 2026-09-27): survived or eliminated, only for this player.
    FlashContent? flash;
    if (revealed && !readOnly && myPid != null) {
      if (survivedIds.contains(myPid)) {
        flash = FlashContent(kind: FlashKind.youWon, title: context.t('match.flash_survived'));
      } else if (eliminatedIds.contains(myPid)) {
        flash = FlashContent(kind: FlashKind.youWrong, title: context.t('match.flash_eliminated'));
      }
    }

    final body = Column(
      children: [
        MatchTopBar(
          overline: context.t(readOnly ? 'match.watching_battle' : 'match.live_match'),
          title: context.t('match.survival_round', {'n': s.roundNumber}),
          onClose: data.onLeave,
          actions: [
            if (data.onReportQuestion != null)
              IconButton(
                onPressed: data.onReportQuestion,
                tooltip: context.t('match.report_question'),
                constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: const Icon(Icons.outlined_flag_rounded, color: OColors.inkSubtle),
              ),
            OPill(
              context.t('match.remaining', {'n': s.activeCount}),
              icon: Icons.groups_rounded,
              background: OColors.sun,
              foreground: OColors.tertiary,
            ),
          ],
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
            children: [
              SurvivalRoster(
                snapshot: s,
                survived: survivedIds,
                eliminatedNow: eliminatedIds,
                reactions: data.liveReactions,
              ),
              if (data.canReact) ...[
                const SizedBox(height: OSpace.sm),
                Align(
                  alignment: Alignment.centerRight,
                  child: ReactionBar(items: data.reactions, used: ui.reactedIn(s), onReact: data.onReact),
                ),
              ],
              const SizedBox(height: OSpace.md),
              TimerBar(nowMs: data.nowMs, startsAtMs: s.startsAtMs, endsAtMs: s.endsAtMs, stopped: revealed),
              for (final b in banners) ...[const SizedBox(height: OSpace.md), b],
              const SizedBox(height: OSpace.md),
              QuestionCard(
                snapshot: s,
                header: Row(
                  children: [
                    Flexible(child: CategoryChip(categoryId: s.categoryId, difficulty: s.difficulty)),
                    if (phaseTag != null) ...[
                      const SizedBox(width: OSpace.sm),
                      OPill(phaseTag, background: OColors.rose, foreground: OColors.secondary),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: OSpace.lg),
              ...options,
              ?footer,
            ],
          ),
        ),
      ],
    );
    return Stack(
      children: [
        body,
        Positioned.fill(
          child: RoundFlash(eventKey: flash == null ? null : '${flash.kind.name}:${s.roundId}', content: flash),
        ),
      ],
    );
  }
}
