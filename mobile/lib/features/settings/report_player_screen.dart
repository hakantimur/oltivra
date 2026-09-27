import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_avatar.dart';
import '../../widgets/o_widgets.dart';
import 'settings_widgets.dart';

/// Backend `PlayerReportReason` enum (moderation/safety.py), in display order.
const reportReasons = ['OFFENSIVE_USERNAME', 'HARASSMENT', 'IMPERSONATION', 'SUSPECTED_CHEATING', 'OTHER'];

/// P07 · Report player: preset reasons only (no free text / uploads), optional block, understated confirmation.
/// `POST /v1/player-reports {target_public_id, reason, match_id?}` and optionally `POST /v1/blocks/{public_id}`.
class ReportPlayerScreen extends ConsumerStatefulWidget {
  const ReportPlayerScreen({super.key, required this.publicId, this.matchId});

  final String publicId;
  final String? matchId;

  @override
  ConsumerState<ReportPlayerScreen> createState() => _ReportPlayerScreenState();
}

class _ReportPlayerScreenState extends ConsumerState<ReportPlayerScreen> {
  String? _reason;
  bool _block = false;
  bool _alreadyBlocked = false;
  bool _submitting = false;
  bool _done = false;
  Json? _target;

  @override
  void initState() {
    super.initState();
    _loadTarget();
  }

  /// Best effort header (username + avatar); the report works without it.
  Future<void> _loadTarget() async {
    try {
      final res = await ref.read(apiClientProvider).get('/v1/users/${widget.publicId}');
      if (!mounted) return;
      setState(() {
        _target = (res['profile'] as Map?)?.cast<String, dynamic>();
        _alreadyBlocked = (res['relationship'] as Map?)?['blocked'] == true;
      });
    } catch (_) {
      // Unknown / hidden player: keep the generic header.
    }
  }

  Future<void> _submit() async {
    final reason = _reason;
    if (reason == null) return;
    setState(() => _submitting = true);
    final api = ref.read(apiClientProvider);
    try {
      await api.post('/v1/player-reports', {
        'target_public_id': widget.publicId,
        'reason': reason,
        if (widget.matchId != null) 'match_id': widget.matchId,
      });
      if (_block && !_alreadyBlocked) {
        try {
          await api.post('/v1/blocks/${widget.publicId}');
        } catch (e) {
          if (mounted) showError(context, e);
        }
      }
      if (mounted) setState(() => _done = true);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  void _close() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go(Routes.home);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_done) return _confirmation(context);
    final name = _target?['username_display'] as String?;
    return OPage(
      title: context.t('settings.report.title'),
      bottom: OButton(
        key: const ValueKey('report_submit'),
        label: context.t('settings.report.submit'),
        trailingIcon: Icons.send_rounded,
        loading: _submitting,
        onPressed: _reason == null ? null : _submit,
      ),
      children: [
        OCard(
          child: Row(
            children: [
              OAvatar(avatarId: _target?['avatar_id'] as String?, frameId: _target?['frame_id'] as String?, size: 52),
              const SizedBox(width: OSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(context.t('settings.report.reporting').toUpperCase(),
                        style: OText.labelSm.copyWith(color: OColors.onSurfaceVariant)),
                    const SizedBox(height: 2),
                    Text(name ?? context.t('settings.report.this_player'),
                        style: OText.headlineSm, overflow: TextOverflow.ellipsis),
                  ],
                ),
              ),
              Container(
                width: 44,
                height: 44,
                decoration: const BoxDecoration(color: OColors.rose, shape: BoxShape.circle),
                child: const Icon(Icons.health_and_safety_rounded, color: OColors.coral),
              ),
            ],
          ),
        ),
        const SizedBox(height: OSpace.lg),
        Text(context.t('settings.report.intro'), style: OText.bodyMd),
        const SizedBox(height: OSpace.lg),
        for (final r in reportReasons)
          Padding(
            padding: const EdgeInsets.only(bottom: OSpace.sm),
            child: _ReasonCard(
              reason: r,
              selected: _reason == r,
              onTap: _submitting ? null : () => setState(() => _reason = r),
            ),
          ),
        const SizedBox(height: OSpace.sm),
        if (!_alreadyBlocked)
          OCard(
            padding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: OSpace.xs),
            child: SwitchListTile(
              key: const ValueKey('report_block_toggle'),
              contentPadding: EdgeInsets.zero,
              value: _block,
              onChanged: _submitting ? null : (v) => setState(() => _block = v),
              title: Text(context.t('settings.report.block'), style: OText.labelLg),
              subtitle: Text(context.t('settings.report.block.sub'),
                  style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
            ),
          ),
        const SizedBox(height: OSpace.lg),
        InfoBanner(icon: Icons.verified_user_outlined, body: context.t('settings.report.confidential')),
      ],
    );
  }

  Widget _confirmation(BuildContext context) => OPage(
        title: context.t('settings.report.title'),
        bottom: OButton(label: context.t('action.done'), onPressed: _close),
        children: [
          const SizedBox(height: OSpace.xxl),
          const HeroIcon(icon: Icons.check_rounded),
          const SizedBox(height: OSpace.xl),
          Text(context.t('settings.report.thanks'), style: OText.headlineMd, textAlign: TextAlign.center),
          const SizedBox(height: OSpace.sm),
          Text(
            context.t(_block && !_alreadyBlocked ? 'settings.report.thanks.blocked' : 'settings.report.thanks.body'),
            style: OText.bodyMd.copyWith(color: OColors.inkSubtle),
            textAlign: TextAlign.center,
          ),
        ],
      );
}

class _ReasonCard extends StatelessWidget {
  const _ReasonCard({required this.reason, required this.selected, this.onTap});

  final String reason;
  final bool selected;
  final VoidCallback? onTap;

  IconData get _icon => switch (reason) {
        'OFFENSIVE_USERNAME' => Icons.badge_outlined,
        'HARASSMENT' => Icons.sentiment_very_dissatisfied_rounded,
        'IMPERSONATION' => Icons.face_retouching_natural_rounded,
        'SUSPECTED_CHEATING' => Icons.gpp_maybe_outlined,
        _ => Icons.shield_outlined,
      };

  @override
  Widget build(BuildContext context) => Semantics(
        selected: selected,
        button: true,
        child: OCard(
          key: ValueKey('reason_$reason'),
          onTap: onTap,
          border: selected ? OColors.turquoise : null,
          padding: const EdgeInsets.all(OSpace.lg),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: selected ? OColors.turquoise : OColors.surfaceContainer,
                  shape: BoxShape.circle,
                ),
                child: Icon(_icon, size: 22, color: selected ? OColors.white : OColors.primary),
              ),
              const SizedBox(width: OSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(context.t('settings.report.reason.$reason'), style: OText.labelLg),
                    const SizedBox(height: 2),
                    Text(context.t('settings.report.reason.$reason.sub'),
                        style: OText.bodySm.copyWith(color: OColors.inkSubtle)),
                  ],
                ),
              ),
              const SizedBox(width: OSpace.sm),
              Icon(
                selected ? Icons.radio_button_checked_rounded : Icons.radio_button_unchecked_rounded,
                color: selected ? OColors.turquoise : OColors.outlineVariant,
              ),
            ],
          ),
        ),
      );
}
