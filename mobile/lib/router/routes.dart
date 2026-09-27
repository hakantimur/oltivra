/// Route paths. Screens navigate with `context.go/push(Routes.x)` or the helpers for parameterised paths.
abstract final class Routes {
  // P01 onboarding
  static const launch = '/';
  static const ageGate = '/onboarding/age';
  static const terms = '/onboarding/terms';
  static const signIn = '/sign-in';
  static const chooseName = '/onboarding/name';
  static const pickAvatar = '/onboarding/avatar';
  static const rename = '/rename';
  static const guide = '/guide';

  // Tabs
  static const home = '/home';
  static const play = '/play';
  static const rankings = '/rankings';
  static const social = '/social';
  static const profile = '/profile';

  // P02 matchmaking
  static String queue(String mode, {String? categoryId}) =>
      '/play/queue/${mode.toLowerCase()}${categoryId == null ? '' : '?category=$categoryId'}';
  static String matchReady(String matchId) => '/match/$matchId/ready';

  // P03/P04 live match (+ P08 reconnect / unavailable)
  static String match(String matchId) => '/match/$matchId';
  static const matchUnavailable = '/match-unavailable';

  // P05 social
  static const findPlayers = '/social/find';
  static const friendRequests = '/social/requests';
  static String player(String publicId) => '/players/$publicId';
  static const newChallenge = '/challenge/new';
  static String challengeLobby(String partyId) => '/challenge/lobby/$partyId';
  static String incomingChallenge(String token) => '/challenge/incoming/$token';

  // P06 progress
  static const league = '/rankings/league';
  static const missions = '/missions';
  static const categoryStats = '/profile/categories';
  static const achievements = '/profile/achievements';

  // P07 settings & safety
  static const settings = '/settings';
  static const editProfile = '/settings/profile';
  static const language = '/settings/language';
  static const blocked = '/settings/blocked';
  static const deleteAccount = '/settings/delete';
  static String reportPlayer(String publicId, {String? matchId}) =>
      '/report/$publicId${matchId == null ? '' : '?match=$matchId'}';

  // P08 monetization
  static const privacyAds = '/settings/privacy';
  static String rewardedOffer(String matchId) => '/rewards/$matchId';
  static const removeAds = '/store/remove-ads';
  static const adFreeActive = '/store/ad-free';

  /// Screens reachable before sign-in / onboarding completion.
  static const preAuth = {launch, ageGate, terms, signIn};
  static const onboarding = {ageGate, terms, signIn, chooseName, pickAvatar, launch};
}
