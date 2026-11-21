"""Typed settings (blueprint Appendix C names where one already existed)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

from lmqa_models.envfile import ROOT, merged_env

EMBEDDING_DIM = 768  # fixed by the schema: chunks.embedding vector(768)
DEFAULT_FALLBACK_MODELS = ("gemini-3-flash-preview", "gemini-3.5-flash-lite")


class ConfigError(RuntimeError):
    """A required setting is missing. The message names the setting, never its value."""


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"
    app_base_url: str = "http://localhost:3000"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"

    # Auth0 authenticates; PostgreSQL authorizes (blueprint 1.2)
    auth0_domain: str | None = None
    auth0_audience: str | None = None
    auth0_claims_namespace: str = "https://claims.onekami.site"
    auth0_issuer_override: str | None = None  # local simulation only
    auth0_jwks_url_override: str | None = None  # local simulation only

    # PostgreSQL: one container, three roles (lmqa_owner, lmqa_app, lmqa_system)
    db_host: str = "localhost"
    db_port: int = 5434
    db_name: str = "lmqa"
    db_superuser_password: str | None = None
    db_owner_password: str | None = None
    db_app_password: str | None = None
    db_system_password: str | None = None

    # Join codes (blueprint 7.6)
    code_pepper_id: str = "v1"
    code_pepper: str | None = None

    # Gemini (blueprint 11.8 provider boundary)
    gemini_api_key: str | None = None
    llm_model: str = "gemini-flash-latest"
    llm_fallback_models: tuple[str, ...] = DEFAULT_FALLBACK_MODELS
    llm_thinking_level: str | None = "low"
    llm_max_output_tokens: int = 8192
    llm_timeout_seconds: float = 40.0
    embedding_model: str = "gemini-embedding-001"
    verify_entailment: bool = True

    # RAG (blueprint 11.3, 11.4 defaults scaled to the MVP)
    retrieval_top_k: int = 8
    context_budget_tokens: int = 12000

    # Limits
    upload_max_mb: int = 25
    queries_per_minute: int = 20
    data_dir: Path = ROOT / "data"

    def __repr__(self) -> str:  # never print secrets
        return f"Settings(app_env={self.app_env!r}, db={self.db_host}:{self.db_port}/{self.db_name})"

    def dsn(self, role: str, *, database: str | None = None) -> str:
        passwords = {
            "postgres": self.db_superuser_password,
            "lmqa_owner": self.db_owner_password,
            "lmqa_app": self.db_app_password,
            "lmqa_system": self.db_system_password,
        }
        password = passwords[role]
        if not password:
            raise ConfigError(f"Database password for role {role} is not set. Run: make setup")
        db = database or (self.db_name if role != "postgres" else "postgres")
        return f"postgresql://{role}:{quote(password, safe='')}@{self.db_host}:{self.db_port}/{db}"

    @property
    def auth0_issuer(self) -> str:
        if self.auth0_issuer_override:
            return self.auth0_issuer_override
        if not self.auth0_domain:
            raise ConfigError("AUTH0_DOMAIN is not set")
        return f"https://{self.auth0_domain}/"

    @property
    def auth0_jwks_url(self) -> str:
        return self.auth0_jwks_url_override or f"{self.auth0_issuer}.well-known/jwks.json"

    @property
    def llm_models(self) -> list[str]:
        """Primary model first, then fallbacks, without duplicates."""
        return list(dict.fromkeys([self.llm_model, *self.llm_fallback_models]))

    def with_overrides(self, **kwargs: object) -> Settings:
        return replace(self, **kwargs)  # type: ignore[arg-type]


def _int(env: dict[str, str], key: str, default: int) -> int:
    try:
        return int(env.get(key, default))
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc


def load_settings() -> Settings:
    env = merged_env()
    thinking = env.get("LLM_THINKING_LEVEL", "low").strip().lower()
    fallbacks = env.get("LLM_FALLBACK_MODELS")
    return Settings(
        app_env=env.get("APP_ENV", "local"),
        app_base_url=env.get("APP_BASE_URL", "http://localhost:3000").rstrip("/"),
        api_port=_int(env, "API_PORT", 8000),
        log_level=env.get("LOG_LEVEL", "INFO"),
        auth0_domain=(env.get("AUTH0_DOMAIN") or "").removeprefix("https://").rstrip("/") or None,
        auth0_audience=env.get("AUTH0_AUDIENCE_MAIN"),
        auth0_claims_namespace=env.get("AUTH0_CLAIMS_NAMESPACE", "https://claims.onekami.site").rstrip("/"),
        db_host=env.get("LMQA_DB_HOST", "localhost"),
        db_port=_int(env, "LMQA_DB_PORT", 5434),
        db_name=env.get("LMQA_DB_NAME", "lmqa"),
        db_superuser_password=env.get("LMQA_DB_SUPERUSER_PASSWORD"),
        db_owner_password=env.get("LMQA_DB_OWNER_PASSWORD"),
        db_app_password=env.get("LMQA_DB_APP_PASSWORD"),
        db_system_password=env.get("LMQA_DB_SYSTEM_PASSWORD"),
        code_pepper_id=env.get("CODE_PEPPER_ID", "v1"),
        code_pepper=env.get(f"CODE_PEPPER_{env.get('CODE_PEPPER_ID', 'v1').upper()}"),
        gemini_api_key=env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY"),
        llm_model=env.get("LLM_MODEL", "gemini-flash-latest").removeprefix("models/"),
        llm_fallback_models=tuple(m.strip() for m in fallbacks.split(",") if m.strip())
        if fallbacks is not None
        else DEFAULT_FALLBACK_MODELS,
        llm_thinking_level=None if thinking in {"", "off", "none"} else thinking,
        llm_max_output_tokens=_int(env, "LLM_MAX_OUTPUT_TOKENS", 8192),
        llm_timeout_seconds=float(env.get("LLM_TIMEOUT_SECONDS", "40")),
        embedding_model=env.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001").removeprefix("models/"),
        verify_entailment=env.get("VERIFY_ENTAILMENT", "on").lower() not in {"off", "false", "0"},
        retrieval_top_k=_int(env, "RETRIEVAL_TOP_K", 8),
        context_budget_tokens=_int(env, "LLM_CONTEXT_BUDGET", 12000),
        upload_max_mb=_int(env, "UPLOAD_MAX_MB", 25),
        queries_per_minute=_int(env, "QUERIES_PER_MINUTE", 20),
        data_dir=Path(env.get("LMQA_DATA_DIR", str(ROOT / "data"))),
    )
