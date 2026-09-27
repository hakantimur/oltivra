import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'progress_api.dart';
import 'progress_widgets.dart';

/// Achievements & cosmetics (P06 achievements_and_cosmetics): earned vs locked badges and owned frames.
/// Cosmetic/recognition only — equipping calls `PATCH /v1/profile/cosmetics` (≤3 featured badges).
class AchievementsScreen extends ConsumerStatefulWidget {
  const AchievementsScreen({super.key});

  @override
  ConsumerState<AchievementsScreen> createState() => _AchievementsScreenState();
}

class _AchievementsScreenState extends ConsumerState<AchievementsScreen> {
  static const maxFeatured = 3;
  String? _busy; // frame id or badge id being saved

  Future<void> _patch(String busyId, Json body) async {
    setState(() => _busy = busyId);
    try {
      final res = await ref.read(apiClientProvider).patch('/v1/profile/cosmetics', body);
      final profile = res['profile'];
      if (profile is Map) ref.read(sessionProvider.notifier).applyProfile(profile.cast<String, dynamic>());
      if (mounted) showMessage(context, context.t('progress.cosmetics.saved'));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  void _toggleFeatured(List<String> featured, String id) {
    final next = [...featured];
    if (next.contains(id)) {
      next.remove(id);
    } else {
      if (next.length >= maxFeatured) {
        showMessage(context, context.t('progress.cosmetics.featured_full', {'n': maxFeatured}));
        return;
      }
      next.add(id);
    }
    _patch(id, {'featured_badge_ids': next});
  }

  Future<void> _refresh() async {
    ref.invalidate(catalogProvider('cosmetics'));
    await Future.wait<void>([
      ref.read(catalogProvider('cosmetics').future).then((_) {}),
      reloadOwnProfile(ref).catchError((_) {}),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final catalog = ref.watch(catalogProvider('cosmetics'));
    final profile = ref.watch(sessionProvider).value?.profile ?? const <String, dynamic>{};
    return OPage(
      title: context.t('progress.cosmetics.title'),
      onRefresh: _refresh,
      children: [
        progressAsync<Json>(catalog, (data) => _body(context, data, profile),
            onRetry: () => ref.invalidate(catalogProvider('cosmetics'))),
      ],
    );
  }

  Widget _body(BuildContext context, Json catalog, Json profile) {
    final ownedFrames = ((profile['frame_ids'] as List?) ?? const ['frame_none']).whereType<String>().toSet()
      ..add('frame_none');
    final equipped = (profile['frame_id'] as String?) ?? 'frame_none';
    final earned = ((profile['badge_ids'] as List?) ?? const []).whereType<String>().toSet();
    final featured = ((profile['featured_badge_ids'] as List?) ?? const []).whereType<String>().toList();
    final frames = asJsonList(catalog['frames']);
    final badges = asJsonList(catalog['badges'])
      ..sort((a, b) => (earned.contains(b['id']) ? 1 : 0).compareTo(earned.contains(a['id']) ? 1 : 0));
    final avatarId = profile['avatar_id'] as String?;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(children: [
          const Icon(Icons.verified_user_outlined, size: 18, color: OColors.tertiary),
          const SizedBox(width: OSpace.sm),
          Expanded(
            child: Text(context.t('progress.cosmetics.disclaimer'),
                style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
          ),
        ]),
        OSectionHeader(
          context.t('progress.cosmetics.frames'),
          trailing: context.t('progress.cosmetics.unlocked', {'n': frames.where((f) => ownedFrames.contains(f['id'])).length}),
        ),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: OSpace.gutter,
          crossAxisSpacing: OSpace.gutter,
          childAspectRatio: 0.72,
          children: [
            for (final f in frames)
              _FrameCard(
                frame: f,
                avatarId: avatarId,
                owned: ownedFrames.contains(f['id']),
                equipped: f['id'] == equipped,
                busy: _busy == f['id'],
                onEquip: _busy != null ? null : () => _patch(f['id'] as String, {'frame_id': f['id']}),
              ),
          ],
        ),
        OSectionHeader(
          context.t('progress.cosmetics.badges'),
          trailing: context.t('progress.cosmetics.badges_count', {'earned': earned.length, 'total': badges.length}),
        ),
        Text(context.t('progress.cosmetics.featured_hint', {'n': maxFeatured}),
            style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
        const SizedBox(height: OSpace.md),
        if (badges.isEmpty)
          OEmptyState(icon: Icons.military_tech_outlined, title: context.t('progress.cosmetics.no_badges'))
        else
          for (final b in badges) ...[
            _BadgeRow(
              badge: b,
              earned: earned.contains(b['id']),
              featured: featured.contains(b['id']),
              busy: _busy == b['id'],
              onToggle: _busy != null ? null : () => _toggleFeatured(featured, b['id'] as String),
            ),
            const SizedBox(height: OSpace.sm),
          ],
      ],
    );
  }
}

Color? _hex(Object? v) {
  if (v is! String || !v.startsWith('#') || v.length != 7) return null;
  final n = int.tryParse(v.substring(1), radix: 16);
  return n == null ? null : Color(0xFF000000 | n);
}

class _FrameCard extends StatelessWidget {
  const _FrameCard({required this.frame, required this.avatarId, required this.owned, required this.equipped,
      required this.busy, required this.onEquip});

  final Json frame;
  final String? avatarId;
  final bool owned;
  final bool equipped;
  final bool busy;
  final VoidCallback? onEquip;

  @override
  Widget build(BuildContext context) {
    final id = frame['id'] as String;
    final color = _hex(frame['color']) ?? frameColors[id];
    return OCard(
      radius: ORadius.lg,
      border: equipped ? OColors.turquoise : null,
      padding: const EdgeInsets.all(OSpace.md),
      child: Column(children: [
        Align(
          alignment: Alignment.centerRight,
          child: equipped
              ? OPill(context.t('progress.cosmetics.equipped'), icon: Icons.check_circle_outline_rounded)
              : owned
                  ? OPill(context.t('progress.cosmetics.available'),
                      background: OColors.surfaceContainer, foreground: OColors.ink)
                  : OPill(context.t('progress.cosmetics.locked'), icon: Icons.lock_outline_rounded,
                      background: OColors.surfaceContainer, foreground: OColors.inkSubtle),
        ),
        const Spacer(),
        Opacity(
          opacity: owned ? 1 : 0.45,
          child: OAvatar(avatarId: avatarId, frameId: id, size: 72),
        ),
        const SizedBox(height: OSpace.sm),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          if (color != null) ...[
            Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
            const SizedBox(width: 6),
          ],
          Flexible(
            child: Text(context.pick(frame['names'] as Map?, fallback: id),
                style: OText.labelLg, maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
        ]),
        const Spacer(),
        SizedBox(
          height: 44,
          width: double.infinity,
          child: equipped
              ? Container(
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                      color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.pill)),
                  child: Text(context.t('progress.cosmetics.active_frame'), style: OText.labelMd),
                )
              : owned
                  ? FilledButton(
                      key: ValueKey('progress.equip.$id'),
                      onPressed: onEquip,
                      style: FilledButton.styleFrom(
                        backgroundColor: OColors.turquoise,
                        foregroundColor: OColors.white,
                        shape: const StadiumBorder(),
                        textStyle: OText.labelMd,
                      ),
                      child: busy
                          ? const SizedBox.square(
                              dimension: 18, child: CircularProgressIndicator(strokeWidth: 2, color: OColors.white))
                          : Text(context.t('progress.cosmetics.equip')),
                    )
                  : Center(
                      child: Text(context.t('progress.cosmetics.earn_to_unlock'),
                          style: OText.bodySm.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
                    ),
        ),
      ]),
    );
  }
}

class _BadgeRow extends StatelessWidget {
  const _BadgeRow({required this.badge, required this.earned, required this.featured, required this.busy,
      required this.onToggle});

  final Json badge;
  final bool earned;
  final bool featured;
  final bool busy;
  final VoidCallback? onToggle;

  @override
  Widget build(BuildContext context) {
    final name = context.pick(badge['names'] as Map?, fallback: badge['id'] as String? ?? '');
    return OCard(
      padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
      child: Row(children: [
        Opacity(
          opacity: earned ? 1 : 0.5,
          child: RowIcon(
            earned ? badgeIcon(badge['icon'] as String?) : Icons.lock_outline_rounded,
            color: earned ? OColors.tertiary : OColors.inkSubtle,
            background: earned ? OColors.sun : OColors.surfaceContainer,
            size: 48,
          ),
        ),
        const SizedBox(width: OSpace.md),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: OText.labelLg.copyWith(color: earned ? OColors.ink : OColors.inkSubtle)),
            const SizedBox(height: 2),
            earned
                ? Row(children: [
                    const Icon(Icons.check_rounded, size: 14, color: OColors.success),
                    const SizedBox(width: 2),
                    Text(context.t('progress.cosmetics.earned'), style: OText.labelSm.copyWith(color: OColors.success)),
                  ])
                : Text(context.t('progress.cosmetics.locked'), style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
          ]),
        ),
        if (earned)
          busy
              ? const SizedBox.square(dimension: 48, child: Padding(padding: EdgeInsets.all(14),
                  child: CircularProgressIndicator(strokeWidth: 2)))
              : IconButton(
                  tooltip: context.t(featured ? 'progress.cosmetics.unfeature' : 'progress.cosmetics.feature'),
                  onPressed: onToggle,
                  icon: Icon(featured ? Icons.push_pin_rounded : Icons.push_pin_outlined,
                      color: featured ? OColors.primary : OColors.inkSubtle),
                ),
      ]),
    );
  }
}
