import 'package:flutter/material.dart';

import '../../../l10n/strings.dart';
import '../../../live/match_snapshot.dart';
import '../../../theme/app_theme.dart';
import '../../../theme/tokens.dart';
import '../match_view_data.dart';
import '../widgets/match_widgets.dart';
import '../widgets/round_flash.dart';

/// Quick Battle live question (P03 screens 1, 2, 3 and 5): active question, local wrong-answer lock, the
/// server reveal, and Sudden Death. The layout stays stable across all of them; only states change.
class QuickQuestionView extends StatelessWidget {
  const QuickQuestionView({super.key, required this.data});

  final MatchViewData data;

  @override
  Widget build(BuildContext context) {
    final s = data.s;
    final ui = data.ui;
    final revealed = s.isRevealed;
    final suddenDeath = s.isSuddenDeath;
    final myPid = s.myPid;
    final selected = ui.selectedFor(s);
    final result = ui.resultFor(s);
    final status = s.ownAnswerStatus;
    final confirmedWrong = status == AnswerStatuses.wrong || result?['correct'] == false;
    final confirmedCorrect = status == AnswerStatuses.correct || result?['correct'] == true;
    final delta = s.scoreDelta ?? (result?['score_delta'] as num?)?.toInt();
    final watchingOnly = s.isSpectator || status == AnswerStatuses.ineligible;
    final canAnswer = data.questionOpen &&
        !s.isSpectator &&
        s.eligibleToAnswer &&
        selected == null &&
        status == AnswerStatuses.notAnswered;
    final tied = ((s.suddenDeath?['tied_pids'] as List?) ?? const []).map((e) => '$e').toSet();
    final reactionsNow = data.liveReactions;

    final banners = <Widget>[];
    if (revealed) {
      final winnerPid = s.roundWinnerPid;
      final winner = winnerPid == null ? null : s.participants[winnerPid];
      if (winner != null) {
        final isMe = winnerPid == myPid;
        final text = suddenDeath
            ? (isMe ? context.t('match.sd_winner_you') : context.t('match.sd_winner', {'name': winner.name}))
            : (isMe
                ? context.t('match.round_winner_you', {'points': s.roundPoints})
                : context.t('match.round_winner', {'name': winner.name, 'points': s.roundPoints}));
        banners.add(StatusBanner(text: text, icon: Icons.bolt_rounded));
      } else {
        banners.add(StatusBanner(
          text: context.t('match.no_winner'),
          icon: Icons.hourglass_bottom_rounded,
          background: OColors.surfaceContainer,
          foreground: OColors.ink,
        ));
      }
    } else if (suddenDeath) {
      banners.add(StatusBanner(
        text: context.t('match.sd_banner'),
        icon: Icons.flash_on_rounded,
        background: OColors.rose,
        foreground: OColors.secondary,
      ));
    }
    if (!revealed && confirmedWrong) {
      banners.add(StatusBanner(
        text: context.t('match.wrong_locked'),
        icon: Icons.lock_rounded,
        background: wrongTint,
        foreground: OColors.coral,
        trailing: delta == null
            ? null
            : Text(signed(delta), style: OText.tabular(OText.headlineSm).copyWith(color: OColors.coral)),
      ));
    }
    if (!revealed && watchingOnly) {
      banners.add(StatusBanner(
        text: context.t(suddenDeath ? 'match.sd_spectating' : 'match.watching_round'),
        icon: Icons.visibility_rounded,
        background: OColors.surfaceContainer,
        foreground: OColors.ink,
      ));
    }

    final options = <Widget>[];
    for (final entry in s.orderedOptions) {
      final concept = entry.value;
      final text = s.optionTexts[concept] ?? '';
      var look = OptionLook.idle;
      String? badge;
      String? caption;
      if (revealed) {
        if (concept == s.correctConceptId) {
          look = OptionLook.correct;
          if (concept == selected) {
            caption = context.t('match.your_answer');
            if (delta != null) badge = signed(delta);
          }
        } else if (concept == selected) {
          look = OptionLook.wrong;
          caption = context.t('match.your_answer');
          if (delta != null) badge = signed(delta);
        } else {
          look = OptionLook.dimmed;
        }
      } else if (selected != null) {
        if (concept == selected) {
          look = confirmedWrong
              ? OptionLook.wrong
              : confirmedCorrect
                  ? OptionLook.correct
                  : (s.selectedConceptId != null || result != null ? OptionLook.locked : OptionLook.pending);
          caption = context.t('match.your_answer');
          if (delta != null && (confirmedWrong || confirmedCorrect)) badge = signed(delta);
        } else {
          look = OptionLook.dimmed;
        }
      } else if (confirmedWrong) {
        look = OptionLook.dimmed;
      }
      options.add(Padding(
        padding: const EdgeInsets.only(bottom: OSpace.md),
        child: AnswerOption(
          letter: entry.key,
          text: text,
          look: look,
          badge: badge,
          caption: caption,
          onTap: canAnswer ? () => data.onAnswer(concept) : null,
        ),
      ));
    }

    final String footer;
    if (revealed) {
      footer = context.t('match.round_closed');
    } else if (suddenDeath) {
      footer = context.t('match.rules_sd');
    } else if (data.wrongPenalty != null) {
      footer = context.t('match.rules_quick_penalty', {'penalty': signed(data.wrongPenalty!)});
    } else {
      footer = context.t('match.rules_quick');
    }

    // Centred round result (playtest 2026-09-27): the winner for everyone, a private card for an own wrong answer.
    String? flashKey;
    FlashContent? flash;
    final roundWinner = s.roundWinnerPid;
    if (revealed && roundWinner != null && s.participants[roundWinner] != null) {
      final isMe = roundWinner == myPid;
      flashKey = 'win:${s.roundId}';
      flash = FlashContent(
        kind: isMe ? FlashKind.youWon : FlashKind.otherWon,
        title: isMe
            ? context.t('match.flash_you_won')
            : context.t('match.flash_other_won', {'name': s.participants[roundWinner]!.name}),
        points: suddenDeath ? null : signed(s.roundPoints),
      );
    } else if (!revealed && confirmedWrong && delta != null && delta != 0) {
      flashKey = 'wrong:${s.roundId}';
      flash = FlashContent(kind: FlashKind.youWrong, title: context.t('match.flash_wrong'), points: signed(delta));
    }

    final players = s.bySlot;
    final body = Column(
      children: [
        MatchTopBar(
          overline: context.t('mode.QUICK'),
          title: suddenDeath
              ? context.t('match.sd_question', {'n': s.roundNumber})
              : context.t('match.round_of', {'n': s.roundNumber, 'total': s.totalNormalRounds}),
          onClose: data.onLeave,
          actions: [
            if (data.onReportQuestion != null)
              IconButton(
                onPressed: data.onReportQuestion,
                tooltip: context.t('match.report_question'),
                constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: const Icon(Icons.outlined_flag_rounded, color: OColors.inkSubtle),
              ),
            TimerRing(nowMs: data.nowMs, startsAtMs: s.startsAtMs, endsAtMs: s.endsAtMs, stopped: revealed),
          ],
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (var i = 0; i < players.length; i++) ...[
                    if (i > 0) const SizedBox(width: OSpace.sm),
                    Expanded(
                      child: PlayerScoreTile(
                        participant: players[i],
                        isMe: players[i].pid == myPid,
                        reaction: reactionsNow[players[i].pid],
                        spectating: suddenDeath && tied.isNotEmpty && !tied.contains(players[i].pid),
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: OSpace.md),
              Row(
                children: [
                  Flexible(child: CategoryChip(categoryId: s.categoryId, difficulty: s.difficulty)),
                  if (data.canReact) ...[
                    const SizedBox(width: OSpace.sm),
                    Flexible(
                      child: ReactionBar(items: data.reactions, used: data.ui.reactedIn(s), onReact: data.onReact),
                    ),
                  ],
                ],
              ),
              for (final b in banners) ...[const SizedBox(height: OSpace.md), b],
              const SizedBox(height: OSpace.md),
              QuestionCard(snapshot: s),
              const SizedBox(height: OSpace.lg),
              ...options,
              InfoFooter(
                text: footer,
                icon: revealed ? Icons.lock_clock_rounded : Icons.bolt_rounded,
              ),
            ],
          ),
        ),
      ],
    );
    return Stack(
      children: [
        body,
        Positioned.fill(
          child: RoundFlash(
            eventKey: flashKey,
            content: flash,
            holdMs: flash?.kind == FlashKind.youWrong ? 1400 : 2400,
          ),
        ),
      ],
    );
  }
}
