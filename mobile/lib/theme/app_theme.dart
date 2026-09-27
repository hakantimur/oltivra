import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'tokens.dart';

/// Typography scale from the design foundation (Plus Jakarta Sans, tabular figures for live numbers).
abstract final class OText {
  static TextStyle _base(double size, double height, FontWeight weight, [double tracking = 0]) =>
      GoogleFonts.plusJakartaSans(
        fontSize: size,
        height: height / size,
        fontWeight: weight,
        letterSpacing: tracking * size,
        color: OColors.ink,
      );

  static final headlineXl = _base(34, 40, FontWeight.w800, -0.03);
  static final headlineXlMobile = _base(28, 34, FontWeight.w800, -0.025);
  static final headlineLg = _base(24, 30, FontWeight.w700, -0.02);
  static final headlineMd = _base(20, 26, FontWeight.w700, -0.015);
  static final headlineSm = _base(18, 24, FontWeight.w700);
  static final bodyLg = _base(17, 24, FontWeight.w500);
  static final bodyMd = _base(15, 22, FontWeight.w500);
  static final bodySm = _base(13, 18, FontWeight.w500);
  static final labelLg = _base(15, 20, FontWeight.w700, 0.01);
  static final labelMd = _base(13, 16, FontWeight.w700, 0.02);
  static final labelSm = _base(11, 14, FontWeight.w800, 0.04);
  static final displayStat = _base(44, 48, FontWeight.w800, -0.04)
      .copyWith(fontFeatures: const [FontFeature.tabularFigures()]);
  static TextStyle tabular(TextStyle style) =>
      style.copyWith(fontFeatures: const [FontFeature.tabularFigures()]);
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: OColors.turquoise,
    brightness: Brightness.light,
  ).copyWith(
    primary: OColors.primary,
    onPrimary: OColors.onPrimary,
    primaryContainer: OColors.primaryContainer,
    onPrimaryContainer: OColors.onPrimaryContainer,
    secondary: OColors.secondary,
    secondaryContainer: OColors.secondaryContainer,
    tertiary: OColors.tertiary,
    tertiaryContainer: OColors.tertiaryContainer,
    error: OColors.coral,
    surface: OColors.canvas,
    onSurface: OColors.ink,
    onSurfaceVariant: OColors.onSurfaceVariant,
    outline: OColors.outline,
    outlineVariant: OColors.divider,
  );
  final text = TextTheme(
    displaySmall: OText.headlineXl,
    headlineLarge: OText.headlineXlMobile,
    headlineMedium: OText.headlineLg,
    headlineSmall: OText.headlineMd,
    titleLarge: OText.headlineSm,
    titleMedium: OText.labelLg,
    bodyLarge: OText.bodyLg,
    bodyMedium: OText.bodyMd,
    bodySmall: OText.bodySm,
    labelLarge: OText.labelLg,
    labelMedium: OText.labelMd,
    labelSmall: OText.labelSm,
  );
  final pill = RoundedRectangleBorder(borderRadius: BorderRadius.circular(ORadius.pill));
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: OColors.canvas,
    textTheme: text,
    splashFactory: InkSparkle.splashFactory,
    appBarTheme: AppBarTheme(
      backgroundColor: OColors.canvas,
      foregroundColor: OColors.ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: OText.headlineMd,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: OColors.turquoise,
        foregroundColor: OColors.white,
        disabledBackgroundColor: OColors.divider,
        disabledForegroundColor: OColors.inkSubtle,
        minimumSize: const Size.fromHeight(54),
        shape: pill,
        textStyle: OText.labelLg,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: OColors.ink,
        minimumSize: const Size.fromHeight(54),
        side: const BorderSide(color: OColors.divider),
        backgroundColor: OColors.white,
        shape: pill,
        textStyle: OText.labelLg,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: OColors.ink,
        minimumSize: const Size(48, 48),
        textStyle: OText.labelLg,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: OColors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.lg),
      hintStyle: OText.bodyMd.copyWith(color: OColors.inkSubtle),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(ORadius.card),
        borderSide: const BorderSide(color: OColors.divider),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(ORadius.card),
        borderSide: const BorderSide(color: OColors.divider),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(ORadius.card),
        borderSide: const BorderSide(color: OColors.turquoise, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(ORadius.card),
        borderSide: const BorderSide(color: OColors.coral, width: 2),
      ),
    ),
    checkboxTheme: CheckboxThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      side: const BorderSide(color: OColors.outline, width: 1.5),
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? OColors.turquoise : OColors.white,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: OColors.white,
      indicatorColor: OColors.mint,
      height: 72,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => OText.labelSm.copyWith(
          color: states.contains(WidgetState.selected) ? OColors.primary : OColors.inkSubtle,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected) ? OColors.primary : OColors.inkSubtle,
        ),
      ),
    ),
    dividerTheme: const DividerThemeData(color: OColors.divider, thickness: 1, space: 1),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: OColors.ink,
      contentTextStyle: OText.bodyMd.copyWith(color: OColors.white),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(ORadius.card)),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: OColors.canvas,
      showDragHandle: true,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(ORadius.md))),
    ),
  );
}
