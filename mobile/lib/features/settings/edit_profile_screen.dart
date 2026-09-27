import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'settings_widgets.dart';

enum _Availability { idle, checking, available, unavailable }

/// P07 · Edit profile: curated avatar (no uploads), owned frame preview, and username change with the
/// server's 30-day cooldown (`username_change_available_at_ms`) and live availability check.
class EditProfileScreen extends ConsumerStatefulWidget {
  const EditProfileScreen({super.key});

  @override
  ConsumerState<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends ConsumerState<EditProfileScreen> {
  final _name = TextEditingController();
  Timer? _debounce;
  _Availability _availability = _Availability.idle;
  String? _availabilityReason;
  String? _avatarId;
  String? _frameId;
  bool _saving = false;
  bool _showAvatars = false;
  bool _initialised = false;

  @override
  void dispose() {
    _debounce?.cancel();
    _name.dispose();
    super.dispose();
  }

  void _init(Json profile) {
    if (_initialised) return;
    _initialised = true;
    _name.text = (profile['username_display'] as String?) ?? '';
    _avatarId = profile['avatar_id'] as String?;
    _frameId = (profile['frame_id'] as String?) ?? 'frame_none';
  }

  String get _currentName => ref.read(sessionProvider).value?.username ?? '';

  bool get _nameChanged {
    final value = _name.text.trim();
    return value.isNotEmpty && value.toLowerCase() != _currentName.toLowerCase();
  }

  void _onNameChanged(String value) {
    _debounce?.cancel();
    if (!_nameChanged) {
      setState(() => _availability = _Availability.idle);
      return;
    }
    setState(() => _availability = _Availability.checking);
    _debounce = Timer(const Duration(milliseconds: 450), () => _check(value.trim()));
  }

  Future<void> _check(String name) async {
    try {
      final res = await ref.read(apiClientProvider).get('/v1/usernames/availability', query: {'username': name});
      if (!mounted || _name.text.trim() != name) return;
      setState(() {
        _availability = res['available'] == true ? _Availability.available : _Availability.unavailable;
        _availabilityReason = res['reason'] as String?;
      });
    } catch (e) {
      if (mounted) setState(() => _availability = _Availability.idle);
    }
  }

  Future<void> _save(Json profile, bool nameLocked) async {
    final api = ref.read(apiClientProvider);
    final session = ref.read(sessionProvider.notifier);
    setState(() => _saving = true);
    var changed = false;
    try {
      if (_avatarId != null && _avatarId != profile['avatar_id']) {
        final res = await api.patch('/v1/profile/avatar', {'avatar_id': _avatarId});
        session.applyProfile((res['profile'] as Map).cast<String, dynamic>());
        changed = true;
      }
      if (_frameId != null && _frameId != (profile['frame_id'] ?? 'frame_none')) {
        final res = await api.patch('/v1/profile/cosmetics', {'frame_id': _frameId});
        session.applyProfile((res['profile'] as Map).cast<String, dynamic>());
        changed = true;
      }
      if (!nameLocked && _nameChanged) {
        final res = await api.post('/v1/profile/username/change', {'username': _name.text.trim()});
        session.applyProfile((res['profile'] as Map).cast<String, dynamic>());
        changed = true;
      }
      if (!mounted) return;
      showMessage(context, context.t(changed ? 'settings.profile.saved' : 'settings.profile.nothing'));
      if (changed && context.canPop()) context.pop();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider).value;
    final profile = session?.profile;
    if (profile == null) {
      return Scaffold(appBar: AppBar(title: Text(context.t('settings.edit_profile'))), body: const OLoading());
    }
    _init(profile);
    final now = ref.read(serverClockProvider).nowMs();
    final availableAt = (profile['username_change_available_at_ms'] as num?)?.toInt();
    final nameLocked = availableAt != null && availableAt > now && !session!.renameRequired;
    final frames = ((profile['frame_ids'] as List?) ?? const ['frame_none']).cast<String>();
    final dirty = (_avatarId != null && _avatarId != profile['avatar_id']) ||
        (_frameId != null && _frameId != (profile['frame_id'] ?? 'frame_none')) ||
        (!nameLocked && _nameChanged && _availability == _Availability.available);
    final blockedByName = !nameLocked && _nameChanged && _availability != _Availability.available;

    return OPage(
      title: context.t('settings.edit_profile'),
      bottom: OButton(
        key: const ValueKey('profile_save'),
        label: context.t('settings.profile.save'),
        icon: Icons.check_rounded,
        loading: _saving,
        onPressed: dirty && !blockedByName ? () => _save(profile, nameLocked) : null,
      ),
      children: [
        const SizedBox(height: OSpace.md),
        Center(
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              OAvatar(avatarId: _avatarId, frameId: _frameId, size: 128),
              Positioned(
                right: -4,
                bottom: -4,
                child: OCircleButton(
                  icon: Icons.edit_rounded,
                  color: OColors.primary,
                  tooltip: context.t('settings.profile.change_avatar'),
                  onPressed: () => setState(() => _showAvatars = !_showAvatars),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: OSpace.md),
        Center(
          child: TextButton.icon(
            onPressed: () => setState(() => _showAvatars = !_showAvatars),
            icon: const Icon(Icons.palette_outlined),
            label: Text(context.t('settings.profile.change_avatar')),
          ),
        ),
        Center(
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.verified_user_outlined, size: 16, color: OColors.primary),
              const SizedBox(width: OSpace.xs),
              Text(context.t('settings.profile.curated'), style: OText.labelMd.copyWith(color: OColors.onSurfaceVariant)),
            ],
          ),
        ),
        if (_showAvatars) ...[
          const SizedBox(height: OSpace.lg),
          _AvatarGrid(selected: _avatarId, onSelect: (id) => setState(() => _avatarId = id)),
        ],
        if (frames.length > 1) ...[
          SettingsCaption(context.t('settings.profile.frame')),
          _FramePicker(frames: frames, selected: _frameId, onSelect: (id) => setState(() => _frameId = id)),
        ],
        SettingsCaption(context.t('settings.profile.username')),
        OCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(child: Text(context.t('settings.profile.username'), style: OText.labelLg)),
                  _availabilityChip(context),
                ],
              ),
              const SizedBox(height: OSpace.md),
              TextField(
                key: const ValueKey('profile_username'),
                controller: _name,
                enabled: !nameLocked && !_saving,
                maxLength: 16,
                autocorrect: false,
                onChanged: _onNameChanged,
                decoration: InputDecoration(
                  counterText: '',
                  suffixIcon: const Icon(Icons.alternate_email_rounded),
                  hintText: context.t('settings.profile.username.hint'),
                ),
              ),
              const SizedBox(height: OSpace.md),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.info_outline_rounded, size: 18, color: OColors.tertiaryContainer),
                  const SizedBox(width: OSpace.sm),
                  Expanded(
                    child: Text(context.t('settings.profile.cooldown_rule'),
                        style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: OSpace.md),
        InfoBanner(
          icon: Icons.calendar_month_rounded,
          iconBackground: OColors.rose,
          iconColor: OColors.secondary,
          title: context.t('settings.profile.name_change'),
          body: nameLocked
              ? context.t('settings.profile.locked',
                  {'time': shortDuration(context, Duration(milliseconds: availableAt - now))})
              : context.t('settings.profile.eligible'),
        ),
      ],
    );
  }

  Widget _availabilityChip(BuildContext context) => switch (_availability) {
        _Availability.idle => const SizedBox.shrink(),
        _Availability.checking =>
          const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2)),
        _Availability.available =>
          OPill(context.t('settings.profile.available'), icon: Icons.check_circle_outline_rounded),
        _Availability.unavailable => OPill(
            Strings.has('settings.profile.unavailable.$_availabilityReason')
                ? context.t('settings.profile.unavailable.$_availabilityReason')
                : context.t('settings.profile.unavailable'),
            icon: Icons.error_outline_rounded,
            background: OColors.rose,
            foreground: OColors.secondary,
          ),
      };
}

