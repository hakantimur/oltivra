import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';

/// Package-local building blocks shared by the settings (P07) and store (P08) screens.

/// White rounded group holding [SettingsTile]s separated by hairline dividers.
class SettingsGroup extends StatelessWidget {
  const SettingsGroup({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: OColors.white,
          borderRadius: BorderRadius.circular(ORadius.md),
          boxShadow: OShadow.card,
        ),
        clipBehavior: Clip.antiAlias,
        child: Material(
          type: MaterialType.transparency,
          child: Column(
            children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0) const Divider(height: 1, indent: 76, color: OColors.divider),
                children[i],
              ],
            ],
          ),
        ),
      );
}

/// A settings row: tinted leading icon, title, optional subtitle and chevron.
class SettingsTile extends StatelessWidget {
  const SettingsTile({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.onTap,
    this.danger = false,
    this.trailing,
    this.iconBackground,
    this.iconColor,
    this.badge,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final VoidCallback? onTap;
  final bool danger;
  final Widget? trailing;
  final Color? iconBackground;
  final Color? iconColor;
  final Widget? badge;

  @override
  Widget build(BuildContext context) {
    final fg = danger ? OColors.coral : OColors.ink;
    return InkWell(
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 64),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: iconBackground ?? (danger ? OColors.rose : OColors.surfaceContainer),
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, size: 22, color: iconColor ?? (danger ? OColors.coral : OColors.ink)),
              ),
              const SizedBox(width: OSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: OSpace.sm,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(title, style: OText.labelLg.copyWith(color: fg)),
                        ?badge,
                      ],
                    ),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(subtitle!, style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: OSpace.sm),
              trailing ??
                  (onTap == null
                      ? const SizedBox.shrink()
                      : Icon(Icons.chevron_right_rounded, color: danger ? OColors.coral : OColors.inkSubtle)),
            ],
          ),
        ),
      ),
    );
  }
}

/// Soft tinted explanation card ("Competitive integrity", "Reports stay confidential").
class InfoBanner extends StatelessWidget {
  const InfoBanner({
    super.key,
    required this.icon,
    required this.body,
    this.title,
    this.background = OColors.surfaceContainer,
    this.iconBackground = OColors.mint,
    this.iconColor = OColors.primary,
  });

  final IconData icon;
  final String? title;
  final String body;
  final Color background;
  final Color iconBackground;
  final Color iconColor;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(OSpace.lg),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(ORadius.card)),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(color: iconBackground, shape: BoxShape.circle),
              child: Icon(icon, size: 20, color: iconColor),
            ),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (title != null) ...[
                    Text(title!, style: OText.labelLg),
                    const SizedBox(height: 2),
                  ],
                  Text(body, style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                ],
              ),
            ),
          ],
        ),
      );
}

/// Small uppercase caption above a group ("CURRENTLY RESTRICTED").
class SettingsCaption extends StatelessWidget {
  const SettingsCaption(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(OSpace.xs, OSpace.xl, OSpace.xs, OSpace.sm),
        child: Row(
          children: [
            Expanded(
              child: Text(text.toUpperCase(), style: OText.labelSm.copyWith(color: OColors.onSurfaceVariant)),
            ),
            ?trailing,
          ],
        ),
      );
}

/// Large centred hero icon used by confirmation / warning states.
class HeroIcon extends StatelessWidget {
  const HeroIcon({super.key, required this.icon, this.background = OColors.mint, this.color = OColors.primary,
      this.size = 96});

  final IconData icon;
  final Color background;
  final Color color;
  final double size;

  @override
  Widget build(BuildContext context) => Center(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(color: background, shape: BoxShape.circle),
          child: Icon(icon, size: size * 0.46, color: color),
        ),
      );
}
