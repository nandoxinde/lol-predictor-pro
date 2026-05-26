"""Local private stats API backed by SQLite.

The database is populated from Oracle's Elixir public match CSVs and queried
by the app before falling back to external APIs.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "private_stats.sqlite"
OE_LEAGUES = {"lck": "LCK", "lpl": "LPL", "cblol": "CBLOL"}
OE_URL_TEMPLATES = (
    "https://oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com/"
    "{year}_LoL_esports_match_data_from_OraclesElixir.csv",
    "https://oracleselixir-downloadable-match-data.s3.us-west-2.amazonaws.com/"
    "{year}_LoL_esports_match_data_from_OraclesElixir.csv",
    "https://huggingface.co/datasets/Finish-him/esports-data/resolve/main/lol/"
    "{year}_LoL_esports_match_data_from_OraclesElixir.csv?download=true",
)


def _team_key(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    aliases = {
        "t1 esports": "t1",
        "gen g esports": "gen g",
        "dplus kia": "dplus kia",
        "dk": "dplus kia",
        "jd gaming": "jdg",
        "bilibili gaming": "blg",
        "top esports": "top esports",
        "tes": "top esports",
        "hanwha life esports": "hanwha life",
        "pain gaming": "pain gaming",
        "loud": "loud",
    }
    return aliases.get(text, text)


def _to_float(value, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _to_bool(value) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "win"}


def _candidate_years() -> list[int]:
    now = datetime.now(timezone.utc).year
    return [now, now - 1, now - 2]


def _open_oracles_csv(year: int):
    last_error: Exception | None = None
    for template in OE_URL_TEMPLATES:
        url = template.format(year=year)
        request = Request(url, headers={"User-Agent": "LoLPredictorPro/2.0 local stats sync"})
        try:
            response = urlopen(request, timeout=30)
            return response
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError(f"Oracle's Elixir CSV unavailable for {year}")


def init_db(db_path: Path | str = DB_PATH) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_stats (
                team_key TEXT NOT NULL,
                team_name TEXT NOT NULL,
                league TEXT NOT NULL,
                year INTEGER NOT NULL,
                games INTEGER NOT NULL,
                wins INTEGER NOT NULL,
                avg_kills REAL NOT NULL,
                avg_deaths REAL NOT NULL,
                avg_towers REAL NOT NULL,
                avg_dragons REAL NOT NULL,
                avg_barons REAL NOT NULL,
                avg_game_length REAL NOT NULL,
                first_dragon_rate REAL NOT NULL,
                first_baron_rate REAL NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (team_key, league)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_team_stats_league ON team_stats(league, team_name)"
        )
    return path


def sync_historical_stats(
    years: list[int] | tuple[int, ...] | None = None,
    leagues: tuple[str, ...] = ("LCK", "LPL", "CBLOL"),
    db_path: Path | str = DB_PATH,
) -> dict:
    """Download Oracle's Elixir data and refresh local team aggregates."""

    path = init_db(db_path)
    wanted_leagues = {league.upper() for league in leagues}
    selected_years = list(years or _candidate_years())
    aggregates: dict[tuple[str, str], dict] = {}
    source_years: list[int] = []

    for year in selected_years:
        try:
            response = _open_oracles_csv(year)
        except Exception:
            continue

        source_years.append(year)
        decoded = (line.decode("utf-8", errors="replace") for line in response)
        reader = csv.DictReader(decoded)
        for row in reader:
            league = (row.get("league") or "").upper().strip()
            if league not in wanted_leagues:
                continue

            position = (row.get("position") or "").lower().strip()
            participant_id = str(row.get("participantid") or "").strip()
            if position != "team" and participant_id not in {"100", "200"}:
                continue

            team_name = (row.get("teamname") or "").strip()
            if not team_name:
                continue

            team_key = _team_key(team_name)
            key = (team_key, league)
            item = aggregates.setdefault(
                key,
                {
                    "team_key": team_key,
                    "team_name": team_name,
                    "league": league,
                    "year": year,
                    "games": 0,
                    "wins": 0,
                    "kills": 0.0,
                    "deaths": 0.0,
                    "towers": 0.0,
                    "dragons": 0.0,
                    "barons": 0.0,
                    "length": 0.0,
                    "first_dragons": 0,
                    "first_barons": 0,
                },
            )
            item["team_name"] = team_name
            item["year"] = max(item["year"], year)
            item["games"] += 1
            item["wins"] += 1 if _to_bool(row.get("result")) else 0
            item["kills"] += _to_float(row.get("kills") or row.get("teamkills"))
            item["deaths"] += _to_float(row.get("deaths") or row.get("teamdeaths"))
            item["towers"] += _to_float(row.get("towers"))
            item["dragons"] += _to_float(row.get("dragons"))
            item["barons"] += _to_float(row.get("barons"))
            item["length"] += _to_float(row.get("gamelength")) / 60.0
            item["first_dragons"] += 1 if _to_bool(row.get("firstdragon")) else 0
            item["first_barons"] += 1 if _to_bool(row.get("firstbaron")) else 0

    updated_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in aggregates.values():
        games = max(int(item["games"]), 1)
        rows.append(
            (
                item["team_key"],
                item["team_name"],
                item["league"],
                int(item["year"]),
                games,
                int(item["wins"]),
                item["kills"] / games,
                item["deaths"] / games,
                item["towers"] / games,
                item["dragons"] / games,
                item["barons"] / games,
                item["length"] / games,
                item["first_dragons"] / games,
                item["first_barons"] / games,
                updated_at,
                "Oracle's Elixir",
            )
        )

    with sqlite3.connect(path) as conn:
        if rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO team_stats (
                    team_key, team_name, league, year, games, wins,
                    avg_kills, avg_deaths, avg_towers, avg_dragons, avg_barons,
                    avg_game_length, first_dragon_rate, first_baron_rate,
                    updated_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        conn.commit()

    return {
        "db_path": str(path),
        "teams_synced": len(rows),
        "source_years": source_years,
        "leagues": sorted(wanted_leagues),
    }


def query_team_stats(team_name: str, league_code: str = "") -> dict:
    path = init_db()
    team_key = _team_key(team_name)
    league = OE_LEAGUES.get((league_code or "").lower(), (league_code or "").upper())

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = None
        if league:
            row = conn.execute(
                """
                SELECT * FROM team_stats
                WHERE league = ? AND (team_key = ? OR team_key LIKE ? OR ? LIKE '%' || team_key || '%')
                ORDER BY games DESC
                LIMIT 1
                """,
                (league, team_key, f"%{team_key}%", team_key),
            ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT * FROM team_stats
                WHERE team_key = ? OR team_key LIKE ? OR ? LIKE '%' || team_key || '%'
                ORDER BY games DESC
                LIMIT 1
                """,
                (team_key, f"%{team_key}%", team_key),
            ).fetchone()

    if row is None:
        return {}

    games = max(int(row["games"] or 0), 1)
    winrate = float(row["wins"] or 0) / games
    return {
        "games_analyzed": games,
        "team_name": row["team_name"],
        "league": row["league"],
        "winrate": winrate,
        "avg_kills": float(row["avg_kills"]),
        "avg_deaths": float(row["avg_deaths"]),
        "avg_towers": float(row["avg_towers"]),
        "avg_dragons": float(row["avg_dragons"]),
        "avg_barons": float(row["avg_barons"]),
        "avg_game_length": float(row["avg_game_length"]),
        "first_dragon_rate": float(row["first_dragon_rate"]),
        "first_baron_rate": float(row["first_baron_rate"]),
        "total_kills_avg": float(row["avg_kills"]) + float(row["avg_deaths"]),
        "form": {
            "results": [],
            "form_class": "good" if winrate >= .58 else ("bad" if winrate <= .43 else "neutral"),
            "form_label": "Boa fase" if winrate >= .58 else ("Instável" if winrate <= .43 else "Regular"),
        },
        "source": f"{row['source']} SQLite",
    }


def has_local_stats(db_path: Path | str = DB_PATH) -> bool:
    path = init_db(db_path)
    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM team_stats").fetchone()[0]
    return bool(count)

