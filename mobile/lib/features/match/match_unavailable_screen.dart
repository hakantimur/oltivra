import 'package:flutter/material.dart';

/// Placeholder until the match package screen is implemented.
class MatchUnavailableScreen extends StatelessWidget {
  const MatchUnavailableScreen({super.key, this.matchId});

  final String? matchId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('MatchUnavailableScreen')));
}
