import 'package:flutter/material.dart';

/// Placeholder until the onboarding package screen is implemented.
class ChooseNameScreen extends StatelessWidget {
  const ChooseNameScreen({super.key, this.rename = false});

  final bool rename;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('ChooseNameScreen')));
}
