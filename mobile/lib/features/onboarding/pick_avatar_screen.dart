import 'package:flutter/material.dart';

/// Placeholder until the onboarding package screen is implemented.
class PickAvatarScreen extends StatelessWidget {
  const PickAvatarScreen({super.key, this.editing = false});

  final bool editing;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('PickAvatarScreen')));
}
