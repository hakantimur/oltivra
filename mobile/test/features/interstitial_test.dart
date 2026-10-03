import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/store/interstitials.dart';
import 'package:oltivra/features/store/store_services.dart';
import 'package:oltivra/session/session.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeInterstitials implements InterstitialAdGateway {
  bool ready = true;
  bool showSucceeds = true;
  int preloads = 0;
  int shows = 0;

  @override
  bool get isReady => ready;

  @override
  void preload() => preloads++;

  @override
  Future<bool> showIfReady() async {
    if (!ready || !showSucceeds) return false;
    shows++;
    return true;
  }
}

class _Session extends SessionController {
  _Session(this.removeAds);

  final bool removeAds;

  @override
  Future<Session?> build() async => Session({
    'profile': {'remove_ads': removeAds},
  });
}

Future<(InterstitialController, _FakeInterstitials)> _setup({
  bool removeAds = false,
  int every = 3,
  bool consent = true,
  List<bool>? consents,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final ads = _FakeInterstitials();
  final c = ProviderContainer(
    overrides: [
      sharedPrefsProvider.overrideWithValue(prefs),
      interstitialAdGatewayProvider.overrideWithValue(ads),
      sessionProvider.overrideWith(() => _Session(removeAds)),
      clientConfigProvider.overrideWith((ref) async => {'ad_gate_every_matches': every}),
      adConsentProvider.overrideWith((ref) async => consents == null ? consent : consents.removeAt(0)),
    ],
  );
  addTearDown(c.dispose);
  await c.read(sessionProvider.future);
  await c.read(clientConfigProvider.future);
  await c.read(adConsentProvider.future);
  return (c.read(interstitialControllerProvider), ads);
}

Future<void> _complete(InterstitialController ctl, int n, {int from = 0}) async {
  for (var i = from; i < from + n; i++) {
    await ctl.recordCompleted('m$i');
  }
}

void main() {
  test('an ad break is due only after every third completed match', () async {
    final (ctl, ads) = await _setup();
    await _complete(ctl, 2);
    expect(ctl.breakDue(), isFalse);
    await _complete(ctl, 1, from: 2);
    expect(ctl.breakDue(), isTrue);

    var noticeShown = 0;
    await ctl.runBreak(() async => noticeShown++);
    expect(noticeShown, 1);
    expect(ads.shows, 1);
    expect(ctl.completedSinceBreak, 0);
    expect(ctl.breakDue(), isFalse);
  });

  test('the same match is counted once', () async {
    final (ctl, _) = await _setup();
    await ctl.recordCompleted('m1');
    await ctl.recordCompleted('m1');
    expect(ctl.completedSinceBreak, 1);
  });

  test('no fill never blocks play and the break is offered again later', () async {
    final (ctl, ads) = await _setup();
    await _complete(ctl, 3);
    ads.ready = false;
    expect(ctl.breakDue(), isFalse);
    expect(ads.preloads, 1);
    ads.ready = true;
    expect(ctl.breakDue(), isTrue);
  });

  test('a failed show keeps the counter so the next match tries again', () async {
    final (ctl, ads) = await _setup();
    await _complete(ctl, 3);
    ads.showSucceeds = false;
    await ctl.runBreak(() async {});
    expect(ads.shows, 0);
    expect(ctl.completedSinceBreak, 3);
  });

  test('ad-free players never load or see ad breaks', () async {
    final (ctl, ads) = await _setup(removeAds: true);
    ctl.preload();
    await _complete(ctl, 5);
    expect(ctl.breakDue(), isFalse);
    expect(ads.preloads, 0);
  });

  test('no ads are loaded or shown without UMP consent', () async {
    final (ctl, ads) = await _setup(consent: false);
    ctl.preload();
    await _complete(ctl, 5);
    expect(ctl.breakDue(), isFalse);
    expect(ads.preloads, 0);
  });

  test('consent that failed at startup is gathered again before the next preload', () async {
    final (ctl, ads) = await _setup(consents: [false, true]);
    ctl.preload();
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);
    expect(ads.preloads, 1);
  });

  test('a zero rhythm from the server turns ad breaks off', () async {
    final (ctl, _) = await _setup(every: 0);
    await _complete(ctl, 10);
    expect(ctl.breakDue(), isFalse);
  });
}
