import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'progress_api.dart';
import 'progress_widgets.dart';

/// Category statistics (P06 category_statistics): the nine approved categories with an accessible
/// bar + percentage accuracy and answered counts from `GET /v1/category-stats`.
class CategoryStatsScreen extends ConsumerWidget {
  const CategoryStatsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stats = ref.watch(categoryStatsProvider);
    return OPage(
      title: context.t('progress.categories.title'),
      onRefresh: () => ref.refresh(categoryStatsProvider.future),
      children: [
        progressAsync<Json>(stats, (data) => _Body(asJsonList(data['categories'])),
            onRetry: () => ref.invalidate(categoryStatsProvider)),
      ],
    );
  }
}

class _Body extends StatelessWidget {
  const _Body(this.categories);

  final List<Json> categories;

  @override
  Widget build(BuildContext context) {
    final played = categories.where((c) => (asInt(c['answered']) ?? 0) > 0 && asDouble(c['accuracy']) != null).toList()
      ..sort((a, b) => asDouble(b['accuracy'])!.compareTo(asDouble(a['accuracy'])!));
    final best = played.length >= 2 ? played.first : null;
    final focus = played.length >= 2 ? played.last : null;
    final totalAnswered = categories.fold<int>(0, (s, c) => s + (asInt(c['answered']) ?? 0));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        OCard(
          color: OColors.surfaceContainer,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Icon(Icons.insights_rounded, size: 18, color: OColors.primary),
              const SizedBox(width: OSpace.sm),
              Text(context.t('progress.categories.breakdown').toUpperCase(),
                  style: OText.labelSm.copyWith(color: OColors.primary)),
            ]),
            const SizedBox(height: OSpace.xs),
            Text(context.t('progress.categories.intro'), style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            if (totalAnswered > 0) ...[
              const SizedBox(height: OSpace.sm),
              Text(context.t('progress.categories.total_answered', {'n': totalAnswered}), style: OText.labelMd),
            ],
            if (best != null && focus != null) ...[
              const SizedBox(height: OSpace.md),
              Row(children: [
                Expanded(child: _Highlight(
                  icon: Icons.verified_rounded,
                  color: OColors.primary,
                  label: context.t('progress.categories.best'),
                  category: best,
                )),
                const SizedBox(width: OSpace.sm),
                Expanded(child: _Highlight(
                  icon: Icons.trending_up_rounded,
                  color: OColors.secondary,
                  label: context.t('progress.categories.focus'),
                  category: focus,
                )),
              ]),
            ],
          ]),
        ),
        const SizedBox(height: OSpace.lg),
        for (final c in categories) ...[_CategoryRow(category: c), const SizedBox(height: OSpace.md)],
        if (totalAnswered == 0)
          OEmptyState(
            icon: Icons.quiz_outlined,
            title: context.t('progress.categories.empty_title'),
            body: context.t('progress.categories.empty_body'),
          ),
      ],
    );
  }
}

String _categoryName(BuildContext context, Json c) {
  final id = c['category_id'] as String?;
  final key = 'category.$id';
  return Strings.has(key) ? context.t(key) : context.pick(c['names'] as Map?, fallback: id ?? '');
}

class _Highlight extends StatelessWidget {
  const _Highlight({required this.icon, required this.color, required this.label, required this.category});

  final IconData icon;
  final Color color;
  final String label;
  final Json category;

  @override
  Widget build(BuildContext context) {
    final pct = (asDouble(category['accuracy'])! * 100).round();
    return Container(
      padding: const EdgeInsets.all(OSpace.md),
      decoration: BoxDecoration(color: OColors.white, borderRadius: BorderRadius.circular(ORadius.card)),
      child: Row(children: [
        Icon(icon, size: 20, color: color),
        const SizedBox(width: OSpace.sm),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
            Text('${_categoryName(context, category)} ($pct%)',
                style: OText.labelMd, maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
      ]),
    );
  }
}

class _CategoryRow extends StatelessWidget {
  const _CategoryRow({required this.category});

  final Json category;

  @override
  Widget build(BuildContext context) {
    final id = category['category_id'] as String?;
    final answered = asInt(category['answered']) ?? 0;
    final correct = asInt(category['correct']) ?? 0;
    final accuracy = asDouble(category['accuracy']);
    final pct = accuracy == null ? null : (accuracy * 100).round();
    final avgMs = asInt(category['avg_correct_ms']);
    final name = _categoryName(context, category);
    final detail = answered == 0
        ? context.t('progress.categories.not_played')
        : [
            context.t('progress.categories.answered', {'correct': correct, 'answered': answered}),
            if (avgMs != null) context.t('progress.categories.avg_time', {'s': (avgMs / 1000).toStringAsFixed(1)}),
          ].join(' · ');

    return OCard(
      child: Semantics(
        label: pct == null ? '$name, $detail' : '$name, ${context.t('progress.categories.accuracy_label', {'pct': pct})}, $detail',
        excludeSemantics: true,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            RowIcon(categoryIcon(id), color: OColors.primary, background: OColors.surfaceContainer),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(name, style: OText.headlineSm, maxLines: 1, overflow: TextOverflow.ellipsis),
                Text(detail, style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
              ]),
            ),
            if (pct != null)
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text('$pct%', style: OText.tabular(OText.headlineMd)),
                Text(context.t('progress.categories.accuracy'), style: OText.labelSm.copyWith(color: OColors.inkSubtle)),
              ]),
          ]),
          if (accuracy != null) ...[
            const SizedBox(height: OSpace.md),
            OProgressBar(value: accuracy),
          ],
        ]),
      ),
    );
  }
}
