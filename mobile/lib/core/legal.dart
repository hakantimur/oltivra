import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../l10n/strings.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../widgets/o_widgets.dart';
import 'providers.dart';

/// Public legal documents served by the backend (`GET /v1/legal/{terms|privacy}`), one per language.
final legalDocumentProvider = FutureProvider.family<Json, (String, String)>(
  (ref, key) => ref.read(apiClientProvider).get('/v1/legal/${key.$1}', query: {'lang': key.$2}),
);

/// Opens the full Terms of Service (`terms`) or Privacy Policy (`privacy`) in a scrollable sheet.
Future<void> showLegalDocument(BuildContext context, String document) => showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      backgroundColor: OColors.canvas,
      builder: (context) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.8,
        maxChildSize: 0.95,
        builder: (context, controller) => _LegalBody(document: document, controller: controller),
      ),
    );

class _LegalBody extends ConsumerWidget {
  const _LegalBody({required this.document, required this.controller});

  final String document;
  final ScrollController controller;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final key = (document, context.lang);
    final doc = ref.watch(legalDocumentProvider(key));
    return doc.when(
      loading: () => const OLoading(),
      error: (e, _) => OErrorView(error: e, onRetry: () => ref.invalidate(legalDocumentProvider(key))),
      data: (d) {
        final sections = ((d['sections'] as List?) ?? const []).cast<Map>();
        return ListView(
          controller: controller,
          padding: const EdgeInsets.fromLTRB(OSpace.margin, 0, OSpace.margin, OSpace.xxl),
          children: [
            Semantics(header: true, child: Text('${d['title']}', style: OText.headlineLg)),
            const SizedBox(height: OSpace.xs),
            Text(context.t('legal.version', {'v': d['version']}),
                style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            for (final s in sections) ...[
              const SizedBox(height: OSpace.lg),
              Text('${s['heading']}', style: OText.headlineSm),
              for (final p in (s['paragraphs'] as List? ?? const [])) ...[
                const SizedBox(height: OSpace.sm),
                Text('$p', style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
              ],
            ],
          ],
        );
      },
    );
  }
}
