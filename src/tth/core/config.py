# src/tth/core/config.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic import AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override wins on conflicts."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


class ComponentConfig(BaseModel):
    mode: str = "api"  # "api" | "self_host"
    primary: str = ""
    fallback: list[str] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Loaded from YAML
    app: AppConfig = Field(default_factory=AppConfig)
    components: dict[str, Any] = Field(default_factory=dict)
    personas: dict[str, Any] = Field(default_factory=dict)

    # API keys — accept both bare name (OPENAI_API_KEY) and prefixed (TTH_OPENAI_API_KEY)
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TTH_OPENAI_API_KEY", "OPENAI_API_KEY", "openai_api_key"),
    )
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "TTH_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "anthropic_api_key"
        ),
    )
    elevenlabs_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "TTH_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY", "elevenlabs_api_key"
        ),
    )
    tavus_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TTH_TAVUS_API_KEY", "TAVUS_API_KEY", "tavus_api_key"),
    )
    heygen_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TTH_HEYGEN_API_KEY", "HEYGEN_API_KEY", "heygen_api_key"),
    )

    profile: str = "api_only_mac"

    @model_validator(mode="before")
    @classmethod
    def load_yaml(cls, values: dict) -> dict:
        profile = os.getenv("TTH_PROFILE", values.get("profile", "api_only_mac"))
        # Look for config relative to cwd or project root
        for search_root in [Path.cwd(), Path(__file__).parent.parent.parent.parent.parent]:
            base_path = search_root / "config" / "base.yaml"
            if base_path.exists():
                cfg: dict = yaml.safe_load(base_path.read_text()) or {}
                profile_path = search_root / "config" / "profiles" / f"{profile}.yaml"
                if profile_path.exists():
                    profile_data = yaml.safe_load(profile_path.read_text()) or {}
                    if profile_data:
                        cfg = deep_merge(cfg, profile_data)
                # YAML values have lowest priority — env vars override them
                return {**cfg, **values}
        # No config found — use defaults
        return values


# Module-level singleton; imported everywhere
settings = Settings()
