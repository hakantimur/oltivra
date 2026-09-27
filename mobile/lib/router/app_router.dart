import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/providers.dart';
import '../features/home/choose_battle_screen.dart';
import '../features/home/finding_match_screen.dart';
import '../features/home/home_screen.dart';
import '../features/home/match_ready_screen.dart';
import '../features/match/match_screen.dart';
import '../features/match/match_unavailable_screen.dart';
import '../features/onboarding/age_gate_screen.dart';
import '../features/onboarding/choose_name_screen.dart';
import '../features/onboarding/game_guide_screen.dart';
import '../features/onboarding/launch_screen.dart';
import '../features/onboarding/pick_avatar_screen.dart';
import '../features/onboarding/sign_in_screen.dart';
import '../features/onboarding/terms_screen.dart';
import '../features/progress/achievements_screen.dart';
import '../features/progress/category_stats_screen.dart';
import '../features/progress/league_screen.dart';
import '../features/progress/missions_screen.dart';
import '../features/progress/my_profile_screen.dart';
import '../features/progress/rankings_screen.dart';
import '../features/settings/blocked_players_screen.dart';
import '../features/settings/delete_account_screen.dart';
import '../features/settings/edit_profile_screen.dart';
import '../features/settings/language_screen.dart';
import '../features/settings/report_player_screen.dart';
import '../features/settings/settings_screen.dart';
import '../features/social/challenge_lobby_screen.dart';
import '../features/social/find_players_screen.dart';
import '../features/social/friend_requests_screen.dart';
import '../features/social/friends_screen.dart';
import '../features/social/incoming_challenge_screen.dart';
import '../features/social/player_profile_screen.dart';
import '../features/store/ad_free_active_screen.dart';
import '../features/store/privacy_ads_screen.dart';
import '../features/store/remove_ads_screen.dart';
import '../features/store/rewarded_offer_screen.dart';
import 'app_shell.dart';
import 'routes.dart';

/// Re-evaluates redirects whenever auth, session or local onboarding changes.
class _RouterRefresh extends ChangeNotifier {
  _RouterRefresh(Ref ref) {
    ref.listen(authStateProvider, (_, _) => notifyListeners());
    ref.listen(sessionProvider, (_, _) => notifyListeners());
    ref.listen(localOnboardingProvider, (_, _) => notifyListeners());
  }
}

