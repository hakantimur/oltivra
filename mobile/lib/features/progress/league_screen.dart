import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'progress_api.dart';
import 'progress_widgets.dart';

/// League status (P06 league_status): current league crest, abstract progress to the next league (or
/// placement matches left) and the ladder. Raw MMR is never sent to or shown by the client (spec §7.3).
class LeagueScreen extends ConsumerWidget {
  const LeagueScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(leagueStatusProvider);
    return OPage(
      title: context.t('progress.league.title'),
      onRefresh: () => ref.refresh(leagueStatusProvider.future),
      children: [
        progressAsync<Json>(status, (data) => _Body(data), onRetry: () => ref.invalidate(leagueStatusProvider)),
      ],
    );
  }
}

class _Body extends StatelessWidget {
  const _Body(this.data);

  final Json data;

  @override
  Widget build(BuildContext context) {
    final league = (data['league'] as String?) ?? 'UNRANKED';
    final next = data['next_league'] as String?;
    final progress = asDouble(data['progress']);
    final placementLeft = asInt(data['placement_matches_remaining']) ?? 0;
    final ladder = ((data['leagues'] as List?) ?? const []).whereType<String>().toList();
    final weeklyXp = asInt(data['ranked_weekly_xp']);
    final rankedMatches = asInt(data['ranked_matches_completed']);
    final unranked = league == 'UNRANKED';
    final percent = progress == null ? null : (progress * 100).round();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        OCard(
          radius: ORadius.lg,
          padding: const EdgeInsets.all(OSpace.xl),
          child: Column(children: [
            OPill(context.t(unranked ? 'progress.league.placement_pill' : 'progress.league.active_pill'), dot: true),
            const SizedBox(height: OSpace.xl),
            LeagueCrest(league: league, size: 112),
            const SizedBox(height: OSpace.lg),
            Text(
              unranked ? context.t('league.UNRANKED') : context.t('progress.league.name', {'league': context.t('league.$league')}),
              style: OText.headlineLg,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: OSpace.sm),
            Text(context.t('progress.league.context'),
                style: OText.bodyMd.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
            if (progress != null) ...[
              const SizedBox(height: OSpace.xl),
              Container(
                padding: const EdgeInsets.all(OSpace.lg),
                decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.md)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const Icon(Icons.trending_up_rounded, size: 18, color: OColors.primary),
                    const SizedBox(width: OSpace.sm),
                    Expanded(
                      child: Text(
                        unranked
                            ? context.t('progress.league.placement_title')
                            : next != null
                                ? context.t('progress.league.to_next', {'league': context.t('league.$next')})
                                : context.t('progress.league.top_league'),
                        style: OText.labelLg,
                      ),
                    ),
                    if (!unranked && next != null && percent != null)
                      Text('$percent%', style: OText.tabular(OText.labelLg)),
                  ]),
                  const SizedBox(height: OSpace.md),
                  Semantics(
                    label: unranked
                        ? context.t('progress.league.placement_left', {'n': placementLeft})
                        : '$percent%',
                    child: OProgressBar(value: progress, height: 12),
                  ),
                  const SizedBox(height: OSpace.sm),
                  Text(
                    unranked
                        ? context.t('progress.league.placement_left', {'n': placementLeft})
                        : next != null
                            ? context.t('progress.league.next_hint')
                            : context.t('progress.league.top_hint'),
                    style: OText.bodySm.copyWith(color: OColors.inkSubtle),
                  ),
                ]),
              ),
            ],
          ]),
        ),
        if (ladder.isNotEmpty) ...[
          OSectionHeader(context.t('progress.league.tiers')),
          OCard(
            padding: const EdgeInsets.symmetric(vertical: OSpace.sm, horizontal: OSpace.lg),
            child: Column(children: [
              for (final l in ladder.reversed) _LadderRow(league: l, current: l == league),
            ]),
          ),
        ],
        if (weeklyXp != null || rankedMatches != null) ...[
          OSectionHeader(context.t('progress.league.this_week')),
          Row(children: [
            if (weeklyXp != null)
              Expanded(
                child: StatTile(
                  label: context.t('progress.league.weekly_xp'),
                  value: weeklyXp,
                  unit: context.t('progress.xp'),
                  icon: Icons.bolt_rounded,
                  accent: OColors.turquoise,
                ),
              ),
            if (weeklyXp != null && rankedMatches != null) const SizedBox(width: OSpace.gutter),
            if (rankedMatches != null)
              Expanded(
                child: StatTile(
                  label: context.t('progress.league.ranked_matches'),
                  value: rankedMatches,
                  unit: context.t('progress.unit.played'),
                  icon: Icons.sports_esports_rounded,
                  accent: OColors.pink,
                ),
              ),
          ]),
        ],
        const SizedBox(height: OSpace.xl),
        OButton(
          label: context.t('progress.league.see_rankings'),
          icon: Icons.leaderboard_rounded,
          style: OButtonStyle.secondary,
          onPressed: () => context.canPop() ? context.pop() : context.go(Routes.rankings),
        ),
      ],
    );
  }
}

class _LadderRow extends StatelessWidget {
  const _LadderRow({required this.league, required this.current});

  final String league;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final color = leagueColor(league);
    return Container(
      margin: const EdgeInsets.symmetric(vertical: OSpace.xs),
      padding: const EdgeInsets.symmetric(horizontal: OSpace.md, vertical: OSpace.sm),
      decoration: BoxDecoration(
        color: current ? OColors.mint : null,
        borderRadius: BorderRadius.circular(ORadius.card),
      ),
      child: Row(children: [
        RowIcon(leagueIcon(league), color: color, background: color.withValues(alpha: 0.14), size: 40),
        const SizedBox(width: OSpace.md),
        Expanded(child: Text(context.t('league.$league'), style: OText.labelLg)),
        if (current) OPill(context.t('progress.league.now'), background: OColors.primary, foreground: OColors.white),
      ]),
    );
  }
}
