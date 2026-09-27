import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import '../settings/settings_widgets.dart';

/// P08 · Ad-free purchase active: calm confirmation backed by `GET /v1/purchases/entitlements`.
class AdFreeActiveScreen extends ConsumerStatefulWidget {
  const AdFreeActiveScreen({super.key});

  @override
  ConsumerState<AdFreeActiveScreen> createState() => _AdFreeActiveScreenState();
}

class _AdFreeActiveScreenState extends ConsumerState<AdFreeActiveScreen> {
  Json? _entitlements;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final res = await ref.read(apiClientProvider).get('/v1/purchases/entitlements');
      if (mounted) setState(() => _entitlements = res);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final e = _entitlements;
    final active = e?['remove_ads'] == true;
    return OPage(
      title: context.t('store.ad_free.title'),
      bottom: e == null
          ? null
          : OButton(
              key: const ValueKey('ad_free_back'),
              label: context.t(active ? 'store.ad_free.back' : 'store.ad_free.get'),
              trailingIcon: Icons.arrow_forward_rounded,
              onPressed: () => active ? context.go(Routes.home) : context.pushReplacement(Routes.removeAds),
            ),
      children: [
        if (e == null && _error != null)
          OErrorView(error: _error!, onRetry: _load)
        else if (e == null)
          const OLoading()
        else if (!active)
          OEmptyState(
            icon: Icons.remove_moderator_outlined,
            title: context.t('store.ad_free.inactive.title'),
            body: context.t(e['state'] == 'REVOKED' ? 'store.ad_free.revoked' : 'store.ad_free.inactive.body'),
          )
        else ...[
          const SizedBox(height: OSpace.lg),
          Center(
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Container(
                  width: 150,
                  height: 150,
                  padding: const EdgeInsets.all(22),
                  decoration: BoxDecoration(color: OColors.mint, shape: BoxShape.circle,
                      border: Border.all(color: OColors.turquoise.withValues(alpha: 0.15), width: 8)),
                  child: Container(
                    decoration: const BoxDecoration(color: OColors.white, shape: BoxShape.circle),
                    child: const Icon(Icons.verified_user_outlined, size: 52, color: OColors.turquoise),
                  ),
                ),
                Positioned(
                  right: 4,
                  bottom: 4,
                  child: Container(
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(color: OColors.success, shape: BoxShape.circle,
                        border: Border.all(color: OColors.white, width: 3)),
                    child: const Icon(Icons.check_rounded, color: OColors.white),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: OSpace.xl),
          Center(child: OPill(context.t('store.ad_free.kicker'), icon: Icons.workspace_premium_outlined)),
          const SizedBox(height: OSpace.md),
          Text(context.t('store.ad_free.heading'), style: OText.headlineXlMobile, textAlign: TextAlign.center),
          const SizedBox(height: OSpace.sm),
          Text(context.t('store.ad_free.body'),
              style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant), textAlign: TextAlign.center),
          const SizedBox(height: OSpace.xl),
          SettingsGroup(children: [
            SettingsTile(
              icon: Icons.verified_outlined,
              iconBackground: OColors.mint,
              iconColor: OColors.primary,
              title: context.t('store.ad_free.status'),
              subtitle: _sourceLabel(context, e['source_store'] as String?),
              trailing: OPill(context.t('store.ad_free.active')),
            ),
            SettingsTile(
              icon: Icons.smart_display_outlined,
              iconBackground: OColors.sun,
              iconColor: OColors.tertiary,
              title: context.t('store.ad_free.rewarded'),
              subtitle: context.t('store.ad_free.rewarded.sub'),
            ),
            SettingsTile(
              icon: Icons.devices_rounded,
              title: context.t('store.ad_free.devices'),
              subtitle: context.t('store.ad_free.devices.sub'),
            ),
          ]),
        ],
      ],
    );
  }

  String _sourceLabel(BuildContext context, String? store) => switch (store) {
        'GOOGLE_PLAY' => context.t('store.ad_free.source.google'),
        'APP_STORE' => context.t('store.ad_free.source.apple'),
        _ => context.t('store.ad_free.source.unknown'),
      };
}
