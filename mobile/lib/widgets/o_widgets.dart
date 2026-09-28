import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../l10n/strings.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';

// ------------------------------------------------------------------------------------------ buttons

enum OButtonStyle { primary, secondary, dark, danger, ghost }

/// Pill button from the foundation: 54px tall, one primary action per screen.
class OButton extends StatelessWidget {
  const OButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.trailingIcon,
    this.style = OButtonStyle.primary,
    this.loading = false,
    this.leading,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final IconData? trailingIcon;
  final Widget? leading;
  final OButtonStyle style;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final (bg, fg, border) = switch (style) {
      OButtonStyle.primary => (OColors.turquoise, OColors.white, null),
      OButtonStyle.secondary => (OColors.white, OColors.ink, OColors.divider),
      OButtonStyle.dark => (OColors.ink, OColors.white, null),
      OButtonStyle.danger => (OColors.coral, OColors.white, null),
      OButtonStyle.ghost => (Colors.transparent, OColors.ink, null),
    };
    final disabled = onPressed == null || loading;
    final child = loading
        ? SizedBox.square(dimension: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: fg))
        : Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (leading != null) ...[leading!, const SizedBox(width: OSpace.md)],
              if (icon != null) ...[Icon(icon, size: 20), const SizedBox(width: OSpace.sm)],
              Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
              if (trailingIcon != null) ...[const SizedBox(width: OSpace.sm), Icon(trailingIcon, size: 20)],
            ],
          );
    return Semantics(
      button: true,
      enabled: !disabled,
      child: FilledButton(
        onPressed: disabled ? null : onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: bg,
          foregroundColor: fg,
          disabledBackgroundColor: style == OButtonStyle.primary ? OColors.divider : bg.withValues(alpha: 0.6),
          disabledForegroundColor: style == OButtonStyle.primary ? OColors.inkSubtle : fg.withValues(alpha: 0.7),
          minimumSize: const Size.fromHeight(54),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(ORadius.pill),
            side: border == null ? BorderSide.none : BorderSide(color: border),
          ),
          textStyle: OText.labelLg,
          elevation: 0,
        ),
        child: child,
      ),
    );
  }
}

class OCircleButton extends StatelessWidget {
  const OCircleButton({super.key, required this.icon, required this.onPressed, this.tooltip, this.color, this.size = 44});

  final IconData icon;
  final VoidCallback? onPressed;
  final String? tooltip;
  final Color? color;
  final double size;

  @override
  Widget build(BuildContext context) => Material(
        color: color ?? OColors.surfaceContainer,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onPressed,
          child: Tooltip(
            message: tooltip ?? '',
            child: SizedBox.square(dimension: size, child: Icon(icon, size: size * 0.5, color: OColors.ink)),
          ),
        ),
      );
}

// ------------------------------------------------------------------------------------------ surfaces

class OCard extends StatelessWidget {
  const OCard({super.key, required this.child, this.padding = const EdgeInsets.all(OSpace.lg), this.color, this.onTap,
      this.radius = ORadius.md, this.border});

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final VoidCallback? onTap;
  final double radius;
  final Color? border;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: color ?? OColors.white,
          borderRadius: BorderRadius.circular(radius),
          boxShadow: OShadow.card,
          border: border == null ? null : Border.all(color: border!, width: 1.5),
        ),
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            borderRadius: BorderRadius.circular(radius),
            onTap: onTap,
            child: Padding(padding: padding, child: child),
          ),
        ),
      );
}

class OSectionHeader extends StatelessWidget {
  const OSectionHeader(this.title, {super.key, this.trailing, this.onTrailing});

  final String title;
  final String? trailing;
  final VoidCallback? onTrailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: OSpace.xl, bottom: OSpace.md),
        child: Row(
          children: [
            Expanded(child: Text(title, style: OText.headlineMd)),
            if (trailing != null)
              GestureDetector(
                onTap: onTrailing,
                child: Text(trailing!, style: OText.labelMd.copyWith(color: OColors.inkSubtle)),
              ),
          ],
        ),
      );
}

/// Small rounded status label ("LIVE DUEL QUEUE", "High Stakes", "Active").
class OPill extends StatelessWidget {
  const OPill(this.label, {super.key, this.background = OColors.mint, this.foreground = OColors.primary, this.icon,
      this.dot = false});

  final String label;
  final Color background;
  final Color foreground;
  final IconData? icon;
  final bool dot;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: OSpace.md, vertical: 6),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(ORadius.pill)),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (dot) ...[
              Container(width: 8, height: 8, decoration: BoxDecoration(color: foreground, shape: BoxShape.circle)),
              const SizedBox(width: 6),
            ],
            if (icon != null) ...[Icon(icon, size: 14, color: foreground), const SizedBox(width: 4)],
            Flexible(
              child: Text(label, style: OText.labelSm.copyWith(color: foreground), overflow: TextOverflow.ellipsis),
            ),
          ],
        ),
      );
}

class OProgressBar extends StatelessWidget {
  const OProgressBar({super.key, required this.value, this.color = OColors.turquoise, this.height = 8,
      this.background = OColors.surfaceContainer});

