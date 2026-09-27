import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'settings_widgets.dart';

/// P07 · Blocked players: username + curated avatar only, each with Unblock (`GET /v1/blocks`,
/// `DELETE /v1/blocks/{public_id}`).
class BlockedPlayersScreen extends ConsumerStatefulWidget {
  const BlockedPlayersScreen({super.key});

  @override
  ConsumerState<BlockedPlayersScreen> createState() => _BlockedPlayersScreenState();
}

class _BlockedPlayersScreenState extends ConsumerState<BlockedPlayersScreen> {
  List<Json>? _items;
  Object? _error;
  final Set<String> _busy = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final res = await ref.read(apiClientProvider).get('/v1/blocks');
      final list = ((res['blocked'] as List?) ?? const []).whereType<Map>().map((e) => e.cast<String, dynamic>());
      if (mounted) setState(() => _items = list.toList());
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _unblock(Json item) async {
    final id = item['public_id'] as String;
    setState(() => _busy.add(id));
    try {
      await ref.read(apiClientProvider).delete('/v1/blocks/$id');
      if (!mounted) return;
      setState(() => _items = [...?_items]..removeWhere((e) => e['public_id'] == id));
      showMessage(context, context.t('settings.blocked.unblocked', {'name': item['username'] ?? ''}));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = _items;
    return OPage(
      title: context.t('settings.blocked'),
      onRefresh: _load,
      children: [
        InfoBanner(
          icon: Icons.shield_outlined,
          iconBackground: OColors.turquoise.withValues(alpha: 0.25),
          title: context.t('settings.blocked.info.title'),
          body: context.t('settings.blocked.info.body'),
        ),
        if (items == null && _error != null)
          OErrorView(error: _error!, onRetry: _load)
        else if (items == null)
          const OLoading()
        else if (items.isEmpty)
          OEmptyState(
            icon: Icons.sentiment_satisfied_alt_rounded,
            title: context.t('settings.blocked.empty.title'),
            body: context.t('settings.blocked.empty.body'),
          )
        else ...[
          SettingsCaption(
            context.t('settings.blocked.caption'),
            trailing: OPill(context.t('settings.blocked.count', {'n': items.length}),
                background: OColors.surfaceContainer, foreground: OColors.ink),
          ),
          for (final item in items)
            Padding(
              padding: const EdgeInsets.only(bottom: OSpace.sm),
              child: OCard(
                padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
                child: Row(
                  children: [
                    OAvatar(avatarId: item['avatar_id'] as String?, size: 52),
                    const SizedBox(width: OSpace.lg),
                    Expanded(
                      child: Text('${item['username'] ?? ''}', style: OText.headlineSm, overflow: TextOverflow.ellipsis),
                    ),
                    const SizedBox(width: OSpace.sm),
                    _busy.contains(item['public_id'])
                        ? const SizedBox.square(dimension: 24, child: CircularProgressIndicator(strokeWidth: 2))
                        : FilledButton.tonalIcon(
                            key: ValueKey('unblock_${item['public_id']}'),
                            onPressed: () => _unblock(item),
                            icon: const Icon(Icons.lock_open_rounded, size: 18),
                            label: Text(context.t('settings.blocked.unblock')),
                            style: FilledButton.styleFrom(
                              backgroundColor: OColors.surfaceContainer,
                              foregroundColor: OColors.ink,
                              minimumSize: const Size(48, 48),
                            ),
                          ),
                  ],
                ),
              ),
            ),
        ],
      ],
    );
  }
}
