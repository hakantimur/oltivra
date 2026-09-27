import 'package:flutter/material.dart';

/// Placeholder until the social package screen is implemented.
class IncomingChallengeScreen extends StatelessWidget {
  const IncomingChallengeScreen({super.key, required this.token});

  final String token;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('IncomingChallengeScreen')));
}
