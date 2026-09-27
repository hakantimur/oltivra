import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/env.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../session/session.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'settings_widgets.dart';

/// App version shown in the footer. Mirrors `pubspec.yaml`; override with `--dart-define=APP_VERSION=…`.
const appVersionLabel = String.fromEnvironment('APP_VERSION', defaultValue: '1.0.0 (1)');

/// Notification preference keys in display order (backend `profiles/service.py` defaults). Keys the server
/// does not return are hidden; the server only accepts keys it already knows.
const notificationKeys = ['friend_requests', 'challenges', 'league', 'leaderboard', 'missions'];

/// Localised name of a language code ("English", "Türkçe"); unknown codes show upper-cased.
String languageName(String code) =>
    Strings.has('settings.lang.$code') ? Strings.lookup('en', 'settings.lang.$code') : code.toUpperCase();

/// P07 · Settings: account, notifications, privacy & safety, store, help and account actions.
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  /// Optimistic toggle values awaiting the PATCH response.
  final Map<String, bool> _pending = {};
  bool _signingOut = false;

  Future<void> _toggle(String key, bool value) async {
    setState(() => _pending[key] = value);
    try {
      final res = await ref.read(apiClientProvider).patch('/v1/profile/preferences', {
        'notifications': {key: value},
      });
      final profile = res['profile'];
      if (profile is Map) ref.read(sessionProvider.notifier).applyProfile(profile.cast<String, dynamic>());
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _pending.remove(key));
    }
  }

  Future<void> _signOut() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.t('settings.sign_out.title')),
        content: Text(ctx.t('settings.sign_out.body')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(ctx.t('action.cancel'))),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: Text(ctx.t('settings.sign_out'))),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _signingOut = true);
    try {
      await ref.read(authServiceProvider).signOut();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _signingOut = false);
    }
  }

  Future<void> _open(String url) async {
    final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    if (!ok && mounted) showMessage(context, context.t('settings.link_failed'));
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider).value;
    final locale = ref.watch(localeProvider);
    final uiLang = locale?.languageCode ?? context.lang;
    final serverNotifications = (session?.profile?['notifications'] as Map?)?.cast<String, dynamic>() ?? const {};
    final keys = [
      for (final k in notificationKeys)
        if (serverNotifications.containsKey(k)) k,
    ];
    final removeAds = session?.removeAds ?? false;

    return OPage(
      title: context.t('settings.title'),
      children: [
        if (session != null && session.profile != null) _ProfileHeader(session: session),
        SettingsCaption(context.t('settings.section.account')),
        SettingsGroup(children: [
          SettingsTile(
            icon: Icons.person_outline_rounded,
            title: context.t('settings.edit_profile'),
            subtitle: context.t('settings.edit_profile.sub'),
            onTap: () => context.push(Routes.editProfile),
          ),
          SettingsTile(
            icon: Icons.language_rounded,
            title: context.t('settings.language'),
            subtitle: languageName(uiLang),
            onTap: () => context.push(Routes.language),
          ),
        ]),
        if (keys.isNotEmpty) ...[
          SettingsCaption(context.t('settings.section.notifications')),
          SettingsGroup(children: [
            for (final k in keys)
              SettingsTile(
                icon: _notificationIcon(k),
                title: context.t('settings.notif.$k'),
                subtitle: context.t('settings.notif.$k.sub'),
                trailing: Switch(
                  value: _pending[k] ?? (serverNotifications[k] == true),
                  onChanged: _pending.containsKey(k) ? null : (v) => _toggle(k, v),
                ),
              ),
          ]),
        ],
        SettingsCaption(context.t('settings.section.privacy')),
        SettingsGroup(children: [
          SettingsTile(
            icon: Icons.shield_outlined,
            title: context.t('settings.privacy_ads'),
            subtitle: context.t('settings.privacy_ads.sub'),
            onTap: () => context.push(Routes.privacyAds),
          ),
          SettingsTile(
            icon: Icons.block_rounded,
            title: context.t('settings.blocked'),
            subtitle: context.t('settings.blocked.sub'),
            onTap: () => context.push(Routes.blocked),
          ),
        ]),
        const SizedBox(height: OSpace.lg),
        SettingsGroup(children: [
          SettingsTile(
            icon: Icons.auto_awesome_rounded,
            iconBackground: OColors.mint,
            iconColor: OColors.primary,
            title: context.t('settings.remove_ads'),
            subtitle: context.t(removeAds ? 'settings.remove_ads.active' : 'settings.remove_ads.sub'),
            badge: removeAds
                ? OPill(context.t('settings.remove_ads.badge'), icon: Icons.check_rounded)
                : null,
            onTap: () => context.push(removeAds ? Routes.adFreeActive : Routes.removeAds),
          ),
        ]),
        SettingsCaption(context.t('settings.section.help')),
        SettingsGroup(children: [
          SettingsTile(
            icon: Icons.menu_book_rounded,
            title: context.t('settings.guide'),
            subtitle: context.t('settings.guide.sub'),
            onTap: () => context.push(Routes.guide),
          ),
          SettingsTile(
            icon: Icons.open_in_new_rounded,
            title: context.t('settings.web_deletion'),
            subtitle: context.t('settings.web_deletion.sub'),
            onTap: () => _open(Env.accountDeletionUrl),
          ),
        ]),
        SettingsCaption(context.t('settings.section.session')),
        SettingsGroup(children: [
          SettingsTile(
            icon: Icons.logout_rounded,
            title: context.t('settings.sign_out'),
            onTap: _signingOut ? null : _signOut,
            trailing: _signingOut
                ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : null,
          ),
          SettingsTile(
            icon: Icons.delete_outline_rounded,
            danger: true,
            title: context.t('settings.delete_account'),
            subtitle: context.t('settings.delete_account.sub'),
            onTap: () => context.push(Routes.deleteAccount),
          ),
        ]),
        const SizedBox(height: OSpace.xxl),
        Center(
          child: Column(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: const BoxDecoration(color: OColors.mint, shape: BoxShape.circle),
                child: const Icon(Icons.bolt_rounded, size: 20, color: OColors.primary),
              ),
              const SizedBox(height: OSpace.sm),
              Text(context.t('app.name').toUpperCase(), style: OText.labelSm.copyWith(color: OColors.onSurfaceVariant)),
              const SizedBox(height: 2),
              Text(context.t('settings.version', {'version': appVersionLabel}),
                  style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            ],
          ),
        ),
      ],
    );
  }

  IconData _notificationIcon(String key) => switch (key) {
        'friend_requests' => Icons.person_add_alt_rounded,
        'challenges' => Icons.sports_esports_rounded,
        'league' => Icons.emoji_events_outlined,
        'leaderboard' => Icons.leaderboard_rounded,
        'missions' => Icons.flag_outlined,
        _ => Icons.notifications_none_rounded,
      };
}

class _ProfileHeader extends StatelessWidget {
  const _ProfileHeader({required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) => OCard(
        onTap: () => context.push(Routes.editProfile),
        child: Row(
          children: [
            OAvatar(avatarId: session.avatarId, frameId: session.frameId, size: 64),
            const SizedBox(width: OSpace.lg),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(session.username, style: OText.headlineSm, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 2),
                  Text(
                    '${context.t('level.short', {'level': session.level})} · ${context.t('league.${session.league}')}',
                    style: OText.bodySm.copyWith(color: OColors.inkSubtle),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
}
