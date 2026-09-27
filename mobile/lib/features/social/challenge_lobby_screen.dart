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
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'social_api.dart';
import 'social_widgets.dart';

/// Friend Challenge (P05 screen 5, spec §6.2).
///
/// Without [partyId] the host picks up to three friends and creates the party (`POST /v1/challenges`);
/// the backend fixes the mode to Quick Battle and the question language to the host's choice. With a party,
/// the lobby polls `GET /v1/parties/{id}` every ~2 s and moves to Match Ready once the party is MATCHED.
class ChallengeLobbyScreen extends ConsumerStatefulWidget {
  const ChallengeLobbyScreen({super.key, this.partyId});

  final String? partyId;

  static const maxInvites = 3;
  static const maxMembers = 4;
  static const pollEvery = Duration(seconds: 2);

  @override
  ConsumerState<ChallengeLobbyScreen> createState() => _ChallengeLobbyScreenState();
}

class _ChallengeLobbyScreenState extends ConsumerState<ChallengeLobbyScreen> {
  static const _open = {'WAITING', 'READY'};

  String? _partyId;
  Json? _party;
  Object? _error;
  Timer? _ticker;
  int _ticks = 0;
  bool _polling = false;
  bool _busy = false;
  bool _navigated = false;

  // Composer state.
  final Set<String> _selected = {};
  bool _preselected = false;

