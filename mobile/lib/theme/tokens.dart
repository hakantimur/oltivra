// Oltivra design tokens, transcribed from docs/design/live_trivia_visual_foundation/DESIGN.md and the
// Stitch foundation brief. Semantic colours are used sparingly: turquoise = action, pink = competitive
// energy, yellow = reward/attention, green = correct only, coral = wrong only.
import 'package:flutter/material.dart';

abstract final class OColors {
  // Foundation palette.
  static const canvas = Color(0xFFFFFDF8);
  static const ink = Color(0xFF1B2130);
  static const inkSubtle = Color(0xFF636D7E);
  static const turquoise = Color(0xFF16B8A6);
  static const pink = Color(0xFFF65F8E);
  static const yellow = Color(0xFFFFC94A);
  static const success = Color(0xFF32B978);
  static const coral = Color(0xFFE95F64);
  static const mint = Color(0xFFE8F8F5);
  static const rose = Color(0xFFFFF0F5);
  static const sun = Color(0xFFFFF7D9);
  static const divider = Color(0xFFE9E5DE);
  static const white = Color(0xFFFFFFFF);

  // Stitch material roles used by the generated screens.
  static const primary = Color(0xFF006B5F);
  static const onPrimary = Color(0xFFFFFFFF);
  static const primaryContainer = Color(0xFF16B8A6);
  static const onPrimaryContainer = Color(0xFF00423B);
  static const secondary = Color(0xFFAF2759);
  static const secondaryContainer = Color(0xFFFF6695);
  static const secondaryFixed = Color(0xFFFFD9E0);
  static const tertiary = Color(0xFF795900);
  static const tertiaryContainer = Color(0xFFCE9D1D);
  static const tertiaryFixed = Color(0xFFFFDF9E);
  static const surfaceContainer = Color(0xFFE9EDFF);
  static const surfaceContainerHigh = Color(0xFFE2E7FD);
  static const onSurfaceVariant = Color(0xFF3C4947);
  static const outline = Color(0xFF6C7A77);
  static const outlineVariant = Color(0xFFBBCAC6);
  static const scrim = Color(0x661B2130);
}

abstract final class OSpace {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
  static const xxl = 32.0;
  static const margin = 20.0;
  static const gutter = 12.0;
}

abstract final class ORadius {
  static const sm = 8.0;
  static const card = 16.0;
  static const md = 24.0;
  static const lg = 32.0;
  static const pill = 999.0;
}

abstract final class OShadow {
  static const card = [BoxShadow(color: Color(0x0A1B2130), blurRadius: 6, offset: Offset(0, 2))];
  static const floating = [BoxShadow(color: Color(0x141B2130), blurRadius: 24, offset: Offset(0, 8))];
}

abstract final class ODuration {
  static const fast = Duration(milliseconds: 150);
  static const medium = Duration(milliseconds: 250);
  static const slow = Duration(milliseconds: 400);
}
