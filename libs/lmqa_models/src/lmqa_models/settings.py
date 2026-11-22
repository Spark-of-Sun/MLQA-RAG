"""Typed settings (blueprint Appendix C names where one already existed)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

from lmqa_models.envfile import ROOT, merged_env
from lmqa_models.quota import DEFAULT_LIMITS, Limits, QuotaTracker, fingerprint, parse_limits, tracker_for

EMBEDDING_DIM = 768  # fixed by the schema: chunks.embedding vector(768)
# Answer and verification chain on the Gemini free tier: the strongest models first (about 20 requests a day each),
# then the Flash-Lite models (about 500 a day each) so answers keep working when the daily quotas run out. Each model
# is tried on every key (GEMINI_API_KEYS) before the next model.
DEFAULT_MODEL = "gemini-4-hydrogen"
DEFAULT_FALLBACK_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
)
# Query planning (rewriting follow-ups, alternative phrasings) is a short task: high-quota Flash-Lite models, so it
# never spends the strong models' small daily quota.
DEFAULT_QUERY_MODEL = "gemini-3.5-flash-lite"
DEFAULT_QUERY_FALLBACK_MODELS = ("gemini-3.1-flash-lite", "gemini-2.5-flash-lite")
# Embeddings: each model has its own daily quota. Passages are embedded with the first model that has quota left,
# and a document always uses one model throughout; search embeds the question with every model in use.
DEFAULT_EMBEDDING_FALLBACK_MODELS = ("gemini-embedding-2",)
# RERANK_MODEL=llm: the answer models score passages instead of a local cross-encoder. By default they are tried in
# reverse order (Flash-Lite first, the strongest last), so re-ranking spends the high-quota models and leaves the
# strong models' small daily quota for answers. A shorter timeout: a slow model is skipped instead of stalling search.
LLM_RERANK = "llm"
RERANK_TIMEOUT_SECONDS = 20.0


# Answer providers (blueprint 11.8 provider boundary). Embeddings always use Gemini (GEMINI_EMBEDDING_MODEL).
# kind: the wire protocol. base: default endpoint, overridable with <PROVIDER>_BASE_URL. key: the API key setting.
PROVIDERS: dict[str, dict[str, str | None]] = {
    "gemini": {"kind": "gemini", "base": "https://generativelanguage.googleapis.com/v1beta", "key": "GEMINI_API_KEY"},
    "anthropic": {"kind": "anthropic", "base": "https://api.anthropic.com/v1", "key": "ANTHROPIC_API_KEY"},
    "openai": {"kind": "openai", "base": "https://api.openai.com/v1", "key": "OPENAI_API_KEY"},
    "groq": {"kind": "openai", "base": "https://api.groq.com/openai/v1", "key": "GROQ_API_KEY"},
    "openrouter": {"kind": "openai", "base": "https://openrouter.ai/api/v1", "key": "OPENROUTER_API_KEY"},
    "deepseek": {"kind": "openai", "base": "https://api.deepseek.com/v1", "key": "DEEPSEEK_API_KEY"},
    "mistral": {"kind": "openai", "base": "https://api.mistral.ai/v1", "key": "MISTRAL_API_KEY"},
    "together": {"kind": "openai", "base": "https://api.together.xyz/v1", "key": "TOGETHER_API_KEY"},
    "ollama": {"kind": "openai", "base": "http://127.0.0.1:11434/v1", "key": None},
    # Any other OpenAI-compatible server (LM Studio, vLLM, a gateway): LLM_BASE_URL and LLM_API_KEY.
    "openai_compatible": {"kind": "openai", "base": None, "key": "LLM_API_KEY"},
}


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

    # Answer models (blueprint 11.8 provider boundary); embeddings stay on Gemini
    gemini_api_key: str | None = None  # the first of gemini_api_keys
    # One key per Google Cloud project, each with its own quota; requests rotate across them (GEMINI_API_KEYS).
    gemini_api_keys: tuple[str, ...] = ()
    model_limits: tuple[tuple[str, Limits], ...] = tuple(DEFAULT_LIMITS.items())
    quota_tracking: bool = True  # count requests locally and skip a key/model before the provider refuses it
    quota_file: Path = ROOT / "data" / "usage" / "quota.json"
    llm_provider: str = "gemini"
    llm_model: str = DEFAULT_MODEL
    # Each entry is a model of llm_provider, or "provider:model" for another provider.
    llm_fallback_models: tuple[str, ...] = DEFAULT_FALLBACK_MODELS
    llm_keys: tuple[tuple[str, str], ...] = ()  # provider -> API key (pairs, so the dataclass stays hashable)
    llm_base_urls: tuple[tuple[str, str], ...] = ()  # provider -> endpoint
    llm_temperature: float | None = None  # unset: the provider's default (some reasoning models accept no other)
    llm_thinking_level: str | None = "low"  # Gemini only
    llm_max_output_tokens: int = 8192
    llm_timeout_seconds: float = 40.0
    embedding_model: str = "gemini-embedding-001"
    embedding_fallback_models: tuple[str, ...] = DEFAULT_EMBEDDING_FALLBACK_MODELS
    query_model: str | None = DEFAULT_QUERY_MODEL  # None: query planning uses the answer chain
    query_fallback_models: tuple[str, ...] = DEFAULT_QUERY_FALLBACK_MODELS
    verify_entailment: bool = True

    # RAG (blueprint 11.3, 11.4)
    retrieval_top_k: int = 12  # passages kept for the answer, at most
    retrieval_prefetch: int = 100  # candidates per search channel and query (dense, full text, exact terms)
    retrieval_neighbors: int = 1  # adjacent passages of the same section added around the best hits (0: off)
    query_expansion: bool = True  # also search with model-written alternative phrasings of the question
    rerank_model: str | None = "BAAI/bge-reranker-v2-m3"  # local cross-encoder, LLM_RERANK, or None: fused ranking
    rerank_llm_models: tuple[str, ...] = ()  # chain for LLM_RERANK; empty: the answer chain in reverse
    rerank_candidates: int = 40  # fused candidates the cross-encoder scores
    rerank_min_score: float = 0.05  # relevance probability a passage needs to be used (calibrate with make eval)
    model_cache_dir: Path = ROOT / "data" / "models"
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
    def llm_chain(self) -> list[tuple[str, str]]:
        """(provider, model) pairs: the primary first, then fallbacks, without duplicates or empty models."""
        pairs = [(self.llm_provider, self.llm_model)] if self.llm_model else []
        for entry in self.llm_fallback_models:
            head, sep, rest = entry.partition(":")
            # "ollama:llama3.1:8b" names a provider; "llama3.1:8b" is a model of the primary provider.
            pairs.append((head, rest) if sep and head in PROVIDERS and rest else (self.llm_provider, entry))
        return list(dict.fromkeys(pairs))

    @property
    def llm_models(self) -> list[str]:
        """Human-readable chain, e.g. ['gemini-3.1-flash-lite', 'groq:llama-3.3-70b-versatile']."""
        return [model_label(p, m) for p, m in self.llm_chain]

    def llm_key(self, provider: str) -> str | None:
        if provider == "gemini":
            return self.gemini_api_key
        return dict(self.llm_keys).get(provider)

    def llm_base_url(self, provider: str) -> str | None:
        return dict(self.llm_base_urls).get(provider) or PROVIDERS.get(provider, {}).get("base")

    @property
    def embedding_models(self) -> list[str]:
        return list(dict.fromkeys([self.embedding_model, *self.embedding_fallback_models]))

    def planner_settings(self) -> Settings | None:
        """Settings for the query-planning client: the query model and its fallbacks, then the answer chain."""
        if not self.query_model:
            return None
        head, sep, rest = self.query_model.partition(":")
        provider, model = (head, rest) if sep and head in PROVIDERS and rest else (self.llm_provider, self.query_model)
        others = [*self.query_fallback_models, *(f"{p}:{m}" for p, m in self.llm_chain)]
        return replace(self, llm_provider=provider, llm_model=model, llm_fallback_models=tuple(others))

    def reranker_settings(self) -> Settings:
        """Settings for the LLM re-ranking client: RERANK_LLM_MODELS, or the answer chain from the weakest model."""
        entries = list(self.rerank_llm_models) or [f"{p}:{m}" for p, m in reversed(self.llm_chain)]
        if not entries:
            return self
        head, sep, rest = entries[0].partition(":")
        provider, model = (head, rest) if sep and head in PROVIDERS and rest else (self.llm_provider, entries[0])
        return replace(
            self,
            llm_provider=provider,
            llm_model=model,
            llm_fallback_models=tuple(entries[1:]),
            llm_timeout_seconds=min(self.llm_timeout_seconds, RERANK_TIMEOUT_SECONDS),
        )

    def quota(self) -> QuotaTracker | None:
        """The process-wide local rate-limit tracker, or None when QUOTA_TRACKING is off."""
        return tracker_for(dict(self.model_limits), self.quota_file) if self.quota_tracking else None

    def gemini_keys(self) -> list[tuple[str, str]]:
        """(fingerprint, key) for every configured Gemini key, primary first. Fingerprints are safe to log."""
        return [(fingerprint(k), k) for k in self.gemini_api_keys]

    def with_overrides(self, **kwargs: object) -> Settings:
        return replace(self, **kwargs)  # type: ignore[arg-type]


def model_label(provider: str, model: str) -> str:
    """Gemini models keep their plain names (as in earlier audit records); others are prefixed."""
    return model if provider == "gemini" else f"{provider}:{model}"


def _secret(env: dict[str, str], key: str | None) -> str | None:
    """A setting's value; empty and template placeholders such as <OPENAI_API_KEY> count as unset."""
    value = (env.get(key) or "").strip() if key else ""
    return None if not value or (value.startswith("<") and value.endswith(">")) else value


