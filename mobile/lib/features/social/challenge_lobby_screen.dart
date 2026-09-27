import 'package:flutter/material.dart';

/// Placeholder until the social package screen is implemented.
class ChallengeLobbyScreen extends StatelessWidget {
  const ChallengeLobbyScreen({super.key, this.partyId});

  final String? partyId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('ChallengeLobbyScreen')));
}
