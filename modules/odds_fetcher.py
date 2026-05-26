"""OddsPapi integration.

PandaScore remains the source of truth for schedule and team logos. OddsPapi is
used only as an odds enrichment layer. If the API is unavailable or a fixture
cannot be matched reliably, callers keep their existing estimated odds.
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from modules.config import get_secret

ODDSPAPI_KEY = (
    get_secret("ODDSPAPI_KEY")
    or get_secret("ODDSPAPI_API_KEY")
    or get_secret("ODDS_PAPI_KEY")
    or get_secret("ODDSPAPI_TOKEN")
)
ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
LOL_SPORT_ID = 18
_FIXTURES_CACHE: dict[str, tuple[datetime, list[dict]]] = {}
_TOURNAMENTS_CACHE: tuple[datetime, list[dict]] | None = None


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

        The most reliable flow is:
        1. Ask OddsPapi for LoL fixtures with odds in the next ~48h.
        2. Match those fixtures against PandaScore teams.
        3. Pull detailed odds for the matched fixture.
        """
        if not self.configured or not matches:
            return {}

        fixtures = self._fetch_lol_fixtures(bookmaker)
        if not fixtures:
            return {}

        result: dict[str, dict] = {}
        for match in matches:
            team1 = match.get("team1", "")
            team2 = match.get("team2", "")
            fixture = self._find_fixture(fixtures, team1, team2)
            if not fixture:
                continue
            odds_payload = self._fetch_fixture_odds(str(fixture.get("fixtureId")), bookmaker)
            odds = self._extract_match_winner_odds(odds_payload)
            if odds:
                result[_pair_key(team1, team2)] = {
                    "team1": odds[0],
                    "team2": odds[1],
                    "source": "OddsPapi",
                    "bookmaker": bookmaker,
                }
        return result

    def fetch_lol_fixtures(self, bookmaker: str = "pinnacle") -> list[dict]:
        cached_at, fixtures = _FIXTURES_CACHE.get(bookmaker, (None, []))
        if cached_at and (datetime.now(timezone.utc) - cached_at).total_seconds() < 240:
            return fixtures

        fixtures = self._fetch_lol_fixtures(bookmaker)
        if fixtures:
            _FIXTURES_CACHE[bookmaker] = (datetime.now(timezone.utc), fixtures)
        return fixtures

    def fetch_lol_tournament_fixtures(self, terms: list[str], days_ahead: int = 5) -> list[dict]:
        tournaments = self._fetch_lol_tournaments()
        if not tournaments:
            return []

        selected_ids: list[str] = []
        normalized_terms = [_norm(term) for term in terms]
        for tournament in tournaments:
            tournament_id = tournament.get("tournamentId") or tournament.get("id")
            if tournament_id is None:
                continue
            text = _norm(_flatten_text(tournament))
            future_count = int(tournament.get("futureFixtures") or 0)
            upcoming_count = int(tournament.get("upcomingFixtures") or 0)
            if (future_count or upcoming_count) and any(term and term in text for term in normalized_terms):
                selected_ids.append(str(tournament_id))

        now = datetime.now(timezone.utc)
        limit = now + timedelta(days=days_ahead)
        fixtures: list[dict] = []
        for tournament_id in selected_ids[:4]:
            # OddsPapi documents a cooldown for fixture endpoints.
            time.sleep(2.05)
            payload = self._get_json(
                "/fixtures",
                {"tournamentId": tournament_id, "language": "en", "apiKey": self.api_key},
                timeout=12,
            )
            if not isinstance(payload, list):
                continue
            for fixture in payload:
                start_time = fixture.get("startTime")
                try:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    continue
                if now - timedelta(hours=3) <= dt <= limit and fixture.get("statusId") in (0, 1):
                    fixtures.append(fixture)
        return fixtures

    def _fetch_lol_tournaments(self) -> list[dict]:
        global _TOURNAMENTS_CACHE
        if _TOURNAMENTS_CACHE:
            cached_at, tournaments = _TOURNAMENTS_CACHE
            if (datetime.now(timezone.utc) - cached_at).total_seconds() < 900:
                return tournaments

        payload = self._get_json(
            "/tournaments",
            {"sportId": LOL_SPORT_ID, "language": "en", "apiKey": self.api_key},
            timeout=12,
        )
        tournaments = payload if isinstance(payload, list) else []
        if tournaments:
            _TOURNAMENTS_CACHE = (datetime.now(timezone.utc), tournaments)
        return tournaments

    def _fetch_lol_fixtures(self, bookmaker: str) -> list[dict]:
        now = datetime.now(timezone.utc)
        payload = self._get_json(
            "/fixtures",
            {
                "sportId": LOL_SPORT_ID,
                "from": (now - timedelta(hours=3)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "to": (now + timedelta(hours=44)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "hasOdds": "true",
                "bookmakers": bookmaker,
                "language": "en",
                "apiKey": self.api_key,
            },
            timeout=12,
        )
        return payload if isinstance(payload, list) else []

    def _find_fixture(self, fixtures: list[dict], team1: str, team2: str) -> dict | None:
        desired_key = _pair_key(team1, team2)
        n1 = _norm(team1)
        n2 = _norm(team2)
        for fixture in fixtures:
            participant1 = fixture.get("participant1Name") or fixture.get("participant1ShortName") or ""
            participant2 = fixture.get("participant2Name") or fixture.get("participant2ShortName") or ""
            if _pair_key(participant1, participant2) == desired_key:
                return fixture

            fixture_text = _norm(_flatten_text(fixture))
            if n1 and n2 and n1 in fixture_text and n2 in fixture_text:
                return fixture
        return None

    def _fetch_fixture_odds(self, fixture_id: str, bookmaker: str) -> Any:
        if not fixture_id:
            return None
        return self._get_json(
            "/odds",
            {
                "fixtureId": fixture_id,
                "bookmakers": bookmaker,
                "oddsFormat": "decimal",
                "language": "en",
                "verbosity": 3,
                "apiKey": self.api_key,
            },
            timeout=12,
        )

    def _extract_match_winner_odds(self, payload: Any) -> tuple[float, float] | None:
        if not isinstance(payload, dict):
            return None

        p1 = _norm(payload.get("participant1Name") or payload.get("participant1ShortName") or "")
        p2 = _norm(payload.get("participant2Name") or payload.get("participant2ShortName") or "")
        bookmaker_odds = payload.get("bookmakerOdds") or {}

        for bookmaker_payload in bookmaker_odds.values():
            markets = bookmaker_payload.get("markets") or {}
            for market in markets.values():
                market_text = _norm(_flatten_text({
                    "bookmakerMarketId": market.get("bookmakerMarketId", ""),
                    "marketName": market.get("marketName", ""),
                }))
                outcomes = market.get("outcomes") or {}
                prices: list[tuple[str, float, str]] = []

                for outcome in outcomes.values():
                    for player in (outcome.get("players") or {}).values():
                        if player.get("active") is False:
                            continue
                        price = _as_float(player.get("price"))
                        if price is None:
                            continue
                        label = _norm(player.get("bookmakerOutcomeId") or outcome.get("name") or "")
                        outcome_text = _norm(_flatten_text({"outcome": outcome, "player": player}))
                        prices.append((label, price, outcome_text))

                if len(prices) < 2:
                    continue

                team1_price = None
                team2_price = None
                generic_prices: list[float] = []
                for label, price, outcome_text in prices:
                    if label in {"home", "1", "team1", "participant1"} or (p1 and p1 in outcome_text):
                        team1_price = price
                    elif label in {"away", "2", "team2", "participant2"} or (p2 and p2 in outcome_text):
                        team2_price = price
                    elif label != "draw":
                        generic_prices.append(price)

                if team1_price and team2_price:
                    return round(team1_price, 2), round(team2_price, 2)

                if ("moneyline" in market_text or "winner" in market_text or "match" in market_text) and len(generic_prices) >= 2:
                    return round(generic_prices[0], 2), round(generic_prices[1], 2)

        return None

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
                    "bookmakers": bookmaker,
                    "tournamentIds": ",".join(chunk),
                    "oddsFormat": "decimal",
                    "language": "en",
                    "verbosity": 3,
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
