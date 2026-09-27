import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'widgets.dart';

/// Play tab (design P02 "Choose your battle"): Quick Battle and Survival mode cards, optional category queue
/// selector (only when the server enables category queues), and the private challenge entry.
class ChooseBattleScreen extends ConsumerStatefulWidget {
  const ChooseBattleScreen({super.key});

  @override
  ConsumerState<ChooseBattleScreen> createState() => _ChooseBattleScreenState();
}

class _ChooseBattleScreenState extends ConsumerState<ChooseBattleScreen> {
  /// `null` = Mixed.
  String? _category;

  void _play(String mode) => context.push(Routes.queue(mode, categoryId: _category));

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider).value;
    final config = ref.watch(clientConfigProvider).value;
    final categories = session?.categoryQueueIds ?? const <String>[];
    if (_category != null && !categories.contains(_category)) _category = null;
    final language = questionLanguageName(context, session?.questionLanguage ?? 'en');
    final survival = (config?['survival'] as Map?) ?? const {};
    final quick = (config?['quick'] as Map?) ?? const {};
    final wrongPenalty = (quick['wrong_penalty'] as num?)?.toInt();
    final survivalSeconds = (survival['seconds'] as num?)?.toInt();
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.only(bottom: OSpace.xxl),
          children: [
            HomeTopBar(title: context.t('home.play.title')),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: OSpace.margin),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: OSpace.sm),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: OPill(
                      context.t('home.play.context', {'category': categoryName(context, _category), 'language': language}),
                      background: OColors.surfaceContainer,
                      foreground: OColors.onSurfaceVariant,
                      icon: _category == null ? Icons.public_rounded : categoryIcon(_category),
                    ),
                  ),
                  const SizedBox(height: OSpace.md),
                  Text(context.t('home.play.heading'), style: OText.headlineXlMobile),
                  const SizedBox(height: OSpace.xs),
                  Text(context.t('home.play.subheading'), style: OText.bodyMd.copyWith(color: OColors.inkSubtle)),
                  if (categories.isNotEmpty) ...[
                    const SizedBox(height: OSpace.lg),
                    _CategorySelector(
                      ids: categories,
                      selected: _category,
                      onSelected: (id) => setState(() => _category = id),
                    ),
                  ],
                  const SizedBox(height: OSpace.xl),
                  _ModeCard(
                    icon: Icons.bolt_rounded,
                    accent: OColors.turquoise,
                    tint: OColors.mint,
                    tag: context.t('home.play.quick.tag'),
                    title: context.t('mode.QUICK'),
                    summary: quickSummary(context, config),
                    rules: [
                      context.t('home.play.quick.rule1'),
                      if (wrongPenalty != null && wrongPenalty != 0)
                        context.t('home.play.quick.rule2', {'n': wrongPenalty.abs()}),
                      context.t('home.play.quick.rule3'),
                    ],
                    cta: context.t('home.play.quick.cta'),
                    buttonColor: OColors.turquoise,
                    onPlay: () => _play('QUICK'),
                  ),
                  if (session?.survivalEnabled ?? true) ...[
                    const SizedBox(height: OSpace.lg),
                    _ModeCard(
                      icon: Icons.emoji_events_outlined,
                      accent: OColors.tertiary,
                      tint: OColors.sun,
                      ruleColor: OColors.secondary,
                      tag: context.t('home.play.survival.tag'),
                      title: context.t('mode.SURVIVAL'),
                      summary: context.t('home.play.survival.summary'),
                      rules: [
                        if (survivalSeconds != null) context.t('home.play.survival.rule1', {'s': survivalSeconds}),
                        context.t('home.play.survival.rule2'),
                        context.t('home.play.survival.rule3'),
                      ],
                      cta: context.t('home.play.survival.cta'),
                      buttonColor: OColors.secondary,
                      dotColor: OColors.secondary,
                      onPlay: () => _play('SURVIVAL'),
                    ),
                  ],
                  const SizedBox(height: OSpace.lg),
                  OCard(
                    onTap: () => context.push(Routes.newChallenge),
                    child: Row(
                      children: [
                        Container(
                          width: 48,
                          height: 48,
                          decoration: const BoxDecoration(color: OColors.surfaceContainer, shape: BoxShape.circle),
                          child: const Icon(Icons.group_add_outlined, color: OColors.primary),
                        ),
                        const SizedBox(width: OSpace.md),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(context.t('home.play.challenge.title'), style: OText.headlineSm),
                              Text(context.t('home.play.challenge.subtitle'),
                                  style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                            ],
                          ),
                        ),
                        const Icon(Icons.chevron_right_rounded, color: OColors.inkSubtle),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CategorySelector extends StatelessWidget {
  const _CategorySelector({required this.ids, required this.selected, required this.onSelected});

  final List<String> ids;
  final String? selected;
  final ValueChanged<String?> onSelected;

  @override
  Widget build(BuildContext context) {
    final options = <String?>[null, ...ids];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(context.t('home.play.category'), style: OText.labelMd.copyWith(color: OColors.inkSubtle)),
        const SizedBox(height: OSpace.sm),
        SizedBox(
          height: 48,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: options.length,
            separatorBuilder: (_, _) => const SizedBox(width: OSpace.sm),
            itemBuilder: (context, i) {
              final id = options[i];
              final isSelected = id == selected;
              return ChoiceChip(
                selected: isSelected,
                onSelected: (_) => onSelected(id),
                showCheckmark: false,
                avatar: Icon(categoryIcon(id), size: 18, color: isSelected ? OColors.white : OColors.primary),
                label: Text(categoryName(context, id)),
                labelStyle: OText.labelMd.copyWith(color: isSelected ? OColors.white : OColors.ink),
                selectedColor: OColors.primary,
                backgroundColor: OColors.white,
                side: BorderSide(color: isSelected ? OColors.primary : OColors.divider),
                shape: const StadiumBorder(),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _ModeCard extends StatelessWidget {
  const _ModeCard({
    required this.icon,
    required this.accent,
    required this.tint,
    required this.tag,
    required this.title,
    required this.summary,
    required this.rules,
    required this.cta,
    required this.buttonColor,
    required this.onPlay,
    this.ruleColor = OColors.turquoise,
    this.dotColor = OColors.turquoise,
  });

  final IconData icon;
  final Color accent;
  final Color tint;
  final Color ruleColor;
  final Color dotColor;
  final String tag;
  final String title;
  final String summary;
  final List<String> rules;
  final String cta;
  final Color buttonColor;
  final VoidCallback onPlay;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(ORadius.md),
          boxShadow: OShadow.card,
          gradient: LinearGradient(
            begin: Alignment.bottomLeft,
            end: Alignment.topRight,
            colors: [OColors.white, OColors.white, tint],
          ),
        ),
        padding: const EdgeInsets.all(OSpace.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 60,
                  height: 60,
                  decoration: BoxDecoration(color: tint, shape: BoxShape.circle),
                  child: Icon(icon, color: accent, size: 30),
                ),
                const Spacer(),
                Flexible(
                  flex: 4,
                  child: Align(
                    alignment: Alignment.centerRight,
                    child: OPill(tag, background: tint, foreground: accent),
                  ),
                ),
              ],
            ),
            const SizedBox(height: OSpace.lg),
            Row(
              children: [
                Flexible(child: Text(title, style: OText.headlineLg)),
                const SizedBox(width: 6),
                Container(width: 10, height: 10, decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle)),
              ],
            ),
            const SizedBox(height: OSpace.xs),
            Text(summary, style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant, fontWeight: FontWeight.w600)),
            const SizedBox(height: OSpace.lg),
            for (final rule in rules)
              Padding(
                padding: const EdgeInsets.only(bottom: OSpace.sm),
                child: Row(
                  children: [
                    Icon(Icons.check_circle_outline_rounded, size: 20, color: ruleColor),
                    const SizedBox(width: OSpace.md),
                    Expanded(child: Text(rule, style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant))),
                  ],
                ),
              ),
            const SizedBox(height: OSpace.md),
            HomeAccentButton(label: cta, color: buttonColor, onPressed: onPlay),
          ],
        ),
      );
}
