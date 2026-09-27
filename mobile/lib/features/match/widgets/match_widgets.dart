import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../api/api_client.dart';
import '../../../l10n/strings.dart';
import '../../../live/match_snapshot.dart';
import '../../../theme/app_theme.dart';
import '../../../theme/tokens.dart';
import '../../../widgets/o_avatar.dart';
import '../../../widgets/o_widgets.dart';

// Tints for the two semantic answer states. Green is used only for a confirmed correct answer and coral only
// for a confirmed wrong answer (design foundation).
const correctTint = Color(0xFFE3F6EC);
const wrongTint = Color(0xFFFDECEC);

/// How long a reaction bubble stays visible (spec §5: 1.5–2.0 s).
const reactionDisplayMs = 1800;

// ------------------------------------------------------------------------------------------ helpers

/// "1st", "2nd", "3rd" in English; "1.", "2." in Turkish.
String ordinal(BuildContext context, int n) {
  if (context.lang == 'tr') return '$n.';
  final mod100 = n % 100;
  final suffix = (mod100 >= 11 && mod100 <= 13)
      ? 'th'
      : switch (n % 10) {
          1 => 'st',
          2 => 'nd',
          3 => 'rd',
          _ => 'th',
        };
  return '$n$suffix';
}

/// Signed score delta as sent by the server: "+7", "−4", "0".
String signed(int value) => value > 0 ? '+$value' : (value < 0 ? '−${value.abs()}' : '0');

/// Whole seconds left until [deadlineMs] on the server clock (display only).
int secondsLeft(int nowMs, int deadlineMs) => deadlineMs <= 0 ? 0 : ((deadlineMs - nowMs) / 1000).ceil().clamp(0, 999);

/// Latest reaction per sender that is still on screen, excluding players this viewer has muted/blocked.
Map<String, String> recentReactions(MatchSnapshot s, int nowMs) {
  final muted = s.mutedPids.toSet();
  final out = <String, String>{};
  for (final e in s.events) {
    if (e['type'] != 'REACTION') continue;
    final pid = e['pid'] as String?;
    final at = (e['at_ms'] as num?)?.toInt() ?? 0;
    if (pid == null || muted.contains(pid) || nowMs - at > reactionDisplayMs || nowMs < at - 5000) continue;
    out[pid] = '${e['value']}';
  }
  return out;
}

/// Reaction catalog entry (`GET /v1/reactions`).
class ReactionItem {
  const ReactionItem(this.id, this.display, this.label);

  factory ReactionItem.fromJson(Json j) =>
      ReactionItem('${j['id']}', '${j['display'] ?? j['id']}', '${j['label'] ?? j['display'] ?? j['id']}');

  final String id;
  final String display;
  final String label;
}

List<ReactionItem> reactionItems(Json? catalog) => ((catalog?['reactions'] as List?) ?? const [])
    .whereType<Map>()
    .map((e) => ReactionItem.fromJson(e.cast<String, dynamic>()))
    .toList();

// ------------------------------------------------------------------------------------------ top bar

class MatchTopBar extends StatelessWidget {
  const MatchTopBar({super.key, required this.title, this.overline, this.onClose, this.actions = const []});

  final String title;
  final String? overline;
  final VoidCallback? onClose;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(OSpace.sm, OSpace.sm, OSpace.margin, OSpace.sm),
        child: Row(
          children: [
            if (onClose != null)
              IconButton(
                onPressed: onClose,
                tooltip: context.t('match.leave'),
                constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: const Icon(Icons.close_rounded, color: OColors.ink),
              )
            else
              const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (overline != null)
                    Text(overline!.toUpperCase(), style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
                  Text(title, style: OText.headlineMd, maxLines: 2, overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
            ...actions,
          ],
        ),
      );
}

// ------------------------------------------------------------------------------------------ timers

/// Countdown ring from `starts_at_ms`/`ends_at_ms` on the server clock. Display only (spec §22.1).
class TimerRing extends StatelessWidget {
  const TimerRing({super.key, required this.nowMs, required this.startsAtMs, required this.endsAtMs,
      this.stopped = false, this.size = 60});

  final int nowMs;
  final int startsAtMs;
  final int endsAtMs;
  final bool stopped;
  final double size;

