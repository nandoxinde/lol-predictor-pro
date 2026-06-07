"""Riot Data Dragon — patch, campeões, itens (JSON oficial gratuito)."""

from __future__ import annotations

import time
from typing import Any

import requests

_DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
_DDRAGON_CHAMPIONS = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
_CACHE: dict[str, Any] = {"at": 0.0, "version": "", "by_id": {}, "by_key": {}, "by_name": {}}
_TTL_SECONDS = 3600


def _fetch_json(url: str, timeout: int = 12) -> Any:
    response = requests.get(url, headers={"User-Agent": "LoLPredictorPro/2.0"}, timeout=timeout)
    if response.status_code != 200:
        return None
    return response.json()


def get_latest_version(force_refresh: bool = False) -> str:
    now = time.time()
    if not force_refresh and _CACHE.get("version") and now - float(_CACHE.get("at") or 0) < _TTL_SECONDS:
        return str(_CACHE["version"])
    payload = _fetch_json(_DDRAGON_VERSIONS)
    if not isinstance(payload, list) or not payload:
        return str(_CACHE.get("version") or "15.10.1")
    version = str(payload[0])
    _CACHE["version"] = version
    _CACHE["at"] = now
    return version


def get_champion_maps(force_refresh: bool = False) -> dict[str, dict]:
    now = time.time()
    if (
        not force_refresh
        and _CACHE.get("by_id")
        and now - float(_CACHE.get("at") or 0) < _TTL_SECONDS
    ):
        return {
            "by_id": _CACHE["by_id"],
            "by_key": _CACHE["by_key"],
            "by_name": _CACHE["by_name"],
            "version": _CACHE.get("version", ""),
        }

    version = get_latest_version(force_refresh=force_refresh)
    payload = _fetch_json(_DDRAGON_CHAMPIONS.format(version=version))
    data = (payload or {}).get("data") if isinstance(payload, dict) else {}
    by_id: dict[str, str] = {}
    by_key: dict[str, str] = {}
    by_name: dict[str, str] = {}

    if isinstance(data, dict):
        for champ in data.values():
            if not isinstance(champ, dict):
                continue
            name = str(champ.get("name") or champ.get("id") or "")
            key = str(champ.get("key") or "")
            if key:
                by_id[key] = name
                by_key[key] = name
            if name:
                by_name[name.lower()] = name

    _CACHE.update({"by_id": by_id, "by_key": by_key, "by_name": by_name, "at": now, "version": version})
    return {"by_id": by_id, "by_key": by_key, "by_name": by_name, "version": version}


def resolve_champion_name(value: Any) -> str:
    if value in (None, ""):
        return "—"
    text = str(value).strip()
    if not text.isdigit():
        return text
    maps = get_champion_maps()
    return maps["by_id"].get(text) or maps["by_key"].get(text) or f"Champ #{text}"


def enrich_live_stats_champions(live_stats: dict) -> dict:
    if not live_stats or live_stats.get("status") != "ok":
        return live_stats
    enriched = dict(live_stats)
    for side_key in ("blue", "red"):
        side = dict(enriched.get(side_key) or {})
        players = []
        for player in side.get("players") or []:
            item = dict(player)
            item["champion"] = resolve_champion_name(item.get("champion"))
            players.append(item)
        side["players"] = players
        enriched[side_key] = side
    if not enriched.get("patch"):
        enriched["patch"] = get_latest_version()
    enriched["data_dragon_version"] = get_latest_version()
    return enriched
