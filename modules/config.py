import os
from pathlib import Path


def load_local_env(path: str = ".env") -> None:
    """Carrega .env local simples sem depender de pacote externo."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_secret(name: str, default: str = "") -> str:
    """Busca segredo em variável de ambiente ou st.secrets."""
    load_local_env()
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get(name, default))
    except Exception:
        return default
