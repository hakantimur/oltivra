import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'progress_api.dart';
import 'progress_widgets.dart';

/// Missions (P06 missions): exactly two sections, Daily and Weekly, with server-defined progress and a
/// restrained Claim action on completed missions (spec §7.8). Claims are idempotent server side.
class MissionsScreen extends ConsumerStatefulWidget {
  const MissionsScreen({super.key});

  @override
  ConsumerState<MissionsScreen> createState() => _MissionsScreenState();
}

class _MissionsScreenState extends ConsumerState<MissionsScreen> {
  final Set<String> _claiming = {};

  Future<void> _refresh() async {
    ref.invalidate(missionsProvider('daily'));
    ref.invalidate(missionsProvider('weekly'));
    await Future.wait([ref.read(missionsProvider('daily').future), ref.read(missionsProvider('weekly').future)]);
  }

  Future<void> _claim(String period, Json mission) async {
    final id = mission['mission_id'] as String;
    setState(() => _claiming.add(id));
    try {
      final res = await ref.read(apiClientProvider).post('/v1/missions/${Uri.encodeComponent(id)}/claim');
      if (!mounted) return;
      final xp = asInt(res['xp_awarded']) ?? 0;
      showMessage(context,
          xp > 0 ? context.t('progress.missions.claimed_xp', {'xp': xp}) : context.t('progress.missions.claimed'));
      ref.invalidate(missionsProvider(period));
      try {
        await reloadOwnProfile(ref);
      } catch (_) {
        // The claim itself succeeded; the profile refreshes on the next bootstrap.
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      showError(context, e);
      if (e.code == 'MISSION_NOT_COMPLETE' || e.code == 'NOT_FOUND') ref.invalidate(missionsProvider(period));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _claiming.remove(id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final daily = ref.watch(missionsProvider('daily'));
    final weekly = ref.watch(missionsProvider('weekly'));
    final readyCount = [daily.value, weekly.value]
        .expand((d) => asJsonList(d?['missions']))
        .where((m) => m['completed'] == true && m['claimed'] != true)
        .length;
    final dailyEnds = asInt(daily.value?['ends_at_ms']);

    return OPage(
      title: context.t('progress.missions.title'),
      onRefresh: _refresh,
      children: [
        if (dailyEnds != null || readyCount > 0)
          OCard(
            color: OColors.surfaceContainer,
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const Icon(Icons.schedule_rounded, size: 16, color: OColors.inkSubtle),
                    const SizedBox(width: 4),
                    Text(context.t('progress.missions.cycles').toUpperCase(),
                        style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
                  ]),
                  const SizedBox(height: OSpace.xs),
                  if (dailyEnds != null)
                    ProgressCountdown(endsAtMs: dailyEnds, labelKey: 'progress.missions.daily_resets',
                        style: OText.headlineSm),
                ]),
              ),
              if (readyCount > 0)
                OPill(context.t('progress.missions.ready', {'n': readyCount}),
                    background: OColors.sun, foreground: OColors.tertiary),
            ]),
          ),
        _Section(
          period: 'daily',
          titleKey: 'progress.missions.daily',
          dot: OColors.primary,
          value: daily,
          claiming: _claiming,
          onClaim: (m) => _claim('daily', m),
          onRetry: () => ref.invalidate(missionsProvider('daily')),
        ),
        _Section(
          period: 'weekly',
          titleKey: 'progress.missions.weekly',
          dot: OColors.pink,
          value: weekly,
          claiming: _claiming,
          onClaim: (m) => _claim('weekly', m),
          onRetry: () => ref.invalidate(missionsProvider('weekly')),
        ),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.period, required this.titleKey, required this.dot, required this.value,
      required this.claiming, required this.onClaim, required this.onRetry});

  final String period;
  final String titleKey;
  final Color dot;
  final AsyncValue<Json> value;
  final Set<String> claiming;
  final void Function(Json mission) onClaim;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final missions = asJsonList(value.value?['missions']);
    final done = missions.where((m) => m['completed'] == true).length;
    final endsAt = asInt(value.value?['ends_at_ms']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: OSpace.xl, bottom: OSpace.md),
          child: Row(children: [
            Container(width: 10, height: 10, decoration: BoxDecoration(color: dot, shape: BoxShape.circle)),
            const SizedBox(width: OSpace.sm),
            Expanded(child: Text(context.t(titleKey), style: OText.headlineMd)),
            if (missions.isNotEmpty)
              OPill(context.t('progress.missions.done_count', {'done': done, 'total': missions.length}),
                  background: OColors.surfaceContainer, foreground: OColors.ink),
          ]),
        ),
        if (period == 'weekly' && endsAt != null)
          Padding(
            padding: const EdgeInsets.only(bottom: OSpace.sm),
            child: ProgressCountdown(endsAtMs: endsAt, labelKey: 'progress.missions.weekly_resets'),
          ),
        progressAsync<Json>(
          value,
          (_) => missions.isEmpty
              ? OEmptyState(icon: Icons.flag_outlined, title: context.t('progress.missions.empty'))
              : Column(children: [
                  for (final m in missions) ...[
                    _MissionCard(
                      mission: m,
                      claiming: claiming.contains(m['mission_id']),
                      onClaim: () => onClaim(m),
                    ),
                    const SizedBox(height: OSpace.md),
                  ],
                ]),
          onRetry: onRetry,
        ),
      ],
    );
  }
}