  @override
  Widget build(BuildContext context) {
    final total = math.max(1, endsAtMs - startsAtMs);
    final leftMs = stopped ? 0 : (endsAtMs - math.max(nowMs, startsAtMs)).clamp(0, total);
    final seconds = stopped ? 0 : secondsLeft(math.max(nowMs, startsAtMs), endsAtMs);
    final urgent = !stopped && seconds <= 3;
    final color = urgent ? OColors.pink : OColors.yellow;
    return Semantics(
      label: context.t('match.time_left', {'n': seconds}),
      excludeSemantics: true,
      child: SizedBox.square(
        dimension: size,
        child: Stack(
          alignment: Alignment.center,
          children: [
            SizedBox.square(
              dimension: size,
              child: CircularProgressIndicator(
                value: leftMs / total,
                strokeWidth: 5,
                color: color,
                backgroundColor: OColors.surfaceContainer,
              ),
            ),
            stopped
                ? const Icon(Icons.timer_off_outlined, size: 22, color: OColors.inkSubtle)
                : Text(context.t('time.seconds_short', {'n': seconds.toString().padLeft(2, '0')}),
                    style: OText.tabular(OText.labelLg)),
          ],
        ),
      ),
    );
  }
}

/// Horizontal countdown used by Survival.
class TimerBar extends StatelessWidget {
  const TimerBar({super.key, required this.nowMs, required this.startsAtMs, required this.endsAtMs,
      this.stopped = false});

  final int nowMs;
  final int startsAtMs;
  final int endsAtMs;
  final bool stopped;

  @override
  Widget build(BuildContext context) {
    final total = math.max(1, endsAtMs - startsAtMs);
    final leftMs = stopped ? 0 : (endsAtMs - math.max(nowMs, startsAtMs)).clamp(0, total);
    final seconds = stopped ? 0 : secondsLeft(math.max(nowMs, startsAtMs), endsAtMs);
    return Semantics(
      label: context.t('match.time_left', {'n': seconds}),
      excludeSemantics: true,
      child: Row(
        children: [
          Expanded(
            child: OProgressBar(
              value: leftMs / total,
              height: 12,
              color: seconds <= 3 && !stopped ? OColors.pink : OColors.turquoise,
            ),
          ),
          const SizedBox(width: OSpace.md),
          OPill(
            context.t('time.seconds_short', {'n': seconds}),
            icon: stopped ? Icons.timer_off_outlined : Icons.timer_outlined,
            background: OColors.surfaceContainer,
            foreground: OColors.ink,
          ),
        ],
      ),
    );
  }
}

// ------------------------------------------------------------------------------------------ question

class CategoryChip extends StatelessWidget {
  const CategoryChip({super.key, this.categoryId, this.difficulty});

  final String? categoryId;
  final String? difficulty;

  @override
  Widget build(BuildContext context) {
    final parts = [
      if (categoryId != null) context.t('category.$categoryId'),
      if (difficulty != null) context.t('difficulty.$difficulty'),
    ];
    if (parts.isEmpty) return const SizedBox.shrink();
    return OPill(parts.join(' · '), icon: categoryIcon(categoryId), background: OColors.surfaceContainer,
        foreground: OColors.ink);
  }
}

/// The question text card shared by both modes.
class QuestionCard extends StatelessWidget {
  const QuestionCard({super.key, required this.snapshot, this.header});

  final MatchSnapshot snapshot;
  final Widget? header;

  // Text-only since the 2026-09-27 playtest: images took the space the answers need and slowed round start.
  @override
  Widget build(BuildContext context) => OCard(
        radius: ORadius.md,
        padding: const EdgeInsets.all(OSpace.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (header != null) ...[header!, const SizedBox(height: OSpace.md)],
            Text(snapshot.questionText, style: OText.headlineMd, textAlign: TextAlign.center),
          ],
        ),
      );
}

enum OptionLook { idle, pending, locked, correct, wrong, dimmed }

/// One of the four large answer targets (A–D). Neutral until the server confirms a result.
class AnswerOption extends StatelessWidget {
  const AnswerOption({super.key, required this.letter, required this.text, this.look = OptionLook.idle,
      this.onTap, this.badge, this.caption});

  final String letter;
  final String text;
  final OptionLook look;
  final VoidCallback? onTap;
  final String? badge;
  final String? caption;

