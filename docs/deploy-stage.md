# Stage deployment (internal testing)

Oltivra shares the Firebase project `synova-36a5f` (and its Auth users) with Synova but never touches
Synova's resources:

| Resource | Oltivra | Synova (do not touch) |
|---|---|---|
| Firestore | named database `oltivra` (europe-west1) | `(default)` (nam5) |
| Realtime Database | `oltivra-live-00` … `oltivra-live-15` (europe-west1, 16 shards) | default instance |
| Storage | `gs://synova-36a5f-oltivra-media` (europe-west1) | default bucket |
| Secrets | `oltivra-*` | everything else |
| Cloud Run | `oltivra-api` (europe-west1) | Cloud Functions (us-central1) |
| Android app | `com.noriloop.oltivra` | Synova apps |

## Rules

Deploy only Oltivra's rules with the dedicated config, which targets the named database and the shard instances:

```bash
firebase deploy --config firebase.oltivra.json --only firestore:oltivra,database --project synova-36a5f
```

## Backend

- Service account `oltivra-api` runs the service and is also the Cloud Tasks OIDC identity and the V4 URL signer
  (it holds `iam.serviceAccountTokenCreator` / `serviceAccountUser` on itself).
- Queues: `python scripts/provision_queues.py stage europe-west1` (16 shards per family, like prod). Strip `\r` on
  Windows. New shard instances: `firebase database:instances:create oltivra-live-NN --location europe-west1`, add
  them to `firebase.oltivra.json`, deploy the rules and add a version of the `oltivra-rtdb-shard-urls` secret.
- Deploy from `backend/` (`.gcloudignore` keeps the upload to what the Dockerfile copies):

```bash
gcloud run deploy oltivra-api --source . --region=europe-west1 --project=synova-36a5f
```

  The first deploy sets `OLTIVRA_ENV=stage`, `OLTIVRA_FIRESTORE_DATABASE=oltivra`, `OLTIVRA_SHARD_COUNT=16`,
  `OLTIVRA_APP_CHECK_MODE=monitor` (verifies and logs App Check failures without rejecting, until every tester runs a
  build with App Check; then switch to `enforce`), `OLTIVRA_TASKS_MODE=cloud`,
  `OLTIVRA_INTERNAL_AUTH_MODE=oidc`, the bucket, the task target URL/service account, the legal identity and
  the `oltivra-*` secrets. Later deploys keep that configuration.

## Question pool

Run the seed importer against the cloud with the same keys the service uses (secrets exported as
`OLTIVRA_*_KEYS`, `OLTIVRA_RTDB_SHARD_URLS`) and `OLTIVRA_TASKS_MODE=recording`:

```bash
python -m app.questions.seed --status ACTIVE
```

It imports catalogs, bots, the text seed and the curated image questions (uploading their WebP files) and
rebuilds the manifests. Re-running skips existing questions.

## Android release

```bash
flutter build appbundle --release \
  --dart-define=API_BASE_URL=https://oltivra-api-269747180478.europe-west1.run.app \
  --dart-define=AUTH_MODE=firebase --dart-define=LIVE_MODE=rtdb --dart-define=USE_EMULATORS=false \
  --dart-define=FIREBASE_PROJECT_ID=synova-36a5f --dart-define=FIREBASE_API_KEY=<android api key> \
  --dart-define=FIREBASE_APP_ID=1:269747180478:android:6c258e7cd845535c8a1fef \
  --dart-define=FIREBASE_SENDER_ID=269747180478 --dart-define=GOOGLE_SERVER_CLIENT_ID=<web oauth client id> \n  --dart-define=ADMOB_INTERSTITIAL_ANDROID=ca-app-pub-8532987166068354/4350238650 \n  --dart-define=ADMOB_REWARDED_ANDROID=ca-app-pub-8532987166068354/7801389346
```

Firebase Analytics (events `match_completed`, `level_up` for Google Ads app campaigns) needs `google_app_id` & co. as
Android resources; `android/app/build.gradle.kts` derives them from the same `--dart-define`s when
`USE_EMULATORS=false`, so no `google-services.json` is committed.

The AdMob app ID lives in `mobile/android/gradle.properties` (`admobAppId`). Debug builds keep Google's sample ad
units, so never tap real ads while developing.

App Check uses Play Integrity (the Firebase Android app lists the SHA-256 of the Play app-signing key and the Play
Console links the Cloud project under *Play Integrity API*). Emulator or sideloaded builds pass
`--dart-define=APP_CHECK_DEBUG_TOKEN=<token registered in Firebase App Check>`.

The API key and web client id come from `firebase apps:sdkconfig ANDROID <app id>`. The Firebase Android app
lists the SHA-1/SHA-256 of the upload key, the Play app-signing key and the local debug key.