class _AvatarGrid extends ConsumerWidget {
  const _AvatarGrid({required this.selected, required this.onSelect});

  final String? selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final catalog = ref.watch(catalogProvider('avatars'));
    return asyncBody<Json>(
      isLoading: catalog.isLoading,
      error: catalog.error,
      value: catalog.value,
      onRetry: () => ref.invalidate(catalogProvider('avatars')),
      data: (json) {
        final ids = [
          for (final a in (json['avatars'] as List?) ?? const [])
            if (a is Map && a['id'] is String) a['id'] as String,
        ];
        return GridView.count(
          crossAxisCount: 4,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: OSpace.md,
          crossAxisSpacing: OSpace.md,
          children: [
            for (final id in ids)
              Semantics(
                button: true,
                selected: id == selected,
                label: context.t('settings.profile.avatar_option'),
                child: InkWell(
                  key: ValueKey('avatar_$id'),
                  customBorder: const CircleBorder(),
                  onTap: () => onSelect(id),
                  child: Container(
                    padding: const EdgeInsets.all(3),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: id == selected ? OColors.turquoise : Colors.transparent, width: 3),
                    ),
                    child: FittedBox(child: OAvatar(avatarId: id, size: 64)),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _FramePicker extends ConsumerWidget {
  const _FramePicker({required this.frames, required this.selected, required this.onSelect});

  final List<String> frames;
  final String? selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final catalog = ref.watch(catalogProvider('cosmetics')).value;
    final names = <String, Map>{
      for (final f in (catalog?['frames'] as List?) ?? const [])
        if (f is Map && f['id'] is String) f['id'] as String: (f['names'] as Map?) ?? const {},
    };
    return Wrap(
      spacing: OSpace.sm,
      runSpacing: OSpace.sm,
      children: [
        for (final id in frames)
          ChoiceChip(
            selected: id == selected,
            onSelected: (_) => onSelect(id),
            avatar: Container(
              width: 14,
              height: 14,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: frameColors[id] ?? OColors.divider,
              ),
            ),
            label: Text(context.pick(names[id], fallback: id)),
          ),
      ],
    );
  }
}
