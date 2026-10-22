from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017/"
    mongodb_db: str = "survey_project1"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_origin: str = "http://127.0.0.1:8000"
    session_ttl_seconds: int = Field(default=86400, ge=60)
    respondent_hmac_secret: str = Field(min_length=32)
    hmac_key_version: int = 1
    cookie_secure: bool = False
    testing: bool = False
    max_definition_bytes: int = 512 * 1024

    @field_validator("respondent_hmac_secret")
    @classmethod
    def reject_placeholder(cls, value):
        if value.startswith("replace-with"):
            raise ValueError("请先运行 scripts/setup.py 生成持久本地密钥")
        return value
