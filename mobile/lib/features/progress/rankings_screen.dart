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
import 'league_standings.dart';
import 'progress_api.dart';
import 'progress_widgets.dart';

/// Rankings tab (P06 weekly_rankings): the player's weekly league group (default, playtest 2026-09-27) or the
/// global weekly leaderboard with the player's own row pinned. Ordered by ranked weekly XP on the server.
class RankingsScreen extends ConsumerStatefulWidget {
  const RankingsScreen({super.key});

  @override
  ConsumerState<RankingsScreen> createState() => _RankingsScreenState();
}

class _RankingsScreenState extends ConsumerState<RankingsScreen> {
  bool _leagueOnly = true;
  final List<Json> _more = [];
  int? _nextOffset;
  bool _loadingMore = false;

  // The global board is never league-filtered any more: the league view is the player's own group.
  String? _filter(String myLeague) => null;

  Future<void> _refresh(String? filter) async {
    setState(() {
      _more.clear();
      _nextOffset = null;
    });
    ref.invalidate(weeklyLeaderboardProvider(filter));
    await ref.read(weeklyLeaderboardProvider(filter).future);
  }

  Future<void> _loadMore(String? filter, int offset) async {
    setState(() => _loadingMore = true);
    try {
      final res = await ref.read(apiClientProvider).get('/v1/leaderboards/weekly', query: {
        'limit': '50',
        'offset': '$offset',
        'league': ?filter,
      });
      if (!mounted) return;
      setState(() {
        _more.addAll(asJsonList(res['entries']));
        _nextOffset = asInt(res['next_offset']) ?? -1;
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider).value;
    final myLeague = session?.league ?? 'BRONZE';
    final myPublicId = session?.publicId;
    final filter = _filter(myLeague);
    final board = ref.watch(weeklyLeaderboardProvider(filter));
    final weekEnd = nextIsoWeekStartMs(ref.read(serverClockProvider).nowMs());

    return OPage(
      title: context.t('progress.rankings.title'),
      showBack: false,
      onRefresh: () => _leagueOnly ? ref.refresh(leagueStatusProvider.future) : _refresh(filter),
      actions: [
        IconButton(
          tooltip: context.t('progress.league.title'),
          icon: const Icon(Icons.shield_outlined),
          onPressed: () => context.push(Routes.league),
        ),
      ],
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(color: OColors.turquoise, shape: BoxShape.circle)),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        context.t(!_leagueOnly ? 'progress.rankings.context_global' : 'progress.rankings.context_league',
                            {'league': context.t('league.$myLeague')}).toUpperCase(),
                        style: OText.labelSm.copyWith(color: OColors.inkSubtle),
                      ),
                    ),
                  ]),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: OSpace.md, vertical: 6),
              decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.pill)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.schedule_rounded, size: 16, color: OColors.tertiary),
                const SizedBox(width: 4),
                ProgressCountdown(endsAtMs: weekEnd, labelKey: 'progress.rankings.ends_in',
                    style: OText.labelMd),
              ]),
            ),
          ],
        ),
        const SizedBox(height: OSpace.lg),
        SegmentedButton<bool>(
            showSelectedIcon: false,
            segments: [
              ButtonSegment(value: true, icon: Icon(leagueIcon(myLeague), size: 18),
                  label: Text(context.t('progress.rankings.tab_league'))),
              ButtonSegment(value: false, icon: const Icon(Icons.public_rounded, size: 18),
                  label: Text(context.t('progress.rankings.tab_global'))),
            ],
            selected: {_leagueOnly},
            onSelectionChanged: (s) => setState(() {
              _leagueOnly = s.first;
              _more.clear();
              _nextOffset = null;
            }),
          ),
        const SizedBox(height: OSpace.lg),
        if (_leagueOnly)
          progressAsync<Json>(
            ref.watch(leagueStatusProvider),
            (data) => LeagueStandings(data: data),
            onRetry: () => ref.invalidate(leagueStatusProvider),
          )
        else
          progressAsync<Json>(
            board,
            (data) => _board(context, data, myPublicId, filter),
            onRetry: () => ref.invalidate(weeklyLeaderboardProvider(filter)),
          ),
        const SizedBox(height: OSpace.lg),
        OCard(
          color: OColors.surfaceContainer,
          onTap: () => context.push(Routes.league),
          child: Row(children: [
            RowIcon(leagueIcon(myLeague), color: OColors.primary, background: OColors.white),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(context.t('progress.rankings.league_link'), style: OText.labelLg),
                Text(context.t('progress.rankings.league_link_body'),
                    style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
              ]),
            ),
            const Icon(Icons.chevron_right_rounded),
          ]),
        ),
      ],
    );
  }

  Widget _board(BuildContext context, Json data, String? myPublicId, String? filter) {
    final entries = [...asJsonList(data['entries']), ..._more];
    final me = data['me'] is Map ? asJson(data['me']) : null;
    final next = _nextOffset == null ? asInt(data['next_offset']) : (_nextOffset! < 0 ? null : _nextOffset);
    bool isMe(Json e) =>
        (myPublicId != null && e['public_id'] == myPublicId) || (me != null && me['public_id'] != null && e['public_id'] == me['public_id']);

    if (entries.isEmpty) {
      return Column(children: [
        if (me != null) _MyRankCard(entry: me),
        OEmptyState(
          icon: Icons.leaderboard_rounded,
          title: context.t('progress.rankings.empty_title'),
          body: context.t('progress.rankings.empty_body'),
        ),
      ]);
    }
    final meVisible = entries.any(isMe);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (me != null) ...[_MyRankCard(entry: me), const SizedBox(height: OSpace.lg)],
        Row(children: [
          Expanded(child: Text(context.t('progress.rankings.players').toUpperCase(), style: OText.labelMd)),
          Text(context.t('progress.rankings.weekly_xp'), style: OText.labelMd.copyWith(color: OColors.inkSubtle)),
        ]),
        const SizedBox(height: OSpace.sm),
        for (final e in entries) ...[
          _RankRow(entry: e, highlighted: isMe(e)),
          const SizedBox(height: OSpace.sm),
        ],
        if (next != null)
          Padding(
            padding: const EdgeInsets.only(top: OSpace.sm),
            child: OButton(
              label: context.t('progress.rankings.load_more'),
              style: OButtonStyle.secondary,
              loading: _loadingMore,
              onPressed: () => _loadMore(filter, next),
            ),
          ),
        if (me != null && !meVisible) ...[
          const SizedBox(height: OSpace.sm),
          const Center(child: Text('• • •', style: TextStyle(color: OColors.outlineVariant))),
          const SizedBox(height: OSpace.sm),
          _RankRow(entry: me, highlighted: true),
        ],
      ],
    );
  }
}

