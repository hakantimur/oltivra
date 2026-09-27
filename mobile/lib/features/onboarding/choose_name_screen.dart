import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/o_widgets.dart';
import 'widgets.dart';

/// Mirrors backend `app/usernames/rules.py` (3–16 ASCII letters, digits, underscore). The server stays
/// authoritative for reserved names, profanity and uniqueness.
final usernamePattern = RegExp(r'^[A-Za-z0-9_]{3,16}$');
const usernameMaxLength = 16;

enum _NameStatus { idle, checking, available, unavailable }

/// P01 · Choose a unique player name (spec §2.3). Also used for renames (`rename: true`), either forced by
/// moderation (`rename_required`) or voluntary from settings (30-day cooldown enforced by the server).
class ChooseNameScreen extends ConsumerStatefulWidget {
  const ChooseNameScreen({super.key, this.rename = false});

  final bool rename;

  @override
  ConsumerState<ChooseNameScreen> createState() => _ChooseNameScreenState();
}

class _ChooseNameScreenState extends ConsumerState<ChooseNameScreen> {
  static const _debounce = Duration(milliseconds: 450);
  final _controller = TextEditingController();
  final _focus = FocusNode();
  Timer? _timer;
  int _seq = 0;
  _NameStatus _status = _NameStatus.idle;
  String? _problem; // localised reason when unavailable
  bool _saving = false;

  @override
  void dispose() {
    _timer?.cancel();
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _timer?.cancel();
    final seq = ++_seq;
    if (value.isEmpty) {
      setState(() {
        _status = _NameStatus.idle;
        _problem = null;
      });
      return;
    }
    if (!usernamePattern.hasMatch(value)) {
      setState(() {
        _status = value.length < 3 ? _NameStatus.idle : _NameStatus.unavailable;
        _problem = value.length < 3 ? null : context.t('onboarding.name.format');
      });
      return;
    }
    setState(() {
      _status = _NameStatus.checking;
      _problem = null;
    });
    _timer = Timer(_debounce, () => _check(value, seq));
  }

  Future<void> _check(String value, int seq) async {
    try {
      final res = await ref.read(apiClientProvider).get('/v1/usernames/availability', query: {'username': value});
      if (!mounted || seq != _seq) return;
      final available = res['available'] == true;
      setState(() {
        _status = available ? _NameStatus.available : _NameStatus.unavailable;
        _problem = available ? null : _reasonText(res['reason'] as String?);
      });
    } catch (_) {
      // Availability is advisory (and rate limited); the claim itself is validated on submit.
      if (mounted && seq == _seq) setState(() => _status = _NameStatus.idle);
    }
  }

  String _reasonText(String? reason) => switch (reason) {
        'TAKEN' => context.t('onboarding.name.taken'),
        'FORMAT' => context.t('onboarding.name.format'),
        'RESERVED' => context.t('onboarding.name.reserved'),
        'PROFANITY' => context.t('onboarding.name.profanity'),
        _ => context.t('onboarding.name.invalid'),
      };

  void _roll() {
    const adjectives = ['quick', 'bright', 'clever', 'lucky', 'swift', 'bold', 'calm', 'witty', 'sunny', 'brave',
        'keen', 'zesty'];
    const nouns = ['fox', 'owl', 'comet', 'atlas', 'quill', 'spark', 'pixel', 'nova', 'orbit', 'maple', 'tiger',
        'river'];
    final r = Random();
    final name = '${adjectives[r.nextInt(adjectives.length)]}_${nouns[r.nextInt(nouns.length)]}${r.nextInt(90) + 10}';
    _controller.value = TextEditingValue(text: name, selection: TextSelection.collapsed(offset: name.length));
    _onChanged(name);
  }

  bool get _canSubmit =>
      !_saving && usernamePattern.hasMatch(_controller.text) && _status != _NameStatus.unavailable;

