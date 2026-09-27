import 'package:flutter/material.dart';

import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';

/// Pre-ad notice card (playtest 2026-09-27): tells the player why an ad follows before the interstitial shows.
Future<void> showAdBreakNotice(BuildContext context) => showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => const _AdBreakNotice(),
    );

class _AdBreakNotice extends StatelessWidget {
  const _AdBreakNotice();

  @override
  Widget build(BuildContext context) => Dialog(
        key: const Key('ad-break-notice'),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(ORadius.lg)),
        child: Padding(
          padding: const EdgeInsets.all(OSpace.xl),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.favorite_rounded, size: 40, color: OColors.primary),
            const SizedBox(height: OSpace.md),
            Text(context.t('store.ad_break.title'), style: OText.headlineSm, textAlign: TextAlign.center),
            const SizedBox(height: OSpace.sm),
            Text(context.t('store.ad_break.body'), style: OText.bodyMd, textAlign: TextAlign.center),
            const SizedBox(height: OSpace.sm),
            Text(context.t('store.ad_break.hint'),
                style: OText.bodySm.copyWith(color: OColors.inkSubtle), textAlign: TextAlign.center),
            const SizedBox(height: OSpace.lg),
            OButton(
              key: const Key('ad-break-continue'),
              label: context.t('store.ad_break.continue'),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ]),
        ),
      );
}
