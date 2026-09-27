import 'package:flutter/material.dart';
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

/// Friend requests (P05 screen 4): incoming requests with Accept / Decline, outgoing pending with cancel.
class FriendRequestsScreen extends ConsumerStatefulWidget {
  const FriendRequestsScreen({super.key});

  @override
  ConsumerState<FriendRequestsScreen> createState() => _FriendRequestsScreenState();
}

class _FriendRequestsScreenState extends ConsumerState<FriendRequestsScreen> {
  final Set<String> _busy = {};

  Future<void> _run(String key, Future<Json> Function(ApiClient api) call, String successKey) async {
    setState(() => _busy.add(key));
    try {
      await call(ref.read(apiClientProvider));
      if (mounted) showMessage(context, context.t(successKey));
      ref.invalidate(friendsOverviewProvider);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy.remove(key));
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(friendsOverviewProvider);
    final data = async.value;
    final incoming = jsonList(data?['incoming_requests']);
    final outgoing = jsonList(data?['outgoing_requests']);

    return OPage(
      title: context.t('social.requests.title'),
      onRefresh: () => ref.refresh(friendsOverviewProvider.future),
      children: [
        if (async.hasError && data == null)
          OErrorView(error: async.error!, onRetry: () => ref.invalidate(friendsOverviewProvider))
        else if (data == null)
          const OLoading()
        else if (incoming.isEmpty && outgoing.isEmpty)
          OEmptyState(
            icon: Icons.mark_email_read_outlined,
            title: context.t('social.requests.empty_title'),
            body: context.t('social.requests.empty_body'),
            action: SizedBox(
              width: 220,
              child: OButton(
                label: context.t('social.find.title'),
                icon: Icons.search_rounded,
                onPressed: () => context.push(Routes.findPlayers),
              ),
            ),
          )
        else ...[
          if (incoming.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.only(bottom: OSpace.md),
              child: Row(children: [
                Text(context.t('social.requests.incoming'), style: OText.headlineMd),
                const SizedBox(width: OSpace.sm),
                OPill('${incoming.length}', background: OColors.secondaryFixed, foreground: OColors.secondary),
              ]),
            ),
            for (final r in incoming) _incomingCard(r),
          ],
          if (outgoing.isNotEmpty) ...[
            const SizedBox(height: OSpace.lg),
            Padding(
              padding: const EdgeInsets.only(bottom: OSpace.md),
              child: Row(children: [
                Expanded(
                  child: Text(context.t('social.requests.outgoing').toUpperCase(),
                      style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
                ),
                Text(context.t('social.requests.outgoing_count', {'n': outgoing.length}),
                    style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
              ]),
            ),
            for (final r in outgoing) _outgoingCard(r),
          ],
        ],
      ],
    );
  }

  Widget _incomingCard(Json r) {
    final id = r['request_id'] as String;
    final busy = _busy.contains(id);
    return PlayerCard(
      key: ValueKey('incoming-$id'),
      player: r,
      onTap: () => context.push(Routes.player(r['public_id'] as String)),
      footer: Row(children: [
        Expanded(
          child: OButton(
            label: context.t('action.decline'),
            style: OButtonStyle.secondary,
            onPressed: busy
                ? null
                : () => _run(id, (api) => api.post('/v1/friends/requests/$id/decline'), 'social.requests.declined'),
          ),
        ),
        const SizedBox(width: OSpace.md),
        Expanded(
          child: OButton(
            label: context.t('action.accept'),
            icon: Icons.check_rounded,
            loading: busy,
            onPressed: () => _run(id, (api) => api.post('/v1/friends/requests/$id/accept'), 'social.requests.accepted'),
          ),
        ),
      ]),
    );
  }

  Widget _outgoingCard(Json r) {
    final pid = r['public_id'] as String;
    final key = 'out-$pid';
    return PlayerCard(
      key: ValueKey(key),
      player: r,
      onTap: () => context.push(Routes.player(pid)),
      subtitle: Text(context.t('social.requests.pending_approval'),
          style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
      trailing: TextButton(
        onPressed: _busy.contains(key)
            ? null
            : () => _run(key, (api) => api.delete('/v1/friends/$pid'), 'social.requests.cancelled'),
        style: TextButton.styleFrom(foregroundColor: OColors.secondary, textStyle: OText.labelMd),
        child: Text(context.t('social.requests.cancel')),
      ),
    );
  }
}
