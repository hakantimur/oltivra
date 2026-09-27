import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';

/// Rule numbers (spec §3.1, §3.2, §4.1 as changed by the 2026-09-27 playtest), used only when
/// `/v1/client-config` does not provide them.
abstract final class _SpecDefaults {
  static const quickPlayers = 4;
  static const quickQuestions = 10;
  static const quickSeconds = 15;
  static const quickWrongPenalty = -6;
  static const quickNoAnswerPenalty = 0;
  static const survivalPlayers = 10;
  static const survivalSeconds = 15;
}

/// P01 · Game guide "Two ways to rise": Quick Battle and Survival explained with server-configured numbers.
class GameGuideScreen extends ConsumerWidget {
  const GameGuideScreen({super.key});

  Future<void> _finish(BuildContext context, WidgetRef ref) async {
    await ref.read(localOnboardingProvider.notifier).markGuideSeen();
    if (context.mounted) context.go(Routes.home);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(clientConfigProvider).value ?? const {};
    final quick = (config['quick'] as Map?) ?? const {};
    final survival = (config['survival'] as Map?) ?? const {};
    int read(Map m, String key, int fallback) => (m[key] as num?)?.toInt() ?? fallback;

    final questions = read(quick, 'questions', _SpecDefaults.quickQuestions);
    final quickSeconds = read(quick, 'seconds', _SpecDefaults.quickSeconds);
    final maxPoints = read(quick, 'max_points', quickSeconds);
    final wrong = read(quick, 'wrong_penalty', _SpecDefaults.quickWrongPenalty).abs();
    final skip = read(quick, 'no_answer_penalty', _SpecDefaults.quickNoAnswerPenalty).abs();
    final survivalSeconds = read(survival, 'seconds', _SpecDefaults.survivalSeconds);
    final session = ref.watch(sessionProvider).value;
    final survivalEnabled = (config['survival_enabled'] as bool?) ?? session?.survivalEnabled ?? true;

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        leading: IconButton(
          tooltip: context.t('onboarding.guide.close'),
          icon: const Icon(Icons.close_rounded),
          onPressed: () => _finish(context, ref),
        ),
        title: Text(context.t('onboarding.guide.title'), style: OText.headlineSm),
      ),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
          children: [
            Row(
              children: [
                const Icon(Icons.flag_outlined, size: 16, color: OColors.primary),
                const SizedBox(width: OSpace.xs),
                Flexible(
                  child: Text(context.t('onboarding.guide.eyebrow'),
                      style: OText.labelMd.copyWith(color: OColors.primary, letterSpacing: 1)),
                ),
              ],
            ),
            const SizedBox(height: OSpace.sm),
            Semantics(header: true, child: Text(context.t('onboarding.guide.heading'), style: OText.headlineXl)),
            const SizedBox(height: OSpace.xs),
            Text(context.t('onboarding.guide.body'), style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant)),
            const SizedBox(height: OSpace.xl),
            _ModeCard(
              key: const Key('guide-quick'),
              number: '01',
              accent: OColors.primary,
              tag: context.t('onboarding.guide.quick_tag'),
              tagIcon: Icons.bolt_rounded,
              tagBackground: const Color(0xFF71F8E4),
              title: context.t('mode.QUICK'),
              summary: context.t('onboarding.guide.quick_summary',
                  {'players': _SpecDefaults.quickPlayers, 'questions': questions}),
              art: const _BarsArt(),
              facts: [
                (Icons.speed_rounded, context.t('onboarding.guide.quick_speed',
                    {'max': maxPoints, 'seconds': quickSeconds})),
                (Icons.remove_circle_outline_rounded, context.t('onboarding.guide.quick_wrong', {'wrong': wrong})),
                (Icons.do_not_disturb_on_outlined, skip == 0
                    ? context.t('onboarding.guide.quick_skip_free')
                    : context.t('onboarding.guide.quick_skip', {'skip': skip})),
              ],
            ),
            if (survivalEnabled) ...[
              const SizedBox(height: OSpace.lg),
              _ModeCard(
                key: const Key('guide-survival'),
                number: '02',
                accent: OColors.secondary,
                tag: context.t('onboarding.guide.survival_tag'),
                tagIcon: Icons.local_fire_department_outlined,
                tagBackground: OColors.secondaryFixed,
                title: context.t('mode.SURVIVAL'),
                summary: context.t('onboarding.guide.survival_summary', {'players': _SpecDefaults.survivalPlayers}),
                art: const _RingArt(),
                facts: [
                  (Icons.timer_outlined, context.t('onboarding.guide.survival_timer', {'seconds': survivalSeconds})),
                  (Icons.verified_outlined, context.t('onboarding.guide.survival_note')),
                ],
              ),
            ],
            const SizedBox(height: OSpace.xl),
            Row(
              children: [
                const Icon(Icons.public_rounded, size: 20, color: OColors.primary),
                const SizedBox(width: OSpace.sm),
                Expanded(
                  child: Text(context.t('onboarding.guide.footer'),
                      style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
                ),
              ],
            ),
            const SizedBox(height: OSpace.xl),
            OButton(
              key: const Key('guide-play'),
              label: context.t('onboarding.guide.play'),
              trailingIcon: Icons.arrow_forward_rounded,
              onPressed: () => _finish(context, ref),
            ),
          ],
        ),
      ),
    );
  }
}

