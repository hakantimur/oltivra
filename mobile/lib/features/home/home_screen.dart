import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../session/session.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'home_api.dart';
import 'widgets.dart';

/// Home tab (design P02 "Home"): profile summary, Quick Battle hero, Survival entry, today's missions and a
/// compact "This week" preview. Only server-provided numbers are shown; missing tiles are hidden.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  Future<void> _refresh(WidgetRef ref) async {
    ref.invalidate(homeDailyMissionsProvider);
    ref.invalidate(homeLeagueProvider);
    ref.invalidate(homeWeeklyRankProvider);
    await Future.wait<void>([
      ref.read(sessionProvider.notifier).refresh(),
      ref.read(homeDailyMissionsProvider.future).then((_) {}, onError: (_) {}),
      ref.read(homeLeagueProvider.future).then((_) {}, onError: (_) {}),
    ]);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider).value;
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: RefreshIndicator(
          onRefresh: () => _refresh(ref),
          child: ListView(
            padding: const EdgeInsets.only(bottom: OSpace.xxl),
            children: [
              HomeTopBar(title: context.t('home.title')),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: OSpace.margin),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (session != null) ...[
                      const SizedBox(height: OSpace.sm),
                      _ProfileCard(session: session),
                    ],
                    if (session != null && session.runtimeState == 'MATCH_ACTIVE' && session.activeMatchId != null)
                      ...[const SizedBox(height: OSpace.lg), _RejoinBanner(matchId: session.activeMatchId!)],
                    const SizedBox(height: OSpace.xl),
                    const _QuickHero(),
                    if (session?.survivalEnabled ?? true) ...[
                      const SizedBox(height: OSpace.lg),
                      const _SurvivalCard(),
                    ],
                    const _MissionsSection(),
                    const _WeekSection(),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------------------------------ header

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    final league = session.league;
    final color = leagueColor(league);
    return OCard(
      padding: const EdgeInsets.all(OSpace.lg),
      onTap: () => context.go(Routes.profile),
      child: Row(
        children: [
          OAvatar(avatarId: session.avatarId, size: 60, frameId: session.frameId, online: true),
          const SizedBox(width: OSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Flexible(
                      child: Text(session.username, style: OText.headlineMd, overflow: TextOverflow.ellipsis),
                    ),
                    const SizedBox(width: OSpace.xs),
                    Text(context.t('level.short', {'level': session.level}),
                        style: OText.labelMd.copyWith(color: OColors.primary)),
                  ],
                ),
                const SizedBox(height: 2),
                Text(context.t('home.tagline'),
                    style: OText.bodySm.copyWith(color: OColors.inkSubtle), overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
          const SizedBox(width: OSpace.sm),
          OPill(context.t('league.$league'),
              background: color.withValues(alpha: 0.14),
              foreground: OColors.ink,
              icon: Icons.military_tech_rounded),
        ],
      ),
    );
  }
}

class _RejoinBanner extends StatelessWidget {
  const _RejoinBanner({required this.matchId});

  final String matchId;

  @override
  Widget build(BuildContext context) => OCard(
        color: OColors.rose,
        border: OColors.pink,
        padding: const EdgeInsets.all(OSpace.lg),
        onTap: () => context.go(Routes.match(matchId)),
        child: Row(
          children: [
            const Icon(Icons.sensors_rounded, color: OColors.secondary, size: 28),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(context.t('home.rejoin.title'), style: OText.labelLg),
                  Text(context.t('home.rejoin.body'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                ],
              ),
            ),
            const SizedBox(width: OSpace.sm),
            FilledButton(
              onPressed: () => context.go(Routes.match(matchId)),
              style: FilledButton.styleFrom(
                backgroundColor: OColors.secondary,
                minimumSize: const Size(48, 44),
                shape: const StadiumBorder(),
                textStyle: OText.labelMd,
              ),
              child: Text(context.t('home.rejoin.action')),
            ),
          ],
        ),
      );
}

// ------------------------------------------------------------------------------------------ mode entries

class _QuickHero extends StatelessWidget {
  const _QuickHero();

