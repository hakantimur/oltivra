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
