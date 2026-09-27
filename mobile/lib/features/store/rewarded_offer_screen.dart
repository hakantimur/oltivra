import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/env.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'store_services.dart';

enum _Phase { loading, ready, watching, verifying, granted, pending, unavailable }

/// P08 · Optional rewarded XP offer (spec §7.2, §31.2): a post-match sheet. The client never grants XP —
/// `POST /v1/rewards/offers/{match}/start` returns signed custom data for AdMob SSV, the backend grants on
/// the verified callback, and this screen polls `GET /v1/rewards/offers/{match}` until `GRANTED`.
/// "Not now" is always available; the offer never gates gameplay.
class RewardedOfferScreen extends ConsumerStatefulWidget {
  const RewardedOfferScreen({super.key, required this.matchId});

  final String matchId;

  @override
  ConsumerState<RewardedOfferScreen> createState() => _RewardedOfferScreenState();
}

class _RewardedOfferScreenState extends ConsumerState<RewardedOfferScreen> {
  static const _pollEvery = Duration(seconds: 2);
  static const _pollAttempts = 15;

  _Phase _phase = _Phase.loading;
  String _unavailableKey = 'store.reward.unavailable';
  int _bonusXp = 0;
  bool _disposed = false;

  String get _path => '/v1/rewards/offers/${widget.matchId}';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  Future<void> _load() async {
    try {
      _applyView(await ref.read(apiClientProvider).get(_path));
    } on ApiException catch (e) {
      _setUnavailable(e);
    } catch (_) {
      _setUnavailable(null);
    }
  }

  void _applyView(Json view) {
    if (!mounted) return;
    final bonus = (view['bonus_xp'] as num?)?.toInt() ?? 0;
    setState(() {
      _bonusXp = bonus;
      if (view['state'] == 'GRANTED') {
        _phase = _Phase.granted;
      } else if (bonus <= 0) {
        _phase = _Phase.unavailable;
        _unavailableKey = 'store.reward.unavailable';
      } else {
        _phase = _Phase.ready;
      }
    });
  }

  void _setUnavailable(ApiException? e) {
    if (!mounted) return;
    setState(() {
      _phase = _Phase.unavailable;
      _unavailableKey = switch ((e?.code, e?.reason)) {
        ('REWARD_CAP_REACHED', _) => 'store.reward.cap',
        (_, 'reward_offer_expired') => 'store.reward.expired',
        ('FEATURE_DISABLED', _) => 'store.reward.disabled',
        ('NETWORK_UNAVAILABLE' || 'NETWORK_TIMEOUT', _) => 'error.NETWORK_UNAVAILABLE',
        _ => 'store.reward.unavailable',
      };
    });
  }

  /// Creates (or reuses) the one-time offer and returns its SSV binding.
  Future<Json?> _start() async {
    try {
      final view = await ref.read(apiClientProvider).post('$_path/start');
      if (view['state'] == 'GRANTED') {
        _applyView(view);
        return null;
      }
      if (view['custom_data'] is! String || view['ssv_user_id'] is! String) {
        _setUnavailable(null);
        return null;
      }
      return view;
    } on ApiException catch (e) {
      _setUnavailable(e);
      return null;
    }
  }

  Future<void> _watch() async {
    setState(() => _phase = _Phase.watching);
    final view = await _start();
    if (view == null || !mounted) return;
    final outcome = await ref
        .read(rewardedAdGatewayProvider)
        .show(userId: view['ssv_user_id'] as String, customData: view['custom_data'] as String);
    if (!mounted) return;
    if (outcome != RewardedAdOutcome.earned) {
      setState(() => _phase = _Phase.ready);
      showMessage(context, context.t(outcome == RewardedAdOutcome.failed ? 'store.reward.ad_failed' : 'store.reward.not_completed'));
      return;
    }
    // Google's sample ad units never call our SSV endpoint; the dev backend accepts a locally signed one.
    if (Env.fakeAuth) await _devCallback(view);
    await _pollUntilGranted();
  }

  /// Dev-only path (`AUTH_MODE=fake`): simulate the AdMob SSV callback against the backend DevSsvVerifier.
  Future<void> _simulate() async {
    setState(() => _phase = _Phase.watching);
    final view = await _start();
    if (view == null || !mounted) return;
    await _devCallback(view);
    await _pollUntilGranted();
  }