  @override
  Widget build(BuildContext context) => Container(
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: OColors.turquoise,
          borderRadius: BorderRadius.circular(ORadius.md),
          boxShadow: OShadow.floating,
        ),
        child: Stack(
          children: [
            Positioned(
              right: -60,
              bottom: -80,
              child: Container(
                width: 220,
                height: 220,
                decoration: BoxDecoration(color: OColors.white.withValues(alpha: 0.08), shape: BoxShape.circle),
              ),
            ),
            Positioned(
              right: 24,
              top: 20,
              child: Container(
                width: 88,
                height: 88,
                decoration: BoxDecoration(color: OColors.white.withValues(alpha: 0.12), shape: BoxShape.circle),
                child: const Icon(Icons.bolt_rounded, color: OColors.onPrimaryContainer, size: 36),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(OSpace.xl),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  OPill(context.t('home.quick.badge'),
                      background: OColors.white.withValues(alpha: 0.25),
                      foreground: OColors.onPrimaryContainer,
                      dot: true),
                  const SizedBox(height: OSpace.xl),
                  Text(context.t('home.quick.title'),
                      style: OText.headlineXlMobile.copyWith(color: OColors.onPrimaryContainer)),
                  const SizedBox(height: OSpace.xs),
                  Text(context.t('home.quick.subtitle'),
                      style: OText.bodyMd.copyWith(color: OColors.onPrimaryContainer.withValues(alpha: 0.85))),
                  const SizedBox(height: OSpace.xl),
                  HomeAccentButton(
                    label: context.t('home.quick.cta'),
                    color: OColors.white,
                    foreground: OColors.onPrimaryContainer,
                    onPressed: () => context.push(Routes.queue('QUICK')),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
}

class _SurvivalCard extends StatelessWidget {
  const _SurvivalCard();

  @override
  Widget build(BuildContext context) => OCard(
        padding: const EdgeInsets.all(OSpace.lg),
        onTap: () => context.push(Routes.queue('SURVIVAL')),
        child: Row(
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: const BoxDecoration(color: OColors.secondaryFixed, shape: BoxShape.circle),
              child: const Icon(Icons.timer_outlined, color: OColors.secondary, size: 28),
            ),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    spacing: OSpace.sm,
                    runSpacing: OSpace.xs,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(context.t('home.survival.title'), style: OText.headlineSm),
                      OPill(context.t('home.survival.badge'),
                          background: OColors.secondaryFixed, foreground: OColors.secondary),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(context.t('home.survival.subtitle'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                ],
              ),
            ),
            const SizedBox(width: OSpace.sm),
            const CircleAvatar(
              radius: 22,
              backgroundColor: OColors.surfaceContainer,
              child: Icon(Icons.chevron_right_rounded, color: OColors.ink),
            ),
          ],
        ),
      );
}

// ------------------------------------------------------------------------------------------ missions

class _MissionsSection extends ConsumerWidget {
  const _MissionsSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(homeDailyMissionsProvider);
    final data = async.value;
    final endsAt = (data?['ends_at_ms'] as num?)?.toInt();
    final remaining = endsAt == null ? null : endsAt - ref.read(serverClockProvider).nowMs();
    Widget body;
    if (async.hasError && data == null) {
      body = OCard(
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
        child: Row(
          children: [
            Expanded(child: Text(errorText(context, async.error!), style: OText.bodySm)),
            TextButton(
              onPressed: () => ref.invalidate(homeDailyMissionsProvider),
              child: Text(context.t('action.retry')),
            ),
          ],
        ),
      );
    } else if (data == null) {
      body = const OCard(child: SizedBox(height: 96, child: Center(child: CircularProgressIndicator())));
    } else {
      final missions = ((data['missions'] as List?) ?? const [])
          .whereType<Map>()
          .map((m) => m.cast<String, dynamic>())
          .take(2)
          .toList();
      body = OCard(
        padding: const EdgeInsets.all(OSpace.md),
        child: missions.isEmpty
            ? Padding(
                padding: const EdgeInsets.all(OSpace.md),
                child: Text(context.t('home.missions.empty'),
                    style: OText.bodyMd.copyWith(color: OColors.inkSubtle)),
              )
            : Column(
                children: [
                  for (var i = 0; i < missions.length; i++) ...[
                    if (i > 0) const SizedBox(height: OSpace.sm),
                    _MissionRow(mission: missions[i]),
                  ],
                ],
              ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: OSpace.xl, bottom: OSpace.md),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(child: Text(context.t('home.missions.title'), style: OText.headlineMd)),
              if (remaining != null && remaining > 0)
                Padding(
                  padding: const EdgeInsets.only(right: OSpace.sm),
                  child: Text(
                    context.t('home.missions.resets',
                        {'time': shortDuration(context, Duration(milliseconds: remaining))}),
                    style: OText.labelSm.copyWith(color: OColors.inkSubtle),
                  ),
                ),
              TextButton(
                onPressed: () => context.push(Routes.missions),
                child: Text(context.t('action.see_all'), style: OText.labelMd.copyWith(color: OColors.primary)),
              ),
            ],
          ),
        ),
        body,
      ],
    );
  }
}

class _MissionRow extends StatelessWidget {
  const _MissionRow({required this.mission});

  final Json mission;

