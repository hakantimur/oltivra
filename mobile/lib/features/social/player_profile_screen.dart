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
import 'social_api.dart';
import 'social_widgets.dart';

enum _MenuAction { remove, block, unblock, report }

/// Public player profile (P05 screen 3): minimum safe profile from `GET /v1/users/{public_id}`,
/// the relationship action and a discreet overflow for remove / block / report.
class PlayerProfileScreen extends ConsumerStatefulWidget {
  const PlayerProfileScreen({super.key, required this.publicId});

  final String publicId;

  @override
  ConsumerState<PlayerProfileScreen> createState() => _PlayerProfileScreenState();
}

class _PlayerProfileScreenState extends ConsumerState<PlayerProfileScreen> {
  bool _busy = false;

  String get _pid => widget.publicId;

  Future<void> _mutate(Future<Json> Function(ApiClient api) call, {String? successKey}) async {
    setState(() => _busy = true);
    try {
      await call(ref.read(apiClientProvider));
      ref.invalidate(publicPlayerProvider(_pid));
      ref.invalidate(friendsOverviewProvider);
      if (mounted && successKey != null) showMessage(context, context.t(successKey));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _onMenu(_MenuAction action, String name) async {
    switch (action) {
      case _MenuAction.report:
        context.push(Routes.reportPlayer(_pid));
      case _MenuAction.remove:
        final ok = await confirmAction(context,
            title: context.t('social.profile.remove_title', {'name': name}),
            body: context.t('social.profile.remove_body'),
            confirm: context.t('social.profile.remove'));
        if (ok) await _mutate((api) => api.delete('/v1/friends/$_pid'), successKey: 'social.profile.removed');
      case _MenuAction.block:
        final ok = await confirmAction(context,
            title: context.t('social.profile.block_title', {'name': name}),
            body: context.t('social.profile.block_body'),
            confirm: context.t('social.profile.block'));
        if (ok) await _mutate((api) => api.post('/v1/blocks/$_pid'), successKey: 'social.profile.blocked_toast');
      case _MenuAction.unblock:
        await _mutate((api) => api.delete('/v1/blocks/$_pid'), successKey: 'social.profile.unblocked_toast');
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(publicPlayerProvider(_pid));
    final data = async.value;
    final profile = (data?['profile'] as Map?)?.cast<String, dynamic>();
    final rel = (data?['relationship'] as Map?)?.cast<String, dynamic>() ?? const {};
    final isSelf = ref.watch(sessionProvider).value?.publicId == _pid;
    final name = (profile?['username_display'] as String?) ?? '';

    return OPage(
      title: context.t('social.profile.title'),
      onRefresh: () => ref.refresh(publicPlayerProvider(_pid).future),
      actions: [
        if (profile != null && !isSelf)
          PopupMenuButton<_MenuAction>(
            key: const ValueKey('profile-menu'),
            tooltip: context.t('social.profile.more'),
            icon: const Icon(Icons.more_vert_rounded),
            onSelected: (a) => _onMenu(a, name),
            itemBuilder: (ctx) => [
              if (rel['friend'] == true)
                PopupMenuItem(value: _MenuAction.remove, child: Text(ctx.t('social.profile.remove'))),
              if (rel['blocked'] == true)
                PopupMenuItem(value: _MenuAction.unblock, child: Text(ctx.t('social.profile.unblock')))
              else
                PopupMenuItem(value: _MenuAction.block, child: Text(ctx.t('social.profile.block'))),
              PopupMenuItem(value: _MenuAction.report, child: Text(ctx.t('social.profile.report'))),
            ],
          ),
      ],
      children: [
        if (async.hasError && data == null)
          OErrorView(error: async.error!, onRetry: () => ref.invalidate(publicPlayerProvider(_pid)))
        else if (profile == null)
          const OLoading()
        else ...[
          _Hero(profile: profile, relationship: rel, isSelf: isSelf, busy: _busy, onMutate: _mutate),
          if (rel['blocked'] != true) ...[
            OSectionHeader(context.t('social.profile.highlights')),
            _Highlights(profile: profile),
            _Badges(ids: ((profile['featured_badge_ids'] as List?) ?? const []).cast<String>()),
          ],
        ],
      ],
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.profile, required this.relationship, required this.isSelf, required this.busy,
      required this.onMutate});

  final Json profile;
  final Json relationship;
  final bool isSelf;
  final bool busy;
  final Future<void> Function(Future<Json> Function(ApiClient api) call, {String? successKey}) onMutate;

  @override
  Widget build(BuildContext context) {
    final pid = profile['public_id'] as String;
    final blocked = relationship['blocked'] == true;
    final friend = relationship['friend'] == true;
    final (IconData? statusIcon, String? statusKey) = blocked
        ? (Icons.block_rounded, 'social.profile.status_blocked')
        : friend
            ? (Icons.how_to_reg_rounded, 'social.relationship.friend')
            : relationship['outgoing_request'] == true
                ? (Icons.schedule_rounded, 'social.relationship.sent')
                : relationship['incoming_request'] == true
                    ? (Icons.mark_email_unread_outlined, 'social.relationship.received')
                    : (null, null);

    Widget? action;
    if (!isSelf) {
      if (blocked) {
        action = OButton(
          label: context.t('social.profile.unblock'),
          style: OButtonStyle.secondary,
          loading: busy,
          onPressed: () => onMutate((api) => api.delete('/v1/blocks/$pid'), successKey: 'social.profile.unblocked_toast'),
        );
      } else if (friend) {
        action = OButton(
          label: context.t('social.challenge.action'),
          icon: Icons.bolt_rounded,
          style: OButtonStyle.primary,
          onPressed: () => openChallenge(context, publicId: pid),
        );
      } else if (relationship['outgoing_request'] == true) {
        action = OButton(label: context.t('social.relationship.sent'), style: OButtonStyle.secondary, onPressed: null);
      } else {
        // Sending a request to someone who already asked us creates the friendship (mutual intent).
        final accept = relationship['incoming_request'] == true;
        action = OButton(
          label: context.t(accept ? 'social.profile.accept_request' : 'social.add_friend'),
          icon: accept ? Icons.check_rounded : Icons.person_add_alt_1_rounded,
          loading: busy,
          onPressed: () => onMutate((api) => api.post('/v1/friends/requests', {'target_public_id': pid}),
              successKey: accept ? 'social.find.now_friends' : 'social.find.request_sent_toast'),
        );
      }
    }

    return Container(
      padding: const EdgeInsets.fromLTRB(OSpace.xl, OSpace.xl, OSpace.xl, OSpace.xl),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [OColors.mint, OColors.white],
        ),
        borderRadius: BorderRadius.circular(ORadius.lg),
        boxShadow: OShadow.card,
      ),
      child: Column(children: [
        OAvatar(avatarId: profile['avatar_id'] as String?, frameId: profile['frame_id'] as String?, size: 112),
        const SizedBox(height: OSpace.lg),
        Text(profile['username_display'] as String? ?? '', style: OText.headlineXlMobile, textAlign: TextAlign.center),
        const SizedBox(height: OSpace.sm),
        LeagueChip(league: profile['league'] as String?, level: (profile['level'] as num?)?.toInt()),
        if (statusKey != null) ...[
          const SizedBox(height: OSpace.sm),
          Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(statusIcon, size: 16, color: blocked ? OColors.coral : OColors.primary),
            const SizedBox(width: 6),
            Flexible(
              child: Text(context.t(statusKey),
                  style: OText.labelMd.copyWith(color: blocked ? OColors.coral : OColors.inkSubtle)),
            ),
          ]),
        ],
        if (action != null) ...[const SizedBox(height: OSpace.xl), action],
      ]),
    );
  }
}

