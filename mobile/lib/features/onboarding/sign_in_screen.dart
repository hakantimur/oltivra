import 'package:firebase_auth/firebase_auth.dart' show FirebaseAuthException;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../auth/auth_service.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'widgets.dart';

enum _Provider { google }

/// P01 · Sign in or create account: Google and email, equally prominent (spec §2.1). Apple sign-in is not offered
/// while the app ships on Android only.
/// Once signed in, `onboardingRedirect` takes over (bootstrap → consent → name → avatar).
class SignInScreen extends ConsumerStatefulWidget {
  const SignInScreen({super.key});

  @override
  ConsumerState<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends ConsumerState<SignInScreen> {
  _Provider? _busy;

  Future<void> _run(_Provider provider, Future<void> Function(AuthService auth) action) async {
    if (_busy != null) return;
    setState(() => _busy = provider);
    try {
      await action(ref.read(authServiceProvider));
    } on AuthCancelled {
      // The player backed out of the provider sheet: nothing to report.
    } catch (e) {
      if (mounted) showMessage(context, authErrorText(context, e));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _email() async {
    if (_busy != null) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      backgroundColor: OColors.canvas,
      builder: (_) => const _EmailSheet(),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: onboardingAppBar(
          context,
          title: context.t('onboarding.signin.title'),
          onBack: () => context.go(Routes.launch),
        ),
        body: SafeArea(
          top: false,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
            children: [
              const OnboardingStepBar(step: 3),
              const SizedBox(height: OSpace.lg),
              Container(
                padding: const EdgeInsets.fromLTRB(OSpace.xl, OSpace.xxl, OSpace.xl, OSpace.xl),
                decoration: BoxDecoration(
                  color: OColors.white,
                  borderRadius: BorderRadius.circular(ORadius.lg),
                  boxShadow: OShadow.card,
                ),
                child: Column(
                  children: [
                    const OnboardingHeroIcon(
                      icon: Icons.bolt_rounded,
                      badgeIcon: Icons.stars_rounded,
                      gradient: true,
                      badgeColor: OColors.secondary,
                    ),
                    const SizedBox(height: OSpace.md),
                    Semantics(
                      header: true,
                      child: Text(context.t('onboarding.signin.heading'),
                          textAlign: TextAlign.center, style: OText.headlineXlMobile),
                    ),
                    const SizedBox(height: OSpace.sm),
                    Text(
                      context.t('onboarding.signin.body'),
                      textAlign: TextAlign.center,
                      style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant),
                    ),
                    const SizedBox(height: OSpace.xl),
                    OButton(
                      key: const Key('signin-google'),
                      label: context.t('onboarding.signin.google'),
                      style: OButtonStyle.secondary,
                      leading: const _GoogleGlyph(),
                      loading: _busy == _Provider.google,
                      onPressed: _busy == null ? () => _run(_Provider.google, (a) => a.signInWithGoogle()) : null,
                    ),
                    const SizedBox(height: OSpace.md),
                    OButton(
                      key: const Key('signin-email'),
                      label: context.t('onboarding.signin.email'),
                      style: OButtonStyle.secondary,
                      icon: Icons.mail_outline_rounded,
                      onPressed: _busy == null ? _email : null,
                    ),
                    const SizedBox(height: OSpace.xl),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.verified_user_outlined, size: 18, color: OColors.primary),
                        const SizedBox(width: OSpace.xs),
                        Flexible(
                          child: Text(context.t('onboarding.signin.safe'),
                              style: OText.labelMd.copyWith(color: OColors.onSurfaceVariant)),
                        ),
                      ],
                    ),
                    const SizedBox(height: OSpace.xs),
                    Text(
                      context.t('onboarding.signin.legal'),
                      textAlign: TextAlign.center,
                      style: OText.bodySm.copyWith(color: OColors.inkSubtle),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}

/// Maps Firebase Auth failures to friendly copy; everything else goes through the shared error mapping.
String authErrorText(BuildContext context, Object error) {
  if (error is FirebaseAuthException) {
    final key = switch (error.code) {
      'wrong-password' || 'user-not-found' || 'invalid-credential' || 'invalid-login-credentials' =>
        'onboarding.email.error.wrong_credentials',
      'email-already-in-use' || 'account-exists-with-different-credential' => 'onboarding.email.error.in_use',
      'weak-password' => 'onboarding.email.error.weak_password',
      'too-many-requests' => 'onboarding.email.error.too_many',
      'invalid-email' => 'onboarding.email.invalid_email',
      'network-request-failed' => 'error.NETWORK_UNAVAILABLE',
      _ => 'error.generic',
    };
    return context.t(key);
  }
  return errorText(context, error);
}

/// Multicolour "G" drawn as text (no bundled brand asset).
class _GoogleGlyph extends StatelessWidget {
  const _GoogleGlyph();

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
        child: ShaderMask(
          shaderCallback: (rect) => const SweepGradient(
            colors: [Color(0xFFEA4335), Color(0xFFFBBC05), Color(0xFF34A853), Color(0xFF4285F4), Color(0xFFEA4335)],
          ).createShader(rect),
          child: Text('G', style: OText.headlineMd.copyWith(color: OColors.white, fontWeight: FontWeight.w800)),
        ),
      );
}

class _EmailSheet extends ConsumerStatefulWidget {
  const _EmailSheet();

  @override
  ConsumerState<_EmailSheet> createState() => _EmailSheetState();
}

class _EmailSheetState extends ConsumerState<_EmailSheet> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _create = true;
  bool _obscure = true;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_form.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authServiceProvider).signInWithEmail(_email.text.trim(), _password.text, create: _create);
      if (mounted) Navigator.of(context).pop();
    } on AuthCancelled {
      // Nothing to report.
    } catch (e) {
      if (mounted) setState(() => _error = authErrorText(context, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(
            OSpace.margin, 0, OSpace.margin, MediaQuery.viewInsetsOf(context).bottom + OSpace.xl),
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                context.t(_create ? 'onboarding.email.title_create' : 'onboarding.email.title_signin'),
                style: OText.headlineLg,
              ),
              const SizedBox(height: OSpace.lg),
              TextFormField(
                key: const Key('email-field'),
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                autofillHints: const [AutofillHints.email],
                textInputAction: TextInputAction.next,
                autocorrect: false,
                decoration: InputDecoration(
                  labelText: context.t('onboarding.email.email'),
                  prefixIcon: const Icon(Icons.mail_outline_rounded),
                ),
                validator: (v) {
                  final value = (v ?? '').trim();
                  final ok = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(value);
                  return ok ? null : context.t('onboarding.email.invalid_email');
                },
              ),
              const SizedBox(height: OSpace.md),
              TextFormField(
                key: const Key('password-field'),
                controller: _password,
                obscureText: _obscure,
                autofillHints: [_create ? AutofillHints.newPassword : AutofillHints.password],
                textInputAction: TextInputAction.done,
                onFieldSubmitted: (_) => _submit(),
                decoration: InputDecoration(
                  labelText: context.t('onboarding.email.password'),
                  prefixIcon: const Icon(Icons.lock_outline_rounded),
                  suffixIcon: IconButton(
                    tooltip: context.t(_obscure ? 'onboarding.email.show_password' : 'onboarding.email.hide_password'),
                    icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                    onPressed: () => setState(() => _obscure = !_obscure),
                  ),
                ),
                validator: (v) => (v ?? '').length >= 6 ? null : context.t('onboarding.email.short_password'),
              ),
              if (_error != null) ...[
                const SizedBox(height: OSpace.md),
                Text(_error!, style: OText.bodySm.copyWith(color: OColors.coral)),
              ],
              const SizedBox(height: OSpace.xl),
              OButton(
                key: const Key('email-submit'),
                label: context.t(_create ? 'onboarding.email.submit_create' : 'onboarding.email.submit_signin'),
                loading: _busy,
                onPressed: _submit,
              ),
              const SizedBox(height: OSpace.sm),
              TextButton(
                onPressed: _busy
                    ? null
                    : () => setState(() {
                          _create = !_create;
                          _error = null;
                        }),
                child: Text(
                  context.t(_create ? 'onboarding.email.toggle_to_signin' : 'onboarding.email.toggle_to_create'),
                  style: OText.labelMd.copyWith(color: OColors.primary),
                ),
              ),
            ],
          ),
        ),
      );
}
