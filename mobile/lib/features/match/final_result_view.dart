import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../../l10n/strings.dart';
import '../../live/match_snapshot.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'widgets/match_widgets.dart';

/// Final result for both modes (P03 screen 6, P04 screen 6). Standings come from `result_summary`; XP and
/// league progress only from this viewer's settlement once `settlement_status == SETTLED` (never raw MMR).
class FinalResultView extends StatelessWidget {
  const FinalResultView({
    super.key,
    required this.snapshot,
    required this.nowMs,
    required this.onHome,
    required this.onPlayAgain,
    this.onRematch,
    this.rematching = false,
    this.onRewardOffer,
    this.onReportPlayer,
  });

  final MatchSnapshot snapshot;
  final int nowMs;
  final VoidCallback onHome;
  final VoidCallback onPlayAgain;
  final VoidCallback? onRematch;
  final bool rematching;

  /// Non-null when this viewer has a rewarded-XP offer and rewarded ads are enabled.
  final VoidCallback? onRewardOffer;

  /// Opens the player report flow for a participant's public id.
  final ValueChanged<String>? onReportPlayer;

  @override
  Widget build(BuildContext context) {
    final s = snapshot;
    final standings = s.standings;
    final myPid = s.myPid;
    final mine = standings.where((e) => e['pid'] == myPid).firstOrNull;
    final me = s.me;
    final settled = s.settlementStatus == 'SETTLED';
    final settlement = settled ? s.settlement : null;
    final place = (mine?['place'] as num?)?.toInt();
    final count = standings.isEmpty ? s.participants.length : standings.length;
    final rematchLeft = s.rematchUntilMs == null ? 0 : secondsLeft(nowMs, s.rematchUntilMs!);

    final String headline;
    if (place == null) {
      headline = context.t('match.match_finished');
    } else if (place == 1) {
      headline = context.t(s.isSurvival ? 'match.result_crowned' : 'match.result_victory');
    } else {
      headline = context.t('match.result_place', {'place': ordinal(context, place)});
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.xl, OSpace.margin, OSpace.xxl),
      children: [
        Center(
          child: OPill(context.t('match.match_finished'), icon: Icons.stars_rounded, background: OColors.sun,
              foreground: OColors.tertiary),
        ),
        if (me != null) ...[
          const SizedBox(height: OSpace.lg),
          Center(
            child: OAvatar(
              avatarId: me.avatarId,
              frameId: me.frameId,
              size: 104,
              badge: place == 1
                  ? Container(
                      padding: const EdgeInsets.all(6),
                      decoration: const BoxDecoration(color: OColors.yellow, shape: BoxShape.circle),
                      child: Icon(s.isSurvival ? Icons.workspace_premium_rounded : Icons.emoji_events_rounded,
                          size: 22, color: OColors.ink),
                    )
                  : null,
            ),
          ),
          const SizedBox(height: OSpace.sm),
          Text(me.name.toUpperCase(),
              style: OText.labelMd.copyWith(color: OColors.primary), textAlign: TextAlign.center),
        ],
        const SizedBox(height: OSpace.xs),
        Text(headline, style: OText.headlineXl, textAlign: TextAlign.center),
        const SizedBox(height: OSpace.xl),
        if (mine != null) ...[
          _StatsGrid(snapshot: s, mine: mine, count: count, settled: settled, settlement: settlement),
          const SizedBox(height: OSpace.md),
        ],
        if (settlement != null) _ProgressCard(settlement: settlement),
        if (onRematch != null && rematchLeft > 0 && me != null) ...[
          const SizedBox(height: OSpace.md),
          _RematchStrip(seconds: rematchLeft, loading: rematching, onTap: onRematch!),
        ],
        OSectionHeader(context.t('match.final_standings')),
        for (final entry in standings)
          _ResultRow(
            snapshot: s,
            entry: entry,
            onReport: onReportPlayer == null || entry['pid'] == myPid ? null : () => onReportPlayer!('${entry['pid']}'),
          ),
        const SizedBox(height: OSpace.xl),
        if (onRewardOffer != null) ...[
          OButton(
            label: context.t('match.reward_offer'),
            icon: Icons.play_circle_outline_rounded,
            style: OButtonStyle.secondary,
            onPressed: onRewardOffer,
          ),
          const SizedBox(height: OSpace.md),
        ],
        if (me != null) ...[
          OButton(label: context.t('match.play_again'), icon: Icons.play_arrow_rounded, onPressed: onPlayAgain),
          const SizedBox(height: OSpace.sm),
          OButton(label: context.t('match.home'), style: OButtonStyle.ghost, onPressed: onHome),
        ] else
          OButton(label: context.t('match.home'), onPressed: onHome),
      ],
    );
  }
}

