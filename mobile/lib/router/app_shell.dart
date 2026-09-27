import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../l10n/strings.dart';

/// Bottom navigation with the five destinations from the design: Home, Play, Rankings, Social, Profile.
class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  @override
  Widget build(BuildContext context) {
    final items = [
      (Icons.home_outlined, Icons.home_rounded, 'nav.home'),
      (Icons.sports_esports_outlined, Icons.sports_esports_rounded, 'nav.play'),
      (Icons.emoji_events_outlined, Icons.emoji_events_rounded, 'nav.rankings'),
      (Icons.group_outlined, Icons.group_rounded, 'nav.social'),
      (Icons.person_outline_rounded, Icons.person_rounded, 'nav.profile'),
    ];
    return Scaffold(
      body: shell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: shell.currentIndex,
        onDestinationSelected: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
        destinations: [
          for (final (icon, selected, key) in items)
            NavigationDestination(icon: Icon(icon), selectedIcon: Icon(selected), label: context.t(key)),
        ],
      ),
    );
  }
}
