import '../api/api_client.dart';

/// Typed view over `POST /v1/session/bootstrap` (spec §19.3). Fields not modelled here stay reachable
/// through [raw] so screens never need a second bootstrap call.
class Session {
  Session(this.raw);

  final Json raw;

  Json get _account => (raw['account'] as Map?)?.cast<String, dynamic>() ?? const {};
  Json get onboarding => (_account['onboarding'] as Map?)?.cast<String, dynamic>() ?? const {};
  Json? get profile => (raw['profile'] as Map?)?.cast<String, dynamic>();
  Json get runtime => (raw['runtime'] as Map?)?.cast<String, dynamic>() ?? const {};
  Json get features => (raw['features'] as Map?)?.cast<String, dynamic>() ?? const {};
  Json get legal => (raw['legal'] as Map?)?.cast<String, dynamic>() ?? const {};

  bool get accountExists => _account['exists'] == true;
  String get accountStatus => (_account['status'] as String?) ?? 'ACTIVE';
  bool get consentDone => onboarding['consent'] == true;
  bool get usernameDone => onboarding['username'] == true;
  bool get avatarDone => onboarding['avatar'] == true;
  bool get renameRequired => onboarding['rename_required'] == true;
  bool get onboarded => consentDone && usernameDone && avatarDone;

  int get serverTimeMs => (raw['server_time_ms'] as num?)?.toInt() ?? DateTime.now().millisecondsSinceEpoch;
  String get runtimeState => (runtime['state'] as String?) ?? 'IDLE';
  String? get activeMatchId => runtime['match_id'] as String?;
  String? get activePartyId => runtime['party_id'] as String?;

  bool get survivalEnabled => features['survival'] != false;
  bool get rewardedXpEnabled => features['rewarded_xp'] == true;
  List<String> get categoryQueueIds => ((features['category_queue_ids'] as List?) ?? const []).cast<String>();

  String get username => (profile?['username_display'] as String?) ?? '';
  String? get avatarId => profile?['avatar_id'] as String?;
  String get frameId => (profile?['frame_id'] as String?) ?? 'frame_none';
  String? get publicId => profile?['public_id'] as String?;
  int get level => (profile?['level'] as num?)?.toInt() ?? 1;
  String get league => (profile?['league'] as String?) ?? 'UNRANKED';
  bool get removeAds => profile?['remove_ads'] == true;
  String get questionLanguage => (profile?['question_language'] as String?) ?? 'en';
  String get uiLanguage => (profile?['ui_language'] as String?) ?? 'en';

  Session withProfile(Json profile) => Session({...raw, 'profile': profile});
}
