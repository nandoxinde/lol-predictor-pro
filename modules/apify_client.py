"""Cliente leve para a API Apify (Actors + datasets)."""

from __future__ import annotations

import time
from typing import Any

import requests

from modules.config import get_apify_token

APIFY_BASE = "https://api.apify.com/v2"
DEFAULT_TIMEOUT = 180


class ApifyClient:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else get_apify_token()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LoLPredictorPro/2.0"})

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def verify_token(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "Token Apify ausente."
        try:
            response = self.session.get(
                f"{APIFY_BASE}/users/me",
                params={"token": self.token},
                timeout=20,
            )
        except Exception as exc:
            return False, f"Falha ao validar Apify: {exc}"
        if response.status_code != 200:
            return False, f"Token Apify recusado (HTTP {response.status_code})."
        username = (response.json().get("data") or {}).get("username") or "conta Apify"
        return True, f"Apify conectado ({username})"

    def run_actor_sync(self, actor_id: str, run_input: dict, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
        return self.run_actor_sync_detail(actor_id, run_input, timeout).get("items") or []

    def run_actor_sync_detail(
        self,
        actor_id: str,
        run_input: dict,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict:
        """Executa actor sync e devolve itens + metadados de erro."""
        if not self.configured:
            return {"ok": False, "items": [], "error": "Token Apify ausente.", "status_code": 0}
        actor = self._normalize_actor_id(actor_id)
        if not actor:
            return {"ok": False, "items": [], "error": "Actor Apify inválido.", "status_code": 0}

        url = f"{APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items"
        try:
            response = self.session.post(
                url,
                params={"token": self.token, "timeout": timeout, "memory": 4096},
                json=run_input,
                timeout=timeout + 30,
            )
        except Exception as exc:
            return {"ok": False, "items": [], "error": f"Timeout/rede Apify: {exc}", "status_code": 0}

        if response.status_code not in (200, 201):
            detail = response.text[:240].replace("\n", " ")
            return {
                "ok": False,
                "items": [],
                "error": f"Apify HTTP {response.status_code}: {detail}",
                "status_code": response.status_code,
            }

        payload = response.json()
        items: list[dict] = []
        if isinstance(payload, list):
            items = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            raw_items = payload.get("items")
            if isinstance(raw_items, list):
                items = [item for item in raw_items if isinstance(item, dict)]
        return {"ok": bool(items), "items": items, "error": None if items else "Actor concluiu sem itens.", "status_code": response.status_code}

    def run_actor(self, actor_id: str, run_input: dict, wait_secs: int = DEFAULT_TIMEOUT) -> dict | None:
        """Executa actor assíncrono e aguarda conclusão."""
        if not self.configured:
            return None
        actor = self._normalize_actor_id(actor_id)
        if not actor:
            return None

        try:
            start = self.session.post(
                f"{APIFY_BASE}/acts/{actor}/runs",
                params={"token": self.token},
                json=run_input,
                timeout=30,
            )
        except Exception:
            return None

        if start.status_code not in (200, 201):
            return None

        run = start.json().get("data") or {}
        run_id = run.get("id")
        if not run_id:
            return None

        deadline = time.time() + max(10, wait_secs)
        while time.time() < deadline:
            try:
                status_resp = self.session.get(
                    f"{APIFY_BASE}/actor-runs/{run_id}",
                    params={"token": self.token},
                    timeout=20,
                )
            except Exception:
                time.sleep(2)
                continue

            if status_resp.status_code != 200:
                time.sleep(2)
                continue

            data = status_resp.json().get("data") or {}
            state = str(data.get("status") or "").upper()
            if state in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
                return data
            time.sleep(2)
        return None

    def get_dataset_items(self, dataset_id: str, limit: int = 200) -> list[dict]:
        if not self.configured or not dataset_id:
            return []
        try:
            response = self.session.get(
                f"{APIFY_BASE}/datasets/{dataset_id}/items",
                params={"token": self.token, "format": "json", "limit": limit},
                timeout=30,
            )
        except Exception:
            return []
        if response.status_code != 200:
            return []
        payload = response.json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    @staticmethod
    def _normalize_actor_id(actor_id: str) -> str:
        actor = (actor_id or "").strip()
        if not actor:
            return ""
        if "/" in actor and "~" not in actor:
            actor = actor.replace("/", "~", 1)
        return actor