  @override
  Widget build(BuildContext context) {
    final template = mission['template_id'] as String? ?? '';
    final target = (mission['target'] as num?)?.toInt() ?? 0;
    final progress = (mission['progress'] as num?)?.toInt() ?? 0;
    final completed = mission['completed'] == true;
    final key = 'home.mission.$template';
    final title = context.t(Strings.has(key) ? key : 'home.mission.generic', {'n': target});
    return Container(
      padding: const EdgeInsets.all(OSpace.md),
      decoration: BoxDecoration(
        color: completed ? OColors.mint : OColors.surfaceContainer.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(ORadius.card),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(completed ? Icons.check_circle_rounded : _missionIcon(template),
                  size: 22, color: completed ? OColors.success : OColors.primary),
              const SizedBox(width: OSpace.md),
              Expanded(child: Text(title, style: OText.bodyMd)),
              const SizedBox(width: OSpace.sm),
              Text(
                completed ? context.t('home.missions.done') : '$progress/$target',
                style: OText.tabular(OText.labelMd.copyWith(color: completed ? OColors.success : OColors.primary)),
              ),
            ],
          ),
          const SizedBox(height: OSpace.sm),
          OProgressBar(
            value: target <= 0 ? 0 : progress / target,
            color: completed ? OColors.success : OColors.turquoise,
            background: OColors.white,
          ),
        ],
      ),
    );
  }

  static IconData _missionIcon(String template) {
    if (template.contains('survival') || template.contains('survive')) return Icons.timer_outlined;
    if (template.contains('reaction')) return Icons.emoji_emotions_outlined;
    if (template.contains('ranked')) return Icons.military_tech_outlined;
    if (template.contains('correct')) return Icons.check_circle_outline_rounded;
    if (template.contains('points')) return Icons.stars_outlined;
    return Icons.bolt_rounded;
  }
}

// ------------------------------------------------------------------------------------------ this week

class _WeekSection extends ConsumerWidget {
  const _WeekSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final league = ref.watch(homeLeagueProvider).value;
    final me = ref.watch(homeWeeklyRankProvider).value;
    final tiles = <Widget>[];
    final rank = (me?['rank'] as num?)?.toInt();
    final leagueId = (me?['league'] as String?) ?? (league?['league'] as String?);
    if (rank != null) {
      tiles.add(_WeekTile(
        icon: Icons.leaderboard_outlined,
        label: context.t('home.week.division'),
        value: context.t('home.week.rank', {'rank': rank}),
        caption: leagueId == null ? null : context.t('home.week.division_name', {'league': context.t('league.$leagueId')}),
        onTap: () => context.go(Routes.rankings),
      ));
    } else if (league != null && leagueId != null) {
      final remaining = (league['placement_matches_remaining'] as num?)?.toInt() ?? 0;
      final next = league['next_league'] as String?;
      tiles.add(_WeekTile(
        icon: Icons.military_tech_outlined,
        label: context.t('home.week.league'),
        value: context.t('league.$leagueId'),
        caption: remaining > 0
            ? context.t('home.week.placement', {'n': remaining})
            : next != null
                ? context.t('home.week.next', {'league': context.t('league.$next')})
                : context.t('home.week.top'),
        progress: (league['progress'] as num?)?.toDouble(),
        onTap: () => context.push(Routes.league),
      ));
    }
    final xp = (league?['ranked_weekly_xp'] as num?)?.toInt() ?? (me?['ranked_weekly_xp'] as num?)?.toInt();
    if (xp != null) {
      tiles.add(_WeekTile(
        icon: Icons.trending_up_rounded,
        iconColor: OColors.tertiaryContainer,
        label: context.t('home.week.xp'),
        value: context.t('home.week.xp_value', {'n': xp}),
        caption: context.t('home.week.xp_hint'),
        onTap: () => context.go(Routes.rankings),
      ));
    }
    if (tiles.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        OSectionHeader(context.t('home.week.title')),
        IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (var i = 0; i < tiles.length; i++) ...[
                if (i > 0) const SizedBox(width: OSpace.gutter),
                Expanded(child: tiles[i]),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _WeekTile extends StatelessWidget {
  const _WeekTile({required this.icon, required this.label, required this.value, this.caption, this.onTap,
      this.progress, this.iconColor = OColors.primary});

  final IconData icon;
  final Color iconColor;
  final String label;
  final String value;
  final String? caption;
  final double? progress;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => OCard(
        padding: const EdgeInsets.all(OSpace.lg),
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: iconColor, size: 26),
                const Spacer(),
                if (onTap != null) const Icon(Icons.north_east_rounded, size: 18, color: OColors.inkSubtle),
              ],
            ),
            const SizedBox(height: OSpace.lg),
            Text(label, style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
            const SizedBox(height: 2),
            Text(value, style: OText.tabular(OText.headlineMd), maxLines: 1, overflow: TextOverflow.ellipsis),
            if (caption != null)
              Text(caption!, style: OText.bodySm.copyWith(color: OColors.inkSubtle), maxLines: 2),
            if (progress != null) ...[
              const SizedBox(height: OSpace.sm),
              OProgressBar(value: progress!, height: 6),
            ],
          ],
        ),
      );
}