  Future<void> _devCallback(Json view) async {
    try {
      await ref.read(apiClientProvider).get('/internal/ads/admob-ssv',
          query: devSsvQuery(userId: view['ssv_user_id'] as String, customData: view['custom_data'] as String));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _pollUntilGranted() async {
    if (!mounted) return;
    setState(() => _phase = _Phase.verifying);
    for (var i = 0; i < _pollAttempts && !_disposed; i++) {
      try {
        final view = await ref.read(apiClientProvider).get(_path);
        if (view['state'] == 'GRANTED') {
          _applyView(view);
          unawaited(ref.read(sessionProvider.notifier).refresh());
          return;
        }
      } catch (_) {
        // Keep polling; a transient error must not look like a failed reward.
      }
      await Future<void>.delayed(_pollEvery);
    }
    if (mounted) setState(() => _phase = _Phase.pending);
  }

  void _close() {
    if (context.canPop()) {
      context.pop(_phase == _Phase.granted);
    } else {
      context.go(Routes.home);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: OColors.scrim,
        body: SafeArea(
          child: Column(
            children: [
              Expanded(child: GestureDetector(onTap: _phase == _Phase.watching ? null : _close)),
              Container(
                width: double.infinity,
                constraints: const BoxConstraints(maxWidth: 560),
                margin: const EdgeInsets.all(OSpace.lg),
                padding: const EdgeInsets.fromLTRB(OSpace.xl, OSpace.xl, OSpace.xl, OSpace.lg),
                decoration: BoxDecoration(
                  color: OColors.white,
                  borderRadius: BorderRadius.circular(ORadius.lg),
                  boxShadow: OShadow.floating,
                ),
                child: AnimatedSize(duration: ODuration.medium, child: _sheet(context)),
              ),
            ],
          ),
        ),
      );

  Widget _sheet(BuildContext context) => switch (_phase) {
        _Phase.loading => const OLoading(),
        _Phase.ready || _Phase.watching => _offer(context),
        _Phase.verifying => _status(context, icon: Icons.hourglass_top_rounded, titleKey: 'store.reward.verifying',
            bodyKey: 'store.reward.verifying.body', busy: true),
        _Phase.granted => _status(context, icon: Icons.bolt_rounded, titleKey: 'store.reward.granted',
            bodyKey: 'store.reward.granted.body', args: {'xp': _bonusXp}),
        _Phase.pending => _status(context, icon: Icons.schedule_rounded, titleKey: 'store.reward.pending',
            bodyKey: 'store.reward.pending.body'),
        _Phase.unavailable => _status(context, icon: Icons.info_outline_rounded, titleKey: 'store.reward.unavailable.title',
            bodyKey: _unavailableKey),
      };

  Widget _offer(BuildContext context) {
    final busy = _phase == _Phase.watching;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 72,
          height: 72,
          decoration: const BoxDecoration(color: OColors.sun, shape: BoxShape.circle),
          child: const Icon(Icons.bolt_rounded, size: 40, color: OColors.tertiaryContainer),
        ),
        const SizedBox(height: OSpace.lg),
        Text(context.t('store.reward.title'), style: OText.headlineLg, textAlign: TextAlign.center),
        const SizedBox(height: OSpace.sm),
        Text(context.t('store.reward.body', {'xp': _bonusXp}),
            style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant), textAlign: TextAlign.center),
        const SizedBox(height: OSpace.lg),
        Container(
          padding: const EdgeInsets.symmetric(vertical: OSpace.lg, horizontal: OSpace.md),
          decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.sm)),
          child: Row(
            children: [
              Expanded(child: _xpColumn(context.t('store.reward.current'), '+$_bonusXp XP', OColors.ink)),
              const Icon(Icons.arrow_forward_rounded, color: OColors.turquoise),
              Expanded(child: _xpColumn(context.t('store.reward.with_boost'), '+${_bonusXp * 2} XP', OColors.primary)),
            ],
          ),
        ),
        const SizedBox(height: OSpace.md),
        Container(
          padding: const EdgeInsets.all(OSpace.md),
          decoration: BoxDecoration(color: OColors.surfaceContainerHigh, borderRadius: BorderRadius.circular(ORadius.sm)),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.verified_user_outlined, size: 20, color: OColors.primary),
              const SizedBox(width: OSpace.sm),
              Expanded(child: Text(context.t('store.reward.xp_only'), style: OText.bodySm)),
            ],
          ),
        ),
        const SizedBox(height: OSpace.lg),
        OButton(
          key: const ValueKey('reward_watch'),
          label: context.t('store.reward.watch'),
          icon: Icons.play_circle_outline_rounded,
          loading: busy,
          onPressed: busy ? null : _watch,
        ),
        if (Env.fakeAuth) ...[
          const SizedBox(height: OSpace.xs),
          TextButton(
            key: const ValueKey('reward_simulate'),
            onPressed: busy ? null : _simulate,
            child: Text(context.t('store.reward.simulate')),
          ),
        ],
        const SizedBox(height: OSpace.xs),
        OButton(
          key: const ValueKey('reward_not_now'),
          label: context.t('store.reward.not_now'),
          style: OButtonStyle.ghost,
          onPressed: _close,
        ),
      ],
    );
  }

  Widget _xpColumn(String label, String value, Color color) => Column(
        children: [
          Text(label.toUpperCase(), style: OText.labelSm.copyWith(color: OColors.onSurfaceVariant)),
          const SizedBox(height: OSpace.xs),
          Text(value, style: OText.tabular(OText.headlineMd).copyWith(color: color)),
        ],
      );

  Widget _status(BuildContext context,
          {required IconData icon,
          required String titleKey,
          required String bodyKey,
          Map<String, Object?>? args,
          bool busy = false}) =>
      Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 72,
            height: 72,
            decoration: const BoxDecoration(color: OColors.mint, shape: BoxShape.circle),
            child: busy
                ? const Padding(padding: EdgeInsets.all(22), child: CircularProgressIndicator(strokeWidth: 3))
                : Icon(icon, size: 36, color: OColors.primary),
          ),
          const SizedBox(height: OSpace.lg),
          Text(context.t(titleKey, args), style: OText.headlineMd, textAlign: TextAlign.center),
          const SizedBox(height: OSpace.sm),
          Text(context.t(bodyKey, args),
              style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant), textAlign: TextAlign.center),
          const SizedBox(height: OSpace.xl),
          OButton(
            key: const ValueKey('reward_close'),
            label: context.t(busy ? 'store.reward.not_now' : 'action.done'),
            style: busy ? OButtonStyle.ghost : OButtonStyle.primary,
            onPressed: _close,
          ),
        ],
      );
}
