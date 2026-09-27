import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../live/match_live_source.dart';
import '../../api/api_client.dart';
import '../../live/match_snapshot.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'widgets.dart';

/// Match ready (design P02 "Quick Battle match ready" / "Survival match ready"): roster, rules recap and the
/// countdown to round 1. Hands over to the live match screen when the first round starts. Every seat is rendered
/// the same way (decision D3).
class MatchReadyScreen extends ConsumerStatefulWidget {
  const MatchReadyScreen({super.key, required this.matchId});

  final String matchId;

  @override
  ConsumerState<MatchReadyScreen> createState() => _MatchReadyScreenState();
}

class _MatchReadyScreenState extends ConsumerState<MatchReadyScreen> {
  Timer? _tick;
  bool _left = false;
  int? _countdownFromMs;

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(const Duration(milliseconds: 200), (_) => _check());
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  /// First round still counting down?
  bool _waiting(MatchSnapshot s) =>
      s.exists && s.state == MatchStates.loading && s.roundNumber <= 1 && s.startsAtMs > 0;

  int _startsAt(MatchSnapshot s) => s.startsAtMs > 0 ? s.startsAtMs : s.nextServerEventAtMs;

  void _go(String location) {
    if (_left || !mounted) return;
    _left = true;
    _tick?.cancel();
    context.go(location);
  }

  void _check() {
    if (!mounted || _left) return;
    final update = ref.read(matchLiveProvider(widget.matchId)).value;
    if (update != null) _evaluate(update);
    if (mounted) setState(() {});
  }