class _StatsGrid extends StatelessWidget {
  const _StatsGrid({required this.snapshot, required this.mine, required this.count, required this.settled,
      required this.settlement});

  final MatchSnapshot snapshot;
  final Json mine;
  final int count;
  final bool settled;
  final Json? settlement;

  @override
  Widget build(BuildContext context) {
    final s = snapshot;
    final place = (mine['place'] as num?)?.toInt() ?? 0;
    final score = (mine['score'] as num?)?.toInt() ?? 0;
    final wins = (mine['wins'] as num?)?.toInt() ?? 0;
    final xp = (settlement?['xp_awarded'] as num?)?.toInt();
    final cards = <Widget>[
      _StatCard(
        label: context.t('match.placement'),
        value: ordinal(context, place),
        suffix: '/ $count',
        icon: Icons.military_tech_rounded,
      ),
      if (s.isQuick) ...[
        _StatCard(
          label: context.t('match.final_score'),
          value: '$score',
          suffix: context.t('match.pts'),
          icon: Icons.bolt_rounded,
        ),
        _StatCard(
          label: context.t('match.question_wins'),
          value: '$wins',
          suffix: '/ ${s.totalNormalRounds}',
          icon: Icons.fact_check_rounded,
        ),
      ] else
        _StatCard(
          label: context.t('match.rounds_cleared'),
          value: '$score',
          icon: Icons.verified_rounded,
        ),
      settled && xp != null
          ? _StatCard(
              label: context.t('match.match_reward'),
              value: '+$xp',
              suffix: context.t('match.xp'),
              icon: Icons.verified_outlined,
              accent: OColors.primary,
            )
          : _StatCard(
              label: context.t('match.match_reward'),
              value: null,
              note: context.t(settled ? 'match.no_xp' : 'match.confirming_results'),
              icon: Icons.hourglass_top_rounded,
            ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = (constraints.maxWidth - OSpace.md) / 2;
        return Wrap(
          spacing: OSpace.md,
          runSpacing: OSpace.md,
          children: [for (final c in cards) SizedBox(width: width, child: c)],
        );
      },
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.label, required this.value, required this.icon, this.suffix, this.note,
      this.accent = OColors.ink});

  final String label;
  final String? value;
  final String? suffix;
  final String? note;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) => OCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(label.toUpperCase(), style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
                ),
                Icon(icon, size: 18, color: OColors.tertiaryContainer),
              ],
            ),
            const SizedBox(height: OSpace.sm),
            if (value != null)
              Text.rich(
                TextSpan(children: [
                  TextSpan(text: value, style: OText.tabular(OText.headlineXlMobile).copyWith(color: accent)),
                  if (suffix != null)
                    TextSpan(text: ' $suffix', style: OText.labelMd.copyWith(color: OColors.inkSubtle)),
                ]),
              ),
            if (note != null) Text(note!, style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
          ],
        ),
      );
}

/// League / level progression from the settlement (no raw MMR, spec §7.3). Hidden when nothing applies.
class _ProgressCard extends StatelessWidget {
  const _ProgressCard({required this.settlement});

  final Json settlement;

