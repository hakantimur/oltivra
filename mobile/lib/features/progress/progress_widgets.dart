import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';

/// Package-local building blocks shared by the progress screens.

/// "Resets in 14h" style label counting down to a server `*_at_ms` deadline (display only).
class ProgressCountdown extends ConsumerStatefulWidget {
  const ProgressCountdown({super.key, required this.endsAtMs, required this.labelKey, this.style});

  final int endsAtMs;

  /// String key with a `{time}` placeholder.
  final String labelKey;
  final TextStyle? style;

  @override
  ConsumerState<ProgressCountdown> createState() => _ProgressCountdownState();
}

class _ProgressCountdownState extends ConsumerState<ProgressCountdown> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final left = Duration(milliseconds: widget.endsAtMs - ref.read(serverClockProvider).nowMs());
    final text = left.isNegative ? context.t('progress.resetting') : _format(context, left);
    return Text(context.t(widget.labelKey, {'time': text}),
        style: widget.style ?? OText.labelMd.copyWith(color: OColors.inkSubtle));
  }

  String _format(BuildContext context, Duration d) {
    if (d.inDays >= 1) {
      final h = d.inHours - d.inDays * 24;
      return h > 0 ? '${shortDuration(context, d)} ${context.t('time.hours_short', {'n': h})}' : shortDuration(context, d);
    }
    if (d.inHours >= 1) {
      final m = d.inMinutes - d.inHours * 60;
      return m > 0 ? '${shortDuration(context, d)} ${context.t('time.minutes_short', {'n': m})}' : shortDuration(context, d);
    }
    return shortDuration(context, d);
  }
}

/// Compact league treatment ("Silver") tinted with the league accent.
class LeagueChip extends StatelessWidget {
  const LeagueChip(this.league, {super.key});

  final String league;

  @override
  Widget build(BuildContext context) {
    final color = leagueColor(league);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: OSpace.sm, vertical: 2),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(ORadius.pill)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(leagueIcon(league), size: 12, color: color),
          const SizedBox(width: 4),
          Text(context.t('league.$league'), style: OText.labelSm.copyWith(color: _readable(color))),
        ],
      ),
    );
  }
}

/// Darkens light league accents so text stays legible on tinted backgrounds.
Color _readable(Color c) => Color.lerp(c, OColors.ink, 0.35)!;

IconData leagueIcon(String league) => switch (league) {
      'BRONZE' => Icons.shield_outlined,
      'SILVER' => Icons.workspace_premium_outlined,
      'GOLD' => Icons.military_tech_rounded,
      'PLATINUM' => Icons.auto_awesome_rounded,
      'DIAMOND' => Icons.diamond_rounded,
      'MASTER' => Icons.emoji_events_rounded,
      'LEGEND' => Icons.stars_rounded,
      _ => Icons.hourglass_top_rounded,
    };

/// League crest: a tinted circle with the league glyph.
class LeagueCrest extends StatelessWidget {
  const LeagueCrest({super.key, required this.league, this.size = 96});

  final String league;
  final double size;

  @override
  Widget build(BuildContext context) {
    final color = leagueColor(league);
    return Semantics(
      label: context.t('league.$league'),
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [color.withValues(alpha: 0.25), color.withValues(alpha: 0.55)],
          ),
          border: Border.all(color: color, width: 3),
        ),
        child: Icon(leagueIcon(league), size: size * 0.5, color: _readable(color)),
      ),
    );
  }
}

/// Material icon for a badge catalog icon name (backend `catalog/data.py`).
IconData badgeIcon(String? name) => switch (name) {
      'bolt' => Icons.bolt_rounded,
      'military_tech' => Icons.military_tech_rounded,
      'local_fire_department' => Icons.local_fire_department_rounded,
      'workspace_premium' => Icons.workspace_premium_rounded,
      'crown' => Icons.emoji_events_rounded,
      'public' => Icons.public_rounded,
      'science' => Icons.science_rounded,
      'diamond' => Icons.diamond_rounded,
      'stars' => Icons.stars_rounded,
      _ => Icons.verified_rounded,
    };

/// Stat card: label, big number, unit, icon ("Best streak · 7 wins").
class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.label, required this.value, required this.unit, required this.icon,
      required this.accent});

  final String label;
  final int value;
  final String unit;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) => OCard(
        padding: const EdgeInsets.all(OSpace.lg),
        child: Semantics(
          label: '$label: $value $unit',
          excludeSemantics: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(child: Text(label, style: OText.labelMd, maxLines: 2, overflow: TextOverflow.ellipsis)),
                  Container(
                    width: 32,
                    height: 32,
                    decoration: BoxDecoration(color: accent.withValues(alpha: 0.16), shape: BoxShape.circle),
                    child: Icon(icon, size: 18, color: _readable(accent)),
                  ),
                ],
              ),
              const SizedBox(height: OSpace.md),
              Wrap(
                crossAxisAlignment: WrapCrossAlignment.end,
                spacing: OSpace.xs,
                children: [
                  Text('$value', style: OText.displayStat.copyWith(fontSize: 36, height: 1.1)),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(unit.toUpperCase(), style: OText.labelMd.copyWith(color: _readable(accent))),
                  ),
                ],
              ),
            ],
          ),
        ),
      );
}

/// Round tinted icon used as the leading element of list rows.
class RowIcon extends StatelessWidget {
  const RowIcon(this.icon, {super.key, this.color = OColors.primary, this.background = OColors.mint, this.size = 44});

  final IconData icon;
  final Color color;
  final Color background;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: background, shape: BoxShape.circle),
        child: Icon(icon, size: size * 0.5, color: color),
      );
}

/// Loading / error / data switch for Riverpod async values in this package.
Widget progressAsync<T>(AsyncValue<T> value, Widget Function(T data) data, {VoidCallback? onRetry}) =>
    asyncBody<T>(isLoading: value.isLoading, error: value.error, value: value.value, data: data, onRetry: onRetry);