  void _evaluate(LiveUpdate update) {
    if (update.health == LiveHealth.unavailable) {
      _go('${Routes.matchUnavailable}?match=${widget.matchId}');
      return;
    }
    final s = update.snapshot;
    if (s == null || !s.exists) return;
    if (!_waiting(s)) {
      _go(Routes.match(widget.matchId));
      return;
    }
    final now = ref.read(serverClockProvider).nowMs();
    _countdownFromMs ??= now;
    if (now >= _startsAt(s)) _go(Routes.match(widget.matchId));
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(matchLiveProvider(widget.matchId), (_, next) {
      final update = next.value;
      if (update != null) _evaluate(update);
    });
    final async = ref.watch(matchLiveProvider(widget.matchId));
    final session = ref.watch(sessionProvider).value;
    final config = ref.watch(clientConfigProvider).value;
    final snapshot = async.value?.snapshot;
    Widget body;
    if (snapshot == null || !snapshot.exists) {
      body = async.hasError
          ? OErrorView(error: async.error!, onRetry: () => ref.invalidate(matchLiveProvider(widget.matchId)))
          : Column(
              children: [
                const SizedBox(height: OSpace.xxl),
                const OLoading(),
                Text(context.t('home.ready.connecting'), style: OText.bodyMd.copyWith(color: OColors.inkSubtle)),
              ],
            );
    } else {
      final now = ref.read(serverClockProvider).nowMs();
      final startsAt = _startsAt(snapshot);
      final remainingMs = math.max(0, startsAt - now);
      final total = math.max(1, startsAt - (_countdownFromMs ?? now));
      final seconds = (remainingMs / 1000).ceil();
      final progress = (remainingMs / total).clamp(0.0, 1.0);
      final language = questionLanguageName(
          context, (snapshot.public['language'] as String?) ?? session?.questionLanguage ?? 'en');
      body = snapshot.isSurvival
          ? _SurvivalReady(snapshot: snapshot, seconds: seconds, progress: progress, config: config?['survival'],
              clientConfig: config)
          : _QuickReady(snapshot: snapshot, seconds: seconds, progress: progress, language: language, config: config);
    }
    return PopScope(
      canPop: false,
      child: Scaffold(
        appBar: AppBar(
          automaticallyImplyLeading: false,
          title: Text(context.t('home.ready.bar')),
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
            children: [body],
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------------------------------ Quick Battle

class _QuickReady extends StatelessWidget {
  const _QuickReady({required this.snapshot, required this.seconds, required this.progress, required this.language,
      this.config});

  final MatchSnapshot snapshot;
  final int seconds;
  final double progress;
  final String language;
  final Json? config;

  @override
  Widget build(BuildContext context) {
    final roster = snapshot.bySlot;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Center(
          child: OPill(context.t('home.ready.context.QUICK', {'language': language}),
              background: OColors.surfaceContainer, foreground: OColors.onSurfaceVariant, icon: Icons.bolt_rounded),
        ),
        const SizedBox(height: OSpace.xl),
        Center(
          child: _CountdownRing(
            seconds: seconds,
            progress: progress,
            color: OColors.turquoise,
            label: context.t('home.ready.starts_in'),
            fill: OColors.mint,
          ),
        ),
        const SizedBox(height: OSpace.lg),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(width: 10, height: 10, decoration: const BoxDecoration(color: OColors.turquoise, shape: BoxShape.circle)),
            const SizedBox(width: OSpace.sm),
            Text(context.t('home.ready.standby'), style: OText.labelLg),
          ],
        ),
        const SizedBox(height: OSpace.lg),
        MatchRulesCard(mode: 'QUICK', config: config),
        const SizedBox(height: OSpace.xl),
        _RosterGrid(snapshot: snapshot, roster: roster, large: true),
        const SizedBox(height: OSpace.xl),
        Container(
          padding: const EdgeInsets.all(OSpace.xl),
          decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.md)),
          child: Row(
            children: [
              Container(
                width: 52,
                height: 52,
                decoration: const BoxDecoration(color: OColors.tertiaryFixed, shape: BoxShape.circle),
                child: const Icon(Icons.emoji_events_outlined, color: OColors.tertiary),
              ),
              const SizedBox(width: OSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(context.t('home.ready.format'), style: OText.labelSm.copyWith(color: OColors.tertiary)),
                    const SizedBox(height: 2),
                    Text(context.t('home.ready.format.QUICK', {'q': snapshot.totalNormalRounds}),
                        style: OText.headlineSm),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// ------------------------------------------------------------------------------------------ Survival

class _SurvivalReady extends StatelessWidget {
  const _SurvivalReady({required this.snapshot, required this.seconds, required this.progress, this.config,
      this.clientConfig});

  final MatchSnapshot snapshot;
  final int seconds;
  final double progress;
  final Object? config;
  final Json? clientConfig;

  @override
  Widget build(BuildContext context) {
    final roster = snapshot.bySlot;
    final roundSeconds = (config is Map ? (config as Map)['seconds'] : null) as num?;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Center(
          child: OPill(context.t('home.ready.context.SURVIVAL'),
              background: OColors.surfaceContainer,
              foreground: OColors.ink,
              icon: Icons.local_fire_department_outlined),
        ),
        const SizedBox(height: OSpace.lg),
        Container(
          padding: const EdgeInsets.symmetric(vertical: OSpace.xl, horizontal: OSpace.lg),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(ORadius.lg),
            boxShadow: OShadow.card,
            gradient: const LinearGradient(
              begin: Alignment.bottomLeft,
              end: Alignment.topRight,
              colors: [OColors.sun, OColors.white, OColors.rose],
            ),
          ),
          child: Column(
            children: [
              _CountdownRing(seconds: seconds, progress: progress, color: OColors.pink, size: 150),
              const SizedBox(height: OSpace.lg),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                      width: 10, height: 10, decoration: const BoxDecoration(color: OColors.secondary, shape: BoxShape.circle)),
                  const SizedBox(width: OSpace.sm),
                  Text(context.t('home.ready.get_ready'), style: OText.headlineMd),
                ],
              ),
              Text(context.t('home.ready.auto'), style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
            ],
          ),
        ),
        const SizedBox(height: OSpace.lg),
        MatchRulesCard(mode: 'SURVIVAL', config: clientConfig),
        const SizedBox(height: OSpace.xl),
        Row(
          children: [
            const Icon(Icons.groups_outlined, color: OColors.primary, size: 20),
            const SizedBox(width: OSpace.sm),
            Expanded(
              child: Text(context.t('home.ready.players', {'n': roster.length}),
                  style: OText.labelMd.copyWith(color: OColors.onSurfaceVariant)),
            ),
            OPill(context.t('home.ready.locked'), dot: true),
          ],
        ),
        const SizedBox(height: OSpace.md),
        _RosterGrid(snapshot: snapshot, roster: roster, large: false),
        const SizedBox(height: OSpace.lg),
        Container(
          padding: const EdgeInsets.all(OSpace.lg),
          decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.card)),
          child: Row(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: const BoxDecoration(color: OColors.secondaryFixed, shape: BoxShape.circle),
                child: const Icon(Icons.timer_outlined, color: OColors.secondary),
              ),
              const SizedBox(width: OSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (roundSeconds != null)
                      Text(context.t('home.ready.format.SURVIVAL_timer', {'s': roundSeconds.toInt()}),
                          style: OText.labelLg),
                    Text(context.t('home.ready.format.SURVIVAL'),
                        style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// ------------------------------------------------------------------------------------------ shared pieces

class _RosterGrid extends StatelessWidget {
  const _RosterGrid({required this.snapshot, required this.roster, required this.large});

  final MatchSnapshot snapshot;
  final List<Participant> roster;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < roster.length; i += 2) {
      rows.add(Padding(
        padding: EdgeInsets.only(bottom: large ? OSpace.lg : OSpace.md),
        child: Row(
          children: [
            Expanded(child: _Seat(p: roster[i], me: roster[i].pid == snapshot.myPid, large: large)),
            SizedBox(width: large ? OSpace.lg : OSpace.md),
            Expanded(
              child: i + 1 < roster.length
                  ? _Seat(p: roster[i + 1], me: roster[i + 1].pid == snapshot.myPid, large: large)
                  : const SizedBox.shrink(),
            ),
          ],
        ),
      ));
    }
    return Column(children: rows);
  }
}

class _Seat extends StatelessWidget {
  const _Seat({required this.p, required this.me, required this.large});

  final Participant p;
  final bool me;
  final bool large;

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.symmetric(horizontal: large ? OSpace.lg : OSpace.md, vertical: large ? OSpace.lg : OSpace.md),
        decoration: BoxDecoration(
          color: me ? OColors.mint : OColors.white,
          borderRadius: BorderRadius.circular(large ? ORadius.lg : ORadius.sm),
          boxShadow: OShadow.card,
          border: me ? Border.all(color: OColors.turquoise.withValues(alpha: 0.5)) : null,
        ),
        child: Row(
          children: [
            OAvatar(avatarId: p.avatarId, size: large ? 52 : 40, frameId: p.frameId),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(p.name, style: large ? OText.headlineSm : OText.labelLg, maxLines: 1, overflow: TextOverflow.ellipsis),
                  Text(
                    me ? context.t('home.ready.you') : context.t('home.ready.status'),
                    style: OText.labelMd.copyWith(color: me ? OColors.primary : OColors.inkSubtle),
                  ),
                ],
              ),
            ),
            if (!large)
              Icon(me ? Icons.check_circle_outline_rounded : Icons.circle,
                  size: me ? 20 : 10, color: me ? OColors.primary : OColors.turquoise),
          ],
        ),
      );
}

class _CountdownRing extends StatelessWidget {
  const _CountdownRing({required this.seconds, required this.progress, required this.color, this.label,
      this.fill = OColors.white, this.size = 190});

