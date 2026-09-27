import '../api/api_client.dart';

/// Match states (backend `MatchState`).
abstract final class MatchStates {
  static const loading = 'ROUND_LOADING';
  static const active = 'ROUND_ACTIVE';
  static const reveal = 'ROUND_REVEAL';
  static const resolve = 'ROUND_RESOLVE';
  static const next = 'NEXT_ROUND';
  static const pendingSettlement = 'FINISHED_PENDING_SETTLEMENT';
  static const finished = 'FINISHED';
  static const cancelled = 'CANCELLED';
  static const expired = 'EXPIRED';
  static const terminal = {pendingSettlement, finished, cancelled, expired};
}

/// Own answer status (backend `AnswerStatus`).
abstract final class AnswerStatuses {
  static const notAnswered = 'NOT_ANSWERED';
  static const wrong = 'ANSWERED_WRONG';
  static const correct = 'ANSWERED_CORRECT';
  static const locked = 'LOCKED';
  static const ineligible = 'INELIGIBLE';
}

class Participant {
  Participant(this.pid, this.raw);

  final String pid;
  final Json raw;

  String get name => (raw['display_name'] as String?) ?? '';
  String? get avatarId => raw['avatar_id'] as String?;
  String get frameId => (raw['frame_id'] as String?) ?? 'frame_none';
  bool get active => raw['active'] == true;
  bool get left => raw['left'] == true;
  bool get answerLocked => raw['answer_locked'] == true;
  int get score => (raw['score'] as num?)?.toInt() ?? 0;
  int get slot => (raw['slot'] as num?)?.toInt() ?? 0;

  /// Survival: ACTIVE, SURVIVED, ELIMINATED, …
  String get survivalStatus => (raw['survival_status'] as String?) ?? 'ACTIVE';
  bool get eliminated => survivalStatus == 'ELIMINATED';
}

/// The safe client projection of a live match: `public` + this viewer's `player_private` (spec §17.2–17.3).
/// Bots and humans are indistinguishable here by construction (decision D3).
class MatchSnapshot {
  MatchSnapshot({required this.matchId, required this.public, this.private, this.role = 'participant',
      this.shardId, this.rtdbUrl, this.receivedAtMs = 0});

  factory MatchSnapshot.fromView(Json view) => MatchSnapshot(
        matchId: view['match_id'] as String,
        public: (view['public'] as Map?)?.cast<String, dynamic>() ?? const {},
        private: (view['player_private'] as Map?)?.cast<String, dynamic>(),
        role: (view['role'] as String?) ?? 'participant',
        shardId: view['rtdb_shard_id'] as String?,
        rtdbUrl: view['rtdb_url'] as String?,
        receivedAtMs: (view['server_time_ms'] as num?)?.toInt() ?? 0,
      );

  final String matchId;
  final Json public;
  final Json? private;
  final String role;
  final String? shardId;
  final String? rtdbUrl;
  final int receivedAtMs;

  MatchSnapshot copyWith({Json? public, Json? private}) => MatchSnapshot(
        matchId: matchId,
        public: public ?? this.public,
        private: private ?? this.private,
        role: role,
        shardId: shardId,
        rtdbUrl: rtdbUrl,
        receivedAtMs: receivedAtMs,
      );

  bool get exists => public.isNotEmpty;
  bool get isSpectator => role == 'spectator';
  String get mode => (public['mode'] as String?) ?? 'QUICK';
  bool get isQuick => mode == 'QUICK';
  bool get isSurvival => mode == 'SURVIVAL';
  String get state => (public['state'] as String?) ?? '';
  String? get phase => public['match_phase'] as String?;
  int get stateVersion => (public['state_version'] as num?)?.toInt() ?? 0;
  int get nextServerEventAtMs => (public['next_server_event_at_ms'] as num?)?.toInt() ?? 0;
  bool get isTerminal => MatchStates.terminal.contains(state);
  bool get isQuestionLive => state == MatchStates.loading || state == MatchStates.active;
  bool get isRevealed => state == MatchStates.reveal || state == MatchStates.resolve;

