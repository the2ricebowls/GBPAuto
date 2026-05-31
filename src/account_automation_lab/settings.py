from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8080
    public_base_url: str = "http://127.0.0.1:8080"
    allowed_host_suffixes: str = ".internal,.test,localhost,127.0.0.1"

    database_backend: str = "supabase"
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    sim_otp_api_base_url: str = ""
    sim_otp_api_key: str = ""
    proxyvn_api_key: str = ""
    proxyvn_base_url: str = "https://proxy.vn/apiv2"
    proxyvn_default_loaiproxy: str = "4Gvinaphone"
    proxyvn_default_days: int = Field(default=1, ge=1)
    proxyvn_default_type: str = "HTTP"
    captcha_provider_enabled: bool = False
    captcha_provider_base_url: str = ""
    captcha_provider_api_key: str = ""
    browser_profile_storage_root: str = ".profiles"
    cloakbrowser_enabled: bool = True
    cloakbrowser_binary_path: str = ""
    cloakbrowser_headless: bool = False
    cloakbrowser_humanize: bool = True
    cloakbrowser_filter_no_sandbox: bool = True
    cloakbrowser_fit_screen: bool = True
    cloakbrowser_start_maximized: bool = True
    cloakbrowser_window_width: int = Field(default=0, ge=0)
    cloakbrowser_window_height: int = Field(default=0, ge=0)

    max_global_concurrency: int = Field(default=2, ge=1)
    max_site_concurrency: int = Field(default=1, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def allowed_suffix_tuple(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.allowed_host_suffixes.split(",") if part.strip())


def get_settings() -> Settings:
    return Settings()
