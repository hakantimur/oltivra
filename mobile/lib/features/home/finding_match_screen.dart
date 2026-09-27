import 'dart:async';
import 'dart:math' as math;

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
import 'home_api.dart';
import 'widgets.dart';

enum _Phase { measuring, joining, queued, matched, over, blocked, leaving }

/// Public matchmaking (design P02 "Finding your Quick Battle", reused for Survival).
///
/// Flow (spec §21.2–21.3): 5 authenticated pings → median RTT → `POST /v1/matchmaking/{mode}/join` → poll
/// `GET /v1/matchmaking/status` at the server's `next_poll_at_ms` until MATCHED / EXPIRED / CANCELLED.
/// Seats are never labelled as people or computer players (decision D3).
class FindingMatchScreen extends ConsumerStatefulWidget {
  const FindingMatchScreen({super.key, required this.mode, this.categoryId});

  final String mode;
  final String? categoryId;

  @override
  ConsumerState<FindingMatchScreen> createState() => _FindingMatchScreenState();
}

class _FindingMatchScreenState extends ConsumerState<FindingMatchScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 2400))..repeat();
  late final ApiClient _api = ref.read(apiClientProvider);

  _Phase _phase = _Phase.measuring;
  bool _busy = false;
  String? _overKey;
  ApiException? _error;
  bool _canRetry = true;
  int _generation = 0;
  int _pollFailures = 0;
  DateTime _startedAt = DateTime.now();
  Timer? _tick;
  Timer? _poll;

  String get _modePath => widget.mode.toLowerCase();

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _searching) setState(() {});
    });
    _start();
  }

  @override
  void dispose() {
    _generation++;
    _tick?.cancel();
    _poll?.cancel();
    _pulse.dispose();
    super.dispose();
  }

  bool get _searching => _phase == _Phase.measuring || _phase == _Phase.joining || _phase == _Phase.queued;

  bool _alive(int gen) => mounted && gen == _generation && _phase != _Phase.leaving;

  // ---------------------------------------------------------------------------------------- flow

  Future<void> _start() async {
    final gen = ++_generation;
    _poll?.cancel();
    setState(() {
      _phase = _Phase.measuring;
      _busy = false;
      _overKey = null;
      _error = null;
      _pollFailures = 0;
      _startedAt = DateTime.now();
    });
    final api = _api;
    final path = _modePath;
    try {
      final rtt = await measureMedianRtt(api);
      if (!_alive(gen)) return;
      setState(() => _phase = _Phase.joining);
      final res = await api.post('/v1/matchmaking/$path/join', {
        'median_rtt_ms': rtt,
        if (widget.categoryId != null) 'category_id': widget.categoryId,
      });
      if (!_alive(gen)) {
        // The player cancelled while the join was in flight: make sure no ticket is left behind.
        if (QueueStatus(res).isQueued) unawaited(_leaveQuietly(api, path));
        return;
      }
      _handle(QueueStatus(res), gen);
    } on ApiException catch (e) {
      if (!_alive(gen)) return;
      _handleJoinError(e, gen);
    }
  }

  static Future<void> _leaveQuietly(ApiClient api, String path) async {
    try {
      await api.delete('/v1/matchmaking/$path/leave');
    } catch (_) {}
  }

  void _handle(QueueStatus status, int gen) {
    final clock = ref.read(serverClockProvider);
    final serverNow = status.serverTimeMs;
    if (serverNow != null) clock.observe(serverNow);
    if (status.isMatched && status.matchId != null) {
      setState(() => _phase = _Phase.matched);
      context.go(Routes.matchReady(status.matchId!));
      return;
    }
    if (status.isQueued) {
      setState(() {
        _phase = _Phase.queued;
        _busy = status.capacityLimited;
      });
      final next = status.nextPollAtMs ?? clock.nowMs() + 1000;
      _schedulePoll(Duration(milliseconds: (next - clock.nowMs()).clamp(300, 5000)), gen);
      return;
    }
    if (status.isSettling) {
      _showOver('home.finding.settling');
      return;
    }
    if (status.isOver) {
      _showOver(status.state == 'EXPIRED' ? 'home.finding.expired' : 'home.finding.cancelled');
      return;
    }
    // Transient states (e.g. a roster claim in progress): check again shortly.
    _schedulePoll(const Duration(milliseconds: 700), gen);
  }

  void _schedulePoll(Duration delay, int gen) {
    _poll?.cancel();
    _poll = Timer(delay, () => _pollOnce(gen));
  }

  Future<void> _pollOnce(int gen) async {
    if (!_alive(gen)) return;
    try {
      final res = await _api.get('/v1/matchmaking/status');
      if (!_alive(gen)) return;
      _pollFailures = 0;
      _handle(QueueStatus(res), gen);
    } on ApiException catch (e) {
      if (!_alive(gen)) return;
      if (e.isNetwork || e.retryable) {
        _pollFailures++;
        _schedulePoll(Duration(milliseconds: math.min(1000 * _pollFailures, 5000)), gen);
      } else {
        _showBlocked(e, retry: true);
      }
    }
  }

  void _handleJoinError(ApiException e, int gen) {
    switch (e.code) {
      case 'ACTIVE_RUNTIME_CONFLICT':
        final state = e.detail['state'] as String?;
        final matchId = e.detail['match_id'] as String?;
        final partyId = e.detail['party_id'] as String?;
        if (state == 'QUEUED') {
          setState(() => _phase = _Phase.queued);
          _pollOnce(gen);
        } else if (state == 'MATCH_ACTIVE' && matchId != null) {
          context.go(Routes.match(matchId));
        } else if (state == 'IN_PARTY' && partyId != null) {
          context.go(Routes.challengeLobby(partyId));
        } else {
          _showBlocked(e, retry: true);
        }
      case 'RENAME_REQUIRED':
        context.go(Routes.rename);
      case 'MATCH_SETTLEMENT_PENDING':
        _showOver('home.finding.settling');
      case 'QUEUE_RESTRICTED' || 'FEATURE_DISABLED' || 'ACCOUNT_SUSPENDED' || 'ACCOUNT_DELETION_PENDING' ||
            'PROFILE_INCOMPLETE':
        _showBlocked(e, retry: false);
      default:
        _showBlocked(e, retry: true);
    }
  }

  void _showOver(String key) {
    _poll?.cancel();
    setState(() {
      _phase = _Phase.over;
      _overKey = key;
      _busy = false;
    });
  }

  void _showBlocked(ApiException e, {required bool retry}) {
    _poll?.cancel();
    setState(() {
      _phase = _Phase.blocked;
      _error = e;
      _canRetry = retry;
      _busy = false;
    });
  }

  /// Cancel: `DELETE /v1/matchmaking/{mode}/leave`, then back to the Play tab. A ticket matched in the meantime
  /// returns the match pointer instead, which takes precedence.
  Future<void> _cancel() async {
    if (!_searching) {
      context.go(Routes.play);
      return;
    }
    _poll?.cancel();
    setState(() => _phase = _Phase.leaving);
    try {
      final status = QueueStatus(await _api.delete('/v1/matchmaking/$_modePath/leave'));
      if (!mounted) return;
      if (status.isMatched && status.matchId != null) {
        context.go(Routes.matchReady(status.matchId!));
        return;
      }
    } catch (_) {
      // QUEUE_TICKET_NOT_ACTIVE or a network error: the ticket expires server-side regardless.
    }
    if (mounted) context.go(Routes.play);
  }

  Future<void> _confirmCancel() async {
    if (!_searching) {
      context.go(Routes.play);
      return;
    }
    final leave = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(context.t('home.finding.confirm.title')),
        content: Text(context.t('home.finding.confirm.body')),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(context.t('home.finding.confirm.stay')),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(context.t('home.finding.confirm.leave')),
          ),
        ],
      ),
    );
    if (leave == true && mounted) await _cancel();
  }

  // ---------------------------------------------------------------------------------------- UI

  String _elapsed() {
    final s = DateTime.now().difference(_startedAt).inSeconds;
    return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
  }

  String _statusText(BuildContext context) => switch (_phase) {
        _Phase.measuring => context.t('home.finding.status.measuring'),
        _Phase.joining => context.t('home.finding.status.joining'),
        _Phase.matched => context.t('home.finding.matched'),
        _ => context.t('home.finding.status.filling'),
      };

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider).value;
    final config = ref.watch(clientConfigProvider).value;
    final survival = widget.mode == 'SURVIVAL';
    final seats = survival ? 9 : 3;
    final ended = _phase == _Phase.over || _phase == _Phase.blocked;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _confirmCancel();
      },
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(
            tooltip: context.t('action.close'),
            icon: const Icon(Icons.close_rounded),
            onPressed: _confirmCancel,
          ),
          title: Text(context.t('home.finding.bar')),
          centerTitle: false,
          actions: [
            if (session?.avatarId != null)
              Padding(
                padding: const EdgeInsets.only(right: OSpace.lg),
                child: OAvatar(avatarId: session!.avatarId, size: 40, frameId: session.frameId),
              ),
          ],
        ),
        body: SafeArea(
          top: false,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xl),
            children: [
              Center(
                child: OPill(context.t('home.finding.live'),
                    background: OColors.surfaceContainer, foreground: OColors.ink, dot: true),
              ),
              const SizedBox(height: OSpace.lg),
              Text(context.t('home.finding.title.${survival ? 'SURVIVAL' : 'QUICK'}'),
                  style: OText.headlineXlMobile, textAlign: TextAlign.center),
              const SizedBox(height: OSpace.xs),
              Text(modeRules(context, widget.mode, config),
                  style: OText.bodyMd.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
              if (ended)
                _EndedView(
                  message: _error != null ? _errorMessage(context, _error!) : context.t(_overKey ?? 'error.generic'),
                  canRetry: _error == null || _canRetry,
                  onRetry: _start,
                  onBack: () => context.go(Routes.play),
                )
              else ...[
                const SizedBox(height: OSpace.xl),
                Center(child: _Radar(animation: _pulse, accent: survival ? OColors.secondary : OColors.turquoise)),
                const SizedBox(height: OSpace.xl),
                _YouSeat(name: session?.username ?? '', avatarId: session?.avatarId, frameId: session?.frameId),
                const SizedBox(height: OSpace.md),
                if (survival)
                  _CompactSeats(count: seats, animation: _pulse)
                else
                  for (var i = 0; i < seats; i++) ...[
                    _SearchingSeat(index: i, animation: _pulse),
                    const SizedBox(height: OSpace.md),
                  ],
                const SizedBox(height: OSpace.lg),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    RotationTransition(
                      turns: _pulse,
                      child: const Icon(Icons.sync_rounded, size: 18, color: OColors.turquoise),
                    ),
                    const SizedBox(width: OSpace.sm),
                    Flexible(
                      child: Text(_statusText(context),
                          style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant), textAlign: TextAlign.center),
                    ),
                  ],
                ),
                const SizedBox(height: OSpace.xs),
                Text(context.t('home.finding.elapsed', {'time': _elapsed()}),
                    style: OText.tabular(OText.labelMd.copyWith(color: OColors.inkSubtle)),
                    textAlign: TextAlign.center),
                if (_busy) ...[
                  const SizedBox(height: OSpace.md),
                  Container(
                    padding: const EdgeInsets.all(OSpace.md),
                    decoration: BoxDecoration(color: OColors.sun, borderRadius: BorderRadius.circular(ORadius.card)),
                    child: Row(
                      children: [
                        const Icon(Icons.hourglass_top_rounded, color: OColors.tertiary, size: 20),
                        const SizedBox(width: OSpace.sm),
                        Expanded(child: Text(context.t('home.finding.busy'), style: OText.bodySm)),
                      ],
                    ),
                  ),
                ],
              ],
            ],
          ),
        ),
        bottomNavigationBar: ended
            ? null
            : SafeArea(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.lg),
                  child: OButton(
                    label: context.t('home.finding.cancel'),
                    style: OButtonStyle.secondary,
                    loading: _phase == _Phase.leaving,
                    onPressed: _phase == _Phase.matched ? null : _cancel,
                  ),
                ),
              ),
      ),
    );
  }

  String _errorMessage(BuildContext context, ApiException e) {
    if (e.code == 'QUEUE_RESTRICTED') {
      final until = (e.detail['available_at_ms'] as num?)?.toInt();
      if (until != null) {
        final left = until - ref.read(serverClockProvider).nowMs();
        if (left > 0) {
          return context.t('home.finding.restricted_until', {'time': shortDuration(context, Duration(milliseconds: left))});
        }
      }
    }
    return errorText(context, e);
  }
}

