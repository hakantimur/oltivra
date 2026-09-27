import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/store/interstitials.dart';
import 'package:oltivra/features/store/store_services.dart';
import 'package:oltivra/session/session.dart';

class _FakeInterstitials implements InterstitialAdGateway {
  bool ready = true;
  int preloads = 0;
  int shows = 0;

  @override
  void preload() => preloads++;

  @override
  Future<bool> showIfReady() async {
    if (!ready) return false;
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
  int interval = 45,
  bool consent = true,
}) async {
  final ads = _FakeInterstitials();
  final c = ProviderContainer(
    overrides: [
      interstitialAdGatewayProvider.overrideWithValue(ads),
      sessionProvider.overrideWith(() => _Session(removeAds)),
      clientConfigProvider.overrideWith((ref) async => {'interstitial_min_interval_s': interval}),
      adConsentProvider.overrideWith((ref) async => consent),
    ],
  );
  addTearDown(c.dispose);
  await c.read(sessionProvider.future);
  await c.read(clientConfigProvider.future);
  await c.read(adConsentProvider.future);
  return (c.read(interstitialControllerProvider), ads);
}

void main() {
  test('shows at most one interstitial per match', () async {
    final (ctl, ads) = await _setup(interval: 0);
    await ctl.maybeShow('m1');
    await ctl.maybeShow('m1');
    expect(ads.shows, 1);
  });

  test('respects the minimum interval between displays across matches', () async {
    final (ctl, ads) = await _setup();
    await ctl.maybeShow('m1');
    await ctl.maybeShow('m2');
    expect(ads.shows, 1);
    expect(ctl.eligible('m2', DateTime.now().millisecondsSinceEpoch + 46000), isTrue);
  });

  test('rewarded completion and reconnect recovery suppress that match only', () async {
    final (ctl, ads) = await _setup(interval: 0);
    ctl.markRewarded('m1');
    ctl.markRecovered('m2');
    await ctl.maybeShow('m1');
    await ctl.maybeShow('m2');
    expect(ads.shows, 0);
    await ctl.maybeShow('m3');
    expect(ads.shows, 1);
  });

  test('ad-free players never load or see interstitials', () async {
    final (ctl, ads) = await _setup(removeAds: true, interval: 0);
    ctl.preload();
    await ctl.maybeShow('m1');
    expect(ads.preloads, 0);
    expect(ads.shows, 0);
  });

  test('an unready ad does not start the interval', () async {
    final (ctl, ads) = await _setup();
    ads.ready = false;
    await ctl.maybeShow('m1');
    ads.ready = true;
    await ctl.maybeShow('m2');
    expect(ads.shows, 1);
  });

  test('no ads are loaded or shown without UMP consent', () async {
    final (ctl, ads) = await _setup(interval: 0, consent: false);
    ctl.preload();
    await ctl.maybeShow('m1');
    expect(ads.preloads, 0);
    expect(ads.shows, 0);
  });
}
