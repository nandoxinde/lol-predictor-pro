"""Integração BetBoom via Apify — extrai mercados reais e cruza com picks da IA."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from modules.apify_client import ApifyClient
from modules.config import get_secret

DEFAULT_ACTOR = get_secret("APIFY_BETBOOM_ACTOR_ID") or "apify~playwright-scraper"
_CACHE: dict[str, tuple[datetime, dict]] = {}
_CACHE_TTL_SECONDS = 90

_PLAYWRIGHT_PAGE_FUNCTION = """
async function pageFunction(context) {
    const { page, request, log } = context;
    await page.waitForLoadState('domcontentloaded', { timeout: 45000 }).catch(() => {});
    await page.waitForTimeout(4500);

    const payload = await page.evaluate(() => {
        const chunks = [];
        const pushText = (value) => {
            if (!value) return;
            const text = String(value).replace(/\\s+/g, ' ').trim();
            if (text.length >= 4 && text.length <= 4000) chunks.push(text);
        };

        pushText(document.body ? document.body.innerText : '');

        document.querySelectorAll(
            '[class*="market"], [class*="Market"], [class*="coeff"], [class*="odd"], [data-testid], button, span, div'
        ).forEach((el) => {
            const txt = el.innerText || el.textContent || '';
            if (txt && txt.length <= 220) pushText(txt);
        });

        const nextData = document.querySelector('#__NEXT_DATA__');
        if (nextData && nextData.textContent) {
            chunks.push('__NEXT_DATA__:' + nextData.textContent.slice(0, 120000));
        }

        return chunks.slice(0, 800);
    });

    return {
        url: request.url,
        scrapedAt: new Date().toISOString(),
        chunks: payload,
    };
}
""".strip()


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_odd(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if number <= 1.0 or number > 100:
        return None
    return round(number, 2)


def _side_from_text(text: str) -> str | None:
    low = _norm(text)
    if any(token in low for token in ("mais de", "over", "acima", " maior ", " > ")):
        return "over"
    if any(token in low for token in ("menos de", "under", "abaixo", " menor ", " < ")):
        return "under"
    return None


def _line_from_text(text: str) -> float | None:
    match = re.search(r"(\d{1,2}[.,]\d)", text)
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", ".")), 1)
    except ValueError:
        return None


def _family_from_text(text: str) -> str | None:
    low = _norm(text)
    if any(token in low for token in ("primeiro abate", "first blood", "1st blood")):
        return "first_blood"
    if any(token in low for token in ("primeiro drag", "first dragon", "1st dragon")):
        return "first_dragon"
    if any(token in low for token in ("primeiro bar", "first baron", "1st baron")):
        return "first_baron"
    if any(token in low for token in ("duracao", "duration", "mapa", "minuto", "min ")):
        if re.search(r"\d{1,2}[.,]\d", text):
            return "duration"
    if any(token in low for token in ("total de abate", "total kills", "total kill", " abates ")):
        return "total_kills"
    if any(token in low for token in ("total de torre", "total towers", " torres ")):
        return "towers"
    if any(token in low for token in ("vence", "vitoria", "moneyline", "match winner", " vencedor")):
        return "winner"
    return None


def _team_side_from_text(text: str, team1: str, team2: str) -> str | None:
    n1 = _norm(team1)
    n2 = _norm(team2)
    low = _norm(text)
    has1 = n1 and n1 in low
    has2 = n2 and n2 in low
    if has1 and not has2:
        return "team1"
    if has2 and not has1:
        return "team2"
    return None


def _extract_markets_from_text(text: str, team1: str, team2: str) -> list[dict]:
    markets: list[dict] = []
    seen: set[str] = set()

    def _push(market: dict) -> None:
        key = (
            f"{market.get('family')}|{market.get('line')}|{market.get('side')}|"
            f"{market.get('team')}|{market.get('label')}|{market.get('odds')}"
        )
        if key in seen:
            return
        seen.add(key)
        markets.append(market)

    chunks = re.split(r"[\n\r|•]+", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 6:
            continue

        odds_matches = re.findall(r"\b(\d[.,]\d{2})\b", chunk)
        if not odds_matches:
            continue

        family = _family_from_text(chunk)
        if not family:
            continue

        for odd_raw in odds_matches[-2:]:
            odd = _as_odd(odd_raw)
            if odd is None:
                continue

            line = _line_from_text(chunk) if family in {"total_kills", "duration", "towers", "team_kills"} else None
            side = _side_from_text(chunk)
            team = _team_side_from_text(chunk, team1, team2)

            if family == "total_kills" and team:
                family = "team_kills"

            label = chunk[:120]
            _push(
                {
                    "family": family,
                    "market_name": label[:80],
                    "line": line,
                    "side": side,
                    "team": team,
                    "odds": odd,
                    "label": label,
                }
            )

    # Padrão compacto: "Mais de 27.5 — 1.85"
    for match in re.finditer(
        r"(?i)(mais de|menos de|over|under)\s*(\d{1,2}[.,]\d)[^\d]{0,24}(\d[.,]\d{2})",
        text,
    ):
        side = _side_from_text(match.group(1))
        line = _line_from_text(match.group(2))
        odd = _as_odd(match.group(3))
        if odd is None or line is None:
            continue
        family = "total_kills"
        if re.search(r"(?i)(min|duracao|duration|mapa)", text[max(0, match.start() - 40): match.end() + 20]):
            family = "duration"
        _push(
            {
                "family": family,
                "market_name": match.group(0)[:80],
                "line": line,
                "side": side,
                "team": None,
                "odds": odd,
                "label": match.group(0)[:120],
            }
        )

    # Moneyline por time
    for team_name, team_key in ((team1, "team1"), (team2, "team2")):
        pattern = re.compile(
            rf"(?i){re.escape(team_name)}[^\d]{{0,40}}(\d[.,]\d{{2}})",
        )
        for match in pattern.finditer(text):
            odd = _as_odd(match.group(1))
            if odd is None:
                continue
            _push(
                {
                    "family": "winner",
                    "market_name": f"{team_name} ML",
                    "line": None,
                    "side": None,
                    "team": team_key,
                    "odds": odd,
                    "label": match.group(0)[:120],
                }
            )

    return markets


def _walk_json_for_markets(value: Any, team1: str, team2: str, bucket: list[dict]) -> None:
    if isinstance(value, dict):
        text_parts = []
        odds_candidates = []
        for key, child in value.items():
            key_text = str(key)
            if isinstance(child, (str, int, float)):
                text_parts.append(f"{key_text} {child}")
            if str(key).lower() in {"price", "odds", "coefficient", "coef", "value"}:
                odd = _as_odd(child)
                if odd is not None:
                    odds_candidates.append(odd)
            _walk_json_for_markets(child, team1, team2, bucket)

        joined = " ".join(text_parts)
        family = _family_from_text(joined)
        if family and odds_candidates:
            bucket.append(
                {
                    "family": family,
                    "market_name": joined[:80],
                    "line": _line_from_text(joined),
                    "side": _side_from_text(joined),
                    "team": _team_side_from_text(joined, team1, team2),
                    "odds": odds_candidates[0],
                    "label": joined[:120],
                }
            )
    elif isinstance(value, list):
        for child in value:
            _walk_json_for_markets(child, team1, team2, bucket)


def _parse_apify_items(items: list[dict], team1: str, team2: str) -> list[dict]:
    markets: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        if isinstance(item.get("markets"), list):
            for market in item["markets"]:
                if not isinstance(market, dict):
                    continue
                odd = _as_odd(market.get("odds") or market.get("price"))
                if odd is None:
                    continue
                markets.append(
                    {
                        "family": market.get("family") or _family_from_text(str(market.get("market_name", ""))) or "generic",
                        "market_name": str(market.get("market_name") or market.get("name") or "")[:80],
                        "line": market.get("line"),
                        "side": market.get("side"),
                        "team": market.get("team"),
                        "odds": odd,
                        "label": str(market.get("label") or market.get("selection") or "")[:120],
                    }
                )

        text_blobs: list[str] = []
        for key in ("bodyText", "text", "html", "content"):
            if item.get(key):
                text_blobs.append(str(item[key]))
        if item.get("chunks"):
            text_blobs.extend(str(chunk) for chunk in item["chunks"] if chunk)

        for key, value in item.items():
            if isinstance(value, str) and ("__NEXT_DATA__" in value or "coeff" in value.lower()):
                text_blobs.append(value)

        joined = "\n".join(text_blobs)
        if joined:
            markets.extend(_extract_markets_from_text(joined, team1, team2))

        json_markets: list[dict] = []
        _walk_json_for_markets(item, team1, team2, json_markets)
        markets.extend(json_markets)

    deduped: list[dict] = []
    seen: set[str] = set()
    for market in markets:
        key = (
            f"{market.get('family')}|{market.get('line')}|{market.get('side')}|"
            f"{market.get('team')}|{market.get('odds')}|{market.get('label')}"
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(market)
    return deduped


def _decision_side(decision: dict) -> str | None:
    entry = str(decision.get("entry") or decision.get("suggestion") or "").lower()
    market = str(decision.get("market") or "").lower()
    text = f"{entry} {market}"
    return _side_from_text(text)


def _decision_line(decision: dict) -> float | None:
    text = f"{decision.get('market', '')} {decision.get('entry', '')} {decision.get('suggestion', '')}"
    return _line_from_text(text)


def _decision_team(decision: dict, team1: str, team2: str) -> str | None:
    text = f"{decision.get('market', '')} {decision.get('entry', '')}"
    side = _team_side_from_text(text, team1, team2)
    if side:
        return side
    family = decision.get("family", "")
    if family == "team_kills_t1":
        return "team1"
    if family == "team_kills_t2":
        return "team2"
    return None


def _line_close(a: float | None, b: float | None, tol: float = 0.51) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def match_house_odds(decision: dict, markets: list[dict], team1: str, team2: str) -> dict | None:
    if not markets:
        return None

    family = str(decision.get("family") or "")
    if not family or family == "generic":
        family = _family_from_text(str(decision.get("market", ""))) or family

    side = _decision_side(decision)
    line = _decision_line(decision)
    team = _decision_team(decision, team1, team2)

    candidates: list[dict] = []
    for market in markets:
        mf = str(market.get("family") or "")
        if mf != family and not (family.startswith("total_kills") and mf == "total_kills"):
            if family.startswith("team_kills") and mf == "team_kills":
                pass
            elif family.startswith("duration") and mf == "duration":
                pass
            else:
                continue

        if side and market.get("side") and market.get("side") != side:
            continue

        if line is not None and market.get("line") is not None and not _line_close(line, market.get("line")):
            continue

        if team and market.get("team") and market.get("team") != team:
            continue

        if family == "winner" and team:
            if market.get("team") != team:
                continue

        candidates.append(market)

    if not candidates and family == "winner":
        fav_text = _norm(str(decision.get("entry") or decision.get("market") or ""))
        for market in markets:
            if market.get("family") != "winner":
                continue
            label = _norm(str(market.get("label") or market.get("market_name") or ""))
            if fav_text and any(token in label for token in fav_text.split()[:2] if len(token) >= 3):
                candidates.append(market)

    if not candidates:
        return None

    best = candidates[0]
    for item in candidates:
        if line is not None and _line_close(line, item.get("line")):
            best = item
            break

    return best


def enrich_decision(decision: dict, markets: list[dict], team1: str, team2: str) -> dict:
    matched = match_house_odds(decision, markets, team1, team2)
    if not matched:
        return decision

    house_odd = float(matched["odds"])
    prob = float(decision.get("probability") or 0)
    ev = round((prob * house_odd - 1) * 100, 1)
    enriched = dict(decision)
    enriched["house_odds"] = house_odd
    enriched["house_label"] = matched.get("label") or matched.get("market_name") or ""
    enriched["house_source"] = "BetBoom"
    enriched["ev_pct"] = ev
    enriched["has_value"] = ev >= 1.0
    return enriched


def enrich_decision_card(dc: dict, markets: list[dict], team1: str, team2: str) -> dict:
    if not markets:
        return dc

    decisions = [enrich_decision(item, markets, team1, team2) for item in dc.get("decisions", [])]
    safe = [enrich_decision(item, markets, team1, team2) for item in dc.get("safe_picks", [])]
    risky = [enrich_decision(item, markets, team1, team2) for item in dc.get("risky_picks", [])]
    top = enrich_decision(dc.get("top_pick") or {}, markets, team1, team2) if dc.get("top_pick") else None

    return {
        **dc,
        "decisions": decisions,
        "safe_picks": safe,
        "risky_picks": risky,
        "top_pick": top,
        "house_markets_count": len(markets),
    }


class BetBoomFetcher:
    def __init__(self, apify: ApifyClient | None = None):
        self.apify = apify or ApifyClient()
        self.actor_id = DEFAULT_ACTOR

    @property
    def configured(self) -> bool:
        return self.apify.configured

    def fetch(self, url: str, team1: str = "", team2: str = "", force_refresh: bool = False) -> dict:
        url = (url or "").strip()
        if not url.startswith("http"):
            return {"ok": False, "markets": [], "error": "Informe um link BetBoom válido (https://...)."}

        cache_key = f"{url}|{team1}|{team2}"
        if not force_refresh and cache_key in _CACHE:
            cached_at, payload = _CACHE[cache_key]
            if datetime.now(timezone.utc) - cached_at < timedelta(seconds=_CACHE_TTL_SECONDS):
                return {**payload, "source": "cache"}

        ok_token, token_msg = self.apify.verify_token()
        if not ok_token:
            return {"ok": False, "markets": [], "error": token_msg}

        run_input = {
            "startUrls": [{"url": url}],
            "pageFunction": _PLAYWRIGHT_PAGE_FUNCTION,
            "proxyConfiguration": {"useApifyProxy": True},
            "launchContext": {
                "launchOptions": {
                    "headless": True,
                }
            },
            "maxRequestsPerCrawl": 1,
            "maxConcurrency": 1,
        }

        run_detail = self.apify.run_actor_sync_detail(self.actor_id, run_input, timeout=180)
        items = run_detail.get("items") or []
        markets = _parse_apify_items(items, team1, team2)
        apify_error = run_detail.get("error")

        payload = {
            "ok": bool(markets),
            "markets": markets,
            "source": "Apify",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "apify_status": token_msg,
            "error": None if markets else (apify_error or "Nenhum mercado BetBoom encontrado nesta URL. Cole o link direto da partida."),
            "raw_items": len(items),
        }
        _CACHE[cache_key] = (datetime.now(timezone.utc), payload)
        return payload

    @staticmethod
    def format_market_badge(decision: dict) -> str:
        house = decision.get("house_odds")
        if not house:
            return ""
        ev = decision.get("ev_pct")
        ev_text = f" · EV {ev:+.1f}%" if isinstance(ev, (int, float)) else ""
        return f"Casa {house:.2f}{ev_text}"