def _int(env: dict[str, str], key: str, default: int) -> int:
    try:
        return int(env.get(key, default))
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc


def _models(env: dict[str, str], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """A comma-separated model list; unset or empty means the default, `none` means no fallbacks."""
    value = (env.get(key) or "").strip()
    if not value:
        return default
    if value.lower() in {"none", "off"}:
        return ()
    return tuple(m.strip().removeprefix("models/") for m in value.split(",") if m.strip())


def _float(env: dict[str, str], key: str, default: float) -> float:
    try:
        return float(env.get(key, default))
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc


def _on(env: dict[str, str], key: str, default: bool = True) -> bool:
    value = (env.get(key) or "").strip().lower()
    return default if not value else value not in {"off", "false", "0", "no"}


def load_settings() -> Settings:
    env = merged_env()
    thinking = env.get("LLM_THINKING_LEVEL", "low").strip().lower()
    fallbacks = env.get("LLM_FALLBACK_MODELS")
    provider = (_secret(env, "LLM_PROVIDER") or "gemini").lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"LLM_PROVIDER must be one of: {', '.join(PROVIDERS)}")
    model = (_secret(env, "LLM_MODEL") or (DEFAULT_MODEL if provider == "gemini" else "")).removeprefix("models/")
    if fallbacks is not None:
        fallback_models = tuple(m.strip().removeprefix("models/") for m in fallbacks.split(",") if m.strip())
    else:  # the built-in list is Gemini models; other providers fall back only to what you list
        fallback_models = DEFAULT_FALLBACK_MODELS if provider == "gemini" else ()
    keys = tuple(
        (name, value) for name, spec in PROVIDERS.items() if name != "gemini" and (value := _secret(env, spec["key"]))
    )
    bases = {name: value for name in PROVIDERS if (value := _secret(env, f"{name.upper()}_BASE_URL"))}
    if value := _secret(env, "LLM_BASE_URL"):
        bases.setdefault("openai_compatible", value)
    rerank = (_secret(env, "RERANK_MODEL") or "BAAI/bge-reranker-v2-m3").strip()
    keys = list(
        dict.fromkeys(
            k
            for k in [
                _secret(env, "GEMINI_API_KEY") or _secret(env, "GOOGLE_API_KEY"),
                *((env.get("GEMINI_API_KEYS") or "").split(",")),
            ]
            if k and _secret({"k": k}, "k")
        )
    )
    keys = [k.strip() for k in keys if k.strip()]
    limits = dict(DEFAULT_LIMITS)
    if extra := _secret(env, "MODEL_LIMITS"):
        try:
            limits.update(parse_limits(extra))
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    query_model = _secret(env, "QUERY_MODEL") or (DEFAULT_QUERY_MODEL if provider == "gemini" else None)
    if query_model and query_model.lower() in {"off", "none", "same"}:
        query_model = None
    temperature = _secret(env, "LLM_TEMPERATURE")
    try:
        temp = float(temperature) if temperature else None
    except ValueError as exc:
        raise ConfigError("LLM_TEMPERATURE must be a number") from exc
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
        gemini_api_key=keys[0] if keys else None,
        gemini_api_keys=tuple(keys),
        model_limits=tuple(limits.items()),
        quota_tracking=_on(env, "QUOTA_TRACKING"),
        quota_file=Path(env.get("QUOTA_FILE", str(ROOT / "data" / "usage" / "quota.json"))),
        llm_provider=provider,
        llm_model=model,
        llm_fallback_models=fallback_models,
        llm_keys=keys,
        llm_base_urls=tuple((k, v.rstrip("/")) for k, v in bases.items()),
        llm_temperature=temp,
        llm_thinking_level=None if thinking in {"", "off", "none"} else thinking,
        llm_max_output_tokens=_int(env, "LLM_MAX_OUTPUT_TOKENS", 8192),
        llm_timeout_seconds=float(env.get("LLM_TIMEOUT_SECONDS", "40")),
        embedding_model=env.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001").removeprefix("models/"),
        embedding_fallback_models=_models(env, "GEMINI_EMBEDDING_FALLBACK_MODELS", DEFAULT_EMBEDDING_FALLBACK_MODELS),
        query_model=query_model,
        query_fallback_models=_models(
            env, "QUERY_FALLBACK_MODELS", DEFAULT_QUERY_FALLBACK_MODELS if provider == "gemini" else ()
        ),
        verify_entailment=_on(env, "VERIFY_ENTAILMENT"),
        retrieval_top_k=_int(env, "RETRIEVAL_TOP_K", 12),
        retrieval_prefetch=_int(env, "RETRIEVAL_PREFETCH", 100),
        retrieval_neighbors=_int(env, "RETRIEVAL_NEIGHBORS", 1),
        query_expansion=_on(env, "QUERY_EXPANSION"),
        rerank_model=None
        if rerank.lower() in {"off", "none", "false", "0"}
        else (LLM_RERANK if rerank.lower() == LLM_RERANK else rerank),
        rerank_llm_models=_models(env, "RERANK_LLM_MODELS", ()),
        rerank_candidates=_int(env, "RERANK_CANDIDATES", 40),
        rerank_min_score=_float(env, "RERANK_MIN_SCORE", 0.05),
        model_cache_dir=Path(env.get("MODEL_CACHE_DIR", str(ROOT / "data" / "models"))),
        context_budget_tokens=_int(env, "LLM_CONTEXT_BUDGET", 12000),
        upload_max_mb=_int(env, "UPLOAD_MAX_MB", 25),
        queries_per_minute=_int(env, "QUERIES_PER_MINUTE", 20),
        data_dir=Path(env.get("LMQA_DATA_DIR", str(ROOT / "data"))),
    )
