import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';

/// Tab header from the design: brand mark + title, bell (social notifications) and own avatar (profile).
class HomeTopBar extends ConsumerWidget {
  const HomeTopBar({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider).value;
    return Padding(
      padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.md, OSpace.md, OSpace.sm),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: const BoxDecoration(color: OColors.turquoise, shape: BoxShape.circle),
            child: const Icon(Icons.bolt_rounded, color: OColors.white, size: 26),
          ),
          const SizedBox(width: OSpace.md),
          Expanded(child: Text(title, style: OText.headlineLg, overflow: TextOverflow.ellipsis)),
          IconButton(
            tooltip: context.t('home.notifications'),
            onPressed: () => context.push(Routes.friendRequests),
            icon: const Icon(Icons.notifications_none_rounded, color: OColors.ink),
            iconSize: 28,
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
          ),
          Semantics(
            button: true,
            label: context.t('home.profile'),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: () => context.go(Routes.profile),
              child: Padding(
                padding: const EdgeInsets.all(OSpace.xs),
                child: session?.avatarId != null
                    ? OAvatar(avatarId: session!.avatarId, size: 40, frameId: session.frameId)
                    : Container(
                        width: 40,
                        height: 40,
                        decoration: const BoxDecoration(color: OColors.primary, shape: BoxShape.circle),
                        child: const Icon(Icons.person_outline_rounded, color: OColors.white),
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Localised name of a question language code.
String questionLanguageName(BuildContext context, String code) {
  final key = 'home.lang.$code';
  return Strings.has(key) ? context.t(key) : code.toUpperCase();
}

/// Localised category name (`category.<id>`, `null` = Mixed).
String categoryName(BuildContext context, String? id) {
  final key = 'category.${id ?? 'mixed'}';
  return Strings.has(key) ? context.t(key) : id ?? context.t('category.mixed');
}

/// "4 players · 10 questions · 11 seconds each" from `/v1/client-config`; falls back to copy without numbers the
/// server has not sent.
String quickSummary(BuildContext context, Json? config) {
  final quick = (config?['quick'] as Map?) ?? const {};
  final q = quick['questions'];
  final s = quick['seconds'];
  if (q is num && s is num) return context.t('home.play.quick.summary', {'q': q.toInt(), 's': s.toInt()});
  return context.t('home.play.quick.summary_short');
}

String modeRules(BuildContext context, String mode, Json? config) =>
    mode == 'SURVIVAL' ? context.t('home.play.survival.summary') : quickSummary(context, config);

/// "How it works" bullets for a mode, shown while matchmaking and on the ready countdown (playtest 2026-09-27:
/// players must see the rules before the first question). Numbers come from `/v1/client-config`.
class MatchRulesCard extends StatelessWidget {
  const MatchRulesCard({super.key, required this.mode, this.config});

  final String mode;
  final Json? config;

  @override
  Widget build(BuildContext context) {
    final quick = (config?['quick'] as Map?) ?? const {};
    final survival = (config?['survival'] as Map?) ?? const {};
    int? read(Map m, String key) => (m[key] as num?)?.toInt();
    final List<(IconData, String)> rules;
    if (mode == 'SURVIVAL') {
      final seconds = read(survival, 'seconds');
      rules = [
        (Icons.close_rounded, context.t('home.rules.survival.out')),
        if (seconds != null) (Icons.timer_outlined, context.t('home.rules.survival.timer', {'s': seconds})),
        (Icons.emoji_events_outlined, context.t('home.rules.survival.win')),
      ];
    } else {
      final seconds = read(quick, 'seconds');
      final max = read(quick, 'max_points') ?? seconds;
      final wrong = read(quick, 'wrong_penalty');
      rules = [
        (Icons.bolt_rounded, context.t('home.rules.quick.first')),
        if (max != null) (Icons.speed_rounded, context.t('home.rules.quick.speed', {'max': max})),
        if (wrong != null) (Icons.remove_circle_outline_rounded,
            context.t('home.rules.quick.wrong', {'wrong': wrong.abs()})),
      ];
    }
    return Container(
      key: const Key('match-rules'),
      padding: const EdgeInsets.all(OSpace.lg),
      decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.card)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(context.t('home.rules.title'), style: OText.labelSm.copyWith(color: OColors.primary)),
          for (final (icon, text) in rules) ...[
            const SizedBox(height: OSpace.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, size: 18, color: OColors.primary),
                const SizedBox(width: OSpace.sm),
                Expanded(child: Text(text, style: OText.bodyMd)),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// Pill button in an arbitrary accent (the shared OButton palette has no pink/secondary style).
class HomeAccentButton extends StatelessWidget {
  const HomeAccentButton({super.key, required this.label, required this.onPressed, required this.color,
      this.foreground = OColors.white});

  final String label;
  final VoidCallback? onPressed;
  final Color color;
  final Color foreground;

  @override
  Widget build(BuildContext context) => FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: color,
          foregroundColor: foreground,
          minimumSize: const Size.fromHeight(54),
          shape: const StadiumBorder(),
          textStyle: OText.labelLg,
          elevation: 0,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
            const SizedBox(width: OSpace.sm),
            const Icon(Icons.arrow_forward_rounded, size: 20),
          ],
        ),
      );
}
