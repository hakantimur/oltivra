import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../live/match_live_source.dart';
import '../../live/match_snapshot.dart';
import '../../router/routes.dart';
import '../../widgets/o_widgets.dart';
import '../store/interstitials.dart';
import 'final_result_view.dart';
import 'match_controller.dart';
import 'match_unavailable_screen.dart';
import 'match_view_data.dart';
import 'quick/quick_question_view.dart';
import 'round_transition_view.dart';
import 'survival/survival_eliminated_view.dart';
import 'survival/survival_question_view.dart';
import 'widgets/match_widgets.dart';

/// Live match host (P03 Quick Battle, P04 Survival, P08 reconnect/unavailable). Renders the server projection
/// from [matchLiveProvider] and routes intents through [MatchController]; it never decides correctness,
/// scores or standings.
class MatchScreen extends ConsumerStatefulWidget {
  const MatchScreen({super.key, required this.matchId});

  final String matchId;

  @override
  ConsumerState<MatchScreen> createState() => _MatchScreenState();
}

class _MatchScreenState extends ConsumerState<MatchScreen> {
  Timer? _ticker;
  bool _rematching = false;
  bool _counted = false;
  bool _adPreloaded = false;

  String get _id => widget.matchId;

  MatchController get _controller => ref.read(matchControllerProvider(_id).notifier);

  @override
  void initState() {
    super.initState();
    // Countdowns and phase boundaries (ROUND_LOADING → open at starts_at_ms) are display-only ticks.
    _ticker = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(matchControllerProvider(_id).select((u) => u.notice), (_, notice) {
      if (notice == null) return;
      showError(context, notice);
      _controller.clearNotice();
    });
    final live = ref.watch(matchLiveProvider(_id));
    final update = live.value;
    if (update == null) {
      if (live.hasError) {
        return MatchUnavailableScreen(matchId: _id, connectionLost: true, onRetry: _retry);
      }
      return const Scaffold(body: OLoading());
    }
    final s = update.snapshot;
    final reconnecting = update.health == LiveHealth.reconnecting;
    final ads = ref.read(interstitialControllerProvider);
    if (!_adPreloaded && s != null && s.exists && !s.isTerminal) {
      _adPreloaded = true;
      ads.preload();
    }
    if (s == null || !s.exists) {
      if (update.health == LiveHealth.unavailable) {
        return MatchUnavailableScreen(matchId: _id, connectionLost: true, onRetry: _retry);
      }
      return Scaffold(body: Stack(children: [const OLoading(), if (reconnecting) const ReconnectingOverlay()]));
    }
    final stopped = s.state == MatchStates.cancelled ||
        s.state == MatchStates.expired ||
        s.settlementStatus == 'CANCELLED_NO_PROGRESSION';
    if (stopped) return MatchUnavailableScreen(matchId: _id);
    if (update.health == LiveHealth.unavailable && !s.isTerminal) {
      return MatchUnavailableScreen(matchId: _id, connectionLost: true, onRetry: _retry);
    }

    final ui = ref.watch(matchControllerProvider(_id));
    final nowMs = ref.read(serverClockProvider).nowMs();
    final reactions = reactionItems(ref.watch(catalogProvider('reactions')).value);
    final quickCfg = (ref.watch(clientConfigProvider).value?['quick'] as Map?)?.cast<String, dynamic>();
    final roundId = s.roundId;
    final data = MatchViewData(
      snapshot: s,
      ui: ui,
      nowMs: nowMs,
      reactions: reactions,
      wrongPenalty: (quickCfg?['wrong_penalty'] as num?)?.toInt(),
      onAnswer: (concept) => _controller.submitAnswer(s, concept),
      onReact: (item) => _controller.react(s, item.id),
      onLeave: () => _leave(s),
      onReportQuestion: roundId != null && !ui.reportedRoundIds.contains(roundId) && (s.isQuestionLive || s.isRevealed)
          ? () => _reportQuestion(roundId)
          : null,
    );

    return PopScope(
      canPop: s.isTerminal,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _leave(s);
      },
      child: Scaffold(
        body: SafeArea(
          child: Stack(
            children: [
              AbsorbPointer(
                absorbing: reconnecting,
                child: ExcludeSemantics(excluding: reconnecting, child: _content(data, ui)),
              ),
              if (reconnecting) const ReconnectingOverlay(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _content(MatchViewData data, MatchUi ui) {
    final s = data.s;
    if (s.isTerminal) {
      if (!_counted && !s.isSpectator && s.me != null) {
        // Completed matches drive the ad break rhythm (every N matches, see InterstitialController).
        _counted = true;
        unawaited(ref.read(interstitialControllerProvider).recordCompleted(_id));
      }
      return FinalResultView(
        snapshot: s,
        nowMs: data.nowMs,
        onHome: _home,
        onPlayAgain: () => context.go(Routes.queue(s.mode)),
        onRematch: s.isSpectator || s.me == null ? null : _rematch,
        rematching: _rematching,
        onReportPlayer: s.isSpectator ? null : (pid) => context.push(Routes.reportPlayer(pid, matchId: _id)),
      );
    }
    final me = s.me;
    final between = data.beforeStart || !(s.isQuestionLive || s.isRevealed);
    if (s.isSurvival) {
      final sawOwnElimination = s.isRevealed && s.ownAnswerStatus != AnswerStatuses.ineligible;
      if (me != null && me.eliminated && !me.left && !ui.watching && !sawOwnElimination) {
        return SurvivalEliminatedView(snapshot: s, onWatch: _controller.watchBattle, onLeave: () => _leave(s));
      }
      if (between) return RoundTransitionView(data: data);
      return SurvivalQuestionView(data: data);
    }
    if (between) return RoundTransitionView(data: data);
    return QuickQuestionView(data: data);
  }

  /// Ads never interrupt the way out of a result; the ad break runs before a later match instead.
  void _home() => context.go(Routes.home);

  void _retry() => ref.invalidate(matchLiveProvider(_id));

  Future<void> _leave(MatchSnapshot s) async {
    final me = s.me;
    if (s.isTerminal || s.isSpectator || me == null || me.left) {
      if (mounted) context.go(Routes.home);
      return;
    }
    final alreadyOut = s.isSurvival && me.eliminated;
    if (!alreadyOut) {
      final ok = await confirmLeave(
          context, context.t(s.isSurvival ? 'match.leave_body_survival' : 'match.leave_body_quick'));
      if (!ok || !mounted) return;
    }
    try {
      await _controller.leave();
      if (mounted) context.go(Routes.home);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _reportQuestion(String roundId) async {
    final reason = await pickQuestionReportReason(context);
    if (reason == null || !mounted) return;
    try {
      await _controller.reportQuestion(roundId, reason);
      if (mounted) showMessage(context, context.t('match.report_sent'));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _rematch() async {
    setState(() => _rematching = true);
    try {
      final party = await _controller.rematch();
      final partyId = party['party_id'] as String?;
      if (!mounted) return;
      if (partyId != null) context.go(Routes.challengeLobby(partyId));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _rematching = false);
    }
  }
}