/// Mission template → icon; titles come from `progress.mission.<template_id>`.
IconData _missionIcon(String? template) {
  final t = template ?? '';
  if (t.startsWith('play_survival') || t.startsWith('survive') || t.startsWith('survival')) return Icons.shield_outlined;
  if (t.startsWith('answer_correct')) return Icons.quiz_outlined;
  if (t.startsWith('send_reactions')) return Icons.emoji_emotions_outlined;
  if (t.startsWith('earn_quick_points')) return Icons.stars_outlined;
  if (t.startsWith('win')) return Icons.emoji_events_outlined;
  return Icons.bolt_rounded;
}

class _MissionCard extends StatelessWidget {
  const _MissionCard({required this.mission, required this.claiming, required this.onClaim});

  final Json mission;
  final bool claiming;
  final VoidCallback onClaim;

  @override
  Widget build(BuildContext context) {
    final template = mission['template_id'] as String?;
    final target = asInt(mission['target']) ?? 1;
    final progress = (asInt(mission['progress']) ?? 0).clamp(0, target);
    final completed = mission['completed'] == true;
    final claimed = mission['claimed'] == true;
    final xp = asInt(mission['xp']);
    final key = 'progress.mission.$template';
    final title = Strings.has(key) ? context.t(key, {'n': target}) : context.t('progress.mission.generic', {'n': target});
    final left = target - progress;

    return OCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          RowIcon(_missionIcon(template),
              color: completed ? OColors.primary : OColors.inkSubtle,
              background: completed ? OColors.mint : OColors.surfaceContainer),
          const SizedBox(width: OSpace.md),
          Expanded(child: Text(title, style: OText.headlineSm)),
          const SizedBox(width: OSpace.sm),
          OPill(
            '$progress/$target',
            icon: completed ? Icons.check_rounded : null,
            background: completed ? OColors.mint : OColors.surfaceContainer,
            foreground: completed ? OColors.primary : OColors.ink,
          ),
        ]),
        const SizedBox(height: OSpace.md),
        Semantics(
          label: context.t('progress.missions.progress_label', {'done': progress, 'total': target}),
          child: OProgressBar(value: progress / target, color: completed ? OColors.success : OColors.turquoise),
        ),
        const SizedBox(height: OSpace.md),
        if (completed && !claimed)
          OButton(
            label: xp != null ? context.t('progress.missions.claim_xp', {'xp': xp}) : context.t('progress.missions.claim'),
            icon: Icons.verified_outlined,
            loading: claiming,
            onPressed: onClaim,
          )
        else
          Row(children: [
            if (xp != null)
              Expanded(
                child: Text(context.t('progress.missions.reward', {'xp': xp}),
                    style: OText.labelMd),
              )
            else
              const Spacer(),
            Text(
              claimed
                  ? context.t('progress.missions.claimed_state')
                  : context.t('progress.missions.left', {'n': left}),
              style: OText.labelMd.copyWith(color: claimed ? OColors.success : OColors.inkSubtle),
            ),
          ]),
      ]),
    );
  }
}
