import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../api/api_client.dart';
import '../../auth/auth_service.dart';
import '../../core/env.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'settings_widgets.dart';

/// Case/locale-insensitive comparison for the typed confirmation word ("DELETE" / "SİL").
bool confirmWordMatches(String input, String word) {
  String norm(String s) =>
      s.trim().replaceAll('İ', 'I').replaceAll('ı', 'i').replaceAll('i̇', 'i').toUpperCase();
  return input.trim().isNotEmpty && norm(input) == norm(word);
}

/// Fresh sign-in before deletion (spec §30.1 step 2; backend `REAUTH_WINDOW_S` = 5 min on `auth_time`).
/// Fake auth only needs its `:fresh` token window; Firebase re-runs the original provider sign-in and
/// refuses to continue if a different account comes back.
typedef FreshSignIn = Future<void> Function(BuildContext context);

final freshSignInProvider = Provider<FreshSignIn>((ref) => (context) async {
      final auth = ref.read(authServiceProvider);
      final before = auth.current;
      if (Env.fakeAuth || before == null) {
        await auth.reauthenticate();
        return;
      }
      switch (before.provider) {
        case 'google.com' || 'google':
          await auth.signInWithGoogle();
        case 'apple.com' || 'apple':
          await auth.signInWithApple();
        case 'password' || 'email':
          final password = await _askPassword(context, before.email);
          if (password == null || before.email == null) throw const AuthCancelled();
          await auth.signInWithEmail(before.email!, password, create: false);
        default:
          await auth.reauthenticate();
          return;
      }
      if (auth.current?.uid != before.uid) {
        await auth.signOut();
        throw ApiException(401, 'UNAUTHENTICATED', detail: const {'reason': 'different_account'});
      }
      await auth.reauthenticate();
    });

Future<String?> _askPassword(BuildContext context, String? email) {
  final controller = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(ctx.t('settings.delete.password.title')),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (email != null) Text(email, style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
          const SizedBox(height: OSpace.sm),
          TextField(
            controller: controller,
            obscureText: true,
            autofocus: true,
            decoration: InputDecoration(hintText: ctx.t('settings.delete.password.hint')),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: Text(ctx.t('action.cancel'))),
        TextButton(onPressed: () => Navigator.pop(ctx, controller.text), child: Text(ctx.t('action.continue'))),
      ],
    ),
  ).whenComplete(controller.dispose);
}

enum _Step { warning, confirm, pending, completed }

/// P07 · Delete shared account: calm warning → typed confirmation → fresh sign-in → `DELETE /v1/account`.
/// Deletion is global across connected products. A player in a live match gets `PENDING_MATCH` and the
/// deletion completes after the match settles; otherwise it completes immediately (backend deletion.py).
class DeleteAccountScreen extends ConsumerStatefulWidget {
  const DeleteAccountScreen({super.key});

  @override
  ConsumerState<DeleteAccountScreen> createState() => _DeleteAccountScreenState();
}