  @override
  Widget build(BuildContext context) {
    final ranked = settlement['progress_ranked'] == true;
    final before = settlement['progress_league_before'] as String?;
    final after = settlement['progress_league_after'] as String?;
    final levelBefore = (settlement['progress_level_before'] as num?)?.toInt();
    final levelAfter = (settlement['progress_level_after'] as num?)?.toInt();
    final missions = settlement['progress_missions_completed'];
    final missionCount = missions is List ? missions.length : (missions is num ? missions.toInt() : 0);
    final lines = <Widget>[];
    if (ranked && after != null) {
      final changed = before != null && before != after;
      lines.add(Row(
        children: [
          Icon(Icons.shield_rounded, color: leagueColor(after)),
          const SizedBox(width: OSpace.md),
          Expanded(
            child: Text(
              changed
                  ? context.t('match.league_changed',
                      {'from': context.t('league.$before'), 'to': context.t('league.$after')})
                  : context.t('match.league_now', {'league': context.t('league.$after')}),
              style: OText.labelLg,
            ),
          ),
        ],
      ));
    }
    if (levelBefore != null && levelAfter != null && levelAfter > levelBefore) {
      lines.add(Row(
        children: [
          const Icon(Icons.trending_up_rounded, color: OColors.primary),
          const SizedBox(width: OSpace.md),
          Expanded(child: Text(context.t('match.level_up', {'level': levelAfter}), style: OText.labelLg)),
        ],
      ));
    }
    if (missionCount > 0) {
      lines.add(Row(
        children: [
          const Icon(Icons.task_alt_rounded, color: OColors.primary),
          const SizedBox(width: OSpace.md),
          Expanded(child: Text(context.t('match.missions_completed', {'n': missionCount}), style: OText.labelLg)),
        ],
      ));
    }
    if (lines.isEmpty) return const SizedBox.shrink();
    return OCard(
      child: Column(
        children: [
          for (var i = 0; i < lines.length; i++) ...[if (i > 0) const SizedBox(height: OSpace.md), lines[i]],
        ],
      ),
    );
  }
}

class _RematchStrip extends StatelessWidget {
  const _RematchStrip({required this.seconds, required this.loading, required this.onTap});

  final int seconds;
  final bool loading;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.sm),
        decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.md)),
        child: Row(
          children: [
            Expanded(child: Text(context.t('match.rematch_hint'), style: OText.bodyMd)),
            TextButton.icon(
              onPressed: loading ? null : onTap,
              style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
              icon: loading
                  ? const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.replay_rounded, color: OColors.secondary),
              label: Text(
                context.t('match.rematch', {'time': '00:${seconds.toString().padLeft(2, '0')}'}),
                style: OText.tabular(OText.labelLg),
              ),
            ),
          ],
        ),
      );
}

class _ResultRow extends StatelessWidget {
  const _ResultRow({required this.snapshot, required this.entry, this.onReport});

  final MatchSnapshot snapshot;
  final Json entry;
  final VoidCallback? onReport;

  @override
  Widget build(BuildContext context) {
    final s = snapshot;
    final pid = '${entry['pid']}';
    final p = s.participants[pid];
    final place = (entry['place'] as num?)?.toInt() ?? 0;
    final score = (entry['score'] as num?)?.toInt() ?? 0;
    final isMe = pid == s.myPid;
    final name = p?.name ?? '';
    final value = s.isSurvival
        ? context.t('match.rounds_value', {'n': score})
        : context.t('match.points', {'n': score});
    return Container(
      margin: const EdgeInsets.only(bottom: OSpace.sm),
      padding: const EdgeInsets.fromLTRB(OSpace.lg, OSpace.sm, OSpace.xs, OSpace.sm),
      decoration: BoxDecoration(
        color: isMe ? OColors.mint : OColors.white,
        borderRadius: BorderRadius.circular(ORadius.card),
        boxShadow: OShadow.card,
      ),
      child: Row(
        children: [
          SizedBox(
            width: 40,
            child: place == 1 && s.isSurvival
                ? Semantics(
                    label: context.t('match.crown'),
                    child: const Icon(Icons.workspace_premium_rounded, color: OColors.tertiaryContainer),
                  )
                : Text(ordinal(context, place), style: OText.labelLg),
          ),
          OAvatar(avatarId: p?.avatarId, frameId: p?.frameId, size: 40),
          const SizedBox(width: OSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: OText.labelLg.copyWith(color: isMe ? OColors.primary : OColors.ink),
                    overflow: TextOverflow.ellipsis),
                if (isMe) Text(context.t('match.you'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
              ],
            ),
          ),
          Text(value, style: OText.tabular(OText.labelLg)),
          if (onReport != null)
            PopupMenuButton<String>(
              tooltip: context.t('match.more_for', {'name': name}),
              icon: const Icon(Icons.more_vert_rounded, color: OColors.inkSubtle),
              onSelected: (_) => onReport!(),
              itemBuilder: (context) => [
                PopupMenuItem(value: 'report', child: Text(context.t('match.report_player'))),
              ],
            )
          else
            const SizedBox(width: 48),
        ],
      ),
    );
  }
}
