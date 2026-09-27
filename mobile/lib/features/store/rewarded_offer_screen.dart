import 'package:flutter/material.dart';

/// Placeholder until the store package screen is implemented.
class RewardedOfferScreen extends StatelessWidget {
  const RewardedOfferScreen({super.key, required this.matchId});

  final String matchId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('RewardedOfferScreen')));
}