  Future<void> _submit() async {
    if (!_canSubmit) return;
    _timer?.cancel();
    final name = _controller.text;
    setState(() => _saving = true);
    try {
      final path = widget.rename ? '/v1/profile/username/change' : '/v1/profile/username';
      final res = await ref.read(apiClientProvider).post(path, {'username': name});
      final profile = (res['profile'] as Map?)?.cast<String, dynamic>();
      if (profile != null) ref.read(sessionProvider.notifier).applyProfile(profile);
      if (!mounted) return;
      // Onboarding and forced renames move on through the redirect; a voluntary rename returns to its caller.
      if (widget.rename && context.canPop()) context.pop();
    } on ApiException catch (e) {
      if (!mounted) return;
      final inline = switch (e.code) {
        'USERNAME_TAKEN' => context.t('onboarding.name.taken'),
        'USERNAME_INVALID' => _reasonText(e.reason),
        'USERNAME_COOLDOWN' => _cooldownText(e.detail['available_at_ms']),
        _ => null,
      };
      if (inline == null) {
        showError(context, e);
      } else {
        _seq++;
        setState(() {
          _status = _NameStatus.unavailable;
          _problem = inline;
        });
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  String _cooldownText(Object? availableAtMs) {
    if (availableAtMs is! num) return context.t('onboarding.name.cooldown_generic');
    final date = DateTime.fromMillisecondsSinceEpoch(availableAtMs.toInt());
    try {
      return context.t('onboarding.name.cooldown', {'date': DateFormat.yMMMd(context.lang).format(date)});
    } catch (_) {
      return context.t('onboarding.name.cooldown_generic'); // date symbols not loaded for this locale
    }
  }

  @override
  Widget build(BuildContext context) {
    final forced = ref.watch(sessionProvider).value?.renameRequired ?? false;
    final canGoBack = widget.rename && !forced && context.canPop();
    return Scaffold(
      appBar: onboardingAppBar(
        context,
        title: context.t('onboarding.name.title'),
        onBack: canGoBack ? () => context.pop() : null,
      ),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(OSpace.margin, OSpace.sm, OSpace.margin, OSpace.xxl),
          children: [
            if (!widget.rename) ...[const OnboardingStepBar(step: 4), const SizedBox(height: OSpace.xl)],
            Semantics(
              header: true,
              child: Text(
                context.t(widget.rename ? 'onboarding.name.heading_rename' : 'onboarding.name.heading'),
                style: OText.headlineXl,
              ),
            ),
            const SizedBox(height: OSpace.sm),
            Text(
              context.t(forced ? 'onboarding.name.body_forced' : 'onboarding.name.body'),
              style: OText.bodyLg.copyWith(color: OColors.onSurfaceVariant),
            ),
            const SizedBox(height: OSpace.xl),
            _NameField(
              controller: _controller,
              focusNode: _focus,
              status: _status,
              onChanged: _onChanged,
              onSubmitted: (_) => _submit(),
            ),
            const SizedBox(height: OSpace.md),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: OSpace.xs),
              child: Text(context.t('onboarding.name.rules'),
                  style: OText.bodyMd.copyWith(color: OColors.onSurfaceVariant)),
            ),
            const SizedBox(height: OSpace.sm),
            Align(alignment: Alignment.centerLeft, child: _StatusChip(status: _status, problem: _problem)),
            const SizedBox(height: OSpace.xl),
            _RollCard(onRoll: _saving ? null : _roll),
            const SizedBox(height: OSpace.xl),
            OButton(
              key: const Key('name-continue'),
              label: context.t(widget.rename ? 'action.save' : 'action.continue'),
              trailingIcon: Icons.arrow_forward_rounded,
              loading: _saving,
              onPressed: _canSubmit ? _submit : null,
            ),
            const SizedBox(height: OSpace.md),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.lock_outline_rounded, size: 16, color: OColors.inkSubtle),
                const SizedBox(width: OSpace.xs),
                Flexible(
                  child: Text(context.t('onboarding.name.change_rule'),
                      style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _NameField extends StatelessWidget {
  const _NameField({required this.controller, required this.focusNode, required this.status,
      required this.onChanged, required this.onSubmitted});

  final TextEditingController controller;
  final FocusNode focusNode;
  final _NameStatus status;
  final ValueChanged<String> onChanged;
  final ValueChanged<String> onSubmitted;

  @override
  Widget build(BuildContext context) {
    final trailing = switch (status) {
      _NameStatus.checking => const Padding(
          padding: EdgeInsets.all(14),
          child: SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2)),
        ),
      _NameStatus.available => const Icon(Icons.check_circle_outline_rounded, color: OColors.turquoise),
      _NameStatus.unavailable => const Icon(Icons.error_outline_rounded, color: OColors.coral),
      _NameStatus.idle => null,
    };
    final borderColor = switch (status) {
      _NameStatus.available => OColors.turquoise,
      _NameStatus.unavailable => OColors.coral,
      _ => Colors.transparent,
    };
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(ORadius.md),
      borderSide: BorderSide(color: borderColor, width: 1.5),
    );
    return DecoratedBox(
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(ORadius.md), boxShadow: OShadow.card),
      child: TextField(
        key: const Key('name-field'),
        controller: controller,
        focusNode: focusNode,
        autocorrect: false,
        enableSuggestions: false,
        textInputAction: TextInputAction.done,
        maxLength: usernameMaxLength,
        inputFormatters: [
          FilteringTextInputFormatter.deny(RegExp(r'\s')),
          LengthLimitingTextInputFormatter(usernameMaxLength),
        ],
        style: OText.headlineSm,
        onChanged: onChanged,
        onSubmitted: onSubmitted,
        decoration: InputDecoration(
          hintText: 'mira_moves',
          labelText: context.t('onboarding.name.hint'),
          floatingLabelBehavior: FloatingLabelBehavior.never,
          counterText: '',
          prefixIcon: const Icon(Icons.badge_outlined, color: OColors.primary),
          suffixIcon: trailing,
          contentPadding: const EdgeInsets.symmetric(horizontal: OSpace.lg, vertical: 20),
          border: border,
          enabledBorder: border,
          focusedBorder: border.copyWith(
            borderSide: BorderSide(
              color: status == _NameStatus.idle || status == _NameStatus.checking ? OColors.primary : borderColor,
              width: 1.5,
            ),
          ),
        ),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status, required this.problem});

  final _NameStatus status;
  final String? problem;

  @override
  Widget build(BuildContext context) {
    final Widget child = switch (status) {
      _NameStatus.available => OPill(
          context.t('onboarding.name.available'),
          key: const Key('name-available'),
          icon: Icons.check_rounded,
          background: OColors.surfaceContainer,
          foreground: OColors.primary,
        ),
      _NameStatus.unavailable => OPill(
          problem ?? context.t('onboarding.name.invalid'),
          key: const Key('name-problem'),
          icon: Icons.close_rounded,
          background: OColors.rose,
          foreground: OColors.coral,
        ),
      _NameStatus.checking => OPill(
          context.t('onboarding.name.checking'),
          background: OColors.surfaceContainer,
          foreground: OColors.inkSubtle,
        ),
      _NameStatus.idle => const SizedBox(height: 26),
    };
    return Semantics(liveRegion: true, child: AnimatedSwitcher(duration: ODuration.fast, child: child));
  }
}

class _RollCard extends StatelessWidget {
  const _RollCard({required this.onRoll});

  final VoidCallback? onRoll;

  @override
  Widget build(BuildContext context) => OCard(
        radius: ORadius.card,
        padding: const EdgeInsets.all(OSpace.lg),
        child: Row(
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: const BoxDecoration(color: OColors.rose, shape: BoxShape.circle),
              child: const Icon(Icons.casino_outlined, color: OColors.secondary),
            ),
            const SizedBox(width: OSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(context.t('onboarding.name.roll_title'), style: OText.labelLg),
                  Text(context.t('onboarding.name.roll_body'),
                      style: OText.bodySm.copyWith(color: OColors.onSurfaceVariant)),
                ],
              ),
            ),
            const SizedBox(width: OSpace.sm),
            FilledButton.icon(
              key: const Key('name-roll'),
              onPressed: onRoll,
              iconAlignment: IconAlignment.end,
              icon: const Icon(Icons.autorenew_rounded, size: 18),
              label: Text(context.t('onboarding.name.roll')),
              style: FilledButton.styleFrom(
                backgroundColor: OColors.surfaceContainer,
                foregroundColor: OColors.ink,
                minimumSize: const Size(48, 48),
                padding: const EdgeInsets.symmetric(horizontal: OSpace.lg),
              ),
            ),
          ],
        ),
      );
}