  @override
  Widget build(BuildContext context) {
    final (bg, border, letterBg, letterFg) = switch (look) {
      OptionLook.correct => (correctTint, OColors.success, OColors.success, OColors.white),
      OptionLook.wrong => (wrongTint, OColors.coral, OColors.coral, OColors.white),
      OptionLook.pending || OptionLook.locked => (OColors.mint, OColors.turquoise, OColors.turquoise, OColors.white),
      _ => (OColors.white, OColors.divider, OColors.surfaceContainer, OColors.ink),
    };
    final status = switch (look) {
      OptionLook.correct => context.t('match.correct_answer'),
      OptionLook.wrong => context.t('match.wrong_answer'),
      OptionLook.pending || OptionLook.locked => context.t('match.answer_locked'),
      _ => null,
    };
    final trailing = switch (look) {
      OptionLook.correct => const Icon(Icons.check_circle_rounded, color: OColors.success),
      OptionLook.wrong => const Icon(Icons.cancel_rounded, color: OColors.coral),
      OptionLook.pending => const SizedBox.square(
          dimension: 20, child: CircularProgressIndicator(strokeWidth: 2.5, color: OColors.turquoise)),
      OptionLook.locked => const Icon(Icons.lock_rounded, color: OColors.primary),
      _ => null,
    };
    final label = [
      context.t('match.option_semantics', {'letter': letter, 'text': text}),
      ?status,
      ?caption,
    ].join(', ');
    return Opacity(
      opacity: look == OptionLook.dimmed ? 0.55 : 1,
      child: Semantics(
        button: onTap != null,
        enabled: onTap != null,
        label: label,
        excludeSemantics: true,
        child: Material(
          color: bg,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(ORadius.card),
            side: BorderSide(color: border, width: look == OptionLook.idle || look == OptionLook.dimmed ? 1 : 2),
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(ORadius.card),
            onTap: onTap,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 64),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
                child: Row(
                  children: [
                    Container(
                      width: 40,
                      height: 40,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(color: letterBg, shape: BoxShape.circle),
                      child: Text(letter, style: OText.headlineSm.copyWith(color: letterFg)),
                    ),
                    const SizedBox(width: OSpace.lg),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(text, style: OText.bodyLg.copyWith(fontWeight: FontWeight.w600)),
                          if (caption != null)
                            Text(caption!,
                                style: OText.bodySm.copyWith(
                                    color: look == OptionLook.wrong ? OColors.coral : OColors.inkSubtle)),
                        ],
                      ),
                    ),
                    if (badge != null) ...[
                      const SizedBox(width: OSpace.sm),
                      OPill(
                        badge!,
                        background: OColors.white,
                        foreground: switch (look) {
                          OptionLook.correct => OColors.success,
                          OptionLook.wrong => OColors.coral,
                          _ => OColors.ink,
                        },
                      ),
                    ],
                    if (trailing != null) ...[const SizedBox(width: OSpace.sm), trailing],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------------------------------ players

/// Compact score tile (Quick): avatar, name, server score. The viewer's tile is highlighted.
class PlayerScoreTile extends StatelessWidget {
  const PlayerScoreTile({super.key, required this.participant, this.isMe = false, this.reaction,
      this.spectating = false, this.showScore = true});

  final Participant participant;
  final bool isMe;
  final String? reaction;
  final bool spectating;
  final bool showScore;

  @override
  Widget build(BuildContext context) {
    final p = participant;
    final name = isMe ? context.t('match.you_name', {'name': p.name}) : p.name;
    final faded = p.left || spectating;
    final status = p.left
        ? context.t('match.player_left')
        : spectating
            ? context.t('match.spectating')
            : null;
    return Semantics(
      label: [
        name,
        if (showScore) context.t('match.points', {'n': p.score}),
        ?status,
        if (p.answerLocked) context.t('match.answer_locked'),
        ?reaction,
      ].join(', '),
      excludeSemantics: true,
      child: Opacity(
        opacity: faded ? 0.5 : 1,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: OSpace.md, horizontal: OSpace.xs),
          decoration: BoxDecoration(
            color: isMe ? OColors.mint : OColors.white,
            borderRadius: BorderRadius.circular(ORadius.card),
            border: Border.all(color: isMe ? OColors.turquoise : OColors.divider),
          ),
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  OAvatar(
                    avatarId: p.avatarId,
                    frameId: p.frameId,
                    size: 36,
                    badge: p.answerLocked
                        ? Container(
                            padding: const EdgeInsets.all(2),
                            decoration: const BoxDecoration(color: OColors.ink, shape: BoxShape.circle),
                            child: const Icon(Icons.lock_rounded, size: 10, color: OColors.white),
                          )
                        : null,
                  ),
                  const SizedBox(height: OSpace.xs),
                  Text(name,
                      style: OText.labelSm.copyWith(color: isMe ? OColors.primary : OColors.ink),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis),
                  if (status != null)
                    Text(status, style: OText.labelSm.copyWith(color: OColors.inkSubtle), maxLines: 1)
                  else if (showScore)
                    Text('${p.score}', style: OText.tabular(OText.headlineSm)),
                ],
              ),
              if (reaction != null)
                Positioned(top: -10, right: 0, left: 0, child: Center(child: ReactionBubble(text: reaction!))),
            ],
          ),
        ),
      ),
    );
  }
}

class ReactionBubble extends StatelessWidget {
  const ReactionBubble({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: OSpace.sm, vertical: 2),
        decoration: BoxDecoration(
          color: OColors.white,
          borderRadius: BorderRadius.circular(ORadius.pill),
          boxShadow: OShadow.floating,
        ),
        child: Text(text, style: OText.labelMd),
      );
}

/// Small curated reaction row (spec §5): one reaction per round, never over the question or answers.
class ReactionBar extends StatelessWidget {
  const ReactionBar({super.key, required this.items, required this.used, required this.onReact});

