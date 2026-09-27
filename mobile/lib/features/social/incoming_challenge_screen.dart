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

/// Incoming friend challenge (P05 screen 6). The deep link carries only the opaque invite token (spec §6.2);
/// details come from `GET /v1/challenges/invites`, which lists only pending, unexpired invites.
class IncomingChallengeScreen extends ConsumerStatefulWidget {
  const IncomingChallengeScreen({super.key, required this.token});

  final String token;

  /// Party invitations last 60 seconds (spec §6.2); used only to scale the expiry bar.
  static const inviteTtl = Duration(seconds: 60);

  @override
  ConsumerState<IncomingChallengeScreen> createState() => _IncomingChallengeScreenState();
}

class _IncomingChallengeScreenState extends ConsumerState<IncomingChallengeScreen> {
  Json? _invite;
  bool _loaded = false;
  Object? _error;

  /// Error code that closed this invite (PARTY_FULL / PARTY_EXPIRED / BLOCKED / NOT_FOUND).
  String? _closedCode;
  bool _accepting = false;
  bool _declining = false;
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    _load();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _error = null;
      _loaded = false;
    });
    try {
      final res = await ref.read(apiClientProvider).get('/v1/challenges/invites');
      if (!mounted) return;
      setState(() {
        _invite = jsonList(res['invites']).where((i) => i['invite_token'] == widget.token).firstOrNull;
        _loaded = true;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Duration? get _remaining {
    final at = (_invite?['expires_at_ms'] as num?)?.toInt();
    if (at == null) return null;
    return Duration(milliseconds: at - ref.read(serverClockProvider).nowMs());
  }

  Future<void> _accept() async {
    final invite = _invite!;
    setState(() => _accepting = true);
    try {
      final party = await ref.read(apiClientProvider).post('/v1/challenges/${widget.token}/accept', {
        // The invitee explicitly accepts the host's question language (spec §6.2).
        'accept_question_language': invite['question_language'],
      });
      if (!mounted) return;
      final partyId = (party['party_id'] ?? invite['party_id']) as String;
      final matchId = party['match_id'] as String?;
      context.go(party['state'] == 'MATCHED' && matchId != null
          ? Routes.matchReady(matchId)
          : Routes.challengeLobby(partyId));
    } on ApiException catch (e) {
      if (!mounted) return;
      if (const {'PARTY_FULL', 'PARTY_EXPIRED', 'BLOCKED', 'NOT_FOUND'}.contains(e.code)) {
        setState(() {
          _closedCode = e.code;
          _accepting = false;
        });
      } else {
        showError(context, e);
        setState(() => _accepting = false);
      }
    } catch (e) {
      if (!mounted) return;
      showError(context, e);
      setState(() => _accepting = false);
    }
  }

  Future<void> _decline() async {
    setState(() => _declining = true);
    try {
      await ref.read(apiClientProvider).post('/v1/challenges/${widget.token}/decline');
    } catch (_) {
      // Declining is best effort: the invite expires on its own within a minute.
    }
    if (mounted) _exit();
  }

  void _exit() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go(Routes.home);
    }
  }

  @override
  Widget build(BuildContext context) {
    final invite = _invite;
    final remaining = _remaining;
    final expired = remaining != null && remaining <= Duration.zero;
    final closed = _closedCode != null || (_loaded && invite == null) || expired;

    Widget? bottom;
    if (invite != null && !closed) {
      bottom = Column(mainAxisSize: MainAxisSize.min, children: [
        OButton(
          key: const ValueKey('challenge-accept'),
          label: context.t('social.incoming.accept'),
          icon: Icons.play_arrow_rounded,
          loading: _accepting,
          onPressed: _declining ? null : _accept,
        ),
        const SizedBox(height: OSpace.sm),
        OButton(
          label: context.t('action.decline'),
          style: OButtonStyle.secondary,
          loading: _declining,
          onPressed: _accepting ? null : _decline,
        ),
      ]);
    } else if (closed) {
      bottom = OButton(label: context.t('action.close'), style: OButtonStyle.secondary, onPressed: _exit);
    }

    return OPage(
      title: context.t('social.incoming.title'),
      bottom: bottom,
      children: [
        if (_error != null)
          OErrorView(error: _error!, onRetry: _load)
        else if (!_loaded)
          const OLoading()
        else if (closed)
          OEmptyState(
            icon: _closedCode == 'BLOCKED' ? Icons.block_rounded : Icons.timer_off_outlined,
            title: context.t(switch (_closedCode) {
              'PARTY_FULL' => 'social.incoming.full',
              'BLOCKED' => 'social.incoming.blocked',
              _ => 'social.incoming.expired',
            }),
            body: context.t('social.incoming.closed_body'),
          )
        else ...[
          if (remaining != null) _ExpiryBar(remaining: remaining),
          const SizedBox(height: OSpace.lg),
          _InviteCard(invite: invite!),
        ],
      ],
    );
  }
}