  final double value;
  final Color color;
  final Color background;
  final double height;

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(ORadius.pill),
        child: LinearProgressIndicator(
          value: value.clamp(0, 1).toDouble(),
          minHeight: height,
          color: color,
          backgroundColor: background,
        ),
      );
}

/// Standard page frame: title bar with back/close, scrollable body with the 20px margin.
class OPage extends StatelessWidget {
  const OPage({super.key, this.title, required this.children, this.actions, this.bottom, this.leading,
      this.padding = const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
      this.showBack = true, this.onRefresh});

  final String? title;
  final List<Widget> children;
  final List<Widget>? actions;
  final Widget? bottom;
  final Widget? leading;
  final EdgeInsets padding;
  final bool showBack;
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context) {
    Widget list = ListView(padding: padding, children: children);
    if (onRefresh != null) list = RefreshIndicator(onRefresh: onRefresh!, child: list);
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: showBack,
        leading: leading,
        title: title == null ? null : Text(title!),
        centerTitle: true,
        actions: actions,
      ),
      body: SafeArea(top: false, child: list),
      bottomNavigationBar: bottom == null
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.lg),
                child: bottom,
              ),
            ),
    );
  }
}

// ------------------------------------------------------------------------------------------ states

class OLoading extends StatelessWidget {
  const OLoading({super.key});

  @override
  Widget build(BuildContext context) =>
      const Center(child: Padding(padding: EdgeInsets.all(OSpace.xl), child: CircularProgressIndicator()));
}

class OEmptyState extends StatelessWidget {
  const OEmptyState({super.key, required this.icon, required this.title, this.body, this.action});

  final IconData icon;
  final String title;
  final String? body;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: OSpace.xxl, horizontal: OSpace.lg),
        child: Column(
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: const BoxDecoration(color: OColors.mint, shape: BoxShape.circle),
              child: Icon(icon, size: 34, color: OColors.primary),
            ),
            const SizedBox(height: OSpace.lg),
            Text(title, style: OText.headlineSm, textAlign: TextAlign.center),
            if (body != null) ...[
              const SizedBox(height: OSpace.sm),
              Text(body!, style: OText.bodyMd.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
            ],
            if (action != null) ...[const SizedBox(height: OSpace.xl), action!],
          ],
        ),
      );
}

class OErrorView extends StatelessWidget {
  const OErrorView({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => OEmptyState(
        icon: Icons.cloud_off_rounded,
        title: errorText(context, error),
        action: onRetry == null
            ? null
            : SizedBox(width: 200, child: OButton(label: context.t('action.retry'), onPressed: onRetry)),
      );
}

/// Human message for any error (backend envelope codes are localised under `error.<CODE>`).
String errorText(BuildContext context, Object error) {
  if (error is ApiException) {
    final key = 'error.${error.code}';
    return Strings.has(key) ? context.t(key) : context.t('error.generic');
  }
  return context.t('error.generic');
}

void showMessage(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

void showError(BuildContext context, Object error) => showMessage(context, errorText(context, error));

/// Renders an [AsyncSnapshot]-like tri-state from Riverpod's AsyncValue without importing Riverpod here.
Widget asyncBody<T>({
  required bool isLoading,
  required Object? error,
  required T? value,
  required Widget Function(T value) data,
  VoidCallback? onRetry,
}) {
  if (error != null && value == null) return OErrorView(error: error, onRetry: onRetry);
  if (value == null) return const OLoading();
  return data(value);
}

/// Countdown label helper: "8h", "3d", "12m".
String shortDuration(BuildContext context, Duration d) {
  if (d.inDays >= 1) return context.t('time.days_short', {'n': d.inDays});
  if (d.inHours >= 1) return context.t('time.hours_short', {'n': d.inHours});
  if (d.inMinutes >= 1) return context.t('time.minutes_short', {'n': d.inMinutes});
  return context.t('time.seconds_short', {'n': d.inSeconds.clamp(0, 59)});
}

/// Icon for a category id (Material Symbols equivalents of the design's glyphs).
IconData categoryIcon(String? id) => switch (id) {
      'geography' => Icons.public_rounded,
      'history' => Icons.account_balance_rounded,
      'science_nature' => Icons.science_rounded,
      'arts_literature' => Icons.palette_rounded,
      'movies_tv' => Icons.movie_rounded,
      'music' => Icons.music_note_rounded,
      'sports' => Icons.sports_soccer_rounded,
      'technology_inventions' => Icons.memory_rounded,
      'food_culture' => Icons.restaurant_rounded,
      'animals' => Icons.pets_rounded,
      'games_internet' => Icons.sports_esports_rounded,
      'brands_logos' => Icons.storefront_rounded,
      _ => Icons.shuffle_rounded,
    };

/// League accent colours for chips and crests.
Color leagueColor(String league) => switch (league) {
      'BRONZE' => const Color(0xFFB87333),
      'SILVER' => const Color(0xFF8A94A6),
      'GOLD' => OColors.tertiaryContainer,
      'PLATINUM' => const Color(0xFF50DBC8),
      'DIAMOND' => const Color(0xFF3FA7F5),
      'MASTER' => OColors.secondary,
      'LEGEND' => const Color(0xFF7A3FF5),
      _ => OColors.inkSubtle,
    };
