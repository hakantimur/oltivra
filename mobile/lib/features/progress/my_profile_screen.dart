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
import '../../widgets/o_widgets.dart';
import 'progress_api.dart';
import 'progress_widgets.dart';

/// Profile tab (P06 my_profile): a confident player card — avatar + frame, name, level/XP, league, streaks,
/// crowns, featured badges, recent matches and routes to stats, achievements, missions and settings.
class MyProfileScreen extends ConsumerWidget {
  const MyProfileScreen({super.key});

  Future<void> _refresh(WidgetRef ref) async {
    ref.invalidate(matchHistoryProvider);
    ref.invalidate(categoryStatsProvider);
    await Future.wait<void>([
      reloadOwnProfile(ref).catchError((_) {}),
      ref.read(matchHistoryProvider.future).then((_) {}, onError: (_) {}),
    ]);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sessionValue = ref.watch(sessionProvider);
    final session = sessionValue.value;
    final profile = session?.profile;

    return OPage(
      title: context.t('progress.profile.title'),
      showBack: false,
      onRefresh: () => _refresh(ref),
      actions: [
        IconButton(
          tooltip: context.t('progress.profile.settings'),
          icon: const Icon(Icons.settings_outlined),
          onPressed: () => context.push(Routes.settings),
        ),
      ],
      children: [
        if (profile == null)
          sessionValue.hasError
              ? OErrorView(error: sessionValue.error!, onRetry: () => ref.read(sessionProvider.notifier).refresh())
              : const OLoading()
        else ...[
          _PlayerCard(profile: profile),
          ..._stats(context, profile),
          const SizedBox(height: OSpace.lg),
          _LinkCard(
            icon: Icons.donut_large_rounded,
            color: OColors.primary,
            background: OColors.mint,
            title: context.t('progress.profile.category_stats'),
            subtitle: _accuracySubtitle(context, ref),
            onTap: () => context.push(Routes.categoryStats),
          ),
          const SizedBox(height: OSpace.md),
          _LinkCard(
            icon: Icons.military_tech_rounded,
            color: OColors.secondary,
            background: OColors.rose,
            title: context.t('progress.profile.achievements'),
            subtitle: _achievementsSubtitle(context, profile),
            onTap: () => context.push(Routes.achievements),
          ),
          const SizedBox(height: OSpace.md),
          _LinkCard(
            icon: Icons.flag_rounded,
            color: OColors.tertiary,
            background: OColors.sun,
            title: context.t('progress.profile.missions'),
            subtitle: context.t('progress.profile.missions_body'),
            onTap: () => context.push(Routes.missions),
          ),
          _FeaturedBadges(ids: ((profile['featured_badge_ids'] as List?) ?? const []).whereType<String>().toList()),
          const _RecentMatches(),
        ],
      ],
    );
  }

  List<Widget> _stats(BuildContext context, Json p) {
    final tiles = <Widget>[
      if (asInt(p['quick_current_ranked_win_streak']) case final v?)
        StatTile(label: context.t('progress.stat.live_streak'), value: v, unit: context.t('progress.unit.wins'),
            icon: Icons.local_fire_department_rounded, accent: OColors.yellow),
      if (asInt(p['quick_best_ranked_win_streak']) case final v?)
        StatTile(label: context.t('progress.stat.best_streak'), value: v, unit: context.t('progress.unit.wins'),
            icon: Icons.stars_rounded, accent: OColors.turquoise),
      if (asInt(p['survival_ranked_crowns_lifetime']) case final v?)
        StatTile(label: context.t('progress.stat.crowns'), value: v, unit: context.t('progress.unit.crowns'),
            icon: Icons.emoji_events_rounded, accent: OColors.yellow),
      if (asInt(p['quick_ranked_wins_lifetime']) case final v?)
        StatTile(label: context.t('progress.stat.ranked_wins'), value: v, unit: context.t('progress.unit.wins'),
            icon: Icons.military_tech_rounded, accent: OColors.pink),
      if (asInt(p['matches_completed']) case final v?)
        StatTile(label: context.t('progress.stat.matches'), value: v, unit: context.t('progress.unit.played'),
            icon: Icons.sports_esports_rounded, accent: OColors.pink),
    ];
    if (tiles.isEmpty) return const [];
    final rows = <Widget>[];
    for (var i = 0; i < tiles.length; i += 2) {
      rows.add(Padding(
        padding: const EdgeInsets.only(bottom: OSpace.gutter),
        child: IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Expanded(child: tiles[i]),
            const SizedBox(width: OSpace.gutter),
            Expanded(child: i + 1 < tiles.length ? tiles[i + 1] : const SizedBox()),
          ]),
        ),
      ));
    }
    return [OSectionHeader(context.t('progress.profile.competitive_stats')), ...rows];
  }

  String? _accuracySubtitle(BuildContext context, WidgetRef ref) {
    final stats = ref.watch(categoryStatsProvider).value;
    if (stats == null) return context.t('progress.profile.category_stats_body');
    var answered = 0, correct = 0;
    for (final c in asJsonList(stats['categories'])) {
      answered += asInt(c['answered']) ?? 0;
      correct += asInt(c['correct']) ?? 0;
    }
    if (answered == 0) return context.t('progress.profile.category_stats_body');
    return context.t('progress.profile.overall_accuracy', {'pct': (correct * 100 / answered).round()});
  }

  String _achievementsSubtitle(BuildContext context, Json p) {
    final badges = ((p['badge_ids'] as List?) ?? const []).length;
    return badges > 0
        ? context.t('progress.profile.badges_unlocked', {'n': badges})
        : context.t('progress.profile.achievements_body');
  }
}