  final List<ReactionItem> items;
  final bool used;
  final ValueChanged<ReactionItem> onReact;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Opacity(
      opacity: used ? 0.45 : 1,
      child: Container(
        decoration: BoxDecoration(color: OColors.white, borderRadius: BorderRadius.circular(ORadius.pill),
            border: Border.all(color: OColors.divider)),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final item in items)
                Semantics(
                  button: true,
                  enabled: !used,
                  label: context.t('match.react_with', {'reaction': item.label}),
                  excludeSemantics: true,
                  child: InkWell(
                    customBorder: const StadiumBorder(),
                    onTap: used ? null : () => onReact(item),
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                      child: Center(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: OSpace.sm),
                          child: Text(item.display, style: OText.labelMd),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Coloured one-line status strip ("Sudden Death · First correct answer wins", "Ava wins +7").
class StatusBanner extends StatelessWidget {
  const StatusBanner({super.key, required this.text, this.icon, this.background = OColors.mint,
      this.foreground = OColors.primary, this.trailing});

  final String text;
  final IconData? icon;
  final Color background;
  final Color foreground;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(ORadius.card)),
        child: Row(
          children: [
            if (icon != null) ...[Icon(icon, color: foreground, size: 20), const SizedBox(width: OSpace.sm)],
            Expanded(child: Text(text, style: OText.labelLg.copyWith(color: foreground))),
            ?trailing,
          ],
        ),
      );
}

class InfoFooter extends StatelessWidget {
  const InfoFooter({super.key, required this.text, this.icon = Icons.info_outline_rounded,
      this.background = OColors.surfaceContainer, this.foreground = OColors.ink});

  final String text;
  final IconData icon;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(OSpace.lg),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(ORadius.card)),
        child: Row(
          children: [
            Icon(icon, size: 20, color: foreground),
            const SizedBox(width: OSpace.md),
            Expanded(child: Text(text, style: OText.bodySm.copyWith(color: foreground))),
          ],
        ),
      );
}

// ------------------------------------------------------------------------------------------ overlays & sheets

/// P08 "Reconnecting to battle": keeps the last snapshot underneath, blocks input, reveals nothing new.
class ReconnectingOverlay extends StatelessWidget {
  const ReconnectingOverlay({super.key});

  @override
  Widget build(BuildContext context) => Positioned.fill(
        child: Semantics(
          liveRegion: true,
          child: ColoredBox(
            color: OColors.canvas.withValues(alpha: 0.86),
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(OSpace.margin),
                child: OCard(
                  radius: ORadius.lg,
                  padding: const EdgeInsets.all(OSpace.xl),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 72,
                        height: 72,
                        decoration: const BoxDecoration(color: OColors.turquoise, shape: BoxShape.circle),
                        child: const Icon(Icons.sync_rounded, color: OColors.white, size: 36),
                      ),
                      const SizedBox(height: OSpace.lg),
                      Text(context.t('match.reconnecting_title'), style: OText.headlineMd,
                          textAlign: TextAlign.center),
                      const SizedBox(height: OSpace.sm),
                      Text(context.t('match.reconnecting_body'),
                          style: OText.bodyMd.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
                      const SizedBox(height: OSpace.lg),
                      OPill(context.t('match.reconnecting_status'), dot: true,
                          background: OColors.surfaceContainer),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      );
}

const questionReportReasons = [
  'WRONG_ANSWER',
  'AMBIGUOUS',
  'OUTDATED',
  'IMAGE_PROBLEM',
  'TRANSLATION_PROBLEM',
  'OTHER',
];

/// Bottom sheet with the predefined question report reasons (spec §11.3). Returns the chosen reason.
Future<String?> pickQuestionReportReason(BuildContext context) => showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      backgroundColor: OColors.canvas,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(OSpace.margin, 0, OSpace.margin, OSpace.lg),
          children: [
            Text(context.t('match.report_question_title'), style: OText.headlineSm),
            const SizedBox(height: OSpace.xs),
            Text(context.t('match.report_question_body'),
                style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            const SizedBox(height: OSpace.md),
            for (final reason in questionReportReasons)
              ListTile(
                minTileHeight: 52,
                contentPadding: EdgeInsets.zero,
                title: Text(context.t('match.report_reason.$reason'), style: OText.bodyLg),
                trailing: const Icon(Icons.chevron_right_rounded),
                onTap: () => Navigator.of(context).pop(reason),
              ),
          ],
        ),
      ),
    );

/// Leave confirmation. Returns true when the player confirms.
Future<bool> confirmLeave(BuildContext context, String body) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(context.t('match.leave_title')),
      content: Text(body),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: Text(context.t('match.leave_stay'))),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: TextButton.styleFrom(foregroundColor: OColors.coral),
          child: Text(context.t('match.leave_confirm')),
        ),
      ],
    ),
  );
  return ok == true;
}
