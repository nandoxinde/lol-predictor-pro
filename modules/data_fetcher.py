"""Data layer for LoL Predictor.

Sources:
- Liquipedia (Liquipedia:Matches) is the schedule source of truth for LCK, LPL and CBLOL.
- LoLEsports for live status, logos and non-regional leagues (LEC, LCS, MSI, etc.).
- PandaScore is used only for EWC live games that LoLEsports does not expose.
- OddsPapi is used by the app only for odds enrichment (strict team matching).
- Leaguepedia Cargo fills residual gaps outside the Liquipedia regional window.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import numpy as np
import requests

from modules.config import get_secret
from modules.my_private_api import query_team_stats
from modules.odds_fetcher import OddsPapiClient
from modules.stats_engine import fetch_liquipedia_schedule_raw

TZ_BRT = ZoneInfo("America/Sao_Paulo")
LIQUIPEDIA_SCHEDULE_LEAGUES = frozenset({"lck", "lpl", "cblol"})
PANDA_BASE = "https://api.pandascore.co"
PANDA_TOKEN = get_secret("PANDASCORE_TOKEN")
LOLESPORTS_DEFAULT_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
LOLESPORTS_KEY = get_secret("LOLESPORTS_API_KEY") or LOLESPORTS_DEFAULT_KEY
LEAGUEPEDIA_CACHE_TTL = 15 * 60
_LEAGUEPEDIA_CACHE: dict[str, tuple[datetime, list[dict]]] = {}
TEAM_STATS_CARGO_CACHE_TTL = 30 * 60
_TEAM_STATS_CARGO_CACHE: dict[str, tuple[datetime, dict]] = {}
SERIES_MEMORY_CACHE_TTL = 60
_SERIES_MEMORY_CACHE: dict[str, tuple[datetime, dict]] = {}


def now_brt() -> datetime:
    return datetime.now(tz=TZ_BRT)


def parse_to_brt(value: str | None) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.isdigit():
            ts = int(raw)
            if ts > 10_000_000_000:
                ts //= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(TZ_BRT)
        normalized = raw.replace("Z", "+00:00").replace(" ", "T")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_BRT)
    except Exception:
        return None


def match_brt_date(match: dict) -> str:
    dt = match.get("datetime_obj")
    if isinstance(dt, datetime):
        return dt.astimezone(TZ_BRT).strftime("%Y-%m-%d")
    parsed = parse_to_brt(match.get("datetime"))
    if parsed:
        return parsed.strftime("%Y-%m-%d")
    return (match.get("datetime") or "")[:10]


def schedule_identity_key(match: dict) -> str:
    teams_key = "|".join(sorted([_team_key(match.get("team1", "")), _team_key(match.get("team2", ""))]))
    return f"{teams_key}|{match_brt_date(match)}"


def minutes_until(value: str | None) -> float | None:
    dt = parse_to_brt(value)
    if not dt:
        return None
    return (dt - now_brt()).total_seconds() / 60


NAME_FIX = {
    "equipe líquida": "Team Liquid",
    "equipe liquid": "Team Liquid",
    "100 ladrões": "100 Thieves",
    "100 ladroes": "100 Thieves",
    "nuvem 9": "Cloud9",
    "equipe vitality": "Team Vitality",
    "time vitality": "Team Vitality",
    "voo de busca": "FlyQuest",
    "dplus": "Dplus KIA",
    "dplus kia": "Dplus KIA",
    "kt challengers": "KT Rolster Challengers",
    "kt rolster challengers": "KT Rolster Challengers",
    "gen.g global academy": "Gen.G Global Academy",
    "hanwha life esports": "Hanwha Life Esports",
    "soopers": "DN SOOPers",
    "dn soopers": "DN SOOPers",
    "fearx": "BNK FEARX",
    "bnk fearx": "BNK FEARX",
}


def fix_name(name: str) -> str:
    cleaned = (name or "").strip()
    return NAME_FIX.get(cleaned.lower(), cleaned)


def _team_key(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    aliases = {
        "dplus": "dplus kia",
        "dk": "dplus kia",
        "gen g": "gen g esports",
        "beijing jdg esports": "jd gaming",
        "jdg esports": "jd gaming",
        "thunder talk gaming": "thundertalk gaming",
        "top esports": "top esports",
        "xi an team we": "team we",
        "edward gaming": "edward gaming",
        "kt challengers": "kt rolster challengers",
        "ns challengers": "nongshim redforce challengers",
        "dns challengers": "dn soopers challengers",
        "soopers": "dn soopers",
        "fearx": "bnk fearx",
    }
    return aliases.get(text, text)


def _clean_image_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if value.startswith("http://static.lolesports.com/"):
        value = value.replace("http://", "https://", 1)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if "team-tbd.png" in value:
        return ""
    return value


LEAGUE_INFO = {
    "cblol": {"name": "CBLOL", "display": "CBLOL 2026", "tier": 1, "main": True},
    "cblol_acad": {"name": "CBLOL Acad", "display": "CBLOL Academy", "tier": 3, "main": False},
    "lck": {"name": "LCK", "display": "LCK 2026", "tier": 1, "main": True},
    "lck_cl": {"name": "LCK CL", "display": "LCK CL 2026", "tier": 3, "main": False},
    "lpl": {"name": "LPL", "display": "LPL 2026", "tier": 1, "main": True},
    "lec": {"name": "LEC", "display": "LEC 2026", "tier": 1, "main": True},
    "lcs": {"name": "LCS", "display": "LCS 2026", "tier": 1, "main": True},
    "lcs_acad": {"name": "LCS Academy", "display": "LCS Academy", "tier": 3, "main": False},
    "lla": {"name": "LLA", "display": "LLA", "tier": 2, "main": True},
    "vcs": {"name": "VCS", "display": "VCS", "tier": 2, "main": True},
    "tcl": {"name": "TCL", "display": "TCL", "tier": 2, "main": True},
    "pcs": {"name": "PCS/LCP", "display": "PCS/LCP", "tier": 2, "main": True},
    "ewc": {"name": "EWC", "display": "EWC", "tier": 1, "main": True},
    "msi": {"name": "MSI", "display": "MSI 2026", "tier": 1, "main": True},
    "_unknown": {"name": "Torneio", "display": "Torneio", "tier": 2, "main": True},
}
LEAGUE_CONFIDENCE_CAP = {1: 1.0, 2: 0.9, 3: 0.78}


def get_league_info(code: str) -> dict:
    return LEAGUE_INFO.get(code, LEAGUE_INFO["_unknown"])


def league_from_text(text: str) -> str:
    lower = (text or "").lower()
    mapping = [
        ("esports world cup", "ewc"),
        ("korea qualifier", "ewc"),
        ("ewc", "ewc"),
        ("cblol academy", "cblol_acad"),
        ("cblol acad", "cblol_acad"),
        ("lck challengers", "lck_cl"),
        ("lck cl", "lck_cl"),
        ("lcs academy", "lcs_acad"),
        ("lcs acad", "lcs_acad"),
        ("lplol", "_unknown"),
        ("liga portuguesa", "_unknown"),
        ("cblol", "cblol"),
        ("lck", "lck"),
        ("lpl", "lpl"),
        ("lec", "lec"),
        ("lcs", "lcs"),
        ("lla", "lla"),
        ("vcs", "vcs"),
        ("tcl", "tcl"),
        ("pcs", "pcs"),
        ("lcp", "pcs"),
        ("msi", "msi"),
    ]
    for needle, code in mapping:
        if needle in lower:
            return code
    return "_unknown"


def guess_league(team1: str, team2: str = "") -> str:
    text = f"{team1} {team2}".lower()
    guesses = [
        ("cblol", ["kabum", "kbm", "loud", "pain", "red canids", "fluxo", "furia", "vivo keyd", "los"]),
        ("lck", ["t1", "gen.g", "hanwha", "dplus", "kt rolster", "drx", "nongshim", "brion", "bnk"]),
        ("lpl", ["jdg", "blg", "edg", "tes", "weibo", "lng", "rng", "omg", "nip"]),
        ("lec", ["g2", "fnatic", "vitality", "karmine", "mad lions", "sk gaming", "giantx"]),
        ("lcs", ["cloud9", "flyquest", "team liquid", "100 thieves", "nrg", "dignitas"]),
        ("vcs", ["gam esports", "team flash"]),
        ("tcl", ["papara", "supermassive", "wildcats", "besiktas"]),
    ]
    for code, names in guesses:
        if any(name in text for name in names):
            return code
    return "_unknown"


LPL_CHINA_HINTS = {
    "jd gaming", "jdg", "top esports", "tes", "bilibili gaming", "blg",
    "edward gaming", "edg", "weibo gaming", "wbg", "lng esports", "lng",
    "royal never give up", "rng", "invictus gaming", "ig", "ninjas in pyjamas",
    "nip", "anyones legend", "anyone's legend", "al", "team we", "we",
    "thundertalk gaming", "tt gaming", "tt", "lgd gaming", "lgd",
    "oh my god", "omg", "ultra prime", "up", "funplus phoenix", "fpx",
    "rare atom", "ra", "weibo", "thundertalk",
}


def is_verified_lpl_match(team1: str, team2: str) -> bool:
    text = f"{team1} {team2}".lower()
    normalized = " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "
    for hint in LPL_CHINA_HINTS:
        hint_norm = " " + re.sub(r"[^a-z0-9]+", " ", hint.lower()).strip() + " "
        if hint_norm in normalized:
            return True
    return False


STREAM_CHANNELS = {
    "cblol": "cblol",
    "cblol_acad": "cblol",
    "lck": "lck",
    "lck_cl": "lck",
    "lpl": "lpl",
    "lec": "lec",
    "lcs": "lcs",
    "lla": "lla",
    "vcs": "vcs",
    "tcl": "tcl",
    "pcs": "riotgames",
    "ewc": "riotgames",
    "msi": "riotgames",
    "_unknown": "riotgames",
}


def get_stream_urls(code: str) -> dict:
    channel = STREAM_CHANNELS.get(code, "riotgames")
    return {"twitch_channel": channel, "twitch": f"https://player.twitch.tv/?channel={channel}&parent=localhost"}


TIER_S = {
    "T1", "T1 Esports", "Gen.G", "Hanwha Life Esports", "Dplus KIA", "JDG", "BLG",
    "G2 Esports", "LOUD", "paiN Gaming", "FlyQuest", "Cloud9", "GAM Esports",
}
TIER_A = {
    "KT Rolster", "DRX", "BNK FearX", "Nongshim RedForce", "BRION", "Fnatic",
    "Team Vitality", "Karmine Corp", "Team Liquid", "100 Thieves", "RED Canids",
    "Fluxo W7M", "FURIA Esports", "KaBuM! Esports", "KaBuM",
}

TIER_PROFILE = {
    "S": {"wr": 0.70, "fb": 0.61, "fd": 0.62, "gd": 650, "kills": 16.5, "length": 32.5},
    "A": {"wr": 0.57, "fb": 0.53, "fd": 0.54, "gd": 180, "kills": 15.0, "length": 33.2},
    "B": {"wr": 0.44, "fb": 0.47, "fd": 0.46, "gd": -160, "kills": 13.5, "length": 34.0},
}


def generate_decision_card(t1n, t1s, t1f, t2n, t2s, t2f, lc, bankroll):
    t1wr = t1s.get("winrate", 0.5)
    t2wr = t2s.get("winrate", 0.5)
    t1len = t1s.get("avg_game_length", 32)
    t2len = t2s.get("avg_game_length", 32)
    fav = t1n if t1wr >= t2wr else t2n
    gap = abs(t1wr - t2wr)
    avg_len = (t1len + t2len) / 2
    decisions = []

    if gap > 0.10:
        prob = min(0.88, 0.60 + gap * 0.8)
        decisions.append({
            "market": f"Vencedor — {fav}",
            "entry": f"{fav} vence",
            "confidence": round(prob * 100, 1),
            "probability": prob,
            "fair_odds": round(1 / max(prob, 0.01), 2),
            "icon": "🏆",
            "category": "segura",
        })

    p27 = min(0.94, max(0.35, 0.55 + (avg_len - 27) * 0.045))
    decisions.append({
        "market": "Duração >27 minutos",
        "entry": "Jogo passa de 27 minutos",
        "confidence": round(p27 * 100, 1),
        "probability": p27,
        "fair_odds": round(1 / max(p27, 0.01), 2),
        "icon": "⏱",
        "category": "segura",
    })

    p30 = min(0.88, max(0.25, 0.50 + (avg_len - 30) * 0.04))
    decisions.append({
        "market": "Duração >30 minutos",
        "entry": "Jogo passa de 30 minutos",
        "confidence": round(p30 * 100, 1),
        "probability": p30,
        "fair_odds": round(1 / max(p30, 0.01), 2),
        "icon": "⌛",
        "category": "segura" if p30 >= 0.63 else "risco",
    })

    fb_team = t1n if t1s.get("first_blood_rate", .5) >= t2s.get("first_blood_rate", .5) else t2n
    fb_prob = min(0.82, max(t1s.get("first_blood_rate", .5), t2s.get("first_blood_rate", .5)))
    decisions.append({
        "market": f"First Blood — {fb_team}",
        "entry": f"{fb_team} primeiro abate",
        "confidence": round(fb_prob * 100, 1),
        "probability": fb_prob,
        "fair_odds": round(1 / max(fb_prob, 0.01), 2),
        "icon": "🩸",
        "category": "risco",
    })

    fd_team = t1n if t1s.get("first_dragon_rate", .5) >= t2s.get("first_dragon_rate", .5) else t2n
    fd_prob = min(0.84, max(t1s.get("first_dragon_rate", .5), t2s.get("first_dragon_rate", .5)))
    decisions.append({
        "market": f"First Dragon — {fd_team}",
        "entry": f"{fd_team} primeiro dragão",
        "confidence": round(fd_prob * 100, 1),
        "probability": fd_prob,
        "fair_odds": round(1 / max(fd_prob, 0.01), 2),
        "icon": "🐉",
        "category": "risco" if fd_prob < 0.70 else "segura",
    })

    decisions.sort(key=lambda item: item["confidence"], reverse=True)
    return {
        "decisions": decisions,
        "top_pick": decisions[0] if decisions else None,
        "safe_picks": [d for d in decisions if d["category"] == "segura"],
        "risky_picks": [d for d in decisions if d["category"] == "risco"],
        "tech_gap": round(gap * 100, 1),
        "avg_duration": round(avg_len, 1),
    }


def generate_analyst_comment(t1n, t1s, t1f, t2n, t2s, t2f, lc="", league_code=""):
    fav = t1n if t1s.get("winrate", 0.5) >= t2s.get("winrate", 0.5) else t2n
    return (
        f"{fav} aparece como favorito pelo modelo. "
        f"Win rate estimado: {t1n} {t1s.get('winrate', .5) * 100:.0f}% vs "
        f"{t2n} {t2s.get('winrate', .5) * 100:.0f}%. "
        f"Duração média projetada: {(t1s.get('avg_game_length', 32) + t2s.get('avg_game_length', 32)) / 2:.1f}min."
    )


class DataFetcher:
    LQ_API = "https://lol.fandom.com/api.php"
    LQ_HEADERS = {"User-Agent": "LoLPredictorPro/2.0 (personal project)", "Accept-Encoding": "gzip"}
    LS_LIVE = "https://esports-api.lolesports.com/persisted/gw/getLive"
    LS_SCHEDULE = "https://esports-api.lolesports.com/persisted/gw/getSchedule"
    LS_WINDOW = "https://feed.lolesports.com/livestats/v1/window"
    LS_DETAILS = "https://feed.lolesports.com/livestats/v1/details"
    LS_LEAGUES = {
        "msi": "98767991325878492",
        "cblol": "98767991332355509",
        "lck": "98767991310872058",
        "lck_cl": "98767991335774713",
        "lpl": "98767991314006698",
        "lec": "98767991302996019",
        "lcs": "98767991299243165",
    }

    def __init__(self):
        self.panda = requests.Session()
        if PANDA_TOKEN:
            self.panda.headers.update({"Authorization": f"Bearer {PANDA_TOKEN}"})
        self.panda.headers.update({"User-Agent": "LoLPredictorPro/2.0"})
        self.live = requests.Session()
        headers = {"User-Agent": "LoLPredictorPro/2.0"}
        if LOLESPORTS_KEY:
            headers["x-api-key"] = LOLESPORTS_KEY
        self.live.headers.update(headers)
        self.team_logos: dict[str, str] = {}

    @staticmethod
    def resolve_tier(name: str) -> str:
        lower = name.lower().strip()
        if any(lower == item.lower() or item.lower() in lower for item in TIER_S):
            return "S"
        if any(lower == item.lower() or item.lower() in lower for item in TIER_A):
            return "A"
        return "B"

    def cargo_search(self, query: str = "") -> tuple[list[dict], str]:
        matches: list[dict] = []
        seen: set[str] = set()
        query_norm = query.strip().lower()
        liquipedia_keys: set[str] = set()

        for match in self._fetch_liquipedia_true_schedule():
            liquipedia_keys.add(schedule_identity_key(match))
            self._append_unique(matches, seen, match, query_norm)

        for match in self._fetch_lolesports_live():
            self._upsert_schedule_match(matches, seen, match, query_norm)

        for match in self._fetch_lolesports_schedule():
            code = match.get("league_code", "")
            if code in LIQUIPEDIA_SCHEDULE_LEAGUES and match.get("state") != "inProgress":
                if schedule_identity_key(match) in liquipedia_keys:
                    continue
                continue
            self._append_unique(matches, seen, match, query_norm)

        for match in self._fetch_pandascore_running():
            if match.get("league_code") == "ewc":
                self._append_unique(matches, seen, match, query_norm)

        for match in self._fetch_leaguepedia_schedule(query):
            code = match.get("league_code", "")
            if code in LIQUIPEDIA_SCHEDULE_LEAGUES and schedule_identity_key(match) in liquipedia_keys:
                continue
            self._append_unique(matches, seen, match, query_norm)

        self._enrich_logos_from_lolesports(matches)
        matches.sort(key=lambda item: (0 if item.get("state") == "inProgress" else 1, item.get("datetime", "")))
        if matches:
            sources = {match.get("source", "") for match in matches}
            label = "Liquipedia + LoLEsports" if "Liquipedia" in sources else "LoLEsports"
            if "Leaguepedia" in sources:
                label += " + Leaguepedia"
            return matches, label
        return self._demo_matches(query), "demo"

    def fetch_lolesports_live_stats(self, game_id: str | None) -> dict:
        if not game_id:
            return {}
        try:
            # The LoLEsports live feed requires startingTime aligned to 10s.
            # Asking for the last two minutes returns the newest delayed frame.
            start = datetime.now(timezone.utc) - timedelta(minutes=2)
            start = start.replace(microsecond=0, second=(start.second // 10) * 10)
            params = {"startingTime": start.isoformat().replace("+00:00", "Z")}
            window = requests.get(
                f"{self.LS_WINDOW}/{game_id}",
                headers={"User-Agent": "LoLPredictorPro/2.0"},
                params=params,
                timeout=10,
            )
            details = requests.get(
                f"{self.LS_DETAILS}/{game_id}",
                headers={"User-Agent": "LoLPredictorPro/2.0"},
                params=params,
                timeout=10,
            )
            if window.status_code != 200:
                return {"status": "unavailable", "message": f"Live stats indisponíveis ({window.status_code})."}

            window_data = window.json()
            detail_data = details.json() if details.status_code == 200 else {}
            frames = window_data.get("frames") or []
            detail_frames = detail_data.get("frames") or []
            if not frames:
                return {"status": "waiting", "message": "Aguardando frames oficiais do LoLEsports."}

            frame = frames[-1]
            detail_frame = detail_frames[-1] if detail_frames else {}
            participant_details = {
                item.get("participantId"): item
                for item in (detail_frame.get("participants") or [])
                if item.get("participantId") is not None
            }

            metadata = window_data.get("gameMetadata") or {}
            participants_meta = (
                (metadata.get("blueTeamMetadata") or {}).get("participantMetadata") or []
            ) + (
                (metadata.get("redTeamMetadata") or {}).get("participantMetadata") or []
            )
            meta_by_id = {item.get("participantId"): item for item in participants_meta}

            def build_team(side_key: str) -> dict:
                side = frame.get(side_key) or {}
                players = []
                for player in side.get("participants") or []:
                    pid = player.get("participantId")
                    meta = meta_by_id.get(pid, {})
                    detail = participant_details.get(pid, {})
                    players.append({
                        "name": meta.get("summonerName") or f"Player {pid}",
                        "champion": meta.get("championId") or "",
                        "role": meta.get("role") or "",
                        "kills": player.get("kills", 0),
                        "deaths": player.get("deaths", 0),
                        "assists": player.get("assists", 0),
                        "cs": player.get("creepScore", 0),
                        "gold": player.get("totalGold") or detail.get("totalGoldEarned", 0),
                        "level": player.get("level", 0),
                    })
                return {
                    "total_gold": side.get("totalGold", 0),
                    "kills": side.get("totalKills", 0),
                    "towers": side.get("towers", 0),
                    "inhibitors": side.get("inhibitors", 0),
                    "barons": side.get("barons", 0),
                    "dragons": side.get("dragons", []),
                    "players": players,
                }

            return {
                "status": "ok",
                "game_id": game_id,
                "timestamp": frame.get("rfc460Timestamp"),
                "game_state": frame.get("gameState"),
                "patch": metadata.get("patchVersion"),
                "blue": build_team("blueTeam"),
                "red": build_team("redTeam"),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def fetch_series_memory(self, match: dict) -> dict:
        """Build short-lived momentum memory for MD3/MD5 series."""
        best_of = int(str(match.get("best_of") or "1").split(".")[0] or 1)
        if best_of < 3:
            return {"status": "disabled", "reason": "Série MD1"}

        is_pandascore = match.get("source") == "PandaScore" and bool(match.get("panda_id"))
        cache_key = (
            f"panda:{match.get('panda_id')}"
            if is_pandascore
            else f"lolesports:{match.get('lolesports_event_id') or match.get('lolesports_game_id')}"
        )
        cached = _SERIES_MEMORY_CACHE.get(cache_key)
        if cached:
            cached_at, data = cached
            if (datetime.now(timezone.utc) - cached_at).total_seconds() < SERIES_MEMORY_CACHE_TTL:
                return dict(data)

        if is_pandascore:
            data = self._fetch_pandascore_series_memory(match)
        else:
            data = {"status": "unavailable", "source": "PandaScore", "reason": "Match sem ID PandaScore"}

        _SERIES_MEMORY_CACHE[cache_key] = (datetime.now(timezone.utc), dict(data))
        return data

    def _fetch_pandascore_series_memory(self, match: dict) -> dict:
        if not PANDA_TOKEN:
            return {"status": "unavailable", "source": "PandaScore", "reason": "Token PandaScore ausente"}

        try:
            response = self.panda.get(
                f"{PANDA_BASE}/lol/matches/{match.get('panda_id')}/games",
                params={"page[size]": 10},
                timeout=10,
            )
            if response.status_code != 200:
                return {
                    "status": "unavailable",
                    "source": "PandaScore",
                    "reason": f"Games indisponíveis ({response.status_code})",
                }
            games = response.json() or []
        except Exception as exc:
            return {"status": "error", "source": "PandaScore", "reason": str(exc)}

        team1 = match.get("team1", "")
        team2 = match.get("team2", "")
        team1_id = match.get("panda_team1_id")
        team2_id = match.get("panda_team2_id")
        completed = [game for game in games if self._is_completed_game(game)]
        completed.sort(key=lambda game: game.get("position") or game.get("number") or game.get("id") or 0)

        if not completed:
            return {
                "status": "empty",
                "source": "PandaScore",
                "maps_played": 0,
                "reason": "Nenhum mapa finalizado na série ainda",
            }

        maps = [
            self._summarize_pandascore_game(game, team1, team2, team1_id, team2_id)
            for game in completed
        ]
        maps = [m for m in maps if m]
        if not maps:
            return {"status": "empty", "source": "PandaScore", "maps_played": 0}

        score = {
            "team1": sum(1 for item in maps if item.get("winner") == "team1"),
            "team2": sum(1 for item in maps if item.get("winner") == "team2"),
        }
        fb = {
            "team1": sum(1 for item in maps if item.get("first_blood") == "team1"),
            "team2": sum(1 for item in maps if item.get("first_blood") == "team2"),
        }
        fd = {
            "team1": sum(1 for item in maps if item.get("first_dragon") == "team1"),
            "team2": sum(1 for item in maps if item.get("first_dragon") == "team2"),
        }
        dragons = {
            "team1": sum(int(item.get("dragons", {}).get("team1", 0)) for item in maps),
            "team2": sum(int(item.get("dragons", {}).get("team2", 0)) for item in maps),
        }
        kills = {
            "team1": sum(int(item.get("kills", {}).get("team1", 0)) for item in maps),
            "team2": sum(int(item.get("kills", {}).get("team2", 0)) for item in maps),
        }
        last = maps[-1]
        momentum_raw = (
            (kills["team1"] - kills["team2"]) * 0.025
            + (dragons["team1"] - dragons["team2"]) * 0.12
            + (1 if last.get("winner") == "team1" else -1 if last.get("winner") == "team2" else 0) * 0.16
            + (1 if last.get("first_dragon") == "team1" else -1 if last.get("first_dragon") == "team2" else 0) * 0.10
        )
        momentum_t1 = float(np.clip(0.5 + momentum_raw, 0.18, 0.82))

        return {
            "status": "ok",
            "source": "PandaScore",
            "maps_played": len(maps),
            "series_score": score,
            "event_rates": {
                "first_blood": self._event_rate(fb, len(maps)),
                "first_dragon": self._event_rate(fd, len(maps)),
            },
            "totals": {"dragons": dragons, "kills": kills},
            "momentum": {"team1": momentum_t1, "team2": 1 - momentum_t1},
            "last_map": last,
            "maps": maps,
            "draft": self._extract_draft_from_game(last.get("raw", {}), team1, team2, team1_id, team2_id),
        }

    @staticmethod
    def _event_rate(counts: dict, total: int) -> dict:
        if total <= 0:
            return {"team1": 0.5, "team2": 0.5}
        # Beta smoothing avoids turning one map into a false 100% lock.
        t1 = (counts.get("team1", 0) + 1) / (total + 2)
        t2 = (counts.get("team2", 0) + 1) / (total + 2)
        return {"team1": t1, "team2": t2}

    @staticmethod
    def _is_completed_game(game: dict) -> bool:
        status = str(game.get("status") or game.get("state") or "").lower()
        return status in {"finished", "completed", "complete"} or bool(game.get("finished") or game.get("winner"))

    def _summarize_pandascore_game(self, game: dict, team1: str, team2: str, team1_id=None, team2_id=None) -> dict:
        game_id = game.get("id")
        events = self._fetch_pandascore_game_feed(game_id, "events")
        frames = self._fetch_pandascore_game_feed(game_id, "frames")
        kills = self._count_events_by_team(events, ("kill", "champion_kill"), team1, team2, team1_id, team2_id)
        dragons = self._count_events_by_team(events, ("dragon", "drake"), team1, team2, team1_id, team2_id)
        winner_obj = game.get("winner") or game.get("winner_team")
        winner = self._team_side_from_object(winner_obj, team1, team2, team1_id, team2_id) if winner_obj else None
        first_blood = self._first_event_team(events, ("kill", "champion_kill"), team1, team2, team1_id, team2_id)
        first_dragon = self._first_event_team(events, ("dragon", "drake"), team1, team2, team1_id, team2_id)
        if frames:
            frame_summary = self._summarize_final_frame(frames[-1], team1, team2, team1_id, team2_id)
            kills = frame_summary.get("kills") or kills
            dragons = frame_summary.get("dragons") or dragons

        return {
            "game_id": game_id,
            "number": game.get("position") or game.get("number"),
            "winner": winner,
            "first_blood": first_blood,
            "first_dragon": first_dragon,
            "kills": kills,
            "dragons": dragons,
            "raw": game,
        }

    def _fetch_pandascore_game_feed(self, game_id, feed: str) -> list:
        if not game_id:
            return []
        try:
            response = self.panda.get(f"{PANDA_BASE}/lol/games/{game_id}/{feed}", params={"page[size]": 200}, timeout=10)
            if response.status_code != 200:
                return []
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _first_event_team(self, events: list, needles: tuple[str, ...], team1: str, team2: str, team1_id=None, team2_id=None) -> str | None:
        for event in events:
            text = str(event.get("type") or event.get("event_type") or event.get("name") or "").lower()
            blob = str(event).lower()
            if any(needle in text or needle in blob for needle in needles):
                side = self._team_side_from_object(event, team1, team2, team1_id, team2_id)
                if side:
                    return side
        return None

    def _count_events_by_team(self, events: list, needles: tuple[str, ...], team1: str, team2: str, team1_id=None, team2_id=None) -> dict:
        counts = {"team1": 0, "team2": 0}
        for event in events:
            text = str(event.get("type") or event.get("event_type") or event.get("name") or "").lower()
            blob = str(event).lower()
            if not any(needle in text or needle in blob for needle in needles):
                continue
            side = self._team_side_from_object(event, team1, team2, team1_id, team2_id)
            if side:
                counts[side] += 1
        return counts

    def _summarize_final_frame(self, frame: dict, team1: str, team2: str, team1_id=None, team2_id=None) -> dict:
        result = {"kills": None, "dragons": None}
        team_dicts = [obj for obj in self._walk_dicts(frame) if self._team_side_from_object(obj, team1, team2, team1_id, team2_id)]
        if not team_dicts:
            return result
        kills = {"team1": 0, "team2": 0}
        dragons = {"team1": 0, "team2": 0}
        found_kills = found_dragons = False
        for obj in team_dicts:
            side = self._team_side_from_object(obj, team1, team2, team1_id, team2_id)
            if not side:
                continue
            if obj.get("kills") is not None or obj.get("totalKills") is not None:
                kills[side] = int(obj.get("kills") or obj.get("totalKills") or 0)
                found_kills = True
            if obj.get("dragons") is not None or obj.get("drakes") is not None:
                value = obj.get("dragons", obj.get("drakes", 0))
                dragons[side] = len(value) if isinstance(value, list) else int(value or 0)
                found_dragons = True
        result["kills"] = kills if found_kills else None
        result["dragons"] = dragons if found_dragons else None
        return result

    def _team_side_from_object(self, obj, team1: str, team2: str, team1_id=None, team2_id=None) -> str | None:
        if not obj:
            return None
        if isinstance(obj, dict):
            for key in (
                "winner_id", "team_id", "killer_team_id", "scorer_team_id",
                "dragon_killer_team_id", "owner_team_id",
            ):
                value = obj.get(key)
                if value is not None:
                    if team1_id is not None and str(value) == str(team1_id):
                        return "team1"
                    if team2_id is not None and str(value) == str(team2_id):
                        return "team2"
            for key in ("winner", "winner_team", "team", "killer_team", "scorer_team", "owner_team"):
                if key in obj:
                    side = self._team_side_from_object(obj.get(key), team1, team2, team1_id, team2_id)
                    if side:
                        return side
        if self._mentions_team(obj, team1, team1_id):
            return "team1"
        if self._mentions_team(obj, team2, team2_id):
            return "team2"
        return None

    def _mentions_team(self, obj, team: str, team_id=None) -> bool:
        team_norm = _team_key(team)
        for value in self._walk_values(obj):
            if team_id is not None and str(value) == str(team_id):
                return True
            if isinstance(value, str) and team_norm and _team_key(value) == team_norm:
                return True
        return False

    def _extract_draft_from_game(self, game: dict, team1: str, team2: str, team1_id=None, team2_id=None) -> dict:
        draft = {"team1": [], "team2": []}
        for obj in self._walk_dicts(game):
            champion = obj.get("champion") or obj.get("champion_name") or obj.get("championId") or obj.get("champion_id")
            if not champion:
                continue
            side = self._team_side_from_object(obj, team1, team2, team1_id, team2_id)
            if side and str(champion) not in draft[side]:
                draft[side].append(str(champion))
        return draft

    def _walk_dicts(self, obj):
        if isinstance(obj, dict):
            yield obj
            for value in obj.values():
                yield from self._walk_dicts(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from self._walk_dicts(item)

    def _walk_values(self, obj):
        if isinstance(obj, dict):
            for value in obj.values():
                yield from self._walk_values(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from self._walk_values(item)
        else:
            yield obj

    def _append_unique(self, matches: list, seen: set, match: dict | None, query: str) -> None:
        if not match:
            return
        if query and query not in match["team1"].lower() and query not in match["team2"].lower():
            return
        key = schedule_identity_key(match)
        if key in seen:
            return
        seen.add(key)
        matches.append(match)

    def _upsert_schedule_match(self, matches: list, seen: set, match: dict | None, query: str) -> None:
        """Merge live LoLEsports rows into an existing Liquipedia slot when possible."""
        if not match:
            return
        if query and query not in match["team1"].lower() and query not in match["team2"].lower():
            return
        key = schedule_identity_key(match)
        if key in seen:
            for index, existing in enumerate(matches):
                if schedule_identity_key(existing) != key:
                    continue
                merged = dict(existing)
                if match.get("state") == "inProgress":
                    merged.update(match)
                    merged["datetime"] = existing.get("datetime", match.get("datetime"))
                    merged["datetime_brt"] = existing.get("datetime_brt", match.get("datetime_brt"))
                    merged["datetime_obj"] = existing.get("datetime_obj", match.get("datetime_obj"))
                    merged["schedule_authority"] = existing.get("schedule_authority", match.get("source"))
                matches[index] = merged
                return
            return
        self._append_unique(matches, seen, match, query)

    def _remember_team_logo(self, team: str, image: str) -> None:
        key = _team_key(team)
        logo = _clean_image_url(image)
        if key and logo:
            self.team_logos[key] = logo

    def _enrich_logos_from_lolesports(self, matches: list[dict]) -> None:
        logos: dict[str, str] = dict(self.team_logos)
        for match in matches:
            if match.get("source") != "LoLEsports":
                continue
            for team_key, image_key in (("team1", "team1_image"), ("team2", "team2_image")):
                team = _team_key(match.get(team_key, ""))
                image = _clean_image_url(match.get(image_key, ""))
                if team and image:
                    logos[team] = image

        if not logos:
            return

        for match in matches:
            for team_key, image_key in (("team1", "team1_image"), ("team2", "team2_image")):
                current = _clean_image_url(match.get(image_key, ""))
                official = logos.get(_team_key(match.get(team_key, "")))
                if official and (not current or match.get("source") != "LoLEsports"):
                    match[image_key] = official
                else:
                    match[image_key] = current

    def _fetch_pandascore_running(self) -> list[dict]:
        if not PANDA_TOKEN:
            return []
        try:
            response = self.panda.get(f"{PANDA_BASE}/lol/matches/running", params={"page[size]": 50}, timeout=10)
            if response.status_code != 200:
                return []
            return [m for raw in response.json() if (m := self._parse_pandascore(raw, "inProgress"))]
        except Exception:
            return []

    def _fetch_pandascore_upcoming(self) -> list[dict]:
        if not PANDA_TOKEN:
            return []
        try:
            response = self.panda.get(
                f"{PANDA_BASE}/lol/matches/upcoming",
                params={"sort": "begin_at", "page[size]": 80},
                timeout=10,
            )
            if response.status_code != 200:
                return []
            limit = datetime.now(timezone.utc) + timedelta(days=4)
            parsed = []
            for raw in response.json():
                begin_at = raw.get("begin_at")
                dt = parse_to_brt(begin_at)
                if not dt or dt.astimezone(timezone.utc) > limit:
                    continue
                item = self._parse_pandascore(raw, "unstarted")
                if item:
                    parsed.append(item)
            return parsed
        except Exception:
            return []

    def _fetch_oddspapi_schedule(self) -> list[dict]:
        client = OddsPapiClient()
        if not client.configured:
            return []

        try:
            fixtures = client.fetch_lol_fixtures("pinnacle")
            if not any(league_from_text(fixture.get("tournamentName", "")) == "lpl" for fixture in fixtures):
                fixtures.extend(client.fetch_lol_tournament_fixtures(["lpl"], days_ahead=5))
        except Exception:
            return []

        matches: list[dict] = []
        for fixture in fixtures:
            t1 = fix_name(fixture.get("participant1Name") or fixture.get("participant1ShortName") or "")
            t2 = fix_name(fixture.get("participant2Name") or fixture.get("participant2ShortName") or "")
            dt = parse_to_brt(fixture.get("startTime"))
            if not t1 or not t2 or not dt or t1.lower() == t2.lower():
                continue

            status_id = fixture.get("statusId")
            state = "unstarted"
            if status_id == 1:
                elapsed = (now_brt() - dt).total_seconds() / 3600
                if 0 <= elapsed <= 5:
                    state = "inProgress"
                else:
                    continue
            elif status_id in (2, 3):
                continue

            tournament = fixture.get("tournamentName") or fixture.get("categoryName") or "OddsPapi"
            code = league_from_text(tournament)
            if code == "_unknown":
                code = guess_league(t1, t2)
            if code == "lpl" and not is_verified_lpl_match(t1, t2):
                code = "_unknown"
            matches.append(self._mk(
                t1,
                t2,
                code,
                get_league_info(code),
                dt,
                state,
                tournament,
                "3",
                "",
                "",
                fixture.get("fixtureId"),
                "OddsPapi",
            ))
        return matches

    def _parse_pandascore(self, raw: dict, forced_state: str) -> dict | None:
        opponents = raw.get("opponents") or []
        if len(opponents) < 2:
            return None
        o1 = opponents[0].get("opponent") or {}
        o2 = opponents[1].get("opponent") or {}
        t1 = fix_name(o1.get("name", ""))
        t2 = fix_name(o2.get("name", ""))
        if not t1 or not t2:
            return None

        begin_at = raw.get("begin_at")
        dt = parse_to_brt(begin_at) or now_brt()
        status = raw.get("status")
        state = "unstarted"
        if forced_state == "inProgress" or status == "running":
            elapsed = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
            if 0 <= elapsed <= 5:
                state = "inProgress"
            else:
                return None
        elif status in ("finished", "canceled"):
            return None

        league = raw.get("league") or {}
        serie = raw.get("serie") or {}
        tournament_name = f"{league.get('name', '')} {serie.get('full_name', '')}".strip()
        code = league_from_text(tournament_name)
        if code == "_unknown":
            code = guess_league(t1, t2)
        if code == "lpl" and not is_verified_lpl_match(t1, t2):
            code = "_unknown"
        info = get_league_info(code)
        item = self._mk(
            t1,
            t2,
            code,
            info,
            dt,
            state,
            tournament_name or league.get("name", ""),
            str(raw.get("number_of_games") or 3),
            o1.get("image_url", ""),
            o2.get("image_url", ""),
            raw.get("id"),
            "PandaScore",
        )
        item["panda_team1_id"] = o1.get("id")
        item["panda_team2_id"] = o2.get("id")
        item["panda_slug"] = raw.get("slug", "")
        return item

    def _fetch_lolesports_live(self) -> list[dict]:
        if not LOLESPORTS_KEY:
            return []
        try:
            response = self.live.get(self.LS_LIVE, params={"hl": "pt-BR"}, timeout=8)
            if response.status_code != 200:
                return []
            events = response.json().get("data", {}).get("schedule", {}).get("events", [])
            parsed = []
            for event in events:
                if event.get("type") != "match":
                    continue
                if str(event.get("state", "")).lower() not in ("inprogress", "in_progress", "live"):
                    continue
                teams = event.get("match", {}).get("teams", [])
                if len(teams) < 2:
                    continue
                for team in teams:
                    self._remember_team_logo(team.get("name", ""), team.get("image", ""))
                dt = parse_to_brt(event.get("startTime"))
                if dt:
                    elapsed = (now_brt() - dt).total_seconds() / 3600
                    if elapsed < 0 or elapsed > 5:
                        continue
                code = league_from_text(event.get("league", {}).get("name", ""))
                if code == "_unknown":
                    code = guess_league(teams[0].get("name", ""), teams[1].get("name", ""))
                if code == "lpl" and not is_verified_lpl_match(teams[0].get("name", ""), teams[1].get("name", "")):
                    code = "_unknown"
                info = get_league_info(code)
                active_game = next(
                    (game for game in event.get("match", {}).get("games", [])
                     if str(game.get("state", "")).lower() in ("inprogress", "in_progress", "live")),
                    None,
                )
                item = self._mk(
                    teams[0].get("name", "Team A"),
                    teams[1].get("name", "Team B"),
                    code,
                    info,
                    dt or now_brt(),
                    "inProgress",
                    event.get("league", {}).get("name", ""),
                    "3",
                    teams[0].get("image", ""),
                    teams[1].get("image", ""),
                    event.get("id"),
                    "LoLEsports",
                )
                item["lolesports_event_id"] = event.get("id")
                item["lolesports_game_id"] = (active_game or {}).get("id", "")
                item["live_stats_status"] = "enabled" if item["lolesports_game_id"] else "waiting_game_id"
                if active_game:
                    team_by_id = {team.get("id"): fix_name(team.get("name", "")) for team in teams}
                    for side_team in active_game.get("teams") or []:
                        if side_team.get("side") == "blue":
                            item["blue_team"] = team_by_id.get(side_team.get("id"), "Azul")
                        if side_team.get("side") == "red":
                            item["red_team"] = team_by_id.get(side_team.get("id"), "Vermelho")
                streams = event.get("streams") or []
                if streams:
                    item["stream_provider"] = streams[0].get("provider", "")
                    item["stream_parameter"] = streams[0].get("parameter", "")
                parsed.append(item)
            return parsed
        except Exception:
            return []

    def _fetch_lolesports_schedule(self) -> list[dict]:
        if not LOLESPORTS_KEY:
            return []

        parsed: list[dict] = []
        now_brt_dt = now_brt()
        window_start = (now_brt_dt - timedelta(hours=5)).astimezone(timezone.utc)
        window_end = (now_brt_dt + timedelta(hours=72)).astimezone(timezone.utc)

        for code, league_id in self.LS_LEAGUES.items():
            try:
                response = self.live.get(
                    self.LS_SCHEDULE,
                    params={"hl": "pt-BR", "leagueId": league_id},
                    timeout=10,
                )
                if response.status_code != 200:
                    continue

                events = response.json().get("data", {}).get("schedule", {}).get("events", [])
                for event in events:
                    if event.get("type") != "match":
                        continue
                    event_teams = event.get("match", {}).get("teams", [])
                    for team in event_teams:
                        self._remember_team_logo(team.get("name", ""), team.get("image", ""))
                    state_raw = str(event.get("state", "")).lower()
                    if state_raw == "completed":
                        continue

                    dt = parse_to_brt(event.get("startTime"))
                    if not dt:
                        continue
                    dt_utc = dt.astimezone(timezone.utc)
                    if dt_utc < window_start or dt_utc > window_end:
                        continue

                    teams = event_teams
                    if len(teams) < 2:
                        continue

                    t1 = fix_name(teams[0].get("name", ""))
                    t2 = fix_name(teams[1].get("name", ""))
                    if not t1 or not t2:
                        continue
                    if t1.lower() == "tbd" and t2.lower() == "tbd":
                        if code != "msi":
                            continue
                        t1 = f"MSI Slot {len([m for m in parsed if m.get('league_code') == 'msi']) * 2 + 1}"
                        t2 = f"MSI Slot {len([m for m in parsed if m.get('league_code') == 'msi']) * 2 + 2}"
                    elif t1.lower() == t2.lower():
                        continue

                    state = "inProgress" if state_raw in ("inprogress", "in_progress", "live") else "unstarted"
                    if code == "lpl" and not is_verified_lpl_match(t1, t2):
                        # LPL schedules can briefly contain TBD slots. Keep named Chinese teams only.
                        continue

                    active_game = next(
                        (game for game in event.get("match", {}).get("games", [])
                         if str(game.get("state", "")).lower() in ("inprogress", "in_progress", "live")),
                        None,
                    )
                    item = self._mk(
                        t1,
                        t2,
                        code,
                        get_league_info(code),
                        dt,
                        state,
                        event.get("league", {}).get("name", get_league_info(code)["name"]),
                        str(event.get("match", {}).get("strategy", {}).get("count") or 3),
                        teams[0].get("image", ""),
                        teams[1].get("image", ""),
                        event.get("id"),
                        "LoLEsports",
                    )
                    item["lolesports_event_id"] = event.get("id")
                    item["lolesports_game_id"] = (active_game or {}).get("id", "") if state == "inProgress" else ""
                    item["live_stats_status"] = "enabled" if item["lolesports_game_id"] else ""
                    if active_game:
                        team_by_id = {team.get("id"): fix_name(team.get("name", "")) for team in teams}
                        for side_team in active_game.get("teams") or []:
                            if side_team.get("side") == "blue":
                                item["blue_team"] = team_by_id.get(side_team.get("id"), "Azul")
                            if side_team.get("side") == "red":
                                item["red_team"] = team_by_id.get(side_team.get("id"), "Vermelho")
                    streams = event.get("streams") or []
                    if streams:
                        item["stream_provider"] = streams[0].get("provider", "")
                        item["stream_parameter"] = streams[0].get("parameter", "")
                    parsed.append(item)
            except Exception:
                continue

        return parsed

    def _fetch_liquipedia_true_schedule(self) -> list[dict]:
        """Liquipedia agenda for LCK, LPL and CBLOL (source of truth for date/teams)."""
        now_brt_dt = now_brt()
        window_start = (now_brt_dt - timedelta(hours=5)).astimezone(timezone.utc)
        window_end = (now_brt_dt + timedelta(hours=72)).astimezone(timezone.utc)
        matches: list[dict] = []

        for row in fetch_liquipedia_schedule_raw():
            code = row.get("league_code", "_unknown")
            if code not in LIQUIPEDIA_SCHEDULE_LEAGUES:
                continue
            dt = row.get("datetime_brt")
            if not isinstance(dt, datetime):
                dt = parse_to_brt(row.get("datetime"))
            if not dt:
                continue
            dt_utc = dt.astimezone(timezone.utc)
            if dt_utc < window_start or dt_utc > window_end:
                continue

            t1 = fix_name(row.get("team1", ""))
            t2 = fix_name(row.get("team2", ""))
            if not t1 or not t2 or t1.lower() == t2.lower():
                continue
            if code == "lpl" and not is_verified_lpl_match(t1, t2):
                continue

            best_of = str(row.get("best_of") or "3")
            tournament = row.get("tournament") or get_league_info(code)["name"]
            item = self._mk(
                t1,
                t2,
                code,
                get_league_info(code),
                dt,
                "unstarted",
                tournament,
                best_of,
                source="Liquipedia",
            )
            item["schedule_authority"] = "Liquipedia"
            item["liquipedia_tournament"] = tournament
            matches.append(item)
        return matches

    def _fetch_leaguepedia_schedule(self, query: str = "") -> list[dict]:
        cache_key = query.strip().lower() or "__all__"
        cached = _LEAGUEPEDIA_CACHE.get(cache_key)
        if cached:
            cached_at, cached_matches = cached
            if (datetime.now(timezone.utc) - cached_at).total_seconds() < LEAGUEPEDIA_CACHE_TTL:
                return [dict(match) for match in cached_matches]

        now_utc = datetime.now(timezone.utc)
        where = (
            "DateTime_UTC >= '" + now_utc.strftime("%Y-%m-%d %H:%M:%S") + "' "
            "AND DateTime_UTC <= '" + (now_utc + timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S") + "'"
        )
        if query.strip():
            q = query.strip().replace("'", "''")
            where += f" AND (Team1 LIKE '%{q}%' OR Team2 LIKE '%{q}%' OR OverviewPage LIKE '%{q}%')"
        params = {
            "action": "cargoquery",
            "tables": "MatchSchedule",
            "fields": "Team1,Team2,DateTime_UTC,OverviewPage,BestOf",
            "where": where,
            "order_by": "DateTime_UTC ASC",
            "limit": "120",
            "format": "json",
        }
        try:
            response = requests.get(self.LQ_API, params=params, headers=self.LQ_HEADERS, timeout=12)
            if response.status_code != 200:
                return [dict(match) for match in cached[1]] if cached else []
            matches = []
            for row in response.json().get("cargoquery", []):
                data = row.get("title", row)
                t1 = (data.get("Team1") or "").strip()
                t2 = (data.get("Team2") or "").strip()
                dt = parse_to_brt(data.get("DateTime UTC") or data.get("DateTime_UTC"))
                if not t1 or not t2 or not dt or t1.lower() == t2.lower():
                    continue
                overview = data.get("OverviewPage") or ""
                code = league_from_text(overview)
                if code == "_unknown":
                    code = guess_league(t1, t2)
                if code == "lpl" and not is_verified_lpl_match(t1, t2):
                    code = "_unknown"
                matches.append(self._mk(
                    t1,
                    t2,
                    code,
                    get_league_info(code),
                    dt,
                    "unstarted",
                    overview,
                    data.get("BestOf") or "3",
                    source="Leaguepedia",
                ))
            if matches:
                _LEAGUEPEDIA_CACHE[cache_key] = (datetime.now(timezone.utc), matches)
            return matches
        except Exception:
            return [dict(match) for match in cached[1]] if cached else []

    def _fetch_liquipedia_schedule(self, query: str = "") -> list[dict]:
        return self._fetch_liquipedia_true_schedule()

    def _demo_matches(self, query: str = "") -> list[dict]:
        base = now_brt()
        rows = [
            ("KaBuM! Esports", "LOUD", "cblol", 1.5),
            ("paiN Gaming", "FURIA Esports", "cblol", 3.0),
            ("T1 Esports", "Gen.G", "lck", 5.0),
            ("BNK FearX", "KT Rolster", "lck", 8.0),
            ("G2 Esports", "Fnatic", "lec", 12.0),
            ("Cloud9", "FlyQuest", "lcs", 20.0),
            ("JDG", "BLG", "lpl", 24.0),
            ("RED Canids", "Fluxo W7M", "cblol", 30.0),
        ]
        matches = [
            self._mk(t1, t2, code, get_league_info(code), base + timedelta(hours=hours), "unstarted", "", "3", source="Demo")
            for t1, t2, code, hours in rows
        ]
        if query.strip():
            q = query.strip().lower()
            matches = [m for m in matches if q in m["team1"].lower() or q in m["team2"].lower()]
        for match in matches:
            match["source"] = "Demo"
            match["is_demo"] = True
        return matches

    def _mk(
        self,
        team1: str,
        team2: str,
        league_code: str,
        league_info: dict,
        dt: datetime,
        state: str,
        tournament: str = "",
        best_of: str = "3",
        team1_image: str = "",
        team2_image: str = "",
        panda_id=None,
        source: str = "Sistema",
    ) -> dict:
        dt = dt.astimezone(TZ_BRT)
        return {
            "league": league_info.get("name", "Torneio"),
            "league_display": league_info.get("display", "Torneio"),
            "league_code": league_code,
            "league_tier": league_info.get("tier", 2),
            "is_main_league": league_info.get("main", True),
            "datetime": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "datetime_brt": dt.strftime("%d/%m %H:%M"),
            "datetime_brt_date": dt.strftime("%Y-%m-%d"),
            "datetime_obj": dt,
            "team1": fix_name(team1),
            "team2": fix_name(team2),
            "team1_code": fix_name(team1)[:4].upper(),
            "team2_code": fix_name(team2)[:4].upper(),
            "team1_image": _clean_image_url(team1_image),
            "team2_image": _clean_image_url(team2_image),
            "state": state,
            "blockName": tournament,
            "tournament": tournament,
            "best_of": str(best_of),
            "panda_id": panda_id,
            "source": source,
            "is_manual": False,
            "is_demo": False,
        }

    def build_manual_match(self, team1: str, team2: str) -> dict:
        code = guess_league(team1, team2)
        return {**self._mk(team1, team2, code, get_league_info(code), now_brt(), "unstarted"), "is_manual": True}

    def get_team_stats(self, team_name: str, league_code: str, last_n: int = 15) -> dict:
        return self._estimate_stats(team_name, league_code)

    def fetch_team_stats_cargo(self, team_name: str, last_n: int = 15) -> dict:
        cache_key = f"{_team_key(team_name)}|{last_n}"
        cached = _TEAM_STATS_CARGO_CACHE.get(cache_key)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < TEAM_STATS_CARGO_CACHE_TTL:
            return dict(cached[1])

        rows = self._query_scoreboard_games(team_name, last_n)
        stats = self._summarize_cargo_stats(team_name, rows, last_n)
        _TEAM_STATS_CARGO_CACHE[cache_key] = (datetime.now(timezone.utc), stats)
        return dict(stats)

    def _query_scoreboard_games(self, team_name: str, last_n: int) -> list[dict]:
        terms = self._cargo_team_terms(team_name)
        if not terms:
            return []
        where_terms = []
        for term in terms:
            safe = term.replace("'", "''")
            where_terms.append(f"Team1 LIKE '%{safe}%' OR Team2 LIKE '%{safe}%'")
        where = (
            "(" + " OR ".join(f"({term})" for term in where_terms) + ") "
            "AND DateTime_UTC <= '" + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "'"
        )
        fields = (
            "Team1,Team2,Winner,Team1Kills,Team2Kills,Team1Towers,Team2Towers,"
            "Team1Dragons,Team2Dragons,Gamelength,DateTime_UTC,OverviewPage"
        )
        params = {
            "action": "cargoquery",
            "tables": "ScoreboardGames",
            "fields": fields,
            "where": where,
            "order_by": "DateTime_UTC DESC",
            "limit": str(max(last_n * 4, 40)),
            "format": "json",
        }
        try:
            response = requests.get(self.LQ_API, params=params, headers=self.LQ_HEADERS, timeout=12)
            if response.status_code != 200:
                return []
            data = response.json()
            if data.get("error"):
                return []
            return [row.get("title", row) for row in data.get("cargoquery", [])]
        except Exception:
            return []

    @staticmethod
    def _cargo_team_terms(team_name: str) -> list[str]:
        cleaned = fix_name(team_name)
        key = _team_key(cleaned)
        terms = {cleaned, key}
        compact_aliases = {
            "t1 esports": "T1",
            "t1": "T1",
            "gen g esports": "Gen.G",
            "dplus kia": "Dplus KIA",
            "hanwha life esports": "Hanwha Life Esports",
            "jd gaming": "JDG",
            "bilibili gaming": "BLG",
            "top esports": "Top Esports",
            "g2 esports": "G2 Esports",
        }
        if key in compact_aliases:
            terms.add(compact_aliases[key])
        if key.endswith(" esports"):
            terms.add(key[:-8].strip())
        return [term for term in terms if term]

    def _summarize_cargo_stats(self, team_name: str, rows: list[dict], last_n: int) -> dict:
        target = _team_key(team_name)
        games: list[dict] = []
        for row in rows:
            team1 = str(self._cargo_value(row, "Team1") or "")
            team2 = str(self._cargo_value(row, "Team2") or "")
            side = 1 if self._same_cargo_team(target, team1) else (2 if self._same_cargo_team(target, team2) else 0)
            if not side:
                continue

            kills_for = self._to_float(self._cargo_value(row, f"Team{side}Kills", f"Team{side} Kills"))
            kills_against = self._to_float(self._cargo_value(row, f"Team{2 if side == 1 else 1}Kills", f"Team{2 if side == 1 else 1} Kills"))
            towers = self._to_float(self._cargo_value(row, f"Team{side}Towers", f"Team{side} Towers"))
            dragons = self._to_float(self._cargo_value(row, f"Team{side}Dragons", f"Team{side} Dragons"))
            length = self._parse_game_length_minutes(self._cargo_value(row, "Gamelength", "GameLength", "Game Length"))
            winner = str(self._cargo_value(row, "Winner") or "").strip()
            won = winner == str(side) or self._same_cargo_team(target, winner)
            games.append({
                "kills_for": kills_for,
                "kills_against": kills_against,
                "towers": towers,
                "dragons": dragons,
                "length": length,
                "won": won,
            })
            if len(games) >= last_n:
                break

        if not games:
            return {}

        def avg(key: str) -> float | None:
            values = [game[key] for game in games if game.get(key) is not None]
            return float(np.mean(values)) if values else None

        wins = sum(1 for game in games if game["won"])
        recent = ["W" if game["won"] else "L" for game in games[:5]]
        avg_kills = avg("kills_for")
        avg_deaths = avg("kills_against")
        avg_length = avg("length")
        avg_towers = avg("towers")
        avg_dragons = avg("dragons")
        total_kills = [
            game["kills_for"] + game["kills_against"]
            for game in games
            if game.get("kills_for") is not None and game.get("kills_against") is not None
        ]
        winrate = wins / len(games)
        return {
            "games_analyzed": len(games),
            "winrate": float(winrate),
            "avg_kills": float(avg_kills) if avg_kills is not None else 0.0,
            "avg_deaths": float(avg_deaths) if avg_deaths is not None else 0.0,
            "avg_game_length": float(avg_length) if avg_length is not None else 0.0,
            "avg_towers": float(avg_towers) if avg_towers is not None else 0.0,
            "avg_dragons": float(avg_dragons) if avg_dragons is not None else 0.0,
            "total_kills_avg": float(np.mean(total_kills)) if total_kills else 0.0,
            "form": {
                "results": recent,
                "form_class": "good" if winrate >= .58 else ("bad" if winrate <= .43 else "neutral"),
                "form_label": "Boa fase" if winrate >= .58 else ("Instável" if winrate <= .43 else "Regular"),
            },
            "source": "Leaguepedia Cargo",
        }

    @staticmethod
    def _same_cargo_team(target_key: str, value: str) -> bool:
        candidate = _team_key(value)
        return bool(candidate and (candidate == target_key or candidate in target_key or target_key in candidate))

    @staticmethod
    def _cargo_value(row: dict, *names: str):
        normalized = {re.sub(r"[^a-z0-9]", "", str(key).lower()): value for key, value in row.items()}
        for name in names:
            if name in row:
                return row[name]
            compact = re.sub(r"[^a-z0-9]", "", name.lower())
            if compact in normalized:
                return normalized[compact]
        return None

    @staticmethod
    def _to_float(value) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_game_length_minutes(cls, value) -> float | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        if ":" in text:
            parts = [cls._to_float(part) or 0.0 for part in text.split(":")]
            if len(parts) == 2:
                return parts[0] + parts[1] / 60
            if len(parts) == 3:
                return parts[0] * 60 + parts[1] + parts[2] / 60
        numeric = cls._to_float(text)
        if numeric is None:
            return None
        return numeric / 60 if numeric > 90 else numeric

    def _estimate_stats(self, name: str, league_code: str) -> dict:
        local_stats = query_team_stats(name, league_code)
        if local_stats:
            tier = self.resolve_tier(local_stats.get("team_name", name))
            return {
                **local_stats,
                "tier": tier,
                "first_blood_rate": 0.5,
                "avg_golddiff15": 0.0,
            }

        tier = self.resolve_tier(name)
        profile = TIER_PROFILE[tier]
        seed = sum(ord(char) for char in f"{name}{league_code}".lower())
        rng = np.random.RandomState(seed)
        winrate = float(np.clip(rng.normal(profile["wr"], 0.06), 0.2, 0.9))
        form = {
            "results": ["W" if rng.random() < winrate else "L" for _ in range(5)],
            "form_class": "good" if winrate >= .58 else ("bad" if winrate <= .43 else "neutral"),
            "form_label": "Boa fase" if winrate >= .58 else ("Instável" if winrate <= .43 else "Regular"),
        }
        estimated = {
            "games_analyzed": 15,
            "tier": tier,
            "winrate": winrate,
            "avg_kills": float(np.clip(rng.normal(profile["kills"], 2.4), 6, 28)),
            "avg_deaths": float(np.clip(rng.normal(profile["kills"] * 0.72, 2.2), 4, 24)),
            "avg_game_length": float(np.clip(rng.normal(profile["length"], 3.0), 24, 46)),
            "avg_towers": float(np.clip(rng.normal(5.2 + profile["wr"] * 2.6, 1.0), 3, 11)),
            "avg_dragons": float(np.clip(rng.normal(1.3 + profile["fd"] * 2.1, .65), .5, 4.8)),
            "first_blood_rate": float(np.clip(rng.normal(profile["fb"], 0.07), .25, .82)),
            "first_dragon_rate": float(np.clip(rng.normal(profile["fd"], 0.07), .25, .82)),
            "first_baron_rate": float(np.clip(rng.normal(profile["fd"], 0.07), .25, .82)),
            "avg_golddiff15": float(rng.normal(profile["gd"], 450)),
            "total_kills_avg": float(np.clip(rng.normal(profile["kills"] * 1.75, 4), 12, 44)),
            "form": form,
            "source": f"Estimado Tier {tier}",
        }
        cargo = self.fetch_team_stats_cargo(name)
        if not cargo:
            return estimated

        merged = {**estimated, **{key: value for key, value in cargo.items() if value not in (None, "", 0, 0.0)}}
        merged["tier"] = tier
        merged["first_blood_rate"] = estimated["first_blood_rate"]
        merged["first_dragon_rate"] = estimated["first_dragon_rate"]
        merged["first_baron_rate"] = estimated["first_baron_rate"]
        merged["avg_golddiff15"] = estimated["avg_golddiff15"]
        merged["source"] = cargo.get("source", "Leaguepedia Cargo")
        return merged

    def scrape_liquipedia_url(self, url: str) -> tuple[list[dict], str]:
        return self._fetch_liquipedia_schedule(url), "Liquipedia"
