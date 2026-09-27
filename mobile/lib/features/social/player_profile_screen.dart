import 'package:flutter/material.dart';

/// Placeholder until the social package screen is implemented.
class PlayerProfileScreen extends StatelessWidget {
  const PlayerProfileScreen({super.key, required this.publicId});

  final String publicId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('PlayerProfileScreen')));
}
