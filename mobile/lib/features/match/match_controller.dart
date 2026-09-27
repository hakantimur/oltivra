import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../live/match_snapshot.dart';

/// Local, non-authoritative UI state of one live match: the optimistic answer lock, the server's answer
/// response, which rounds this viewer already reacted in, and whether an eliminated player chose to watch.
/// Scores, correctness and standings always come from the server projection, never from here.
class MatchUi {
  const MatchUi({
    this.roundId,
    this.pendingConceptId,
    this.answerResult,
    this.notice,
    this.reactedRoundIds = const {},
    this.reportedRoundIds = const {},
    this.watching = false,
  });

  /// Round of the answer submitted from this device.
  final String? roundId;

  /// Concept id tapped on this device (shown as locked until the projection confirms it).
  final String? pendingConceptId;

  /// Server response of `POST /answer` for [roundId] (Quick: correct/score_delta, Survival: locked).
  final Json? answerResult;

  /// One-shot error to surface as a snackbar.
  final Object? notice;
  final Set<String> reactedRoundIds;
  final Set<String> reportedRoundIds;

  /// An eliminated Survival player chose "Watch battle".
  final bool watching;

  MatchUi copyWith({
    String? roundId,
    String? pendingConceptId,
    bool clearPending = false,
    Json? answerResult,
    bool clearResult = false,
    Object? notice,
    bool clearNotice = false,
    Set<String>? reactedRoundIds,
    Set<String>? reportedRoundIds,
    bool? watching,
  }) =>
      MatchUi(
        roundId: roundId ?? this.roundId,
        pendingConceptId: clearPending ? null : (pendingConceptId ?? this.pendingConceptId),
        answerResult: clearResult ? null : (answerResult ?? this.answerResult),
        notice: clearNotice ? null : (notice ?? this.notice),
        reactedRoundIds: reactedRoundIds ?? this.reactedRoundIds,
        reportedRoundIds: reportedRoundIds ?? this.reportedRoundIds,
        watching: watching ?? this.watching,
      );

  /// Concept id this viewer picked for [s]'s current round: the server's value wins over the optimistic one.
  String? selectedFor(MatchSnapshot s) {
    if (s.selectedConceptId != null) return s.selectedConceptId;
    return roundId != null && roundId == s.roundId ? pendingConceptId : null;
  }

  /// Server answer response for [s]'s current round, if any.
  Json? resultFor(MatchSnapshot s) => roundId != null && roundId == s.roundId ? answerResult : null;

  bool reactedIn(MatchSnapshot s) => s.reactionUsed || (s.roundId != null && reactedRoundIds.contains(s.roundId));
}

class MatchController extends Notifier<MatchUi> {
  MatchController(this.matchId);

  final String matchId;

  /// Delay before retrying an answer after a network failure.
  static Duration retryDelay(int attempt) => Duration(milliseconds: 250 * attempt);
  static const maxAnswerAttempts = 4;

  @override
  MatchUi build() => const MatchUi();

  ApiClient get _api => ref.read(apiClientProvider);

  /// Submits one answer for the current round. The request id is generated once and reused for every retry
  /// so a retried request replays the stored answer instead of submitting twice (spec §19.1, §22.3).
  Future<void> submitAnswer(MatchSnapshot s, String conceptId) async {
    final roundId = s.roundId;
    if (roundId == null || !s.eligibleToAnswer || s.selectedConceptId != null) return;
    if (state.roundId == roundId && state.pendingConceptId != null) return; // one answer per round
    final requestId = ApiClient.newRequestId();
    state = state.copyWith(roundId: roundId, pendingConceptId: conceptId, clearResult: true);
    final body = <String, dynamic>{
      'round_id': roundId,
      'option_id': conceptId,
      if (s.shardId != null) 'rtdb_shard_id': s.shardId,
    };
    for (var attempt = 1;; attempt++) {
      try {
        final res = await _api.post('/v1/matches/$matchId/answer', body, requestId);
        if (!ref.mounted) return;
        if (state.roundId == roundId) state = state.copyWith(answerResult: res);
        return;
      } on ApiException catch (e) {
        if (!ref.mounted || state.roundId != roundId) return;
        final transient = e.isNetwork || e.status >= 500;
        if (transient && attempt < maxAnswerAttempts) {
          await Future<void>.delayed(retryDelay(attempt));
          if (!ref.mounted || state.roundId != roundId) return;
          continue;
        }
        if (e.code == 'ANSWER_ALREADY_SUBMITTED') return; // the server holds this round's answer already
        // ROUND_NOT_ACTIVE / ROUND_EXPIRED (round closed first) and other rejections: unlock and explain.
        state = state.copyWith(clearPending: true, clearResult: true, notice: e);
        return;
      }
    }
  }

  /// One curated reaction per round (spec §5); the id is recorded first so a double tap sends once.
  Future<void> react(MatchSnapshot s, String reactionId) async {
    final roundId = s.roundId;
    if (roundId == null || state.reactedIn(s)) return;
    state = state.copyWith(reactedRoundIds: {...state.reactedRoundIds, roundId});
    try {
      await _api.post('/v1/matches/$matchId/reaction', {'round_id': roundId, 'reaction_id': reactionId});
    } on ApiException catch (e) {
      if (!ref.mounted) return;
      if (e.code == 'REACTION_ALREADY_USED' || e.code == 'ROUND_NOT_ACTIVE') return;
      state = state.copyWith(
        reactedRoundIds: {...state.reactedRoundIds}..remove(roundId),
        notice: e,
      );
    }
  }

  /// `POST /question-report` for the round the viewer is looking at. Throws [ApiException] on failure.
  Future<void> reportQuestion(String roundId, String reason) async {
    await _api.post('/v1/matches/$matchId/question-report', {'round_id': roundId, 'reason': reason});
    if (!ref.mounted) return;
    state = state.copyWith(reportedRoundIds: {...state.reportedRoundIds, roundId});
  }

  /// Explicit leave (spec §25): Quick records abandonment, Survival eliminates an alive player.
  Future<void> leave() => _api.post('/v1/matches/$matchId/leave');

  /// Joins the rematch window of a settled match; returns the rematch party view.
  Future<Json> rematch() => _api.post('/v1/matches/$matchId/rematch');

  void watchBattle() => state = state.copyWith(watching: true);

  void clearNotice() => state = state.copyWith(clearNotice: true);
}

final matchControllerProvider =
    NotifierProvider.autoDispose.family<MatchController, MatchUi, String>(MatchController.new);