// ------------------------------------------------------------------------------------------ pieces

class _EndedView extends StatelessWidget {
  const _EndedView({required this.message, required this.canRetry, required this.onRetry, required this.onBack});

  final String message;
  final bool canRetry;
  final VoidCallback onRetry;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) => OEmptyState(
        icon: Icons.hourglass_empty_rounded,
        title: message,
        action: Column(
          children: [
            if (canRetry) ...[
              OButton(label: context.t('home.finding.retry'), icon: Icons.refresh_rounded, onPressed: onRetry),
              const SizedBox(height: OSpace.md),
            ],
            OButton(label: context.t('home.finding.back'), style: OButtonStyle.secondary, onPressed: onBack),
          ],
        ),
      );
}

class _Radar extends StatelessWidget {
  const _Radar({required this.animation, required this.accent});

  final Animation<double> animation;
  final Color accent;

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: 220,
        child: AnimatedBuilder(
          animation: animation,
          builder: (context, _) => Stack(
            alignment: Alignment.center,
            children: [
              for (var i = 0; i < 3; i++)
                Builder(builder: (_) {
                  final t = (animation.value + i / 3) % 1.0;
                  return Container(
                    width: 100 + 120 * t,
                    height: 100 + 120 * t,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: accent.withValues(alpha: 0.16 * (1 - t)),
                    ),
                  );
                }),
              Container(
                width: 100,
                height: 100,
                decoration: BoxDecoration(color: accent, shape: BoxShape.circle, boxShadow: OShadow.floating),
                child: const Icon(Icons.alternate_email_rounded, color: OColors.white, size: 44),
              ),
            ],
          ),
        ),
      );
}

