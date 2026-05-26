"""OddsPapi integration.

PandaScore remains the source of truth for schedule and team logos. OddsPapi is
used only as an odds enrichment layer. If the API is unavailable or a fixture
cannot be matched reliably, callers keep their existing estimated odds.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

from modules.config import get_secret

ODDSPAPI_KEY = get_secret("ODDSPAPI_KEY")
ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
LOL_SPORT_ID = 18


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\b(esports|esport|gaming|team|academy|global|challengers|club)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _pair_key(team1: str, team2: str) -> str:
    return "|".join(sorted([_norm(team1), _norm(team2)]))


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _flatten_text(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                parts.append(key)
            parts.append(_flatten_text(child))
    elif isinstance(value, list):
        for child in value:
            parts.append(_flatten_text(child))
    elif isinstance(value, (str, int, float)):
        parts.append(str(value))
    return " ".join(part for part in parts if part)


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 1.0 or number > 1000:
        return None
    return number


class OddsPapiClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else ODDSPAPI_KEY
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LoLPredictorPro/2.0"})

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def fetch_lol_odds_for_matches(self, matches: list[dict], bookmaker: str = "pinnacle") -> dict[str, dict]:
        """Return odds keyed by normalized team pair.

        The OddsPapi response can vary by market/bookmaker, so parsing is
        intentionally defensive. It only returns odds when both team names can
        be found around the same fixture payload.
        """
        if not self.configured or not matches:
            return {}

        tournament_ids = self._find_relevant_tournament_ids(matches)
        if not tournament_ids:
            return {}

        odds_payloads = self._fetch_odds_by_tournaments(tournament_ids, bookmaker)
        if not odds_payloads:
            return {}

        result: dict[str, dict] = {}
        for match in matches:
            team1 = match.get("team1", "")
            team2 = match.get("team2", "")
            odds = self._find_match_odds(odds_payloads, team1, team2)
            if odds:
                result[_pair_key(team1, team2)] = {
                    "team1": odds[0],
                    "team2": odds[1],
                    "source": "OddsPapi",
                    "bookmaker": bookmaker,
                }
        return result

    def _find_relevant_tournament_ids(self, matches: list[dict]) -> list[str]:
        tournaments = self._get_json(
            "/tournaments",
            {"sportId": LOL_SPORT_ID, "apiKey": self.api_key},
            timeout=10,
        )
        if not tournaments:
            return []

        desired_terms = {
            _norm(match.get("league", "")) for match in matches if match.get("league")
        } | {
            _norm(match.get("league_display", "")) for match in matches if match.get("league_display")
        } | {"lck", "lpl", "lec", "lcs", "cblol", "vcs", "tcl", "pcs", "lcp", "league of legends"}

        ids: list[str] = []
        for item in _walk_dicts(tournaments):
            item_id = item.get("id") or item.get("tournamentId") or item.get("tournament_id")
            if item_id is None:
                continue
            item_text = _norm(_flatten_text(item))
            if any(term and term in item_text for term in desired_terms):
                ids.append(str(item_id))

        deduped: list[str] = []
        for item_id in ids:
            if item_id not in deduped:
                deduped.append(item_id)
        return deduped[:30]

    def _fetch_odds_by_tournaments(self, tournament_ids: list[str], bookmaker: str) -> Any:
        payloads = []
        # Keep chunks small to avoid URL length and provider limits.
        for start in range(0, len(tournament_ids), 8):
            chunk = tournament_ids[start:start + 8]
            payload = self._get_json(
                "/odds-by-tournaments",
                {
                    "bookmaker": bookmaker,
                    "tournamentIds": ",".join(chunk),
                    "oddsFormat": "decimal",
                    "apiKey": self.api_key,
                },
                timeout=14,
            )
            if payload:
                payloads.append(payload)
        return payloads

    def _find_match_odds(self, payload: Any, team1: str, team2: str) -> tuple[float, float] | None:
        n1 = _norm(team1)
        n2 = _norm(team2)
        if not n1 or not n2:
            return None

        for container in _walk_dicts(payload):
            container_text = _norm(_flatten_text(container))
            if n1 not in container_text or n2 not in container_text:
                continue

            team1_price = None
            team2_price = None
            generic_prices: list[float] = []
            for item in _walk_dicts(container):
                price = _as_float(item.get("price") or item.get("odds") or item.get("decimal"))
                if price is None:
                    continue
                item_text = _norm(_flatten_text(item))
                if n1 in item_text:
                    team1_price = price
                elif n2 in item_text:
                    team2_price = price
                else:
                    generic_prices.append(price)

            if team1_price and team2_price:
                return round(team1_price, 2), round(team2_price, 2)

            if not team1_price and not team2_price and len(generic_prices) >= 2:
                # Fallback for bookmaker markets that label outcomes as home/away.
                return round(generic_prices[0], 2), round(generic_prices[1], 2)

        return None

    def _get_json(self, endpoint: str, params: dict, timeout: int) -> Any:
        try:
            response = self.session.get(f"{ODDSPAPI_BASE}{endpoint}", params=params, timeout=timeout)
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None


def odds_pair_key(team1: str, team2: str) -> str:
    return _pair_key(team1, team2)