/// Onboarding gate (spec §2.2): age gate → legal → sign in → player name → avatar → guide → home.
String? onboardingRedirect(Ref ref, String location) {
  final auth = ref.read(authStateProvider);
  final local = ref.read(localOnboardingProvider);
  if (auth.isLoading) return location == Routes.launch ? null : Routes.launch;
  final user = auth.value;
  if (user == null) {
    if (location == Routes.launch) return null;
    if (!local.ageConfirmed) return location == Routes.ageGate ? null : Routes.ageGate;
    if (!local.termsAccepted) return location == Routes.terms ? null : Routes.terms;
    return location == Routes.signIn ? null : Routes.signIn;
  }
  final session = ref.read(sessionProvider);
  if (session.isLoading && !session.hasValue) return location == Routes.launch ? null : Routes.launch;
  final s = session.value;
  if (s == null) return location == Routes.launch ? null : Routes.launch; // bootstrap error: launch shows retry
  if (!s.consentDone) {
    if (!local.ageConfirmed) return location == Routes.ageGate ? null : Routes.ageGate;
    return location == Routes.terms ? null : Routes.terms;
  }
  if (!s.usernameDone) return location == Routes.chooseName ? null : Routes.chooseName;
  if (s.renameRequired) return location == Routes.rename ? null : Routes.rename;
  if (!s.avatarDone) return location == Routes.pickAvatar ? null : Routes.pickAvatar;
  if (Routes.onboarding.contains(location) || location == Routes.rename) {
    return local.guideSeen ? Routes.home : Routes.guide;
  }
  return null;
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = _RouterRefresh(ref);
  ref.onDispose(refresh.dispose);
  return GoRouter(
    initialLocation: Routes.launch,
    refreshListenable: refresh,
    redirect: (context, state) => onboardingRedirect(ref, state.matchedLocation),
    routes: [
      GoRoute(path: Routes.launch, builder: (_, _) => const LaunchScreen()),
      GoRoute(path: Routes.ageGate, builder: (_, _) => const AgeGateScreen()),
      GoRoute(path: Routes.terms, builder: (_, _) => const TermsScreen()),
      GoRoute(path: Routes.signIn, builder: (_, _) => const SignInScreen()),
      GoRoute(path: Routes.chooseName, builder: (_, _) => const ChooseNameScreen()),
      GoRoute(path: Routes.rename, builder: (_, _) => const ChooseNameScreen(rename: true)),
      GoRoute(path: Routes.pickAvatar, builder: (_, _) => const PickAvatarScreen()),
      GoRoute(path: Routes.guide, builder: (_, _) => const GameGuideScreen()),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => AppShell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: Routes.home, builder: (_, _) => const HomeScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: Routes.play, builder: (_, _) => const ChooseBattleScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: Routes.rankings, builder: (_, _) => const RankingsScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: Routes.social, builder: (_, _) => const FriendsScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: Routes.profile, builder: (_, _) => const MyProfileScreen())]),
        ],
      ),
      GoRoute(
        path: '/play/queue/:mode',
        builder: (_, s) => FindingMatchScreen(mode: s.pathParameters['mode']!.toUpperCase(),
            categoryId: s.uri.queryParameters['category']),
      ),
      GoRoute(path: '/match/:id/ready', builder: (_, s) => MatchReadyScreen(matchId: s.pathParameters['id']!)),
      GoRoute(path: '/match/:id', builder: (_, s) => MatchScreen(matchId: s.pathParameters['id']!)),
      GoRoute(
        path: Routes.matchUnavailable,
        builder: (_, s) => MatchUnavailableScreen(matchId: s.uri.queryParameters['match']),
      ),
      GoRoute(path: Routes.findPlayers, builder: (_, _) => const FindPlayersScreen()),
      GoRoute(path: Routes.friendRequests, builder: (_, _) => const FriendRequestsScreen()),
      GoRoute(path: '/players/:pid', builder: (_, s) => PlayerProfileScreen(publicId: s.pathParameters['pid']!)),
      GoRoute(path: Routes.newChallenge, builder: (_, _) => const ChallengeLobbyScreen()),
      GoRoute(
        path: '/challenge/lobby/:partyId',
        builder: (_, s) => ChallengeLobbyScreen(partyId: s.pathParameters['partyId']),
      ),
      GoRoute(
        path: '/challenge/incoming/:token',
        builder: (_, s) => IncomingChallengeScreen(token: s.pathParameters['token']!),
      ),
      GoRoute(path: Routes.league, builder: (_, _) => const LeagueScreen()),
      GoRoute(path: Routes.missions, builder: (_, _) => const MissionsScreen()),
      GoRoute(path: Routes.categoryStats, builder: (_, _) => const CategoryStatsScreen()),
      GoRoute(path: Routes.achievements, builder: (_, _) => const AchievementsScreen()),
      GoRoute(path: Routes.settings, builder: (_, _) => const SettingsScreen()),
      GoRoute(path: Routes.editProfile, builder: (_, _) => const EditProfileScreen()),
      GoRoute(path: Routes.language, builder: (_, _) => const LanguageScreen()),
      GoRoute(path: Routes.blocked, builder: (_, _) => const BlockedPlayersScreen()),
      GoRoute(path: Routes.deleteAccount, builder: (_, _) => const DeleteAccountScreen()),
      GoRoute(
        path: '/report/:pid',
        builder: (_, s) =>
            ReportPlayerScreen(publicId: s.pathParameters['pid']!, matchId: s.uri.queryParameters['match']),
      ),
      GoRoute(path: Routes.privacyAds, builder: (_, _) => const PrivacyAdsScreen()),
      GoRoute(path: '/rewards/:matchId', builder: (_, s) => RewardedOfferScreen(matchId: s.pathParameters['matchId']!)),
      GoRoute(path: Routes.removeAds, builder: (_, _) => const RemoveAdsScreen()),
      GoRoute(path: Routes.adFreeActive, builder: (_, _) => const AdFreeActiveScreen()),
    ],
  );
});
