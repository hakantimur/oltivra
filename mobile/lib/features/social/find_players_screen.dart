import 'dart:async';

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

/// Find players (P05 screen 2): one username field, exact/prefix search via `GET /v1/users/search`.
class FindPlayersScreen extends ConsumerStatefulWidget {
  const FindPlayersScreen({super.key});

  static const debounce = Duration(milliseconds: 400);
  static const minLength = 2;

  @override
  ConsumerState<FindPlayersScreen> createState() => _FindPlayersScreenState();
}

class _FindPlayersScreenState extends ConsumerState<FindPlayersScreen> {
  final _controller = TextEditingController();
  Timer? _debounce;
  String _query = '';
  bool _loading = false;
  Object? _error;
  List<Json>? _results;
  final Set<String> _busy = {};
  int _generation = 0;

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    final query = value.trim();
    setState(() => _query = query);
    if (query.length < FindPlayersScreen.minLength) {
      _generation++;
      setState(() {
        _results = null;
        _error = null;
        _loading = false;
      });
      return;
    }
    _debounce = Timer(FindPlayersScreen.debounce, () => _search(query));
  }

  Future<void> _search(String query) async {
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final res = await ref.read(apiClientProvider).get('/v1/users/search', query: {'username': query});
      if (!mounted || generation != _generation) return;
      setState(() {
        _results = jsonList(res['results']);
        _loading = false;
      });
    } catch (e) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _addFriend(Json player) async {
    final publicId = player['public_id'] as String;
    setState(() => _busy.add(publicId));
    try {
      final res = await ref.read(apiClientProvider).post('/v1/friends/requests', {'target_public_id': publicId});
      if (!mounted) return;
      setState(() => player['relationship'] = res['relationship'] ?? Relationship.sent);
      ref.invalidate(friendsOverviewProvider);
      showMessage(context, context.t(res['relationship'] == Relationship.friend
          ? 'social.find.now_friends'
          : 'social.find.request_sent_toast'));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy.remove(publicId));
    }
  }

  Widget _action(Json player) {
    final publicId = player['public_id'] as String;
    final busy = _busy.contains(publicId);
    return switch (player['relationship']) {
      Relationship.friend => SmallAction(
          label: context.t('social.challenge.action'),
          icon: Icons.bolt_rounded,
          style: SmallActionStyle.pink,
          onPressed: () => openChallenge(context, publicId: publicId),
        ),
      Relationship.sent => SmallAction(
          label: context.t('social.relationship.sent'),
          icon: Icons.schedule_rounded,
          style: SmallActionStyle.muted,
          onPressed: null,
        ),
      Relationship.received => SmallAction(
          label: context.t('action.accept'),
          icon: Icons.check_rounded,
          loading: busy,
          onPressed: () => _addFriend(player),
        ),
      _ => SmallAction(
          label: context.t('social.add_friend'),
          icon: Icons.person_add_alt_1_rounded,
          loading: busy,
          onPressed: () => _addFriend(player),
        ),
    };
  }

  Widget? _relationshipNote(Json player) => switch (player['relationship']) {
        Relationship.friend => Text(context.t('social.relationship.friend'),
            style: OText.labelSm.copyWith(color: OColors.primary)),
        Relationship.received => Text(context.t('social.relationship.received'),
            style: OText.labelSm.copyWith(color: OColors.secondary)),
        _ => null,
      };

  @override
  Widget build(BuildContext context) {
    final results = _results;
    return OPage(
      title: context.t('social.find.title'),
      children: [
        Text(context.t('social.find.subtitle'), style: OText.bodyMd.copyWith(color: OColors.inkSubtle)),
        const SizedBox(height: OSpace.lg),
        TextField(
          key: const ValueKey('social-search-field'),
          controller: _controller,
          autofocus: true,
          autocorrect: false,
          enableSuggestions: false,
          textInputAction: TextInputAction.search,
          maxLength: 32,
          onChanged: _onChanged,
          onSubmitted: (v) {
            _debounce?.cancel();
            if (v.trim().length >= FindPlayersScreen.minLength) _search(v.trim());
          },
          decoration: InputDecoration(
            counterText: '',
            hintText: context.t('social.find.hint'),
            prefixIcon: const Icon(Icons.search_rounded, color: OColors.primary),
            suffixIcon: _query.isEmpty
                ? null
                : IconButton(
                    tooltip: context.t('social.find.clear'),
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () {
                      _controller.clear();
                      _onChanged('');
                    },
                  ),
          ),
        ),
        const SizedBox(height: OSpace.lg),
        if (_query.isNotEmpty && _query.length < FindPlayersScreen.minLength)
          Text(context.t('social.find.too_short'), style: OText.bodySm.copyWith(color: OColors.inkSubtle))
        else if (_loading && results == null)
          const OLoading()
        else if (_error != null)
          OErrorView(error: _error!, onRetry: () => _search(_query))
        else if (results != null) ...[
          if (results.isEmpty)
            OEmptyState(
              icon: Icons.person_search_rounded,
              title: context.t('social.find.no_results'),
              body: context.t('social.find.no_results_body'),
            )
          else ...[
            Padding(
              padding: const EdgeInsets.only(bottom: OSpace.md),
              child: Row(children: [
                Expanded(
                  child: Text(context.t('social.find.results', {'n': results.length}).toUpperCase(),
                      style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
                ),
                if (_loading) const SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2)),
              ]),
            ),
            for (final player in results)
              PlayerCard(
                key: ValueKey('result-${player['public_id']}'),
                player: player,
                subtitle: Wrap(
                  crossAxisAlignment: WrapCrossAlignment.center,
                  spacing: OSpace.sm,
                  children: [
                    LeagueChip(league: player['league'] as String?, level: (player['level'] as num?)?.toInt()),
                    ?_relationshipNote(player),
                  ],
                ),
                onTap: () => context.push(Routes.player(player['public_id'] as String)),
                trailing: _action(player),
              ),
          ],
        ],
        const SizedBox(height: OSpace.lg),
        OCard(
          color: OColors.surfaceContainer,
          radius: ORadius.card,
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.lock_outline_rounded, color: OColors.primary),
            const SizedBox(width: OSpace.md),
            Expanded(child: Text(context.t('social.find.privacy'), style: OText.bodySm)),
          ]),
        ),
      ],
    );
  }
}