class _PlayerCard extends StatelessWidget {
  const _PlayerCard({required this.profile});

  final Json profile;

  @override
  Widget build(BuildContext context) {
    final lp = asJson(profile['level_progress']);
    final level = asInt(lp['level']) ?? asInt(profile['level']);
    final into = asInt(lp['xp_into_level']);
    final forLevel = asInt(lp['xp_for_level']);
    final league = (profile['league'] as String?) ?? 'UNRANKED';
    final name = (profile['username_display'] as String?) ?? '';

    return Container(
      padding: const EdgeInsets.fromLTRB(OSpace.xl, OSpace.lg, OSpace.xl, OSpace.xl),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(ORadius.lg),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [OColors.surfaceContainer, OColors.rose],
        ),
      ),
      child: Column(children: [
        Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            onPressed: () => context.push(Routes.editProfile),
            icon: const Icon(Icons.tune_rounded, size: 18),
            label: Text(context.t('progress.profile.edit')),
            style: TextButton.styleFrom(
              backgroundColor: OColors.white.withValues(alpha: 0.7),
              foregroundColor: OColors.ink,
              minimumSize: const Size(48, 40),
            ),
          ),
        ),
        Stack(clipBehavior: Clip.none, alignment: Alignment.bottomCenter, children: [
          OAvatar(avatarId: profile['avatar_id'] as String?, frameId: profile['frame_id'] as String?, size: 128),
          if (level != null)
            Positioned(
              bottom: -12,
              child: OPill(
                context.t('level.short', {'level': level}).toUpperCase(),
                icon: Icons.verified_rounded,
                background: OColors.primary,
                foreground: OColors.white,
              ),
            ),
        ]),
        const SizedBox(height: OSpace.xl),
        Text(name, style: OText.headlineLg, textAlign: TextAlign.center, maxLines: 1, overflow: TextOverflow.ellipsis),
        const SizedBox(height: OSpace.sm),
        LeagueChip(league),
        if (into != null && forLevel != null && forLevel > 0) ...[
          const SizedBox(height: OSpace.lg),
          Row(children: [
            Expanded(
              child: Text(context.t('progress.profile.level_progress', {'level': (level ?? 1) + 1}),
                  style: OText.labelMd.copyWith(color: OColors.inkSubtle)),
            ),
            Text(context.t('progress.profile.xp_fraction', {'into': into, 'total': forLevel}),
                style: OText.tabular(OText.labelMd)),
          ]),
          const SizedBox(height: OSpace.sm),
          OProgressBar(value: into / forLevel, height: 10, background: OColors.white),
        ],
      ]),
    );
  }
}

class _LinkCard extends StatelessWidget {
  const _LinkCard({required this.icon, required this.color, required this.background, required this.title,
      this.subtitle, required this.onTap});

  final IconData icon;
  final Color color;
  final Color background;
  final String title;
  final String? subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => OCard(
        onTap: onTap,
        radius: ORadius.lg,
        child: Row(children: [
          RowIcon(icon, color: color, background: background, size: 52),
          const SizedBox(width: OSpace.lg),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: OText.headlineSm),
              if (subtitle != null)
                Text(subtitle!, style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            ]),
          ),
          const Icon(Icons.chevron_right_rounded),
        ]),
      );
}