  final int seconds;
  final double progress;
  final Color color;
  final Color fill;
  final String? label;
  final double size;

  @override
  Widget build(BuildContext context) => Semantics(
        liveRegion: true,
        label: '${label ?? ''} $seconds',
        child: SizedBox.square(
          dimension: size,
          child: CustomPaint(
            painter: _RingPainter(progress: progress, color: color, fill: fill),
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (label != null) Text(label!, style: OText.labelMd.copyWith(color: OColors.onSurfaceVariant)),
                  Text('$seconds', style: OText.displayStat.copyWith(fontSize: size * 0.32, height: 1.1)),
                ],
              ),
            ),
          ),
        ),
      );
}

class _RingPainter extends CustomPainter {
  _RingPainter({required this.progress, required this.color, required this.fill});

  final double progress;
  final Color color;
  final Color fill;

  @override
  void paint(Canvas canvas, Size size) {
    final stroke = size.width * 0.07;
    final rect = Offset.zero & size;
    final inner = rect.deflate(stroke / 2);
    canvas.drawCircle(rect.center, inner.width / 2 - stroke / 2, Paint()..color = fill);
    canvas.drawArc(inner, 0, math.pi * 2, false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = stroke
          ..color = OColors.surfaceContainer);
    canvas.drawArc(inner, -math.pi / 2, math.pi * 2 * progress, false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = stroke
          ..strokeCap = StrokeCap.round
          ..color = color);
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.progress != progress || old.color != color || old.fill != fill;
}