class _Highlights extends StatelessWidget {
  const _Highlights({required this.profile});

  final Json profile;

  int? _int(String key) => (profile[key] as num?)?.toInt();

  @override
  Widget build(BuildContext context) {
    final tiles = <Widget>[
      if (_int('quick_ranked_wins_lifetime') case final v?)
        _StatTile(label: context.t('social.stat.quick_wins'), value: '$v', icon: Icons.sports_esports_rounded,
            tint: OColors.mint, color: OColors.primary),
      if (_int('survival_ranked_crowns_lifetime') case final v?)
        _StatTile(label: context.t('social.stat.crowns'), value: '$v', icon: Icons.emoji_events_rounded,
            tint: OColors.sun, color: OColors.tertiary),
      if (_int('quick_best_ranked_win_streak') case final v?)
        _StatTile(label: context.t('social.stat.best_streak'), value: '$v', icon: Icons.local_fire_department_rounded,
            tint: OColors.rose, color: OColors.secondary),
      if (_int('level') case final v?)
        _StatTile(label: context.t('social.stat.level'), value: '$v', icon: Icons.military_tech_rounded,
            tint: OColors.surfaceContainer, color: OColors.ink),
    ];
    return LayoutBuilder(builder: (context, c) {
      final w = (c.maxWidth - OSpace.md) / 2;
      return Wrap(
        spacing: OSpace.md,
        runSpacing: OSpace.md,
        children: [for (final t in tiles) SizedBox(width: w, child: t)],
      );
    });
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile({required this.label, required this.value, required this.icon, required this.tint,
      required this.color});

  final String label;
  final String value;
  final IconData icon;
  final Color tint;
  final Color color;

  @override
  Widget build(BuildContext context) => OCard(
        radius: ORadius.md,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: Text(label, style: OText.labelMd.copyWith(color: OColors.onSurfaceVariant))),
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(color: tint, shape: BoxShape.circle),
              child: Icon(icon, size: 20, color: color),
            ),
          ]),
          const SizedBox(height: OSpace.sm),
          Text(value, style: OText.tabular(OText.headlineXlMobile)),
        ]),
      );
}

class _Badges extends ConsumerWidget {
  const _Badges({required this.ids});

  final List<String> ids;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ids.isEmpty) return const SizedBox.shrink();
    final catalog = ref.watch(catalogProvider('cosmetics')).value;
    final byId = {for (final b in jsonList(catalog?['badges'])) b['id']: b};
    final known = [for (final id in ids) if (byId[id] != null) byId[id]!];
    if (known.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      OSectionHeader(context.t('social.profile.badges')),
      Wrap(
        spacing: OSpace.sm,
        runSpacing: OSpace.sm,
        children: [
          for (final b in known)
            OPill(context.pick(b['names'] as Map?, fallback: b['id'] as String),
                icon: Icons.workspace_premium_rounded, background: OColors.sun, foreground: OColors.tertiary),
        ],
      ),
    ]);
  }
}