class _MyRankCard extends StatelessWidget {
  const _MyRankCard({required this.entry});

  final Json entry;

  @override
  Widget build(BuildContext context) {
    final rank = asInt(entry['rank']);
    final league = entry['league'] as String?;
    return Container(
      padding: const EdgeInsets.all(OSpace.lg),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(ORadius.lg),
        gradient: const LinearGradient(colors: [OColors.mint, OColors.surfaceContainer]),
      ),
      child: Row(children: [
        OAvatar(avatarId: entry['avatar_id'] as String?, frameId: entry['frame_id'] as String?, size: 56),
        const SizedBox(width: OSpace.md),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Flexible(
                  child: Text((entry['username'] as String?) ?? '', style: OText.headlineSm, overflow: TextOverflow.ellipsis)),
              if (league != null) ...[const SizedBox(width: OSpace.sm), LeagueChip(league)],
            ]),
            if (rank != null)
              Text(context.t('progress.rankings.your_rank', {'rank': rank}),
                  style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
          ]),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('${asInt(entry['ranked_weekly_xp']) ?? 0}',
              style: OText.tabular(OText.headlineMd).copyWith(color: OColors.primary)),
          Text(context.t('progress.xp'), style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
        ]),
      ]),
    );
  }
}

class _RankRow extends StatelessWidget {
  const _RankRow({required this.entry, required this.highlighted});

  final Json entry;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    final rank = asInt(entry['rank']);
    final publicId = entry['public_id'] as String?;
    final league = entry['league'] as String?;
    final wins = asInt(entry['quick_ranked_wins']) ?? 0;
    final crowns = asInt(entry['survival_ranked_crowns']) ?? 0;
    final podium = rank != null && rank <= 3;
    final subtitle = [
      if (wins > 0) context.t('progress.rankings.wins', {'n': wins}),
      if (crowns > 0) context.t('progress.rankings.crowns', {'n': crowns}),
    ].join(' · ');
    return KeyedSubtree(
      key: highlighted ? const ValueKey('progress.rankings.me') : null,
      child: OCard(
        color: highlighted ? OColors.mint : null,
        border: highlighted ? OColors.turquoise : null,
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
        onTap: !highlighted && publicId != null ? () => context.push(Routes.player(publicId)) : null,
        child: Row(children: [
          SizedBox(
            width: 36,
            child: podium
                ? Icon(Icons.emoji_events_rounded,
                    color: [OColors.yellow, const Color(0xFF8A94A6), const Color(0xFFB87333)][rank - 1],
                    semanticLabel: '#$rank')
                : Text(rank == null ? '–' : '$rank',
                    style: OText.tabular(OText.labelLg).copyWith(color: highlighted ? OColors.primary : OColors.ink)),
          ),
          OAvatar(avatarId: entry['avatar_id'] as String?, frameId: entry['frame_id'] as String?, size: 44),
          const SizedBox(width: OSpace.md),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(
                  child: Text((entry['username'] as String?) ?? '',
                      style: OText.labelLg, overflow: TextOverflow.ellipsis),
                ),
                if (highlighted) ...[
                  const SizedBox(width: OSpace.xs),
                  OPill(context.t('progress.you'), background: OColors.turquoise, foreground: OColors.white),
                ] else if (league != null) ...[
                  const SizedBox(width: OSpace.xs),
                  LeagueChip(league),
                ],
              ]),
              if (subtitle.isNotEmpty)
                Text(subtitle, style: OText.bodySm.copyWith(color: OColors.inkSubtle), overflow: TextOverflow.ellipsis),
            ]),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('${asInt(entry['ranked_weekly_xp']) ?? 0}', style: OText.tabular(OText.headlineSm)),
            Text(context.t('progress.xp'), style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
          ]),
        ]),
      ),
    );
  }
}
