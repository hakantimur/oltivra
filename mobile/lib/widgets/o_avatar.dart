import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/tokens.dart';

/// Curated avatar catalog mirror (backend `app/catalog/data.py`): original abstract motifs drawn as vectors,
/// never photos or uploads (spec §2.3). Unknown IDs fall back to a neutral motif.
class AvatarSpec {
  const AvatarSpec(this.motif, this.bg, this.fg, this.accent);

  final String motif;
  final Color bg;
  final Color fg;
  final Color accent;

  static const catalog = <String, AvatarSpec>{
    'av_001': AvatarSpec('scholar', Color(0xFFD5EFEA), Color(0xFF16B8A6), Color(0xFF0C4A43)),
    'av_002': AvatarSpec('crescent', Color(0xFFFFE3EC), Color(0xFFAF2759), Color(0xFFFFB1C3)),
    'av_003': AvatarSpec('quarter', Color(0xFFF7EEDC), Color(0xFFCE9D1D), Color(0xFF6B4F00)),
    'av_004': AvatarSpec('eye_diamond', Color(0xFFDDFBF4), Color(0xFF16B8A6), Color(0xFF1B2130)),
    'av_005': AvatarSpec('person', Color(0xFFE2E7FD), Color(0xFF1B2130), Color(0xFF636D7E)),
    'av_006': AvatarSpec('star', Color(0xFFFFF4DE), Color(0xFFF4BF40), Color(0xFF6B4F00)),
    'av_007': AvatarSpec('arch', Color(0xFFE9EDFF), Color(0xFF16B8A6), Color(0xFFF65F8E)),
    'av_008': AvatarSpec('stripes', Color(0xFFFFF0F5), Color(0xFFAF2759), Color(0xFFFFFFFF)),
    'av_009': AvatarSpec('orbit', Color(0xFFE2E7FD), Color(0xFF006B5F), Color(0xFF71F8E4)),
    'av_010': AvatarSpec('prism', Color(0xFFDDE2F7), Color(0xFF1B2130), Color(0xFFF65F8E)),
    'av_011': AvatarSpec('lever', Color(0xFFE8F8F5), Color(0xFF16B8A6), Color(0xFFF4BF40)),
    'av_012': AvatarSpec('octagon', Color(0xFFF1EDE4), Color(0xFF6B4F00), Color(0xFFFFC94A)),
  };

  static AvatarSpec of(String? id) =>
      catalog[id] ?? const AvatarSpec('person', OColors.surfaceContainer, OColors.inkSubtle, OColors.divider);
}

/// Frame colours mirror the cosmetic catalog; `frame_none` draws nothing.
const frameColors = <String, Color>{
  'frame_streak_5': Color(0xFFF65F8E),
  'frame_crown': Color(0xFFFFC94A),
  'frame_diamond': Color(0xFF50DBC8),
  'frame_legend': Color(0xFFAF2759),
  'frame_level_3': Color(0xFF16B8A6),
  'frame_level_5': Color(0xFF5B7CFA),
  'frame_level_10': Color(0xFF8E5CF6),
  'frame_level_20': Color(0xFFF28C28),
  'frame_level_30': Color(0xFF1B2130),
};

class OAvatar extends StatelessWidget {
  const OAvatar({super.key, required this.avatarId, this.size = 48, this.frameId, this.online = false, this.badge});

  final String? avatarId;
  final double size;
  final String? frameId;
  final bool online;
  final Widget? badge;

  @override
  Widget build(BuildContext context) {
    final spec = AvatarSpec.of(avatarId);
    final frame = frameColors[frameId];
    final ring = frame != null ? math.max(2.0, size * 0.06) : 0.0;
    return SizedBox.square(
      dimension: size,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Container(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: frame != null ? Border.all(color: frame, width: ring) : null,
            ),
            padding: EdgeInsets.all(frame != null ? ring * 0.6 : 0),
            child: ClipOval(child: CustomPaint(size: Size.square(size), painter: _MotifPainter(spec))),
          ),
          if (online)
            Positioned(
              right: 0,
              bottom: 0,
              child: Container(
                width: size * 0.26,
                height: size * 0.26,
                decoration: BoxDecoration(
                  color: OColors.turquoise,
                  shape: BoxShape.circle,
                  border: Border.all(color: OColors.white, width: 2),
                ),
              ),
            ),
          if (badge != null) Positioned(right: -2, bottom: -2, child: badge!),
        ],
      ),
    );
  }
}

class _MotifPainter extends CustomPainter {
  _MotifPainter(this.spec);