class _YouSeat extends StatelessWidget {
  const _YouSeat({required this.name, required this.avatarId, required this.frameId});

  final String name;
  final String? avatarId;
  final String? frameId;

  @override
  Widget build(BuildContext context) => OCard(
        radius: ORadius.card,
        padding: const EdgeInsets.all(OSpace.lg),
        child: Row(
          children: [
            OAvatar(avatarId: avatarId, size: 52, frameId: frameId, online: true),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(name, style: OText.headlineSm, overflow: TextOverflow.ellipsis),
                  Text(context.t('home.finding.you'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                ],
              ),
            ),
            OPill(context.t('home.finding.ready'), icon: Icons.check_circle_outline_rounded),
          ],
        ),
      );
}

class _SearchingSeat extends StatelessWidget {
  const _SearchingSeat({required this.index, required this.animation});

  final int index;
  final Animation<double> animation;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(OSpace.lg),
        decoration: BoxDecoration(
          color: OColors.surfaceContainer.withValues(alpha: 0.55),
          borderRadius: BorderRadius.circular(ORadius.card),
        ),
        child: Row(
          children: [
            const CircleAvatar(
              radius: 26,
              backgroundColor: OColors.surfaceContainerHigh,
              child: Icon(Icons.person_outline_rounded, color: OColors.outline),
            ),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(context.t('home.finding.searching'),
                      style: OText.headlineSm.copyWith(color: OColors.onSurfaceVariant)),
                  Text(context.t('home.finding.seat'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                ],
              ),
            ),
            _PulseDot(animation: animation, phase: index / 3),
          ],
        ),
      );
}

