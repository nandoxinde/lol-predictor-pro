import os
from html import unescape
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_LOADED = False


def project_root() -> Path:
    return _PROJECT_ROOT


def load_local_env(path: str | None = None) -> None:
    """Carrega .env local simples sem depender de pacote externo."""
    global _ENV_LOADED
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.extend([
        _PROJECT_ROOT / ".env",
        Path.cwd() / ".env",
    ])
    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        _ENV_LOADED = True
        return


def get_secret(name: str, default: str = "") -> str:
    """Busca segredo em variável de ambiente ou st.secrets."""
    load_local_env()
    aliases = {
        "APIFY_TOKEN": ("APIFY_TOKEN", "APIFY_API_TOKEN", "APIFY_API_KEY"),
        "ODDSPAPI_KEY": ("ODDSPAPI_KEY", "ODDSPAPI_API_KEY", "ODDS_PAPI_KEY", "ODDSPAPI_TOKEN"),
    }
    keys = aliases.get(name, (name,))
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    try:
        import streamlit as st
        for key in keys:
            value = st.secrets.get(key)
            if value:
                return str(value)
    except Exception:
        pass
    return default


def get_apify_token() -> str:
    load_local_env()
    return get_secret("APIFY_TOKEN")
