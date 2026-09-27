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

/// P08 · Remove Ads Forever (spec §31.3): one non-consumable. The price comes from the store product only;
/// the entitlement is granted by the server after `POST /v1/purchases/verify/google|apple`. PENDING grants
/// nothing. In dev (`AUTH_MODE=fake`) the buy button signs a transaction for the backend fake App Store
/// verifier so the flow works end to end on an emulator.
class RemoveAdsScreen extends ConsumerStatefulWidget {
  const RemoveAdsScreen({super.key});

  @override
  ConsumerState<RemoveAdsScreen> createState() => _RemoveAdsScreenState();
}

class _RemoveAdsScreenState extends ConsumerState<RemoveAdsScreen> {
  StoreProduct? _product;
  bool _loadingProduct = true;
  bool _buying = false;
  bool _restoring = false;
  bool _pending = false;
  StreamSubscription<List<StorePurchase>>? _sub;

  @override
  void initState() {
    super.initState();
    final gateway = ref.read(purchaseGatewayProvider);
    if (!Env.fakeAuth) {
      _sub = gateway.purchases.listen(_onPurchases, onError: (_) {});
    }
    _loadProduct(gateway);
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _loadProduct(PurchaseGateway gateway) async {
    StoreProduct? product;
    if (!Env.fakeAuth) {
      try {
        product = await gateway.loadProduct();
      } catch (_) {
        product = null;
      }
    }
    if (mounted) {
      setState(() {
        _product = product;
        _loadingProduct = false;
      });
    }
  }

  Future<void> _onPurchases(List<StorePurchase> purchases) async {
    for (final p in purchases) {
      if (p.productId != removeAdsProductId) continue;
      switch (p.status) {
        case StorePurchaseStatus.pending:
          if (mounted) setState(() => _pending = true);
        case StorePurchaseStatus.purchased || StorePurchaseStatus.restored:
          await _verify(p);
        case StorePurchaseStatus.error:
          if (mounted) {
            setState(() => _buying = false);
            showMessage(context, context.t('store.remove_ads.failed'));
          }
        case StorePurchaseStatus.canceled:
          if (mounted) setState(() => _buying = false);
      }
    }
  }

  Future<void> _verify(StorePurchase p) async {
    final api = ref.read(apiClientProvider);
    setState(() => _buying = true);
    try {
      final res = p.store == 'apple'
          ? await api.post('/v1/purchases/verify/apple', {'signed_transaction': p.verificationData})
          : await api.post('/v1/purchases/verify/google',
              {'product_id': removeAdsProductId, 'purchase_token': p.verificationData});
      // Finish the store transaction only after the server recorded it.
      await ref.read(purchaseGatewayProvider).complete(p);
      await _afterVerify(res);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _buying = false);
    }
  }

  Future<void> _afterVerify(Json res) async {
    if (res['remove_ads'] == true) {
      await ref.read(sessionProvider.notifier).refresh();
      if (mounted) context.pushReplacement(Routes.adFreeActive);
    } else if (mounted) {
      setState(() => _pending = res['purchase_state'] == 'PENDING');
      showMessage(context, context.t(_pending ? 'store.remove_ads.pending' : 'store.remove_ads.not_active'));
    }
  }

  Future<void> _buy() async {
    if (Env.fakeAuth) return _devBuy();
    setState(() => _buying = true);
    try {
      await ref.read(purchaseGatewayProvider).buy();
      // The result arrives on the purchase stream.
    } catch (e) {
      if (mounted) {
        setState(() => _buying = false);
        showMessage(context, context.t('store.remove_ads.store_unavailable'));
      }
    }
  }