class _DeleteAccountScreenState extends ConsumerState<DeleteAccountScreen> {
  _Step _step = _Step.warning;
  final _confirm = TextEditingController();
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  @override
  void dispose() {
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _loadStatus() async {
    try {
      final res = await ref.read(apiClientProvider).get('/v1/account/deletion');
      final status = res['status'];
      if (!mounted) return;
      if (status == 'PENDING_MATCH' || status == 'PROCESSING') setState(() => _step = _Step.pending);
    } catch (_) {
      // No status available: start from the warning.
    }
  }

  Future<void> _delete() async {
    setState(() => _busy = true);
    try {
      await ref.read(freshSignInProvider)(context);
      final res = await ref.read(apiClientProvider).delete('/v1/account');
      if (!mounted) return;
      setState(() => _step = res['status'] == 'COMPLETED' ? _Step.completed : _Step.pending);
    } on AuthCancelled {
      if (mounted) showMessage(context, context.t('settings.delete.reauth_cancelled'));
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.code == 'UNAUTHENTICATED' && e.reason == 'recent_login_required') {
        showMessage(context, context.t('settings.delete.reauth_required'));
      } else if (e.reason == 'different_account') {
        showMessage(context, context.t('settings.delete.different_account'));
      } else {
        showError(context, e);
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finish() async {
    await ref.read(authServiceProvider).signOut();
    if (mounted) context.go(Routes.launch);
  }

  void _keep() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go(Routes.settings);
    }
  }

  Future<void> _openWeb() async {
    final ok = await launchUrl(Uri.parse(Env.accountDeletionUrl), mode: LaunchMode.externalApplication);
    if (!ok && mounted) showMessage(context, context.t('settings.link_failed'));
  }

  @override
  Widget build(BuildContext context) => switch (_step) {
        _Step.warning => _warning(context),
        _Step.confirm => _confirmStep(context),
        _Step.pending => _result(context, pending: true),
        _Step.completed => _result(context, pending: false),
      };

  Widget _warning(BuildContext context) => OPage(
        title: context.t('settings.delete.title'),
        bottom: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            OButton(
              key: const ValueKey('delete_keep'),
              label: context.t('settings.delete.keep'),
              icon: Icons.verified_user_outlined,
              onPressed: _keep,
            ),
            const SizedBox(height: OSpace.md),
            OButton(
              key: const ValueKey('delete_continue'),
              label: context.t('settings.delete.continue'),
              icon: Icons.delete_outline_rounded,
              style: OButtonStyle.danger,
              onPressed: () => setState(() => _step = _Step.confirm),
            ),
          ],
        ),
        children: [
          const SizedBox(height: OSpace.md),
          const HeroIcon(icon: Icons.health_and_safety_rounded, background: OColors.rose, color: OColors.coral),
          const SizedBox(height: OSpace.xl),
          OCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                OPill(context.t('settings.delete.irreversible'),
                    icon: Icons.info_outline_rounded, background: OColors.rose, foreground: OColors.coral),
                const SizedBox(height: OSpace.md),
                Text(context.t('settings.delete.heading'), style: OText.headlineMd),
                const SizedBox(height: OSpace.sm),
                Text(context.t('settings.delete.body'), style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
                const SizedBox(height: OSpace.lg),
                Container(
                  padding: const EdgeInsets.all(OSpace.lg),
                  decoration: BoxDecoration(
                    color: OColors.surfaceContainer,
                    borderRadius: BorderRadius.circular(ORadius.sm),
                  ),
                  child: Column(
                    children: [
                      _Consequence(icon: Icons.military_tech_outlined, text: context.t('settings.delete.point.progress')),
                      _Consequence(icon: Icons.sync_problem_rounded, text: context.t('settings.delete.point.match')),
                      _Consequence(icon: Icons.group_off_outlined, text: context.t('settings.delete.point.social')),
                      _Consequence(icon: Icons.workspace_premium_outlined,
                          text: context.t('settings.delete.point.purchases')),
                      _Consequence(icon: Icons.alternate_email_rounded, text: context.t('settings.delete.point.name')),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: OSpace.lg),
          SettingsGroup(children: [
            SettingsTile(
              icon: Icons.devices_rounded,
              title: context.t('settings.delete.shared.title'),
              subtitle: context.t('settings.delete.shared.body'),
            ),
            SettingsTile(
              icon: Icons.open_in_new_rounded,
              title: context.t('settings.web_deletion'),
              subtitle: context.t('settings.web_deletion.sub'),
              onTap: _openWeb,
            ),
          ]),
        ],
      );

  Widget _confirmStep(BuildContext context) {
    final word = context.t('settings.delete.confirm_word');
    final matches = confirmWordMatches(_confirm.text, word);
    return OPage(
      title: context.t('settings.delete.title'),
      bottom: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          OButton(
            key: const ValueKey('delete_confirm'),
            label: context.t('settings.delete.confirm_button'),
            icon: Icons.lock_outline_rounded,
            style: OButtonStyle.danger,
            loading: _busy,
            onPressed: matches ? _delete : null,
          ),
          const SizedBox(height: OSpace.md),
          OButton(
            label: context.t('settings.delete.keep'),
            style: OButtonStyle.secondary,
            onPressed: _busy ? null : _keep,
          ),
        ],
      ),
      children: [
        const SizedBox(height: OSpace.lg),
        Text(context.t('settings.delete.confirm.heading'), style: OText.headlineMd),
        const SizedBox(height: OSpace.sm),
        Text(context.t('settings.delete.confirm.body', {'word': word}),
            style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
        const SizedBox(height: OSpace.lg),
        TextField(
          key: const ValueKey('delete_confirm_field'),
          controller: _confirm,
          enabled: !_busy,
          autocorrect: false,
          textCapitalization: TextCapitalization.characters,
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(hintText: word),
        ),
        const SizedBox(height: OSpace.lg),
        InfoBanner(
          icon: Icons.login_rounded,
          title: context.t('settings.delete.reauth.title'),
          body: context.t('settings.delete.reauth.body'),
        ),
      ],
    );
  }

  Widget _result(BuildContext context, {required bool pending}) => OPage(
        title: context.t('settings.delete.title'),
        showBack: pending,
        bottom: OButton(
          key: const ValueKey('delete_finish'),
          label: context.t(pending ? 'settings.sign_out' : 'action.done'),
          onPressed: _finish,
        ),
        children: [
          const SizedBox(height: OSpace.xxl),
          HeroIcon(
            icon: pending ? Icons.hourglass_top_rounded : Icons.check_rounded,
            background: pending ? OColors.sun : OColors.mint,
            color: pending ? OColors.tertiary : OColors.primary,
          ),
          const SizedBox(height: OSpace.xl),
          Text(context.t(pending ? 'settings.delete.pending.title' : 'settings.delete.done.title'),
              style: OText.headlineMd, textAlign: TextAlign.center),
          const SizedBox(height: OSpace.sm),
          Text(context.t(pending ? 'settings.delete.pending.body' : 'settings.delete.done.body'),
              style: OText.bodyMd.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
        ],
      );
}

class _Consequence extends StatelessWidget {
  const _Consequence({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: OSpace.xs + 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 20, color: OColors.onSurfaceVariant),
            const SizedBox(width: OSpace.md),
            Expanded(child: Text(text, style: OText.bodyMd)),
          ],
        ),
      );
}
