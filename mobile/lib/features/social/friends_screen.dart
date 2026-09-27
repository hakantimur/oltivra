import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'social_api.dart';
import 'social_widgets.dart';

/// Social tab (P05 screen 1): friends list, search entry, pending-request summary.
class FriendsScreen extends ConsumerWidget {
  const FriendsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final overview = ref.watch(friendsOverviewProvider);
    final data = overview.value;
    final incoming = jsonList(data?['incoming_requests']);
    Future<void> refresh() => ref.refresh(friendsOverviewProvider.future);

    return OPage(
      title: context.t('social.title'),
      showBack: false,
      onRefresh: refresh,
      actions: [
        Padding(
          padding: const EdgeInsets.only(right: OSpace.sm),
          child: IconButton(
            tooltip: context.t('social.requests.title'),
            onPressed: () => context.push(Routes.friendRequests),
            icon: Badge(
              isLabelVisible: incoming.isNotEmpty,
              label: Text('${incoming.length}'),
              backgroundColor: OColors.pink,
              child: const Icon(Icons.person_add_alt_1_rounded),
            ),
          ),
        ),
      ],
      children: [
        _SearchEntry(onTap: () => context.push(Routes.findPlayers)),
        const SizedBox(height: OSpace.lg),
        if (overview.hasError && data == null)
          OErrorView(error: overview.error!, onRetry: () => ref.invalidate(friendsOverviewProvider))
        else if (data == null)
          const OLoading()
        else ...[
          if (incoming.isNotEmpty) _RequestsSummary(count: incoming.length),
          _FriendsList(friends: jsonList(data['friends'])),
          const SizedBox(height: OSpace.xl),
          const _ShareUsername(),
        ],
      ],
    );
  }
}

class _SearchEntry extends StatelessWidget {
  const _SearchEntry({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: context.t('social.search.entry'),
        child: Material(
          color: OColors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(ORadius.pill),
            side: const BorderSide(color: OColors.divider),
          ),
          child: InkWell(
            customBorder: const StadiumBorder(),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: OSpace.xl, vertical: OSpace.lg),
              child: Row(children: [
                const Icon(Icons.search_rounded, color: OColors.inkSubtle),
                const SizedBox(width: OSpace.md),
                Expanded(
                  child: Text(context.t('social.search.entry'),
                      style: OText.bodyLg.copyWith(color: OColors.inkSubtle)),
                ),
              ]),
            ),
          ),
        ),
      );
}

class _RequestsSummary extends StatelessWidget {
  const _RequestsSummary({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: OSpace.sm),
        child: OCard(
          color: OColors.surfaceContainer,
          radius: ORadius.card,
          onTap: () => context.push(Routes.friendRequests),
          child: Row(children: [
            Container(
              width: 44,
              height: 44,
              decoration: const BoxDecoration(color: OColors.rose, shape: BoxShape.circle),
              child: const Icon(Icons.person_add_alt_rounded, color: OColors.secondary),
            ),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Flexible(child: Text(context.t('social.requests.title'), style: OText.labelLg)),
                  const SizedBox(width: OSpace.sm),
                  OPill('$count', background: OColors.pink, foreground: OColors.white),
                ]),
                const SizedBox(height: 2),
                Text(context.t('social.requests.pending', {'n': count}),
                    style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
              ]),
            ),
            const Icon(Icons.chevron_right_rounded, color: OColors.ink),
          ]),
        ),
      );
}

class _FriendsList extends StatelessWidget {
  const _FriendsList({required this.friends});

  final List<Json> friends;

  @override
  Widget build(BuildContext context) {
    if (friends.isEmpty) {
      return OEmptyState(
        icon: Icons.group_rounded,
        title: context.t('social.friends.empty_title'),
        body: context.t('social.friends.empty_body'),
        action: SizedBox(
          width: 220,
          child: OButton(
            label: context.t('social.find.title'),
            icon: Icons.search_rounded,
            onPressed: () => context.push(Routes.findPlayers),
          ),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: OSpace.md, bottom: OSpace.md),
          child: Text.rich(TextSpan(children: [
            TextSpan(text: context.t('social.friends.title'), style: OText.headlineMd),
            TextSpan(text: '  (${friends.length})', style: OText.bodyMd.copyWith(color: OColors.inkSubtle)),
          ])),
        ),
        for (final friend in friends)
          PlayerCard(
            key: ValueKey('friend-${friend['public_id']}'),
            player: friend,
            onTap: () => context.push(Routes.player(friend['public_id'] as String)),
            trailing: friend['can_challenge'] == false
                ? SmallAction(label: context.t('social.friends.busy'), onPressed: null, style: SmallActionStyle.muted)
                : SmallAction(
                    label: context.t('social.challenge.action'),
                    onPressed: () => openChallenge(context, publicId: friend['public_id'] as String),
                  ),
          ),
      ],
    );
  }
}

/// "Share your username" card: the only growth path the package allows (no contacts, no suggestions).
class _ShareUsername extends ConsumerWidget {
  const _ShareUsername();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final username = ref.watch(sessionProvider).value?.username ?? '';
    if (username.isEmpty) return const SizedBox.shrink();
    return OCard(
      color: OColors.surfaceContainer,
      radius: ORadius.card,
      child: Column(children: [
        Text(context.t('social.share.title'), style: OText.headlineSm, textAlign: TextAlign.center),
        const SizedBox(height: OSpace.xs),
        Text(context.t('social.share.body'),
            style: OText.bodySm.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
        const SizedBox(height: OSpace.md),
        Container(
          padding: const EdgeInsets.only(left: OSpace.lg),
          decoration: BoxDecoration(color: OColors.white, borderRadius: BorderRadius.circular(ORadius.pill)),
          child: Row(children: [
            const Icon(Icons.alternate_email_rounded, size: 18, color: OColors.turquoise),
            const SizedBox(width: OSpace.sm),
            Expanded(child: Text(username, style: OText.labelLg, overflow: TextOverflow.ellipsis)),
            TextButton.icon(
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: username));
                if (context.mounted) showMessage(context, context.t('social.share.copied'));
              },
              icon: const Icon(Icons.copy_rounded, size: 18),
              label: Text(context.t('social.share.copy')),
            ),
          ]),
        ),
      ]),
    );
  }
}