  final AvatarSpec spec;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final c = Offset(w / 2, w / 2);
    final fg = Paint()..color = spec.fg;
    final accent = Paint()..color = spec.accent;
    canvas.drawRect(Offset.zero & size, Paint()..color = spec.bg);
    switch (spec.motif) {
      case 'scholar':
        canvas.drawCircle(c.translate(0, -w * 0.08), w * 0.2, fg);
        canvas.drawRect(Rect.fromCenter(center: c.translate(0, -w * 0.3), width: w * 0.46, height: w * 0.08), accent);
        canvas.drawOval(Rect.fromCenter(center: c.translate(0, w * 0.34), width: w * 0.7, height: w * 0.4), fg);
      case 'crescent':
        canvas.drawCircle(c, w * 0.3, fg);
        canvas.drawCircle(c.translate(w * 0.12, -w * 0.08), w * 0.26, Paint()..color = spec.bg);
        canvas.drawCircle(c.translate(w * 0.18, w * 0.16), w * 0.06, accent);
      case 'quarter':
        canvas.drawArc(Rect.fromCircle(center: Offset(w * 0.2, w * 0.8), radius: w * 0.6), -math.pi / 2, math.pi / 2,
            true, fg);
        canvas.drawCircle(Offset(w * 0.68, w * 0.32), w * 0.12, accent);
      case 'eye_diamond':
        final path = Path()
          ..moveTo(w / 2, w * 0.18)
          ..lineTo(w * 0.82, w / 2)
          ..lineTo(w / 2, w * 0.82)
          ..lineTo(w * 0.18, w / 2)
          ..close();
        canvas.drawPath(path, fg);
        canvas.drawCircle(c, w * 0.11, accent);
      case 'star':
        canvas.drawPath(_star(c, w * 0.34, w * 0.15, 5), fg);
        canvas.drawCircle(c, w * 0.06, accent);
      case 'arch':
        canvas.drawRRect(
            RRect.fromRectAndCorners(Rect.fromLTWH(w * 0.24, w * 0.24, w * 0.52, w * 0.62),
                topLeft: Radius.circular(w * 0.26), topRight: Radius.circular(w * 0.26)),
            fg);
        canvas.drawCircle(c.translate(0, -w * 0.02), w * 0.09, accent);
      case 'stripes':
        for (var i = 0; i < 4; i++) {
          canvas.drawRect(Rect.fromLTWH(0, w * (0.14 + i * 0.2), w, w * 0.1), i.isEven ? fg : accent);
        }
      case 'orbit':
        canvas.drawCircle(c, w * 0.14, fg);
        canvas.drawOval(Rect.fromCenter(center: c, width: w * 0.8, height: w * 0.32),
            Paint()
              ..color = spec.fg
              ..style = PaintingStyle.stroke
              ..strokeWidth = w * 0.04);
        canvas.drawCircle(Offset(w * 0.86, w / 2), w * 0.06, accent);
      case 'prism':
        final path = Path()
          ..moveTo(w / 2, w * 0.18)
          ..lineTo(w * 0.82, w * 0.78)
          ..lineTo(w * 0.18, w * 0.78)
          ..close();
        canvas.drawPath(path, fg);
        canvas.drawRect(Rect.fromLTWH(w * 0.56, w * 0.46, w * 0.36, w * 0.06), accent);
      case 'lever':
        canvas.drawRRect(
            RRect.fromRectAndRadius(Rect.fromCenter(center: c, width: w * 0.64, height: w * 0.18),
                Radius.circular(w * 0.09)),
            fg);
        canvas.drawCircle(c.translate(w * 0.18, 0), w * 0.12, accent);
      case 'octagon':
        canvas.drawPath(_polygon(c, w * 0.34, 8), fg);
        canvas.drawPath(_polygon(c, w * 0.16, 8), accent);
      default: // person
        canvas.drawCircle(c.translate(0, -w * 0.1), w * 0.18, fg);
        canvas.drawOval(Rect.fromCenter(center: c.translate(0, w * 0.36), width: w * 0.66, height: w * 0.44), accent);
    }
  }

  Path _star(Offset c, double outer, double inner, int points) {
    final path = Path();
    for (var i = 0; i < points * 2; i++) {
      final r = i.isEven ? outer : inner;
      final a = -math.pi / 2 + i * math.pi / points;
      final p = c + Offset(math.cos(a) * r, math.sin(a) * r);
      i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    return path..close();
  }

  Path _polygon(Offset c, double r, int sides) {
    final path = Path();
    for (var i = 0; i < sides; i++) {
      final a = math.pi / sides + i * 2 * math.pi / sides;
      final p = c + Offset(math.cos(a) * r, math.sin(a) * r);
      i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    return path..close();
  }

  @override
  bool shouldRepaint(_MotifPainter old) => old.spec != spec;
}
