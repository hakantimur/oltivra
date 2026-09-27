import 'package:flutter/material.dart';

/// Placeholder until the settings package screen is implemented.
class ReportPlayerScreen extends StatelessWidget {
  const ReportPlayerScreen({super.key, required this.publicId, this.matchId});

  final String publicId;
  final String? matchId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('ReportPlayerScreen')));
}