  // Round
  String? get roundId => public['round_id'] as String?;
  int get roundNumber => (public['round_number'] as num?)?.toInt() ?? 0;
  String? get roundKind => public['round_kind'] as String?;
  bool get isSuddenDeath => roundKind == 'SUDDEN_DEATH' || phase == 'QUICK_SUDDEN_DEATH';
  String? get difficulty => public['difficulty'] as String?;
  String? get categoryId => public['category_id'] as String?;
  int get startsAtMs => (public['starts_at_ms'] as num?)?.toInt() ?? 0;
  int get endsAtMs => (public['ends_at_ms'] as num?)?.toInt() ?? 0;
  int get revealEndsAtMs => (public['reveal_ends_at_ms'] as num?)?.toInt() ?? 0;
  int get totalNormalRounds => (public['total_normal_rounds'] as num?)?.toInt() ?? 10;
  Json get question => (public['current_question'] as Map?)?.cast<String, dynamic>() ?? const {};
  String get questionText => (question['text'] as String?) ?? '';
  Map<String, String> get optionTexts =>
      ((question['options'] as Map?) ?? const {}).map((k, v) => MapEntry(k.toString(), v.toString()));
  Json? get reveal => (public['correct_answer_reveal'] as Map?)?.cast<String, dynamic>();
  String? get correctConceptId => reveal?['concept_id'] as String?;
  String? get roundWinnerPid => reveal?['winner_pid'] as String?;
  int get roundPoints => (reveal?['points'] as num?)?.toInt() ?? 0;
  Json? get suddenDeath => (public['sudden_death'] as Map?)?.cast<String, dynamic>();

  // Survival extras
  int get activeCount => (public['active_count'] as num?)?.toInt() ?? 0;
  Json? get roundOutcome => (public['round_outcome'] as Map?)?.cast<String, dynamic>();

  // Participants
  Map<String, Participant> get participants => ((public['participants'] as Map?) ?? const {})
      .map((k, v) => MapEntry(k.toString(), Participant(k.toString(), (v as Map).cast<String, dynamic>())));
  List<Participant> get bySlot => participants.values.toList()..sort((a, b) => a.slot.compareTo(b.slot));
  List<Participant> get byScore => participants.values.toList()..sort((a, b) => b.score.compareTo(a.score));

  // Viewer
  String? get myPid => private?['pid'] as String?;
  Participant? get me => myPid == null ? null : participants[myPid];
  bool get eligibleToAnswer => private?['eligible_to_answer'] == true;
  String get ownAnswerStatus => (private?['own_answer_status'] as String?) ?? AnswerStatuses.notAnswered;
  String? get selectedConceptId => private?['selected_concept_id'] as String?;
  int? get scoreDelta => (private?['score_delta'] as num?)?.toInt();
  bool get reactionUsed => private?['reaction_used'] == true;
  List<String> get mutedPids => ((private?['muted_pids'] as List?) ?? const []).cast<String>();
  Json? get settlement => (private?['settlement'] as Map?)?.cast<String, dynamic>();

  /// Display order A–D → concept id for this viewer (spec §22.4); falls back to server order.
  List<MapEntry<String, String>> get orderedOptions {
    final order = (private?['option_order'] as Map?)?.cast<String, dynamic>();
    final texts = optionTexts;
    if (order == null || order.isEmpty) {
      final keys = texts.keys.toList();
      return [for (var i = 0; i < keys.length; i++) MapEntry(String.fromCharCode(65 + i), keys[i])];
    }
    final positions = order.keys.toList()..sort();
    return [for (final p in positions) MapEntry(p, order[p].toString())];
  }

  // Result
  Json? get resultSummary => (public['result_summary'] as Map?)?.cast<String, dynamic>();
  List<Json> get standings =>
      ((resultSummary?['standings'] as List?) ?? const []).map((e) => (e as Map).cast<String, dynamic>()).toList();
  String? get settlementStatus => public['settlement_status'] as String?;
  int? get rematchUntilMs => (public['rematch_until_ms'] as num?)?.toInt();
  List<Json> get events =>
      ((public['events'] as List?) ?? const []).map((e) => (e as Map).cast<String, dynamic>()).toList();
}
