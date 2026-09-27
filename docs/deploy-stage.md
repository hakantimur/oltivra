# Stage deployment (internal testing)

Oltivra shares the Firebase project `synova-36a5f` (and its Auth users) with Synova but never touches
Synova's resources:

| Resource | Oltivra | Synova (do not touch) |
|---|---|---|
| Firestore | named database `oltivra` (europe-west1) | `(default)` (nam5) |
| Realtime Database | `oltivra-live-00`, `oltivra-live-01` (europe-west1) | default instance |
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
- Queues: `python scripts/provision_queues.py stage europe-west1` (2 shards per family). Strip `\r` on Windows.
- Deploy from `backend/` (`.gcloudignore` keeps the upload to what the Dockerfile copies):

```bash
gcloud run deploy oltivra-api --source . --region=europe-west1 --project=synova-36a5f
```

  The first deploy sets `OLTIVRA_ENV=stage`, `OLTIVRA_FIRESTORE_DATABASE=oltivra`, `OLTIVRA_SHARD_COUNT=2`,
  `OLTIVRA_APP_CHECK_MODE=off` (the client does not ship App Check yet), `OLTIVRA_TASKS_MODE=cloud`,
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
  --dart-define=FIREBASE_SENDER_ID=269747180478 --dart-define=GOOGLE_SERVER_CLIENT_ID=<web oauth client id>
```

The API key and web client id come from `firebase apps:sdkconfig ANDROID <app id>`. The Firebase Android app
lists the SHA-1/SHA-256 of the upload key, the Play app-signing key and the local debug key.
