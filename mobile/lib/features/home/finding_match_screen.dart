import 'package:flutter/material.dart';

/// Placeholder until the home package screen is implemented.
class FindingMatchScreen extends StatelessWidget {
  const FindingMatchScreen({super.key, required this.mode, this.categoryId});

  final String mode;
  final String? categoryId;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('FindingMatchScreen')));
}
