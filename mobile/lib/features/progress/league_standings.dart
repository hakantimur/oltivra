import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'progress_api.dart';

/// This week's league group from `/v1/league` (playtest 2026-09-27): every seat ranked by weekly XP with the
/// promotion zone (top) and relegation zone (bottom) marked. The group itself is never numbered.
class LeagueStandings extends StatelessWidget {
  const LeagueStandings({super.key, required this.data});

  final Json data;

  @override
  Widget build(BuildContext context) {
    final league = (data['league'] as String?) ?? 'BRONZE';
    final rows = asJsonList(data['standings']);
    if (data['joined'] != true || rows.isEmpty) {
      return OEmptyState(
        icon: Icons.shield_outlined,
        title: context.t('progress.league.join_title', {'league': context.t('league.$league')}),
        body: context.t('progress.league.join_body'),
      );
    }
    final promote = asInt(data['promote_count']) ?? 0;
    final demote = asInt(data['demote_count']) ?? 0;
    final size = rows.length;
    final children = <Widget>[];
    for (final row in rows) {
      final rank = asInt(row['rank']) ?? 0;
      if (rank == 1 && promote > 0) {
        children.add(_ZoneLabel(text: context.t('progress.league.zone_promote', {'n': promote}),
            color: OColors.success, icon: Icons.arrow_upward_rounded));
      }
      if (demote > 0 && rank == size - demote + 1) {
        children.add(_ZoneLabel(text: context.t('progress.league.zone_demote', {'n': demote}),
            color: OColors.coral, icon: Icons.arrow_downward_rounded));
      }
      children
        ..add(LeagueRow(entry: row))
        ..add(const SizedBox(height: OSpace.sm));
      if (promote > 0 && rank == promote) {
        children.add(const Divider(height: OSpace.lg, color: OColors.success, thickness: 1.5));
      }
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
  }
}

class _ZoneLabel extends StatelessWidget {
  const _ZoneLabel({required this.text, required this.color, required this.icon});

  final String text;
  final Color color;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: OSpace.sm, top: OSpace.xs),
        child: Row(children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: OSpace.xs),
          Expanded(child: Text(text, style: OText.labelMd.copyWith(color: color))),
        ]),
      );
}

class LeagueRow extends StatelessWidget {
  const LeagueRow({super.key, required this.entry});

  final Json entry;

  @override
  Widget build(BuildContext context) {
    final rank = asInt(entry['rank']);
    final me = entry['me'] == true;
    final zone = entry['zone'] as String?;
    final publicId = entry['public_id'] as String?;
    final rankColor = zone == 'PROMOTE'
        ? OColors.success
        : zone == 'DEMOTE'
            ? OColors.coral
            : OColors.ink;
    return KeyedSubtree(
      key: me ? const ValueKey('league.me') : null,
      child: OCard(
        color: me ? OColors.mint : null,
        border: me ? OColors.turquoise : null,
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.sm),
        onTap: !me && publicId != null ? () => context.push(Routes.player(publicId)) : null,
        child: Row(children: [
          SizedBox(
            width: 36,
            child: Text(rank == null ? '–' : '$rank', style: OText.tabular(OText.labelLg).copyWith(color: rankColor)),
          ),
          OAvatar(avatarId: entry['avatar_id'] as String?, frameId: entry['frame_id'] as String?, size: 40),
          const SizedBox(width: OSpace.md),
          Expanded(
            child: Row(children: [
              Flexible(
                child: Text((entry['username'] as String?) ?? '', style: OText.labelLg, overflow: TextOverflow.ellipsis),
              ),
              if (me) ...[
                const SizedBox(width: OSpace.xs),
                OPill(context.t('progress.you'), background: OColors.turquoise, foreground: OColors.white),
              ],
            ]),
          ),
          Text('${asInt(entry['weekly_xp']) ?? 0} ${context.t('progress.xp')}',
              style: OText.tabular(OText.labelLg)),
        ]),
      ),
    );
  }
}
