"""多 LLM 提供商配置：从环境变量加载，支持星火 Lite 与 Sub2API 等 OpenAI 兼容网关。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# 各提供商默认可选模型（可被 PROVIDER_*_MODELS 覆盖）
_DEFAULT_MODEL_LISTS: dict[str, tuple[str, ...]] = {
    "spark-lite": ("lite", "generalv3.5", "4.0Ultra", "max-32k", "generalv3", "pro-128k"),
    "sub2api": (
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.5",
        "gpt-5.2",
        "gpt-5.3-codex",
        "glm-5.1",
        "glm-5-turbo",
    ),
}


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    label: str
    api_key: str
    base_url: str
    model: str
    models: tuple[str, ...]


def _reload_env() -> None:
    if _DOTENV_PATH.is_file():
        load_dotenv(_DOTENV_PATH, override=True)


def _normalize_base_url(url: str) -> str:
    u = url.strip().rstrip("/")
    if not u:
        return ""
    if u.endswith("/v1"):
        return f"{u}/"
    return f"{u}/v1/"


def _parse_models(raw: str, default_model: str, provider_id: str) -> tuple[str, ...]:
    items = [m.strip() for m in raw.split(",") if m.strip()]
    if not items:
        items = list(_DEFAULT_MODEL_LISTS.get(provider_id, (default_model,)))
    if default_model and default_model not in items:
        items = [default_model, *items]
    # 去重且保持顺序
    seen: set[str] = set()
    out: list[str] = []
    for m in items:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return tuple(out)


def _fetch_remote_models(base_url: str, api_key: str, timeout: float = 8.0) -> tuple[str, ...]:
    """从 OpenAI 兼容 /v1/models 拉取模型 id 列表。"""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        url = f"{root}/models"
    else:
        url = f"{root}/v1/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return ()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return ()
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]).strip())
    return tuple(ids)


def _read_provider(
    provider_id: str,
    *,
    default_label: str,
    default_base: str,
    default_model: str,
    fallback_key: str = "",
    fallback_base: str = "",
    fallback_model: str = "",
) -> ProviderConfig | None:
    prefix = f"PROVIDER_{provider_id.upper().replace('-', '_')}_"
    api_key = os.getenv(f"{prefix}API_KEY", "").strip() or fallback_key.strip()
    if not api_key:
        return None
    raw_base = os.getenv(f"{prefix}BASE_URL", "").strip() or fallback_base.strip() or default_base
    base_url = _normalize_base_url(raw_base)
    model = (
        os.getenv(f"{prefix}MODEL", "").strip()
        or fallback_model.strip()
        or default_model
    )
    models_raw = os.getenv(f"{prefix}MODELS", "").strip()
    models = _parse_models(models_raw, model, provider_id)

    fetch_flag = os.getenv(f"{prefix}FETCH_MODELS", "").strip().lower()
    if fetch_flag in ("1", "true", "yes") or (not models_raw and provider_id == "sub2api"):
        remote = _fetch_remote_models(base_url, api_key)
        if remote:
            models = _parse_models(",".join(remote), model, provider_id)

    label = os.getenv(f"{prefix}LABEL", "").strip() or default_label
    return ProviderConfig(
        id=provider_id,
        label=label,
        api_key=api_key,
        base_url=base_url,
        model=model,
        models=models,
    )


def load_providers() -> dict[str, ProviderConfig]:
    """加载已配置密钥的提供商；spark-lite 可回退到旧版 OPENAI_*。"""
    _reload_env()
    legacy_key = os.getenv("OPENAI_API_KEY", "").strip()
    legacy_base = os.getenv("OPENAI_BASE_URL", "").strip()
    legacy_model = os.getenv("OPENAI_MODEL", "lite").strip() or "lite"

    spark = _read_provider(
        "spark-lite",
        default_label="讯飞星火 Lite",
        default_base="https://spark-api-open.xf-yun.com/v1/",
        default_model="lite",
        fallback_key=legacy_key,
        fallback_base=legacy_base,
        fallback_model=legacy_model,
    )
    sub2api = _read_provider(
        "sub2api",
        default_label="Sub2API 商城",
        default_base="https://sub2api-mall.faibak.com/v1/",
        default_model="gpt-5.4-mini",
    )

    out: dict[str, ProviderConfig] = {}
    if spark:
        out[spark.id] = spark
    if sub2api:
        out[sub2api.id] = sub2api
    return out


def default_provider_id(providers: dict[str, ProviderConfig]) -> str:
    if not providers:
        return ""
    preferred = os.getenv("DEFAULT_PROVIDER", "").strip()
    if preferred in providers:
        return preferred
    if "spark-lite" in providers:
        return "spark-lite"
    return next(iter(providers))


def _pick_model(cfg: ProviderConfig, model_override: str | None) -> str:
    override = (model_override or "").strip()
    if override:
        if override in cfg.models:
            return override
        # 允许网关新增模型名，仍尝试使用
        return override
    return cfg.model if cfg.model in cfg.models else cfg.models[0]


def resolve_provider(
    provider_id: str | None,
    model_override: str | None = None,
) -> ProviderConfig:
    providers = load_providers()
    if not providers:
        raise ValueError(
            "未配置任何 LLM 提供商：请在 backend/.env 设置 PROVIDER_*_API_KEY 或 OPENAI_API_KEY"
        )
    pid = (provider_id or "").strip() or default_provider_id(providers)
    cfg = providers.get(pid)
    if not cfg:
        available = ", ".join(sorted(providers))
        raise ValueError(f"未知提供商 '{pid}'，可用：{available}")
    effective = _pick_model(cfg, model_override)
    if effective == cfg.model:
        return cfg
    return replace(cfg, model=effective)


def providers_for_api() -> dict:
    """供 GET /chat/providers 返回的 JSON 结构（不含密钥）。"""
    providers = load_providers()
    default_id = default_provider_id(providers)
    return {
        "default_provider": default_id,
        "providers": [
            {
                "id": p.id,
                "label": p.label,
                "model": p.model,
                "models": list(p.models),
                "base_url": p.base_url,
            }
            for p in providers.values()
        ],
    }