class _ExpiryBar extends StatelessWidget {
  const _ExpiryBar({required this.remaining});

  final Duration remaining;

  @override
  Widget build(BuildContext context) {
    final fraction = remaining.inMilliseconds / IncomingChallengeScreen.inviteTtl.inMilliseconds;
    return OCard(
      radius: ORadius.card,
      child: Column(children: [
        Row(children: [
          const Icon(Icons.timer_outlined, size: 20, color: OColors.tertiary),
          const SizedBox(width: OSpace.sm),
          Expanded(child: Text(context.t('social.incoming.expires'), style: OText.labelMd)),
          Text(clockText(remaining), style: OText.tabular(OText.headlineMd).copyWith(color: OColors.secondary)),
        ]),
        const SizedBox(height: OSpace.sm),
        OProgressBar(value: fraction),
      ]),
    );
  }
}

class _InviteCard extends StatelessWidget {
  const _InviteCard({required this.invite});

  final Json invite;

  @override
  Widget build(BuildContext context) {
    final host = (invite['host'] as Map?)?.cast<String, dynamic>() ?? const {};
    final mode = invite['mode'] as String? ?? 'QUICK';
    return Container(
      padding: const EdgeInsets.all(OSpace.xl),
      decoration: BoxDecoration(
        color: OColors.white,
        borderRadius: BorderRadius.circular(ORadius.lg),
        boxShadow: OShadow.floating,
      ),
      child: Column(children: [
        OPill(context.t('social.incoming.live'), dot: true, background: OColors.rose, foreground: OColors.secondary),
        const SizedBox(height: OSpace.lg),
        OAvatar(avatarId: host['avatar_id'] as String?, frameId: host['frame_id'] as String?, size: 104),
        const SizedBox(height: OSpace.md),
        Text(host['username'] as String? ?? '', style: OText.headlineXlMobile, textAlign: TextAlign.center),
        const SizedBox(height: OSpace.xs),
        Text.rich(
          TextSpan(children: [
            TextSpan(text: context.t('social.incoming.invited_you')),
            TextSpan(text: context.t('mode.$mode'), style: OText.bodyLg.copyWith(fontWeight: FontWeight.w800)),
          ]),
          style: OText.bodyLg.copyWith(color: OColors.inkSubtle),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: OSpace.lg),
        Container(
          padding: const EdgeInsets.all(OSpace.md),
          decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.sm)),
          child: Column(children: [
            _InfoRow(icon: Icons.groups_rounded, label: context.t('social.incoming.format'),
                value: context.t('social.incoming.format_value')),
            const SizedBox(height: OSpace.sm),
            _InfoRow(icon: Icons.translate_rounded, label: context.t('social.incoming.language'),
                value: context.t('social.incoming.language_value',
                    {'language': languageName(context, invite['question_language'] as String?)})),
          ]),
        ),
      ]),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.icon, required this.label, required this.value});

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Row(children: [
        Icon(icon, size: 20, color: OColors.primary),
        const SizedBox(width: OSpace.sm),
        Text(label, style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
        const SizedBox(width: OSpace.md),
        Expanded(child: Text(value, style: OText.labelMd, textAlign: TextAlign.end)),
      ]);
}
