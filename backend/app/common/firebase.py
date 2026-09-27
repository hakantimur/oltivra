"""Firebase / Google Cloud client construction for the ``firebase`` store backend."""

from __future__ import annotations

import os

import anyio
import firebase_admin

from app.common.settings import Settings


def default_app(settings: Settings) -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        credential = None
        if _using_emulators():
            from firebase_admin import credentials
            from google.auth.credentials import AnonymousCredentials

            class _EmulatorCredential(credentials.Base):
                def get_credential(self):
                    return AnonymousCredentials()

            credential = _EmulatorCredential()
        return firebase_admin.initialize_app(credential, {
            "projectId": settings.firebase_project_id,
            "storageBucket": settings.storage_bucket,
        })


def _using_emulators() -> bool:
    return bool(os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"))


def firestore_client(settings: Settings):
    from google.cloud import firestore

    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        from google.auth.credentials import AnonymousCredentials

        return firestore.Client(project=settings.firebase_project_id, credentials=AnonymousCredentials(),
                                database=settings.firestore_database)
    return firestore.Client(project=settings.firebase_project_id, database=settings.firestore_database)


def build_firebase_stores(settings: Settings, limiter: anyio.CapacityLimiter):
    from app.common.store.firestore_docstore import FirestoreDocStore
    from app.common.store.rtdb_livestore import RtdbLiveStore

    app = default_app(settings)
    doc_store = FirestoreDocStore(firestore_client(settings), limiter)
    shard_urls = {sid: settings.shard_url(sid) for sid in settings.shard_ids}
    live_store = RtdbLiveStore(shard_urls, settings.firebase_project_id, limiter, credential=app.credential)
    return app, doc_store, live_store
