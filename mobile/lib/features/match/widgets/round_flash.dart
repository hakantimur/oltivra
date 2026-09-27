import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../../../theme/tokens.dart';

/// Which round result a [RoundFlash] celebrates.
enum FlashKind {
  /// Another player answered first: "{name} got it +N".
  otherWon,

  /// This player answered first: confetti and "You got it! +N".
  youWon,

  /// This player's own wrong answer, shown only to them: "Wrong −6".
  youWrong,
}

class FlashContent {
  const FlashContent({required this.kind, required this.title, this.points});

  final FlashKind kind;
  final String title;
  final String? points;
}

/// Centred round-result card over the question (playtest 2026-09-27). It plays once per [eventKey]: scales in,
/// holds for [holdMs] and fades out, so a result is readable without covering the answers for long. Input
/// passes through; the card is purely informative.
class RoundFlash extends StatefulWidget {
  const RoundFlash({super.key, required this.eventKey, required this.content, this.holdMs = 2200});

  /// Identifies the event (e.g. round id + kind). A new key replays the animation; null hides the card.
  final String? eventKey;
  final FlashContent? content;
  final int holdMs;

  @override
  State<RoundFlash> createState() => _RoundFlashState();
}

class _RoundFlashState extends State<RoundFlash> with SingleTickerProviderStateMixin {
  static const _inMs = 260;
  static const _outMs = 320;

  late final AnimationController _controller = AnimationController(vsync: this);
  String? _playedKey;

  int get _totalMs => _inMs + widget.holdMs + _outMs;

  @override
  void initState() {
    super.initState();
    _maybePlay();
  }

  @override
  void didUpdateWidget(RoundFlash oldWidget) {
    super.didUpdateWidget(oldWidget);
    _maybePlay();
  }

  void _maybePlay() {
    final key = widget.eventKey;
    if (key == null || widget.content == null || key == _playedKey) return;
    _playedKey = key;
    _controller.duration = Duration(milliseconds: _totalMs);
    _controller.forward(from: 0);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final content = widget.content;
    if (content == null) return const SizedBox.shrink();
    return IgnorePointer(
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          final t = _controller.value * _totalMs;
          if (!_controller.isAnimating && (_controller.value == 0 || _controller.value == 1)) {
            return const SizedBox.shrink();
          }
          final double opacity;
          final double scale;
          if (t < _inMs) {
            final p = Curves.easeOutBack.transform(t / _inMs);
            opacity = (t / _inMs).clamp(0.0, 1.0);
            scale = 0.7 + 0.3 * p;
          } else if (t < _inMs + widget.holdMs) {
            opacity = 1;
            scale = 1;
          } else {
            final p = ((t - _inMs - widget.holdMs) / _outMs).clamp(0.0, 1.0);
            opacity = 1 - p;
            scale = 1 - 0.08 * p;
          }
          return Stack(
            children: [
              if (content.kind == FlashKind.youWon)
                Positioned.fill(child: CustomPaint(painter: _ConfettiPainter(_controller.value))),
              Center(
                child: Opacity(
                  opacity: opacity,
                  child: Transform.scale(
                    scale: scale,
                    child: _FlashCard(content: content),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _FlashCard extends StatelessWidget {
  const _FlashCard({required this.content});

  final FlashContent content;

  @override
  Widget build(BuildContext context) {
    final (emoji, background, foreground) = switch (content.kind) {
      FlashKind.youWon => ('🎉', OColors.success, OColors.white),
      FlashKind.otherWon => ('🎉', OColors.white, OColors.ink),
      FlashKind.youWrong => ('😔', OColors.coral, OColors.white),
    };
    return Semantics(
      liveRegion: true,
      label: [content.title, ?content.points].join(' '),
      excludeSemantics: true,
      child: Container(
        key: ValueKey('round-flash-${content.kind.name}'),
        constraints: const BoxConstraints(maxWidth: 300),
        padding: const EdgeInsets.symmetric(horizontal: OSpace.xl, vertical: OSpace.lg),
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(ORadius.lg),
          boxShadow: OShadow.floating,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(emoji, style: const TextStyle(fontSize: 44)),
            const SizedBox(height: OSpace.sm),
            Text(
              content.title,
              textAlign: TextAlign.center,
              style: OText.headlineMd.copyWith(color: foreground),
            ),
            if (content.points != null) ...[
              const SizedBox(height: OSpace.xs),
              Text(content.points!, style: OText.tabular(OText.headlineLg).copyWith(color: foreground)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Light confetti burst for the player's own win: fixed pseudo-random pieces falling with a little sway.
class _ConfettiPainter extends CustomPainter {
  _ConfettiPainter(this.progress);

  final double progress;

  static const _colors = [OColors.turquoise, OColors.pink, OColors.yellow, OColors.success, OColors.coral];
  static final _pieces = List.generate(36, (i) {
    final r = math.Random(i * 7919);
    return (
      x: r.nextDouble(),
      delay: r.nextDouble() * 0.25,
      speed: 0.7 + r.nextDouble() * 0.6,
      sway: r.nextDouble() * 2 * math.pi,
      color: _colors[i % _colors.length],
      size: 5 + r.nextDouble() * 5,
    );
  });

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint();
    for (final p in _pieces) {
      final t = ((progress - p.delay) / (1 - p.delay)).clamp(0.0, 1.0);
      if (t <= 0) continue;
      final y = -20 + t * p.speed * (size.height + 40);
      final x = p.x * size.width + math.sin(p.sway + t * 8) * 14;
      paint.color = p.color.withValues(alpha: t > 0.8 ? (1 - t) * 5 : 1);
      canvas.save();
      canvas.translate(x, y);
      canvas.rotate(p.sway + t * 6);
      canvas.drawRect(Rect.fromCenter(center: Offset.zero, width: p.size, height: p.size * 0.6), paint);
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(_ConfettiPainter old) => old.progress != progress;
}
