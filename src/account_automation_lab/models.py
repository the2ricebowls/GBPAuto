from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class RuntimeKind(StrEnum):
    PLAYWRIGHT_CHROMIUM = "playwright_chromium"
    CLOAKBROWSER = "cloakbrowser"


class BrowserSessionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"


class CaptchaMode(StrEnum):
    NONE = "none"
    MANUAL = "manual"
    TEST_KEY = "test_key"
    PROVIDER = "provider"


class CaptchaOutcome(StrEnum):
    SOLVED = "solved"
    WAITING = "waiting"
    FAILED = "failed"


class ProxyPolicy(StrEnum):
    NONE = "none"
    STICKY_PROFILE = "sticky_profile"
    FRESH_PER_JOB = "fresh_per_job"
    REFRESH_BEFORE_OTP = "refresh_before_otp"
    MOBILE_RESIDENTIAL = "mobile_residential"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CAPTCHA = "waiting_captcha"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FingerprintPlatform(StrEnum):
    WINDOWS = "windows"
    MACOS = "macos"


class ProfileStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SiteSpec(BaseModel):
    key: str
    display_name: str
    base_url: str
    allowed_host_suffixes: tuple[str, ...] = ("localhost", "127.0.0.1", ".internal", ".test")
    captcha_mode: CaptchaMode = CaptchaMode.TEST_KEY
    otp_sender_hints: tuple[str, ...] = ()
    proxy_policy: ProxyPolicy = ProxyPolicy.STICKY_PROFILE
    default_runtime: RuntimeKind = RuntimeKind.CLOAKBROWSER
    enabled: bool = True

    def is_url_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return False
        return any(host == suffix or host.endswith(suffix) for suffix in self.allowed_host_suffixes)


class JobCreate(BaseModel):
    site_key: str
    sim_id: str
    runtime: RuntimeKind = RuntimeKind.CLOAKBROWSER
    profile_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FingerprintConfig(BaseModel):
    platform: FingerprintPlatform = FingerprintPlatform.WINDOWS
    seed: int | None = None
    timezone: str | None = None
    locale: str | None = None
    color_scheme: str | None = None
    user_agent: str | None = None
    viewport: dict[str, int] | None = None
    geoip_from_proxy: bool = False
    extension_paths: list[str] = Field(default_factory=list)


class ProfileGroup(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    color: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ProfileGroupCreate(BaseModel):
    name: str
    color: str | None = None


class ProfileGroupUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class BrowserProfileCreate(BaseModel):
    id: str | None = None
    name: str
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind = RuntimeKind.CLOAKBROWSER
    startup_url: str | None = None
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)


class BrowserProfileUpdate(BaseModel):
    name: str | None = None
    group_id: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind | None = None
    startup_url: str | None = None
    status: ProfileStatus | None = None
    fingerprint: FingerprintConfig | None = None


class BrowserProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind = RuntimeKind.CLOAKBROWSER
    storage_dir: str
    startup_url: str | None = None
    status: ProfileStatus = ProfileStatus.ACTIVE
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BrowserSession(BaseModel):
    profile_id: str
    runtime: RuntimeKind
    status: BrowserSessionStatus = BrowserSessionStatus.RUNNING
    started_at: datetime = Field(default_factory=utc_now)
    start_url: str | None = None


class BrowserProfileView(BaseModel):
    id: str
    name: str
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind
    storage_dir: str
    status: ProfileStatus = ProfileStatus.ACTIVE
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)
    proxy_assigned: bool = False
    proxy: str | None = None
    session_status: BrowserSessionStatus = BrowserSessionStatus.IDLE


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    site_key: str
    sim_id: str
    runtime: RuntimeKind
    status: JobStatus = JobStatus.QUEUED
    profile_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JobEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    event_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class CaptchaResult(BaseModel):
    outcome: CaptchaOutcome
    token: str | None = None
    manual_checkpoint_id: str | None = None
    error: str | None = None


class OtpRequest(BaseModel):
    sim_id: str
    site_key: str
    sender_hints: tuple[str, ...] = ()
    requested_after: datetime
    timeout_seconds: float = 120.0


class OtpMessage(BaseModel):
    sim_id: str
    site_key: str
    sender: str
    otp: str
    received_at: datetime


class RegistrationContext(BaseModel):
    job: JobRecord
    site: SiteSpec
    profile_id: str
    proxy_url: str | None = None


class RegistrationResult(BaseModel):
    status: JobStatus
    account_identifier: str | None = None
    message: str
    artifacts: list[str] = Field(default_factory=list)


class ProxyLeaseSummary(BaseModel):
    idproxy: int
    loaiproxy: str
    ip: str
    port: int
    type: str
    expires_at: int | None = None
    masked_proxy: str


class ProxyEnsureRequest(BaseModel):
    policy: ProxyPolicy = ProxyPolicy.STICKY_PROFILE


class ProxyAttachRequest(BaseModel):
    idproxy: int
    policy: ProxyPolicy = ProxyPolicy.STICKY_PROFILE


class ProfileProxyAssignment(BaseModel):
    profile_id: str
    policy: ProxyPolicy
    proxy: ProxyLeaseSummary
    assigned_at: datetime = Field(default_factory=utc_now)


class SecretCheck(BaseModel):
    configured: bool
    enabled: bool = True
    missing: list[str] = Field(default_factory=list)
