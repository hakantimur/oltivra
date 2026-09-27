import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';

/// Compact league + level summary used on every social card (P05 guardrail: same chip everywhere).
class LeagueChip extends StatelessWidget {
  const LeagueChip({super.key, this.league, this.level});

  final String? league;
  final int? level;

  @override
  Widget build(BuildContext context) {
    final parts = <Widget>[];
    if (league != null) {
      final color = leagueColor(league!);
      parts.add(Container(
        padding: const EdgeInsets.symmetric(horizontal: OSpace.sm, vertical: 3),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(ORadius.pill),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.shield_outlined, size: 13, color: color),
          const SizedBox(width: 4),
          Flexible(
            child: Text(context.t('league.$league'),
                style: OText.labelSm.copyWith(color: OColors.ink), overflow: TextOverflow.ellipsis),
          ),
        ]),
      ));
    }
    if (level != null) {
      parts.add(Text(context.t('level.short', {'level': level}),
          style: OText.labelSm.copyWith(color: OColors.inkSubtle)));
    }
    if (parts.isEmpty) return const SizedBox.shrink();
    return Wrap(spacing: OSpace.sm, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: parts);
  }
}

/// A player row: curated avatar, username, league summary / subtitle and one trailing action.
class PlayerCard extends StatelessWidget {
  const PlayerCard({super.key, required this.player, this.subtitle, this.trailing, this.onTap, this.footer,
      this.tag});

  /// Card fields as returned by the backend: public_id, username, avatar_id, frame_id, league?, level?.
  final Json player;
  final Widget? subtitle;
  final Widget? trailing;
  final Widget? footer;
  final Widget? tag;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final name = (player['username'] ?? player['username_display'] ?? '') as String;
    return Padding(
      padding: const EdgeInsets.only(bottom: OSpace.md),
      child: OCard(
        onTap: onTap,
        radius: ORadius.card,
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                OAvatar(avatarId: player['avatar_id'] as String?, frameId: player['frame_id'] as String?, size: 52),
                const SizedBox(width: OSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Flexible(
                          child: Text(name, style: OText.headlineSm, maxLines: 1, overflow: TextOverflow.ellipsis),
                        ),
                        if (tag != null) ...[const SizedBox(width: OSpace.sm), tag!],
                      ]),
                      const SizedBox(height: 4),
                      subtitle ??
                          LeagueChip(league: player['league'] as String?, level: (player['level'] as num?)?.toInt()),
                    ],
                  ),
                ),
                if (trailing != null) ...[const SizedBox(width: OSpace.sm), trailing!],
              ],
            ),
            if (footer != null) ...[const SizedBox(height: OSpace.md), footer!],
          ],
        ),
      ),
    );
  }
}

enum SmallActionStyle { primary, pink, muted }

/// Compact pill action for list rows (the full-width [OButton] is reserved for the screen's main action).
class SmallAction extends StatelessWidget {
  const SmallAction({super.key, required this.label, required this.onPressed, this.icon,
      this.style = SmallActionStyle.primary, this.loading = false});

  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final SmallActionStyle style;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = switch (style) {
      SmallActionStyle.primary => (OColors.turquoise, OColors.white),
      SmallActionStyle.pink => (OColors.pink, OColors.white),
      SmallActionStyle.muted => (OColors.surfaceContainer, OColors.ink),
    };
    return FilledButton(
      onPressed: loading ? null : onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: bg,
        foregroundColor: fg,
        disabledBackgroundColor: style == SmallActionStyle.muted ? bg : bg.withValues(alpha: 0.45),
        disabledForegroundColor: style == SmallActionStyle.muted ? OColors.inkSubtle : fg,
        minimumSize: const Size(48, 44),
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg),
        textStyle: OText.labelMd,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(ORadius.pill)),
        elevation: 0,
      ),
      child: loading
          ? SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2, color: fg))
          : Row(mainAxisSize: MainAxisSize.min, children: [
              if (icon != null) ...[Icon(icon, size: 18), const SizedBox(width: 6)],
              Text(label),
            ]),
    );
  }
}

/// Confirmation dialog for destructive social actions (block, remove friend, leave lobby).
Future<bool> confirmAction(BuildContext context, {required String title, required String body,
    required String confirm}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(ctx.t('action.cancel'))),
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(true),
          style: TextButton.styleFrom(foregroundColor: OColors.coral),
          child: Text(confirm),
        ),
      ],
    ),
  );
  return ok == true;
}
