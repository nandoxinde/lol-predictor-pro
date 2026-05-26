"""Data layer for LoL Predictor.

Sources:
- PandaScore for real running/upcoming matches and team images.
- LoLEsports for additional validated live events when configured.
- Liquipedia Cargo as a schedule fallback only. It never marks games live.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

from modules.config import get_secret
from modules.odds_fetcher import OddsPapiClient

TZ_BRT = timezone(timedelta(hours=-3))
PANDA_BASE = "https://api.pandascore.co"
PANDA_TOKEN = get_secret("PANDASCORE_TOKEN")
LOLESPORTS_KEY = get_secret("LOLESPORTS_API_KEY")


def now_brt() -> datetime:
    return datetime.now(tz=TZ_BRT)


def parse_to_brt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T")).astimezone(TZ_BRT)
    except Exception:
        return None


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
}


def fix_name(name: str) -> str:
    cleaned = (name or "").strip()
    return NAME_FIX.get(cleaned.lower(), cleaned)


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
    "_unknown": {"name": "Torneio", "display": "Torneio", "tier": 2, "main": True},
}
LEAGUE_CONFIDENCE_CAP = {1: 1.0, 2: 0.9, 3: 0.78}


def get_league_info(code: str) -> dict:
    return LEAGUE_INFO.get(code, LEAGUE_INFO["_unknown"])


def league_from_text(text: str) -> str:
    lower = (text or "").lower()
    mapping = [
        ("cblol academy", "cblol_acad"),
        ("cblol acad", "cblol_acad"),
        ("lck challengers", "lck_cl"),
        ("lck cl", "lck_cl"),
        ("lcs academy", "lcs_acad"),
        ("lcs acad", "lcs_acad"),
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
        ("ewc", "ewc"),
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
            "icon": "🏆",
            "category": "segura",
        })

    p27 = min(0.94, max(0.35, 0.55 + (avg_len - 27) * 0.045))
    decisions.append({
        "market": "Duração >27 minutos",
        "entry": "Jogo passa de 27 minutos",
        "confidence": round(p27 * 100, 1),
        "probability": p27,
        "icon": "⏱",
        "category": "segura",
    })

    p30 = min(0.88, max(0.25, 0.50 + (avg_len - 30) * 0.04))
    decisions.append({
        "market": "Duração >30 minutos",
        "entry": "Jogo passa de 30 minutos",
        "confidence": round(p30 * 100, 1),
        "probability": p30,
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
        "icon": "🩸",
        "category": "risco",
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

        for match in self._fetch_pandascore_running():
            self._append_unique(matches, seen, match, query_norm)
        for match in self._fetch_lolesports_live():
            self._append_unique(matches, seen, match, query_norm)
        for match in self._fetch_pandascore_upcoming():
            self._append_unique(matches, seen, match, query_norm)
        for match in self._fetch_oddspapi_schedule():
            self._append_unique(matches, seen, match, query_norm)
        for match in self._fetch_liquipedia_schedule(query):
            self._append_unique(matches, seen, match, query_norm)

        matches.sort(key=lambda item: (0 if item.get("state") == "inProgress" else 1, item.get("datetime", "")))
        if matches:
            return matches, "real"
        return self._demo_matches(query), "demo"

    def _append_unique(self, matches: list, seen: set, match: dict | None, query: str) -> None:
        if not match:
            return
        if query and query not in match["team1"].lower() and query not in match["team2"].lower():
            return
        key = f"{match['team1'].lower()}|{match['team2'].lower()}|{match.get('datetime', '')[:10]}"
        if key in seen:
            return
        seen.add(key)
        matches.append(match)

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
        code = league_from_text(f"{league.get('name', '')} {serie.get('full_name', '')}")
        if code == "_unknown":
            code = guess_league(t1, t2)
        info = get_league_info(code)
        return self._mk(
            t1,
            t2,
            code,
            info,
            dt,
            state,
            league.get("name", ""),
            str(raw.get("number_of_games") or 3),
            o1.get("image_url", ""),
            o2.get("image_url", ""),
            raw.get("id"),
            "PandaScore",
        )

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
                dt = parse_to_brt(event.get("startTime"))
                if dt:
                    elapsed = (now_brt() - dt).total_seconds() / 3600
                    if elapsed < 0 or elapsed > 5:
                        continue
                code = league_from_text(event.get("league", {}).get("name", ""))
                if code == "_unknown":
                    code = guess_league(teams[0].get("name", ""), teams[1].get("name", ""))
                info = get_league_info(code)
                parsed.append(self._mk(
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
                ))
            return parsed
        except Exception:
            return []

    def _fetch_liquipedia_schedule(self, query: str = "") -> list[dict]:
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
                return []
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
            return matches
        except Exception:
            return []

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
            "datetime_obj": dt,
            "team1": fix_name(team1),
            "team2": fix_name(team2),
            "team1_code": fix_name(team1)[:4].upper(),
            "team2_code": fix_name(team2)[:4].upper(),
            "team1_image": team1_image or "",
            "team2_image": team2_image or "",
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

    def fetch_team_stats_cargo(self, team_name: str) -> dict:
        return {}

    def _estimate_stats(self, name: str, league_code: str) -> dict:
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
        return {
            "games_analyzed": 15,
            "tier": tier,
            "winrate": winrate,
            "avg_kills": float(np.clip(rng.normal(profile["kills"], 2.4), 6, 28)),
            "avg_deaths": float(np.clip(rng.normal(profile["kills"] * 0.72, 2.2), 4, 24)),
            "avg_game_length": float(np.clip(rng.normal(profile["length"], 3.0), 24, 46)),
            "first_blood_rate": float(np.clip(rng.normal(profile["fb"], 0.07), .25, .82)),
            "first_dragon_rate": float(np.clip(rng.normal(profile["fd"], 0.07), .25, .82)),
            "first_baron_rate": float(np.clip(rng.normal(profile["fd"], 0.07), .25, .82)),
            "avg_golddiff15": float(rng.normal(profile["gd"], 450)),
            "total_kills_avg": float(np.clip(rng.normal(profile["kills"] * 1.75, 4), 12, 44)),
            "form": form,
            "source": f"Estimado Tier {tier}",
        }

    def scrape_liquipedia_url(self, url: str) -> tuple[list[dict], str]:
        return self._fetch_liquipedia_schedule(url), "Liquipedia"