  @override
  void initState() {
    super.initState();
    _partyId = widget.partyId;
    if (_partyId != null) _startLobby();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_preselected || _partyId != null) return;
    _preselected = true;
    try {
      final friend = GoRouterState.of(context).uri.queryParameters['friend'];
      if (friend != null && friend.isNotEmpty) _selected.add(friend);
    } catch (_) {
      // Not built by the router (tests / embedding): nothing to pre-select.
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  // ------------------------------------------------------------------------------------------ lobby

  void _startLobby() {
    _poll();
    _ticker?.cancel();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      _ticks++;
      if (_ticks % ChallengeLobbyScreen.pollEvery.inSeconds == 0) _poll();
      setState(() {}); // countdown
    });
  }

  Future<void> _poll() async {
    final id = _partyId;
    if (id == null || _polling || _navigated) return;
    _polling = true;
    try {
      final party = await ref.read(apiClientProvider).get('/v1/parties/$id');
      if (!mounted) return;
      _apply(party);
    } catch (e) {
      if (mounted && _party == null) setState(() => _error = e);
    } finally {
      _polling = false;
    }
  }

  void _apply(Json party) {
    setState(() {
      _party = party;
      _error = null;
    });
    final matchId = party['match_id'] as String?;
    if (party['state'] == 'MATCHED' && matchId != null && !_navigated) {
      _navigated = true;
      _ticker?.cancel();
      context.go(Routes.matchReady(matchId));
      return;
    }
    if (!_open.contains(party['state']) && party['state'] != 'STARTING') _ticker?.cancel();
  }

  Future<void> _start() async {
    setState(() => _busy = true);
    try {
      final party = await ref.read(apiClientProvider).post('/v1/parties/$_partyId/start');
      if (mounted) _apply(party);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _leave({required bool host}) async {
    final ok = await confirmAction(context,
        title: context.t(host ? 'social.lobby.cancel_title' : 'social.lobby.leave_title'),
        body: context.t(host ? 'social.lobby.cancel_body' : 'social.lobby.leave_body'),
        confirm: context.t(host ? 'social.lobby.cancel' : 'action.leave'));
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    try {
      await ref.read(apiClientProvider).post('/v1/parties/$_partyId/leave');
      _ticker?.cancel();
      if (mounted) _exit();
    } catch (e) {
      if (mounted) {
        showError(context, e);
        setState(() => _busy = false);
      }
    }
  }

  void _exit() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go(Routes.social);
    }
  }

  // ------------------------------------------------------------------------------------------ composer

  Future<void> _create() async {
    final language = ref.read(sessionProvider).value?.questionLanguage ?? 'en';
    setState(() => _busy = true);
    try {
      final party = await ref.read(apiClientProvider).post('/v1/challenges', {
        'friend_public_ids': _selected.toList(),
        'question_language': language,
      });
      if (!mounted) return;
      _partyId = party['party_id'] as String?;
      _apply(party);
      if (_partyId != null) _startLobby();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ------------------------------------------------------------------------------------------ build

  @override
  Widget build(BuildContext context) {
    final party = _party;
    if (_partyId == null) return _composer(context);
    if (party == null) {
      return OPage(
        title: context.t('social.lobby.title'),
        children: [
          if (_error != null) OErrorView(error: _error!, onRetry: _poll) else const OLoading(),
        ],
      );
    }
    return _lobby(context, party);
  }

  Widget _composer(BuildContext context) {
    final overview = ref.watch(friendsOverviewProvider);
    final data = overview.value;
    final friends = jsonList(data?['friends']);
    final language = ref.watch(sessionProvider).value?.questionLanguage ?? 'en';
    final full = _selected.length >= ChallengeLobbyScreen.maxInvites;

    return OPage(
      title: context.t('social.lobby.title'),
      bottom: friends.isEmpty
          ? null
          : OButton(
              label: _selected.isEmpty
                  ? context.t('social.lobby.invite')
                  : context.t('social.lobby.invite_n', {'n': _selected.length}),
              icon: Icons.group_add_rounded,
              loading: _busy,
              onPressed: _selected.isEmpty ? null : _create,
            ),
      children: [
        const _FormatCard(),
        const SizedBox(height: OSpace.md),
        _LanguageChip(language: language),
        OSectionHeader(context.t('social.lobby.pick_friends'),
            trailing: context.t('social.lobby.selected', {'n': _selected.length, 'max': ChallengeLobbyScreen.maxInvites})),
        if (overview.hasError && data == null)
          OErrorView(error: overview.error!, onRetry: () => ref.invalidate(friendsOverviewProvider))
        else if (data == null)
          const OLoading()
        else if (friends.isEmpty)
          OEmptyState(
            icon: Icons.group_rounded,
            title: context.t('social.friends.empty_title'),
            body: context.t('social.lobby.no_friends_body'),
            action: SizedBox(
              width: 220,
              child: OButton(label: context.t('social.find.title'), onPressed: () => context.push(Routes.findPlayers)),
            ),
          )
        else
          for (final f in friends) _friendOption(f, full),
      ],
    );
  }

  Widget _friendOption(Json f, bool full) {
    final pid = f['public_id'] as String;
    final selected = _selected.contains(pid);
    final available = f['can_challenge'] != false;
    final enabled = available && (selected || !full);
    return PlayerCard(
      key: ValueKey('pick-$pid'),
      player: f,
      subtitle: available
          ? null
          : Text(context.t('social.friends.busy_long'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
      onTap: enabled ? () => setState(() => selected ? _selected.remove(pid) : _selected.add(pid)) : null,
      trailing: Checkbox(
        value: selected,
        onChanged: enabled ? (v) => setState(() => v == true ? _selected.add(pid) : _selected.remove(pid)) : null,
      ),
    );
  }

  Widget _lobby(BuildContext context, Json party) {
    final state = party['state'] as String? ?? 'WAITING';
    final members = jsonList(party['members']);
    final me = members.where((m) => m['is_you'] == true).firstOrNull;
    final isHost = me?['is_host'] == true;
    final accepted = members.where((m) => m['status'] == 'ACCEPTED').length;
    final minHumans = (party['min_humans'] as num?)?.toInt() ?? 2;
    final open = _open.contains(state);
    final expiresAt = (party['expires_at_ms'] as num?)?.toInt();
    final remaining = expiresAt == null
        ? null
        : Duration(milliseconds: expiresAt - ref.read(serverClockProvider).nowMs());
    final emptySlots = (ChallengeLobbyScreen.maxMembers - members.length).clamp(0, ChallengeLobbyScreen.maxMembers);

    Widget? bottom;
    if (open) {
      bottom = Column(mainAxisSize: MainAxisSize.min, children: [
        if (isHost)
          OButton(
            key: const ValueKey('lobby-start'),
            label: context.t('social.lobby.start'),
            icon: Icons.play_arrow_rounded,
            loading: _busy,
            onPressed: state == 'READY' ? _start : null,
          )
        else
          Padding(
            padding: const EdgeInsets.only(bottom: OSpace.sm),
            child: Text(context.t('social.lobby.waiting_host'),
                style: OText.bodyMd.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
          ),
        const SizedBox(height: OSpace.sm),
        OButton(
          label: context.t(isHost ? 'social.lobby.cancel' : 'action.leave'),
          style: OButtonStyle.secondary,
          onPressed: _busy ? null : () => _leave(host: isHost),
        ),
      ]);
    } else if (state != 'STARTING' && state != 'MATCHED') {
      bottom = OButton(label: context.t('social.lobby.back'), onPressed: _exit);
    }

    return OPage(
      title: context.t('social.lobby.title'),
      bottom: bottom,
      children: [
        const _FormatCard(),
        const SizedBox(height: OSpace.md),
        Wrap(spacing: OSpace.sm, runSpacing: OSpace.sm, children: [
          _LanguageChip(language: party['question_language'] as String?),
          if (open && remaining != null) _ExpiryChip(remaining: remaining),
        ]),
        const SizedBox(height: OSpace.lg),
        if (state == 'STARTING' || state == 'MATCHED')
          _Banner(icon: Icons.bolt_rounded, text: context.t('social.lobby.starting'), color: OColors.mint)
        else if (state == 'CANCELLED')
          _Banner(icon: Icons.cancel_outlined, text: context.t('social.lobby.cancelled'), color: OColors.rose)
        else if (state == 'EXPIRED')
          _Banner(icon: Icons.timer_off_outlined, text: context.t('social.lobby.expired'), color: OColors.rose)
        else if (isHost && state == 'WAITING')
          _Banner(
              icon: Icons.hourglass_top_rounded,
              text: context.t('social.lobby.need_players', {'n': minHumans}),
              color: OColors.sun),
        for (final m in members) _MemberRow(member: m),
        if (open) for (var i = 0; i < emptySlots; i++) const _EmptySlot(),
        if (open && accepted >= minHumans)
          Padding(
            padding: const EdgeInsets.only(top: OSpace.sm),
            child: Text(context.t('social.lobby.autostart'),
                style: OText.bodySm.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
          ),
      ],
    );
  }
}

class _FormatCard extends StatelessWidget {
  const _FormatCard();

  @override
  Widget build(BuildContext context) => OCard(
        color: OColors.surfaceContainer,
        radius: ORadius.md,
        child: Row(children: [
          const Icon(Icons.bolt_rounded, color: OColors.primary),
          const SizedBox(width: OSpace.md),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(context.t('social.lobby.format'), style: OText.labelLg),
              const SizedBox(height: 2),
              Text(context.t('social.lobby.format_body'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            ]),
          ),
        ]),
      );
}

class _LanguageChip extends StatelessWidget {
  const _LanguageChip({required this.language});

  final String? language;

  @override
  Widget build(BuildContext context) => OPill(
        context.t('social.lobby.language', {'language': languageName(context, language)}),
        icon: Icons.translate_rounded,
        background: OColors.surfaceContainer,
        foreground: OColors.ink,
      );
}

class _ExpiryChip extends StatelessWidget {
  const _ExpiryChip({required this.remaining});

  final Duration remaining;

  @override
  Widget build(BuildContext context) => Semantics(
        liveRegion: false,
        child: OPill(
          context.t('social.lobby.expires', {'time': clockText(remaining)}),
          icon: Icons.timer_outlined,
          background: OColors.tertiaryFixed,
          foreground: OColors.tertiary,
        ),
      );
}

class _Banner extends StatelessWidget {
  const _Banner({required this.icon, required this.text, required this.color});

  final IconData icon;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: OSpace.md),
        padding: const EdgeInsets.all(OSpace.md),
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(ORadius.card)),
        child: Row(children: [
          Icon(icon, size: 20, color: OColors.ink),
          const SizedBox(width: OSpace.sm),
          Expanded(child: Text(text, style: OText.bodyMd)),
        ]),
      );
}

class _MemberRow extends StatelessWidget {
  const _MemberRow({required this.member});

  final Json member;

  @override
  Widget build(BuildContext context) {
    final accepted = member['status'] == 'ACCEPTED';
    final host = member['is_host'] == true;
    final you = member['is_you'] == true;
    final status = host
        ? 'social.lobby.status_ready'
        : accepted
            ? 'social.lobby.status_joined'
            : 'social.lobby.status_invited';
    final detail = host
        ? 'social.lobby.detail_host'
        : accepted
            ? 'social.lobby.detail_joined'
            : 'social.lobby.detail_invited';
    return Padding(
      padding: const EdgeInsets.only(bottom: OSpace.md),
      child: OCard(
        radius: ORadius.lg,
        padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
        child: Row(children: [
          OAvatar(avatarId: member['avatar_id'] as String?, frameId: member['frame_id'] as String?, size: 52),
          const SizedBox(width: OSpace.md),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Wrap(spacing: OSpace.sm, crossAxisAlignment: WrapCrossAlignment.center, children: [
                Text(member['username'] as String? ?? '', style: OText.headlineSm, overflow: TextOverflow.ellipsis),
                if (host) OPill(context.t('social.lobby.host'), background: OColors.mint, foreground: OColors.primary),
                if (you) OPill(context.t('social.lobby.you'), background: OColors.surfaceContainer, foreground: OColors.ink),
              ]),
              const SizedBox(height: 2),
              Text(context.t(detail), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            ]),
          ),
          OPill(
            context.t(status),
            icon: accepted ? Icons.check_circle_outline_rounded : Icons.schedule_rounded,
            background: accepted ? OColors.mint : OColors.surfaceContainer,
            foreground: accepted ? OColors.primary : OColors.inkSubtle,
          ),
        ]),
      ),
    );
  }
}

class _EmptySlot extends StatelessWidget {
  const _EmptySlot();

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: OSpace.md),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.md),
          decoration: BoxDecoration(
            color: OColors.surfaceContainer.withValues(alpha: 0.5),
            borderRadius: BorderRadius.circular(ORadius.lg),
          ),
          child: Row(children: [
            Container(
              width: 52,
              height: 52,
              decoration: const BoxDecoration(color: OColors.surfaceContainerHigh, shape: BoxShape.circle),
              child: const Icon(Icons.shuffle_rounded, color: OColors.inkSubtle),
            ),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(context.t('social.lobby.empty_slot'), style: OText.labelLg.copyWith(color: OColors.inkSubtle)),
                Text(context.t('social.lobby.empty_slot_body'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
              ]),
            ),
          ]),
        ),
      );
}
