from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="UPENFLOW_", extra="ignore")

    database_url: str = "sqlite:///./upenflow.db"
    otp_pepper: str = "local-development-only-change-me"
    cookie_secure: bool = True
    otp_validity_seconds: int = 300
    otp_resend_seconds: int = 60
    session_idle_seconds: int = 1800
    session_absolute_seconds: int = 43200
    auth_rate_limit_window_seconds: int = 900
    auth_rate_limit_ip_attempts: int = 30
    auth_rate_limit_email_attempts: int = 10
    first_admin_email: str | None = None
    first_admin_password: str | None = None
    first_admin_name: str = "Super Admin"
    frontend_base_url: str = "http://localhost:5173"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "notify@localhost"
    service_a_api_key: str | None = None
    service_a_hmac_secret: str | None = None
    service_b_dlr_api_key: str | None = None
    service_b_dlr_hmac_secret: str | None = None
    service_b_reply_api_key: str | None = None
    redis_url: str | None = None
    auto_create_schema: bool = True
    secret_encryption_key: str | None = None
    enable_scheduler: bool = True
    scheduler_interval_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()