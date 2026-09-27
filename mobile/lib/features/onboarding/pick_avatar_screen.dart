import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'widgets.dart';

/// P01 · Curated avatar selection (spec §2.3): vector motifs from `/v1/avatars`, no uploads. With
/// `editing: true` (from settings) the screen pops after saving instead of relying on the onboarding redirect.
class PickAvatarScreen extends ConsumerStatefulWidget {
  const PickAvatarScreen({super.key, this.editing = false});

  final bool editing;

  @override
  ConsumerState<PickAvatarScreen> createState() => _PickAvatarScreenState();
}

class _PickAvatarScreenState extends ConsumerState<PickAvatarScreen> {
  String? _selected;
  bool _saving = false;

  static List<Map<String, dynamic>> _avatars(Map<String, dynamic> catalog) {
    final list =
        ((catalog['avatars'] as List?) ?? const [])
            .whereType<Map>()
            .map((a) => a.cast<String, dynamic>())
            .where((a) => a['active'] != false && a['id'] is String)
            .toList()
          ..sort((a, b) => ((a['sort'] as num?) ?? 0).compareTo((b['sort'] as num?) ?? 0));
    return list;
  }

  Future<void> _save() async {
    final id = _selected;
    if (id == null) return;
    setState(() => _saving = true);
    try {
      final res = await ref.read(apiClientProvider).patch('/v1/profile/avatar', {'avatar_id': id});
      final profile = (res['profile'] as Map?)?.cast<String, dynamic>();
      if (profile != null) ref.read(sessionProvider.notifier).applyProfile(profile);
      if (mounted && widget.editing && context.canPop()) context.pop();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final catalog = ref.watch(catalogProvider('avatars'));
    final current = ref.watch(sessionProvider).value?.avatarId;
    final avatars = catalog.hasValue ? _avatars(catalog.value!) : const <Map<String, dynamic>>[];
    final selected = _selected ?? (avatars.any((a) => a['id'] == current) ? current : null);

    final Widget grid;
    if (catalog.hasError && !catalog.hasValue) {
      grid = OErrorView(error: catalog.error!, onRetry: () => ref.invalidate(catalogProvider('avatars')));
    } else if (!catalog.hasValue) {
      grid = const OLoading();
    } else if (avatars.isEmpty) {
      grid = OEmptyState(icon: Icons.face_retouching_natural, title: context.t('onboarding.avatar.empty'));
    } else {
      grid = GridView.builder(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        itemCount: avatars.length,
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 3,
          mainAxisSpacing: OSpace.gutter,
          crossAxisSpacing: OSpace.gutter,
        ),
        itemBuilder: (context, i) {
          final id = avatars[i]['id'] as String;
          return _AvatarTile(
            key: Key('avatar-$id'),
            avatarId: id,
            index: i + 1,
            selected: id == selected,
            onTap: _saving ? null : () => setState(() => _selected = id),
          );
        },
      );
    }

    return Scaffold(
      appBar: onboardingAppBar(
        context,
        title: context.t('onboarding.avatar.title'),
        onBack: widget.editing && context.canPop() ? () => context.pop() : null,
      ),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
          children: [
            if (!widget.editing) ...[const OnboardingStepBar(step: 5), const SizedBox(height: OSpace.lg)],
            Center(
              child: _ScaleDown(
                OPill(
                  context.t('onboarding.avatar.badge'),
                  icon: Icons.auto_awesome_rounded,
                  background: OColors.surfaceContainer,
                  foreground: OColors.primary,
                ),
              ),
            ),
            const SizedBox(height: OSpace.md),
            Semantics(
              header: true,
              child: Text(
                context.t('onboarding.avatar.heading'),
                textAlign: TextAlign.center,
                style: OText.headlineXlMobile,
              ),
            ),
            const SizedBox(height: OSpace.sm),
            Text(
              context.t('onboarding.avatar.body'),
              textAlign: TextAlign.center,
              style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant),
            ),
            const SizedBox(height: OSpace.xl),
            grid,
            const SizedBox(height: OSpace.xl),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.info_outline_rounded, size: 18, color: OColors.primary),
                const SizedBox(width: OSpace.xs),
                Flexible(
                  child: Text(
                    context.t('onboarding.avatar.helper'),
                    style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      // Pinned above the system gesture area so the primary action is always reachable.
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.lg),
        child: OButton(
          key: const Key('avatar-save'),
          label: context.t(widget.editing ? 'onboarding.avatar.save' : 'onboarding.avatar.start'),
          trailingIcon: Icons.arrow_forward_rounded,
          loading: _saving,
          onPressed: selected == null
              ? null
              : () {
                  _selected = selected;
                  _save();
                },
        ),
      ),
    );
  }
}

class _AvatarTile extends StatelessWidget {
  const _AvatarTile({
    super.key,
    required this.avatarId,
    required this.index,
    required this.selected,
    required this.onTap,
  });

  final String avatarId;
  final int index;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    selected: selected,
    label: context.t('onboarding.avatar.option', {'n': index}),
    excludeSemantics: true,
    child: Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned.fill(
          child: AnimatedContainer(
            duration: ODuration.fast,
            decoration: BoxDecoration(
              color: OColors.white,
              borderRadius: BorderRadius.circular(ORadius.md),
              boxShadow: selected ? OShadow.floating : OShadow.card,
              border: Border.all(color: selected ? OColors.turquoise : Colors.transparent, width: 2.5),
            ),
            child: Material(
              type: MaterialType.transparency,
              child: InkWell(
                borderRadius: BorderRadius.circular(ORadius.md),
                onTap: onTap,
                child: Padding(
                  padding: const EdgeInsets.all(OSpace.sm),
                  child: LayoutBuilder(
                    builder: (context, c) => Center(
                      child: OAvatar(avatarId: avatarId, size: c.biggest.shortestSide),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
        if (selected)
          Positioned(
            top: -6,
            right: -6,
            child: Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                color: OColors.turquoise,
                shape: BoxShape.circle,
                border: Border.all(color: OColors.white, width: 2),
              ),
              child: const Icon(Icons.check_rounded, size: 16, color: OColors.white),
            ),
          ),
      ],
    ),
  );
}

/// Keeps fixed-layout pills inside the available width on narrow screens / large text.
class _ScaleDown extends StatelessWidget {
  const _ScaleDown(this.child);

  final Widget child;

  @override
  Widget build(BuildContext context) => FittedBox(fit: BoxFit.scaleDown, child: child);
}
