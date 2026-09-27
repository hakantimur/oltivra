import 'package:flutter/foundation.dart';

import '../../live/match_snapshot.dart';
import 'match_controller.dart';
import 'widgets/match_widgets.dart';

/// Everything a match view needs for one frame: the server projection, local UI state, the server-clock
/// "now" for countdowns, and the intents it may send.
class MatchViewData {
  const MatchViewData({
    required this.snapshot,
    required this.ui,
    required this.nowMs,
    required this.reactions,
    required this.onAnswer,
    required this.onReact,
    required this.onLeave,
    this.onReportQuestion,
    this.wrongPenalty,
  });

  final MatchSnapshot snapshot;
  final MatchUi ui;
  final int nowMs;
  final List<ReactionItem> reactions;
  final ValueChanged<String> onAnswer;
  final ValueChanged<ReactionItem> onReact;
  final VoidCallback onLeave;

  /// Null when the current question cannot be reported (no live round, or already reported).
  final VoidCallback? onReportQuestion;

  /// Quick Battle wrong-answer penalty from `/v1/client-config` (display only; absent → not shown).
  final int? wrongPenalty;

  MatchSnapshot get s => snapshot;

  /// The question is open for answers on the server clock (ROUND_LOADING flips to ACTIVE at `starts_at_ms`).
  bool get questionOpen =>
      s.state == MatchStates.active || (s.state == MatchStates.loading && s.startsAtMs > 0 && nowMs >= s.startsAtMs);

  /// A published round whose start is still ahead: shown as the "next question incoming" transition.
  bool get beforeStart => s.state == MatchStates.loading && !questionOpen;

  /// Recent reactions keyed by sender pid (blocked/muted senders removed).
  Map<String, String> get liveReactions {
    final raw = recentReactions(s, nowMs);
    final byId = {for (final r in reactions) r.id: r.display};
    return raw.map((pid, id) => MapEntry(pid, byId[id] ?? ''))..removeWhere((_, v) => v.isEmpty);
  }

  /// Reactions are allowed for participants (including eliminated ones) in reactable states.
  bool get canReact =>
      !s.isSpectator &&
      s.me != null &&
      !(s.me!.left) &&
      s.roundId != null &&
      (s.isQuestionLive || s.isRevealed) &&
      reactions.isNotEmpty;
}
