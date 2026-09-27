"""Process configuration (environment only).

Game rules live in versioned server configuration (``server_config`` collection, see
``app.common.server_config``). This module only holds deployment wiring and secret references.
"""

from __future__ import annotations

from functools import cached_property
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLTIVRA_", env_file=".env", extra="ignore")

    env: Literal["dev", "stage", "prod", "test"] = "dev"
    region: str = "europe-west1"

    store_backend: Literal["memory", "firebase"] = "memory"
    auth_mode: Literal["firebase", "fake"] = "fake"
    app_check_mode: Literal["enforce", "debug", "off"] = "off"
    tasks_mode: Literal["local", "cloud", "recording"] = "local"
    internal_auth_mode: Literal["oidc", "shared_secret"] = "shared_secret"

    firebase_project_id: str = "demo-oltivra"
    # Comma separated RTDB URLs, index == shard number. Empty -> derived emulator namespaces.
    rtdb_shard_urls: str = ""
    shard_count: int = 2
    rtdb_emulator_host: str = "127.0.0.1:9000"
    # Public web config for the external account-deletion page (not secrets).
    firebase_web_api_key: str = "demo-api-key"
    firebase_auth_domain: str = ""
    auth_emulator_host: str = "127.0.0.1:9099"
    storage_bucket: str = "demo-oltivra.appspot.com"

    cloud_tasks_project: str = ""
    cloud_tasks_location: str = "europe-west1"
    task_target_base_url: str = "http://127.0.0.1:8000"
    task_service_account: str = ""
    internal_shared_secret: str = Field(default="dev-internal-secret", repr=False)

    # HMAC secrets: "<key_id>:<secret>" pairs separated by "," — first entry is current.
    tiebreak_keys: str = Field(default="k1:dev-tiebreak", repr=False)
    resolver_keys: str = Field(default="k1:dev-resolver", repr=False)
    shard_keys: str = Field(default="k1:dev-shard", repr=False)
    bot_plan_keys: str = Field(default="k1:dev-botplan", repr=False)
    reward_keys: str = Field(default="k1:dev-reward", repr=False)
    mission_keys: str = Field(default="k1:dev-mission", repr=False)
    username_hash_keys: str = Field(default="k1:dev-username", repr=False)

    admin_require_mfa: bool = False
    admob_ssv_mode: Literal["google", "fake"] = "fake"
    purchase_verify_mode: Literal["store", "fake"] = "fake"
    google_play_package: str = "com.oltivra.app"
    apple_bundle_id: str = "com.oltivra.app"
    # Comma separated paths to pinned Apple root certificates (e.g. AppleRootCA-G3.cer), mounted from secrets.
    apple_root_cert_paths: str = ""
    ai_provider: Literal["anthropic", "fake"] = "fake"
    anthropic_api_key: str = Field(default="", repr=False)
    ai_model: str = "claude-sonnet-5"

    blocking_io_threads: int = 32

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.env in ("prod", "stage"):
            if self.auth_mode != "firebase":
                raise ValueError("fake auth is forbidden outside dev/test")
            if self.store_backend != "firebase":
                raise ValueError("memory store is forbidden outside dev/test")
            if self.admob_ssv_mode != "google" or self.purchase_verify_mode != "store":
                raise ValueError("fake reward/purchase verification is forbidden outside dev/test")
        if self.env == "prod":
            if self.app_check_mode != "enforce":
                raise ValueError("App Check must be enforced in prod")
            if self.internal_auth_mode != "oidc":
                raise ValueError("internal routes must use OIDC in prod")
            if not self.admin_require_mfa:
                raise ValueError("admin MFA is mandatory in prod")
            if self.shard_count != 16:
                raise ValueError("production uses a 16 shard ring")
        return self

    @cached_property
    def shard_ids(self) -> list[str]:
        return [f"live-{i:02d}" for i in range(self.shard_count)]

    def shard_url(self, shard_id: str) -> str:
        index = int(shard_id.split("-")[1])
        urls = [u.strip() for u in self.rtdb_shard_urls.split(",") if u.strip()]
        if urls:
            return urls[index]
        return f"http://{self.rtdb_emulator_host}?ns={self.firebase_project_id}-{shard_id}"