class _ModeCard extends StatelessWidget {
  const _ModeCard({super.key, required this.number, required this.accent, required this.tag, required this.tagIcon,
      required this.tagBackground, required this.title, required this.summary, required this.art,
      required this.facts});

  final String number;
  final Color accent;
  final String tag;
  final IconData tagIcon;
  final Color tagBackground;
  final String title;
  final String summary;
  final Widget art;
  final List<(IconData, String)> facts;

  @override
  Widget build(BuildContext context) => OCard(
        radius: ORadius.lg,
        padding: const EdgeInsets.all(OSpace.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: FittedBox(
                      fit: BoxFit.scaleDown,
                      child: OPill(tag, icon: tagIcon, background: tagBackground, foreground: OColors.ink),
                    ),
                  ),
                ),
                const SizedBox(width: OSpace.sm),
                ExcludeSemantics(child: Text(number, style: OText.headlineSm.copyWith(color: accent))),
              ],
            ),
            const SizedBox(height: OSpace.lg),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: OText.headlineLg),
                      const SizedBox(height: OSpace.xs),
                      Text(summary, style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
                    ],
                  ),
                ),
                const SizedBox(width: OSpace.md),
                ExcludeSemantics(
                  child: Container(
                    width: 88,
                    height: 88,
                    decoration: BoxDecoration(
                      color: const Color(0xFFF2F3FF),
                      borderRadius: BorderRadius.circular(ORadius.md),
                    ),
                    child: art,
                  ),
                ),
              ],
            ),
            const SizedBox(height: OSpace.lg),
            for (final (icon, text) in facts)
              Padding(
                padding: const EdgeInsets.only(top: OSpace.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(icon, size: 20, color: accent),
                    const SizedBox(width: OSpace.sm),
                    Expanded(child: Text(text, style: OText.bodyMd)),
                  ],
                ),
              ),
          ],
        ),
      );
}

class _BarsArt extends StatelessWidget {
  const _BarsArt();

  @override
  Widget build(BuildContext context) {
    Widget bar(double h, double alpha) => Container(
          width: 12,
          height: h,
          margin: const EdgeInsets.symmetric(horizontal: 2),
          decoration: BoxDecoration(
            color: OColors.turquoise.withValues(alpha: alpha),
            borderRadius: BorderRadius.circular(4),
          ),
        );
    return Padding(
      padding: const EdgeInsets.all(OSpace.md),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [bar(30, 0.55), bar(52, 1), bar(38, 0.7), bar(22, 0.4)],
      ),
    );
  }
}

class _RingArt extends StatelessWidget {
  const _RingArt();

  @override
  Widget build(BuildContext context) => CustomPaint(painter: _RingPainter());
}

class _RingPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = size.shortestSide * 0.34;
    const colors = [OColors.pink, Color(0xFFCFD3E0), Color(0xFFCFD3E0), OColors.pink, Color(0xFFCFD3E0),
        OColors.yellow, Color(0xFFCFD3E0), OColors.pink, Color(0xFFCFD3E0), Color(0xFFCFD3E0)];
    for (var i = 0; i < colors.length; i++) {
      final a = i * 2 * math.pi / colors.length;
      canvas.drawCircle(c + Offset(r * math.cos(a), r * math.sin(a)), 4, Paint()..color = colors[i]);
    }
    canvas.drawCircle(c, size.shortestSide * 0.16, Paint()..color = OColors.surfaceContainerHigh);
    canvas.drawCircle(c, size.shortestSide * 0.07, Paint()..color = OColors.secondary);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
