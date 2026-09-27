import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/store/store_services.dart';

import '../l10n/strings.dart';

/// Bottom navigation with the five destinations from the design: Home, Play, Rankings, Social, Profile.
/// Entering the signed-in shell also starts the UMP consent flow once, before any ad is requested.
class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(adConsentProvider);
    });
  }

  @override
  Widget build(BuildContext context) {
    final shell = widget.shell;
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
