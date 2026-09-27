import 'package:flutter/material.dart';

/// Placeholder until the home package screen is implemented.
class MatchReadyScreen extends StatelessWidget {
  const MatchReadyScreen({super.key, required this.matchId});

  final String matchId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('MatchReadyScreen')));
}
