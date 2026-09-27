import 'package:flutter/material.dart';

/// Placeholder until the match package screen is implemented.
class MatchScreen extends StatelessWidget {
  const MatchScreen({super.key, required this.matchId});

  final String matchId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('MatchScreen')));
}