class _FeaturedBadges extends ConsumerWidget {
  const _FeaturedBadges({required this.ids});

  final List<String> ids;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ids.isEmpty) return const SizedBox.shrink();
    final catalog = ref.watch(catalogProvider('cosmetics')).value;
    final byId = {for (final b in asJsonList(catalog?['badges'])) b['id']: b};
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      OSectionHeader(context.t('progress.profile.featured_badges'),
          trailing: context.t('progress.profile.manage'), onTrailing: () => context.push(Routes.achievements)),
      Row(children: [
        for (var i = 0; i < 3; i++) ...[
          if (i > 0) const SizedBox(width: OSpace.sm),
          Expanded(
            child: i < ids.length
                ? OCard(
                    padding: const EdgeInsets.symmetric(vertical: OSpace.lg, horizontal: OSpace.sm),
                    child: Column(children: [
                      RowIcon(badgeIcon(byId[ids[i]]?['icon'] as String?),
                          color: OColors.tertiary, background: OColors.sun),
                      const SizedBox(height: OSpace.sm),
                      Text(context.pick(byId[ids[i]]?['names'] as Map?, fallback: ''),
                          style: OText.labelMd, textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis),
                    ]),
                  )
                : const SizedBox(),
          ),
        ],
      ]),
    ]);
  }
}

class _RecentMatches extends ConsumerWidget {
  const _RecentMatches();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final history = ref.watch(matchHistoryProvider);
    final matches = asJsonList(history.value?['matches']);
    if (history.hasError && history.value == null) {
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        OSectionHeader(context.t('progress.profile.recent_matches')),
        OErrorView(error: history.error!, onRetry: () => ref.invalidate(matchHistoryProvider)),
      ]);
    }
    if (history.value == null) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      OSectionHeader(context.t('progress.profile.recent_matches')),
      if (matches.isEmpty)
        OEmptyState(
          icon: Icons.history_rounded,
          title: context.t('progress.history.empty_title'),
          body: context.t('progress.history.empty_body'),
        )
      else
        for (final m in matches) ...[_MatchRow(match: m), const SizedBox(height: OSpace.sm)],
    ]);
  }
}

class _MatchRow extends ConsumerWidget {
  const _MatchRow({required this.match});

  final Json match;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = (match['mode'] as String?) ?? 'QUICK';
    final cancelled = match['cancelled'] == true;
    final place = asInt(match['place']);
    final players = asInt(match['players']);
    final score = asInt(match['score']);
    final xp = asInt(match['xp_awarded']);
    final at = asInt(match['completed_at_ms']);
    final won = !cancelled && place == 1;
    final details = [
      if (at != null)
        context.t('progress.history.ago', {
          'time': shortDuration(context, Duration(milliseconds: ref.read(serverClockProvider).nowMs() - at)),
        }),
      if (score != null && mode != 'SURVIVAL') context.t('progress.history.score', {'n': score}),
    ].join(' · ');

    return OCard(
      padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
      child: Row(children: [
        RowIcon(
          mode == 'SURVIVAL' ? Icons.shield_outlined : Icons.bolt_rounded,
          color: won ? OColors.tertiary : OColors.primary,
          background: won ? OColors.sun : OColors.mint,
          size: 40,
        ),
        const SizedBox(width: OSpace.md),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Flexible(child: Text(context.t('mode.$mode'), style: OText.labelLg, overflow: TextOverflow.ellipsis)),
              if (match['ranked'] == true) ...[
                const SizedBox(width: OSpace.xs),
                OPill(context.t('progress.history.ranked'), background: OColors.rose, foreground: OColors.secondary),
              ],
            ]),
            if (details.isNotEmpty)
              Text(details, style: OText.bodySm.copyWith(color: OColors.inkSubtle), overflow: TextOverflow.ellipsis),
          ]),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(
            cancelled
                ? context.t('progress.history.cancelled')
                : place != null
                    ? (players != null
                        ? context.t('progress.history.place_of', {'place': place, 'players': players})
                        : '#$place')
                    : '',
            style: OText.labelLg.copyWith(color: won ? OColors.tertiary : OColors.ink),
          ),
          if (xp != null && xp > 0)
            Text(context.t('progress.history.xp', {'n': xp}), style: OText.labelSm.copyWith(color: OColors.primary)),
        ]),
      ]),
    );
  }
}
