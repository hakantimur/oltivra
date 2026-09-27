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

/// League status (P06 league_status): this week's tier, rank in the weekly group, promotion/relegation rules,
/// last week's result and the ladder (weekly cohort leagues, playtest 2026-09-27). Raw MMR is never shown.
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
    final league = (data['league'] as String?) ?? 'BRONZE';
    final ladder = ((data['leagues'] as List?) ?? const []).whereType<String>().toList();
    final joined = data['joined'] == true;
    final rank = asInt(data['rank']);
    final size = asInt(data['group_size']) ?? 100;
    final promote = asInt(data['promote_count']) ?? 0;
    final demote = asInt(data['demote_count']) ?? 0;
    final weeklyXp = asInt(data['ranked_weekly_xp']) ?? 0;
    final endsAt = asInt(data['week_ends_at_ms']);
    final last = data['last_result'] is Map ? asJson(data['last_result']) : null;
    final String status;
    if (!joined || rank == null) {
      status = context.t('progress.league.join_body');
    } else if (rank <= promote) {
      status = context.t('progress.league.status_promote');
    } else if (demote > 0 && rank > size - demote) {
      status = context.t('progress.league.status_demote');
    } else {
      status = context.t('progress.league.status_safe');
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (last != null) ...[_LastResult(result: last), const SizedBox(height: OSpace.lg)],
        OCard(
          radius: ORadius.lg,
          padding: const EdgeInsets.all(OSpace.xl),
          child: Column(children: [
            OPill(context.t('progress.league.active_pill'), dot: true),
            const SizedBox(height: OSpace.xl),
            LeagueCrest(league: league, size: 112),
            const SizedBox(height: OSpace.lg),
            Text(context.t('progress.league.name', {'league': context.t('league.$league')}),
                style: OText.headlineLg, textAlign: TextAlign.center),
            const SizedBox(height: OSpace.sm),
            if (joined && rank != null)
              Text(context.t('progress.league.rank', {'rank': rank, 'size': size, 'xp': weeklyXp}),
                  key: const Key('league-rank'), style: OText.labelLg, textAlign: TextAlign.center),
            const SizedBox(height: OSpace.xs),
            Text(status, style: OText.bodyMd.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
            if (endsAt != null) ...[
              const SizedBox(height: OSpace.md),
              ProgressCountdown(endsAtMs: endsAt, labelKey: 'progress.rankings.ends_in', style: OText.labelMd),
            ],
          ]),
        ),
        OSectionHeader(context.t('progress.league.how_title')),
        OCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _Rule(Icons.groups_rounded, context.t('progress.league.how_group', {'size': size})),
            if (promote > 0)
              _Rule(Icons.arrow_upward_rounded, context.t('progress.league.how_up', {'n': promote}),
                  color: OColors.success),
            if (demote > 0)
              _Rule(Icons.arrow_downward_rounded, context.t('progress.league.how_down', {'n': demote}),
                  color: OColors.coral)
            else
              _Rule(Icons.shield_rounded, context.t('progress.league.how_bronze')),
            _Rule(Icons.bolt_rounded, context.t('progress.league.how_xp')),
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
        const SizedBox(height: OSpace.xl),
        OButton(
          label: context.t('progress.league.see_group'),
          icon: Icons.leaderboard_rounded,
          style: OButtonStyle.secondary,
          onPressed: () => context.canPop() ? context.pop() : context.go(Routes.rankings),
        ),
      ],
    );
  }
}

class _Rule extends StatelessWidget {
  const _Rule(this.icon, this.text, {this.color = OColors.primary});

  final IconData icon;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: OSpace.xs),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: OSpace.sm),
          Expanded(child: Text(text, style: OText.bodyMd)),
        ]),
      );
}

class _LastResult extends StatelessWidget {
  const _LastResult({required this.result});

  final Json result;

  @override
  Widget build(BuildContext context) {
    final outcome = result['outcome'] as String? ?? 'STAYED';
    final to = (result['to'] as String?) ?? 'BRONZE';
    final (color, icon) = switch (outcome) {
      'PROMOTED' => (OColors.success, Icons.arrow_circle_up_rounded),
      'RELEGATED' => (OColors.coral, Icons.arrow_circle_down_rounded),
      _ => (OColors.primary, Icons.shield_rounded),
    };
    return Container(
      key: const Key('league-last-result'),
      padding: const EdgeInsets.all(OSpace.lg),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(ORadius.card)),
      child: Row(children: [
        Icon(icon, color: color),
        const SizedBox(width: OSpace.md),
        Expanded(
          child: Text(
            context.t('progress.league.last_$outcome',
                {'rank': asInt(result['rank']) ?? 0, 'league': context.t('league.$to')}),
            style: OText.labelLg,
          ),
        ),
      ]),
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
