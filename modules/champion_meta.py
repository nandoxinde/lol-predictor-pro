"""Meta de campeões — OP.GG (soloQ) + pool pro (Leaguepedia) + ajustes no analyzer."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import requests

from modules.data_dragon import get_champion_maps, resolve_champion_name

OPGG_API = "https://lol-api-champion.op.gg/api/{region}/champions/ranked"
_TIER_LABELS = {0: "OP", 1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}
_TIER_COLORS = {0: "#EF4444", 1: "#F59E0B", 2: "#22C55E", 3: "#1A9FFF", 4: "#8B5CF6", 5: "#6B7280"}
_LEAGUE_REGION = {
    "lck": "KR", "lck_cl": "KR", "lpl": "KR", "lec": "EUW", "lcs": "NA",
    "cblol": "BR", "cblol_acad": "BR", "tcl": "TR", "vcs": "VN", "pcs": "OC",
    "msi": "GLOBAL", "ewc": "GLOBAL", "_unknown": "GLOBAL",
}
_EARLY_GAME = {
    "draven", "lucian", "renekton", "lee sin", "elise", "nidalee", "pantheon",
    "jarvan iv", "xin zhao", "talon", "syndra", "annie", "ziggs", "kalista",
}
_SCALING = {
    "kassadin", "kayle", "jinx", "kogmaw", "vayne", "azir", "veigar", "nasus",
    "sion", "malzahar", "twitch", "senna",
}
_SKIRMISH = {
    "graves", "nidalee", "lee sin", "vi", "wukong", "nocturne", "hecarim",
    "diana", "sylas", "akali", "yasuo", "yone", "irelia",
}
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 1800


def _norm_champ(name: str) -> str:
    text = re.sub(r"[^a-z0-9' ]+", " ", (name or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def league_to_opgg_region(league_code: str) -> str:
    return _LEAGUE_REGION.get((league_code or "").lower(), "GLOBAL")


def tier_label(tier_value: int | None) -> str:
    if tier_value is None:
        return "?"
    return _TIER_LABELS.get(int(tier_value), "?")


def tier_color(tier_value: int | None) -> str:
    if tier_value is None:
        return "#6B7280"
    return _TIER_COLORS.get(int(tier_value), "#6B7280")


def strength_score(profile: dict) -> float:
    if not profile:
        return 50.0
    tier = profile.get("tier")
    if tier is not None:
        return float(np.clip(92 - int(tier) * 14, 20, 95))
    wr = float(profile.get("win_rate") or 0.5)
    pr = float(profile.get("pick_rate") or 0.0)
    return float(np.clip(40 + (wr - 0.5) * 120 + pr * 40, 15, 92))


class ChampionMetaEngine:
    def __init__(self, region: str = "GLOBAL", tier: str = "EMERALD_PLUS"):
        self.region = region.upper()
        self.tier = tier

    def fetch_opgg_meta(self, region: str | None = None, force_refresh: bool = False) -> dict:
        region = (region or self.region).upper()
        cache_key = f"opgg:{region}:{self.tier}"
        now = time.time()
        if not force_refresh and cache_key in _CACHE:
            cached_at, payload = _CACHE[cache_key]
            if now - cached_at < _CACHE_TTL:
                return payload

        url = OPGG_API.format(region=region)
        try:
            response = requests.get(
                url,
                params={"tier": self.tier},
                headers={"User-Agent": "LoLPredictorPro/2.0", "Accept": "application/json"},
                timeout=15,
            )
        except Exception as exc:
            return {"ok": False, "champions": {}, "error": str(exc), "region": region}

        if response.status_code != 200:
            return {"ok": False, "champions": {}, "error": f"OP.GG HTTP {response.status_code}", "region": region}

        by_name: dict[str, dict] = {}
        by_id: dict[str, dict] = {}
        for item in response.json().get("data") or []:
            if not isinstance(item, dict):
                continue
            stats = item.get("average_stats") or {}
            if not stats:
                continue
            champ_id = str(item.get("id") or "")
            name = resolve_champion_name(champ_id)
            profile = {
                "id": champ_id,
                "name": name,
                "win_rate": round(float(stats.get("win_rate") or 0) * 100, 1),
                "pick_rate": round(float(stats.get("pick_rate") or 0) * 100, 2),
                "ban_rate": round(float(stats.get("ban_rate") or 0) * 100, 2),
                "kda": round(float(stats.get("kda") or 0), 2),
                "tier": stats.get("tier"),
                "tier_label": tier_label(stats.get("tier")),
                "rank": stats.get("rank"),
                "positions": item.get("positions") or [],
                "roles": item.get("roles") or [],
                "strength": round(strength_score({"tier": stats.get("tier"), "win_rate": stats.get("win_rate")}), 1),
                "source": f"OP.GG {region}",
            }
            by_name[_norm_champ(name)] = profile
            if champ_id:
                by_id[champ_id] = profile

        payload = {
            "ok": bool(by_name),
            "region": region,
            "tier": self.tier,
            "champions": by_name,
            "by_id": by_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "OP.GG",
        }
        _CACHE[cache_key] = (now, payload)
        return payload

    def get_profile(self, champion: str, region: str | None = None) -> dict | None:
        meta = self.fetch_opgg_meta(region)
        if not meta.get("ok"):
            return None
        key = _norm_champ(champion)
        if key in meta["champions"]:
            return meta["champions"][key]
        for name, profile in meta["champions"].items():
            if key in name or name in key:
                return profile
        return None

    def enrich_pool(self, pool: dict, region: str | None = None) -> dict:
        enriched = dict(pool)
        champions = []
        for item in pool.get("champions") or []:
            champ = item.get("champion") or ""
            profile = self.get_profile(champ, region) or {}
            tier_val = profile.get("tier")
            champions.append({
                **item,
                "meta": profile,
                "tier_label": profile.get("tier_label", "?"),
                "win_rate": profile.get("win_rate"),
                "strength": profile.get("strength"),
                "on_meta": tier_val is not None and int(tier_val) <= 2,
            })
        enriched["champions"] = champions
        enriched["meta_source"] = f"OP.GG {region or self.region}"
        return enriched

    def analyze_comp(self, champion_names: list[str], region: str | None = None) -> dict:
        profiles = [self.get_profile(name, region) for name in champion_names if name]
        profiles = [p for p in profiles if p]
        if not profiles:
            return {"status": "empty", "champions": champion_names}

        avg_strength = float(np.mean([p.get("strength", 50) for p in profiles]))
        avg_wr = float(np.mean([p.get("win_rate", 50) for p in profiles])) / 100.0
        norms = [_norm_champ(p.get("name", "")) for p in profiles]
        early = sum(1 for n in norms if n in _EARLY_GAME)
        scaling = sum(1 for n in norms if n in _SCALING)
        skirmish = sum(1 for n in norms if n in _SKIRMISH)
        s_tier = sum(1 for p in profiles if p.get("tier") is not None and int(p["tier"]) <= 1)

        style = "equilibrado"
        if early >= 2 and early > scaling:
            style = "early_agressivo"
        elif scaling >= 2 and scaling > early:
            style = "scaling_late"

        return {
            "status": "ok",
            "champions": [p.get("name") for p in profiles],
            "avg_strength": round(avg_strength, 1),
            "avg_win_rate": round(avg_wr * 100, 1),
            "s_or_op_count": s_tier,
            "early_game_count": early,
            "scaling_count": scaling,
            "skirmish_count": skirmish,
            "comp_style": style,
            "profiles": profiles,
        }

    def build_match_context(
        self,
        match: dict,
        draft_context: dict | None = None,
        live_stats: dict | None = None,
    ) -> dict:
        league = match.get("league_code", "_unknown")
        region = league_to_opgg_region(league)
        opgg = self.fetch_opgg_meta(region)

        draft = draft_context or {}
        team1_pool = self.enrich_pool(draft.get("team1") or {}, region)
        team2_pool = self.enrich_pool(draft.get("team2") or {}, region)

        live_picks = self._live_champions(match, live_stats)
        t1_live = live_picks.get("team1") or []
        t2_live = live_picks.get("team2") or []
        t1_name = match.get("team1", "")
        t2_name = match.get("team2", "")

        pool1_names = [c["champion"] for c in team1_pool.get("champions", [])[:5]]
        pool2_names = [c["champion"] for c in team2_pool.get("champions", [])[:5]]
        comp1 = self.analyze_comp(t1_live or pool1_names, region)
        comp2 = self.analyze_comp(t2_live or pool2_names, region)

        top_meta = sorted(
            opgg.get("champions", {}).values(),
            key=lambda item: (item.get("tier") if item.get("tier") is not None else 9, -(item.get("strength") or 0)),
        )[:12]

        return {
            "status": "ok" if opgg.get("ok") else "partial",
            "region": region,
            "opgg": opgg,
            "team1_pool": team1_pool,
            "team2_pool": team2_pool,
            "team1_comp": comp1,
            "team2_comp": comp2,
            "live_picks": live_picks,
            "top_meta_champions": top_meta,
            "insights": self._build_insights(comp1, comp2, t1_name, t2_name),
            "patch": get_champion_maps().get("version", ""),
        }

    @staticmethod
    def _live_champions(match: dict, live_stats: dict | None) -> dict:
        if not live_stats or live_stats.get("status") != "ok":
            return {"team1": [], "team2": []}
        blue = [
            p.get("champion") for p in (live_stats.get("blue") or {}).get("players") or []
            if p.get("champion") and p.get("champion") != "—"
        ]
        red = [
            p.get("champion") for p in (live_stats.get("red") or {}).get("players") or []
            if p.get("champion") and p.get("champion") != "—"
        ]
        t1 = match.get("team1", "")
        t2 = match.get("team2", "")
        blue_team = match.get("blue_team") or ""
        red_team = match.get("red_team") or ""
        t1_key = re.sub(r"[^a-z0-9]+", "", t1.lower())
        if re.sub(r"[^a-z0-9]+", "", blue_team.lower()) == t1_key:
            return {"blue": blue, "red": red, "team1": blue, "team2": red}
        if re.sub(r"[^a-z0-9]+", "", red_team.lower()) == t1_key:
            return {"blue": blue, "red": red, "team1": red, "team2": blue}
        return {"blue": blue, "red": red, "team1": blue, "team2": red}

    @staticmethod
    def _build_insights(comp1: dict, comp2: dict, t1: str, t2: str) -> list[str]:
        notes: list[str] = []
        for comp, name in ((comp1, t1), (comp2, t2)):
            if comp.get("status") != "ok":
                continue
            if comp.get("comp_style") == "early_agressivo":
                notes.append(f"{name}: comp early — favorece First Blood e ritmo rápido.")
            elif comp.get("comp_style") == "scaling_late":
                notes.append(f"{name}: comp scaling — favorece mapa mais longo.")
            if int(comp.get("s_or_op_count") or 0) >= 3:
                notes.append(f"{name}: {comp['s_or_op_count']} picks S/OP no meta (OP.GG).")
        s1 = float(comp1.get("avg_strength") or 50)
        s2 = float(comp2.get("avg_strength") or 50)
        if abs(s1 - s2) >= 8:
            stronger = t1 if s1 > s2 else t2
            notes.append(f"Vantagem de meta: {stronger} com draft mais forte no patch.")
        return notes

    def apply_analyzer_adjustments(
        self,
        t1_stats: dict,
        t2_stats: dict,
        champion_context: dict,
        t1_name: str,
        t2_name: str,
    ) -> tuple[dict, dict, dict]:
        t1 = dict(t1_stats)
        t2 = dict(t2_stats)
        comp1 = champion_context.get("team1_comp") or {}
        comp2 = champion_context.get("team2_comp") or {}
        applied: list[str] = []

        for stats, comp, name in ((t1, comp1, t1_name), (t2, comp2, t2_name)):
            if comp.get("status") != "ok":
                continue
            style = comp.get("comp_style")
            skirmish = int(comp.get("skirmish_count") or 0)
            early = int(comp.get("early_game_count") or 0)
            scaling = int(comp.get("scaling_count") or 0)
            strength = float(comp.get("avg_strength") or 50)

            if style == "early_agressivo":
                stats["first_blood_rate"] = float(
                    np.clip(stats.get("first_blood_rate", 0.5) + 0.04 + early * 0.01, 0.2, 0.9)
                )
                stats["avg_kills"] = float(stats.get("avg_kills", 14) * (1.0 + 0.03 * early))
                applied.append(f"{name}: ajuste early/FB")
            if style == "scaling_late":
                stats["avg_game_length"] = float(stats.get("avg_game_length", 32) * (1.0 + 0.04 * scaling))
                applied.append(f"{name}: ajuste duração/scaling")
            if skirmish >= 2:
                stats["avg_kills"] = float(stats.get("avg_kills", 14) * 1.05)
                applied.append(f"{name}: +kills skirmish")
            if strength >= 65:
                stats["winrate"] = float(np.clip(stats.get("winrate", 0.5) + 0.02, 0.1, 0.9))
                applied.append(f"{name}: +WR meta forte")

        return t1, t2, {"applied": bool(applied), "notes": applied}
