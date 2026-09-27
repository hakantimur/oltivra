import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';

/// Total steps of the first-run setup shown in the step bar: age → legal → sign in → name → avatar.
const onboardingTotalSteps = 5;

/// Segmented progress bar from the P01 designs ("Step 1 of 5 · Account setup").
class OnboardingStepBar extends StatelessWidget {
  const OnboardingStepBar({super.key, required this.step, this.total = onboardingTotalSteps});

  final int step;
  final int total;

  @override
  Widget build(BuildContext context) => Semantics(
        label: context.t('onboarding.progress_label'),
        value: context.t('onboarding.step', {'n': step, 'total': total}),
        child: ExcludeSemantics(
          child: Row(
            children: [
              for (var i = 1; i <= total; i++) ...[
                if (i > 1) const SizedBox(width: OSpace.sm),
                Expanded(
                  child: AnimatedContainer(
                    duration: ODuration.medium,
                    height: 6,
                    decoration: BoxDecoration(
                      color: i < step
                          ? OColors.turquoise
                          : i == step
                              ? OColors.primary
                              : OColors.surfaceContainerHigh,
                      borderRadius: BorderRadius.circular(ORadius.pill),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      );
}

/// Caption under the primary action ("Step 2 of 5 · Account setup").
class OnboardingStepCaption extends StatelessWidget {
  const OnboardingStepCaption({super.key, required this.step, this.total = onboardingTotalSteps});

  final int step;
  final int total;

  @override
  Widget build(BuildContext context) => Text(
        context.t('onboarding.step', {'n': step, 'total': total}),
        textAlign: TextAlign.center,
        style: OText.bodySm.copyWith(color: OColors.inkSubtle),
      );
}

/// Onboarding app bar: centred title, optional back action, no profile chip (there is no profile yet).
PreferredSizeWidget onboardingAppBar(BuildContext context, {required String title, VoidCallback? onBack,
    IconData backIcon = Icons.arrow_back_rounded}) =>
    AppBar(
      automaticallyImplyLeading: false,
      centerTitle: true,
      title: Text(title, style: OText.headlineSm),
      leading: onBack == null
          ? null
          : IconButton(
              tooltip: backIcon == Icons.close_rounded
                  ? context.t('action.close')
                  : context.t('action.back'),
              icon: Icon(backIcon),
              onPressed: onBack,
            ),
    );

/// Large tappable card with a rounded check box (age declaration, legal acceptance).
class OCheckTile extends StatelessWidget {
  const OCheckTile({super.key, required this.value, required this.onChanged, required this.title, this.subtitle,
      this.titleStyle});

  final bool value;
  final ValueChanged<bool> onChanged;
  final String title;
  final String? subtitle;
  final TextStyle? titleStyle;

  @override
  Widget build(BuildContext context) => Semantics(
        checked: value,
        button: true,
        label: title,
        excludeSemantics: true,
        child: AnimatedContainer(
          duration: ODuration.fast,
          decoration: BoxDecoration(
            color: value ? OColors.mint : OColors.white,
            borderRadius: BorderRadius.circular(ORadius.card),
            boxShadow: OShadow.card,
            border: Border.all(color: value ? OColors.turquoise : Colors.transparent, width: 1.5),
          ),
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              borderRadius: BorderRadius.circular(ORadius.card),
              onTap: () => onChanged(!value),
              child: Padding(
                padding: const EdgeInsets.all(OSpace.lg),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(padding: const EdgeInsets.only(top: 2), child: OCheckBox(value: value)),
                    const SizedBox(width: OSpace.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(title, style: titleStyle ?? OText.headlineSm),
                          if (subtitle != null) ...[
                            const SizedBox(height: OSpace.xs),
                            Text(subtitle!, style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
}

/// The design's rounded-square check box (visual only; the parent handles taps and semantics).
class OCheckBox extends StatelessWidget {
  const OCheckBox({super.key, required this.value});

  final bool value;

  @override
  Widget build(BuildContext context) => AnimatedContainer(
        duration: ODuration.fast,
        width: 24,
        height: 24,
        decoration: BoxDecoration(
          color: value ? OColors.turquoise : OColors.surfaceContainerHigh,
          borderRadius: BorderRadius.circular(ORadius.sm),
        ),
        child: value ? const Icon(Icons.check_rounded, size: 18, color: OColors.white) : null,
      );
}

/// Circular hero glyph with an optional small badge (terms shield, sign-in bolt).
class OnboardingHeroIcon extends StatelessWidget {
  const OnboardingHeroIcon({super.key, required this.icon, this.badgeIcon, this.gradient = false,
      this.badgeColor = OColors.turquoise});

  final IconData icon;
  final IconData? badgeIcon;
  final bool gradient;
  final Color badgeColor;

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: 116,
        child: Stack(
          clipBehavior: Clip.none,
          alignment: Alignment.center,
          children: [
            Container(
              width: 100,
              height: 100,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: gradient
                    ? const LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [OColors.turquoise, OColors.primary],
                      )
                    : const LinearGradient(colors: [OColors.surfaceContainer, OColors.mint]),
                boxShadow: gradient
                    ? [BoxShadow(color: OColors.turquoise.withValues(alpha: 0.35), blurRadius: 24)]
                    : null,
              ),
              child: Icon(icon, size: 44, color: gradient ? OColors.white : OColors.primary),
            ),
            if (badgeIcon != null)
              Positioned(
                right: 6,
                bottom: gradient ? null : 6,
                top: gradient ? 6 : null,
                child: Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: badgeColor,
                    shape: BoxShape.circle,
                    border: Border.all(color: OColors.white, width: 2),
                  ),
                  child: Icon(badgeIcon, size: 18, color: OColors.white),
                ),
              ),
          ],
        ),
      );
}

/// Abstract brand accent from the launch design: two overlapping capsules and a sun dot. Decorative only.
class OltivraMark extends StatelessWidget {
  const OltivraMark({super.key, this.size = 170});

  final double size;

  @override
  Widget build(BuildContext context) =>
      ExcludeSemantics(child: CustomPaint(size: Size.square(size), painter: _MarkPainter()));
}

class _MarkPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    RRect capsule(double cx, double cy, double len, double thick) => RRect.fromRectAndRadius(
        Rect.fromCenter(center: Offset(cx, cy), width: thick, height: len), Radius.circular(thick / 2));

    void turn(double angle, Offset pivot) => canvas
      ..translate(pivot.dx, pivot.dy)
      ..rotate(angle)
      ..translate(-pivot.dx, -pivot.dy);

    void rotated(double angle, Offset pivot, void Function() draw) {
      canvas.save();
      turn(angle, pivot);
      draw();
      canvas.restore();
    }

    final teal = Paint()..color = OColors.turquoise;
    final pink = Paint()..color = OColors.pink.withValues(alpha: 0.92);
    final pinkPivot = Offset(w * 0.6, w * 0.47);
    final tealPivot = Offset(w * 0.47, w * 0.5);
    final pinkShape = capsule(pinkPivot.dx, pinkPivot.dy, w * 0.62, w * 0.3);
    final tealShape = capsule(tealPivot.dx, tealPivot.dy, w * 0.9, w * 0.3);

    rotated(math.pi / 4, pinkPivot, () => canvas.drawRRect(pinkShape, pink));
    rotated(-math.pi / 12, tealPivot, () => canvas.drawRRect(tealShape, teal));

    // Overlap tinted with ink for depth.
    canvas.save();
    turn(math.pi / 4, pinkPivot);
    canvas.clipRRect(pinkShape);
    turn(-math.pi / 4, pinkPivot);
    rotated(-math.pi / 12, tealPivot, () => canvas.drawRRect(tealShape, Paint()..color = const Color(0xFF174F5F)));
    canvas.restore();

    canvas.drawCircle(Offset(w * 0.52, w * 0.43), w * 0.06, Paint()..color = const Color(0xFFE9EDF5));
    canvas.drawCircle(Offset(w * 0.3, w * 0.73), w * 0.14, Paint()..color = const Color(0xFFF4BF40));
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// Opens a legal document summary in a bottom sheet (the backend does not serve legal pages yet).
Future<void> showLegalSheet(BuildContext context, {required String title, required String body, String? version}) =>
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      backgroundColor: OColors.canvas,
      builder: (context) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        maxChildSize: 0.92,
        builder: (context, controller) => ListView(
          controller: controller,
          padding: const EdgeInsets.fromLTRB(OSpace.margin, 0, OSpace.margin, OSpace.xxl),
          children: [
            Text(title, style: OText.headlineLg),
            if (version != null) ...[
              const SizedBox(height: OSpace.xs),
              Text(context.t('onboarding.terms.version', {'v': version}),
                  style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            ],
            const SizedBox(height: OSpace.lg),
            Text(body, style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
          ],
        ),
      ),
    );