class _CompactSeats extends StatelessWidget {
  const _CompactSeats({required this.count, required this.animation});

  final int count;
  final Animation<double> animation;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(OSpace.lg),
        decoration: BoxDecoration(
          color: OColors.surfaceContainer.withValues(alpha: 0.55),
          borderRadius: BorderRadius.circular(ORadius.card),
        ),
        child: Column(
          children: [
            Wrap(
              alignment: WrapAlignment.center,
              spacing: OSpace.md,
              runSpacing: OSpace.md,
              children: [
                for (var i = 0; i < count; i++)
                  AnimatedBuilder(
                    animation: animation,
                    builder: (context, child) {
                      final t = (animation.value + i / count) % 1.0;
                      return Opacity(opacity: 0.45 + 0.55 * (1 - (2 * t - 1).abs()), child: child);
                    },
                    child: const CircleAvatar(
                      radius: 22,
                      backgroundColor: OColors.surfaceContainerHigh,
                      child: Icon(Icons.person_outline_rounded, color: OColors.outline, size: 20),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: OSpace.md),
            Text(context.t('home.finding.searching'), style: OText.labelMd.copyWith(color: OColors.onSurfaceVariant)),
          ],
        ),
      );
}

class _PulseDot extends StatelessWidget {
  const _PulseDot({required this.animation, required this.phase});

  final Animation<double> animation;
  final double phase;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: animation,
        builder: (context, _) {
          final t = (animation.value + phase) % 1.0;
          return Container(
            width: 14,
            height: 14,
            decoration: BoxDecoration(
              color: OColors.turquoise.withValues(alpha: 0.3 + 0.5 * (1 - (2 * t - 1).abs())),
              shape: BoxShape.circle,
            ),
          );
        },
      );
}