  /// Dev only: a transaction signed for the backend `FakeAppleVerifier`, verified like a real one.
  Future<void> _devBuy() async {
    setState(() => _buying = true);
    try {
      final res = await ref
          .read(apiClientProvider)
          .post('/v1/purchases/verify/apple', {'signed_transaction': devAppleSignedTransaction()});
      await _afterVerify(res);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _buying = false);
    }
  }

  Future<void> _restore() async {
    setState(() => _restoring = true);
    try {
      // Entitlements are bound to the account server side, so a signed-in restore usually needs no store.
      final res = await ref.read(apiClientProvider).get('/v1/purchases/entitlements');
      if (res['remove_ads'] == true) {
        await ref.read(sessionProvider.notifier).refresh();
        if (mounted) context.pushReplacement(Routes.adFreeActive);
        return;
      }
      if (!Env.fakeAuth) {
        await ref.read(purchaseGatewayProvider).restore();
        if (mounted) showMessage(context, context.t('store.remove_ads.restoring'));
      } else if (mounted) {
        showMessage(context, context.t('store.remove_ads.nothing_to_restore'));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _restoring = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final price = _product?.price;
    final canBuy = Env.fakeAuth || price != null;
    final String label;
    if (Env.fakeAuth) {
      label = context.t('store.remove_ads.buy_dev');
    } else if (price != null) {
      label = context.t('store.remove_ads.buy', {'price': price});
    } else {
      label = context.t(_loadingProduct ? 'store.remove_ads.loading_price' : 'store.remove_ads.price_unavailable');
    }
    return OPage(
      title: context.t('store.remove_ads.title'),
      bottom: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          OButton(
            key: const ValueKey('remove_ads_buy'),
            label: label,
            icon: Icons.phonelink_lock_rounded,
            loading: _buying,
            onPressed: canBuy && !_restoring ? _buy : null,
          ),
          const SizedBox(height: OSpace.xs),
          TextButton(
            key: const ValueKey('remove_ads_restore'),
            onPressed: _buying || _restoring ? null : _restore,
            child: _restoring
                ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : Text(context.t('store.remove_ads.restore')),
          ),
        ],
      ),
      children: [
        Container(
          padding: const EdgeInsets.all(OSpace.xl),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(ORadius.lg),
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [OColors.surfaceContainer, OColors.mint],
            ),
          ),
          child: Column(
            children: [
              Container(
                width: 80,
                height: 80,
                decoration: BoxDecoration(color: OColors.turquoise.withValues(alpha: 0.2), shape: BoxShape.circle),
                child: const Icon(Icons.bolt_rounded, size: 44, color: OColors.primary),
              ),
              const SizedBox(height: OSpace.lg),
              OPill(context.t('store.remove_ads.kicker'), dot: true, background: OColors.white),
              const SizedBox(height: OSpace.md),
              Text(context.t('store.remove_ads.heading'), style: OText.headlineLg, textAlign: TextAlign.center),
              const SizedBox(height: OSpace.sm),
              Text(context.t('store.remove_ads.body'),
                  style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant), textAlign: TextAlign.center),
            ],
          ),
        ),
        const SizedBox(height: OSpace.lg),
        _Benefit(icon: Icons.check_circle_outline_rounded, titleKey: 'store.remove_ads.b1', bodyKey: 'store.remove_ads.b1.sub'),
        _Benefit(icon: Icons.sports_esports_outlined, titleKey: 'store.remove_ads.b2', bodyKey: 'store.remove_ads.b2.sub'),
        _Benefit(icon: Icons.verified_user_outlined, titleKey: 'store.remove_ads.b3', bodyKey: 'store.remove_ads.b3.sub'),
        const SizedBox(height: OSpace.sm),
        Container(
          padding: const EdgeInsets.all(OSpace.lg),
          decoration: BoxDecoration(color: OColors.surfaceContainer, borderRadius: BorderRadius.circular(ORadius.card)),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.info_outline_rounded, color: OColors.onSurfaceVariant),
              const SizedBox(width: OSpace.md),
              Expanded(child: Text(context.t('store.remove_ads.fair'), style: OText.bodyMd)),
            ],
          ),
        ),
        if (_pending) ...[
          const SizedBox(height: OSpace.md),
          OPill(context.t('store.remove_ads.pending'), icon: Icons.schedule_rounded,
              background: OColors.sun, foreground: OColors.tertiary),
        ],
        if (Env.fakeAuth) ...[
          const SizedBox(height: OSpace.md),
          Text(context.t('store.remove_ads.dev_note'),
              style: OText.bodySm.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
        ],
      ],
    );
  }
}

class _Benefit extends StatelessWidget {
  const _Benefit({required this.icon, required this.titleKey, required this.bodyKey});

  final IconData icon;
  final String titleKey;
  final String bodyKey;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: OSpace.md),
        child: OCard(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: const BoxDecoration(color: OColors.mint, shape: BoxShape.circle),
                child: Icon(icon, size: 22, color: OColors.primary),
              ),
              const SizedBox(width: OSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(context.t(titleKey), style: OText.labelLg),
                    const SizedBox(height: 2),
                    Text(context.t(bodyKey), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
