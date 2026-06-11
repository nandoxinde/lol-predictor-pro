"""Orquestrador da stack de fontes do analyzer (camadas da arquitetura pro)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from modules.apify_client import ApifyClient
from modules.config import get_secret
from modules.champion_meta import ChampionMetaEngine, league_to_opgg_region
from modules.data_dragon import enrich_live_stats_champions, get_latest_version
from modules.my_private_api import has_local_stats
from modules.odds_fetcher import OddsPapiClient


def _status_icon(ok: bool, partial: bool = False) -> str:
    if ok:
        return "🟢"
    if partial:
        return "🟡"
    return "🔴"


class DataStack:
    """Camada única que roteia histórico, draft, agenda, patch, odds e live."""

    LAYERS: list[dict[str, str]] = [
        {"id": "oracle", "camada": "Histórico pro", "fonte": "Oracle's Elixir", "uso": "CSV/SQLite — kills, objetivos, duração"},
        {"id": "draft", "camada": "Draft/champions", "fonte": "Leaguepedia + OP.GG", "uso": "Pool pro + tier meta soloQ/região"},
        {"id": "meta", "camada": "Meta patch", "fonte": "OP.GG API", "uso": "Tier S/A/B, WR, pick/ban — forte/fraco no patch"},
        {"id": "roster", "camada": "Roster/calendário", "fonte": "Leaguepedia + Liquipedia", "uso": "Elenco, BO, substituições"},
        {"id": "agenda", "camada": "Agenda oficial", "fonte": "LoLEsports + PandaScore", "uso": "Jogos, ligas, live, VOD"},
        {"id": "patch", "camada": "Patch/campeões", "fonte": "Riot Data Dragon", "uso": "Nomes de campeões, versão do patch"},
        {"id": "soloq", "camada": "SoloQ/player", "fonte": "Riot Developer API", "uso": "Opcional — ranked/conta (se token)"},
        {"id": "grid", "camada": "Dados oficiais esports", "fonte": "Riot/GRID Portal", "uso": "Opcional — requer credencial comercial"},
        {"id": "odds_agg", "camada": "Odds agregadores", "fonte": "OddsPapi / PandaScore", "uso": "ML e fixtures comerciais"},
        {"id": "odds_sharp", "camada": "Odds sharp", "fonte": "Pinnacle via OddsPapi", "uso": "Benchmark de preço ML"},
        {"id": "odds_house", "camada": "Odds casa (BetBoom)", "fonte": "Apify + BetBoom", "uso": "Kills, duração, FB — onde você aposta"},
    ]

    def __init__(self, fetcher: Any | None = None):
        from modules.data_fetcher import DataFetcher
        self.fetcher = fetcher or DataFetcher()

    def layer_status(self) -> list[dict]:
        rows: list[dict] = []
        oracle_ok = has_local_stats()
        rows.append(self._row("oracle", oracle_ok, "SQLite local pronto" if oracle_ok else "Rode sync Oracle's Elixir"))

        draft_ok = True
        rows.append(self._row("draft", draft_ok, "Pool Leaguepedia + tier OP.GG"))

        try:
            region = league_to_opgg_region("lck")
            opgg_ok = ChampionMetaEngine(region=region).fetch_opgg_meta(region).get("ok", False)
            rows.append(self._row("meta", opgg_ok, f"OP.GG {region} — tier/WR/pick rate"))
        except Exception:
            rows.append(self._row("meta", False, "OP.GG indisponível"))

        rows.append(self._row("roster", True, "Liquipedia + rosters locais 2025"))

        agenda_ok = bool(get_secret("LOLESPORTS_API_KEY") or get_secret("PANDASCORE_TOKEN"))
        rows.append(self._row("agenda", agenda_ok, "LoLEsports + PandaScore" if agenda_ok else "LoLEsports fallback embutido", partial=not agenda_ok))

        try:
            patch = get_latest_version()
            rows.append(self._row("patch", bool(patch), f"Patch {patch}"))
        except Exception:
            rows.append(self._row("patch", False, "Data Dragon indisponível"))

        riot_key = get_secret("RIOT_API_KEY")
        rows.append(self._row("soloq", bool(riot_key), "Token Riot configurado" if riot_key else "Opcional — adicione RIOT_API_KEY", partial=not riot_key))

        grid_key = get_secret("GRID_API_KEY")
        rows.append(self._row("grid", bool(grid_key), "GRID conectado" if grid_key else "Opcional — acesso comercial", partial=not grid_key))

        oddsp = OddsPapiClient()
        rows.append(self._row("odds_agg", oddsp.configured, "OddsPapi ativo" if oddsp.configured else "Sem chave OddsPapi", partial=oddsp.configured))

        rows.append(self._row("odds_sharp", oddsp.configured, "Pinnacle via OddsPapi" if oddsp.configured else "Benchmark ML indisponível", partial=oddsp.configured))

        apify_ok, apify_msg = ApifyClient().verify_token()
        rows.append(self._row("odds_house", apify_ok, apify_msg if apify_ok else "Configure APIFY_TOKEN", partial=False))

        return rows

    def _row(self, layer_id: str, ok: bool, detail: str, partial: bool = False) -> dict:
        meta = next((item for item in self.LAYERS if item["id"] == layer_id), {})
        return {
            **meta,
            "ok": ok,
            "icon": _status_icon(ok, partial=partial and not ok),
            "detail": detail,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def enrich_live_stats(self, live_stats: dict) -> dict:
        return enrich_live_stats_champions(live_stats)

    def fetch_draft_context(self, team1: str, team2: str) -> dict:
        pool1 = self.fetcher.fetch_team_champion_pool(team1)
        pool2 = self.fetcher.fetch_team_champion_pool(team2)
        return {
            "status": "ok" if pool1.get("champions") or pool2.get("champions") else "empty",
            "team1": pool1,
            "team2": pool2,
            "source": "Leaguepedia Cargo (ScoreboardPlayers)",
        }

    def enrich_analysis(self, match: dict, analysis: dict, live_stats: dict | None = None) -> dict:
        enriched = dict(analysis)
        t1 = match.get("team1", "")
        t2 = match.get("team2", "")
        draft = self.fetch_draft_context(t1, t2)
        if draft.get("status") == "ok":
            enriched["draft_context"] = draft

        champion_ctx = ChampionMetaEngine().build_match_context(match, draft, live_stats)
        enriched["champion_meta"] = champion_ctx
        if champion_ctx.get("insights"):
            enriched["alerts"] = list(enriched.get("alerts") or []) + champion_ctx["insights"]

        for side_key, team_name in (("team1_stats", t1), ("team2_stats", t2)):
            stats = dict(enriched.get(side_key) or {})
            if stats:
                stats["data_layers"] = stats.get("data_layers") or []
                if stats.get("source"):
                    stats["data_layers"].append(stats["source"])
                enriched[side_key] = stats
        enriched["data_stack"] = {
            "layers_active": [row for row in self.layer_status() if row.get("ok")],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        return enriched

    def prepare_match_for_analysis(self, match: dict, live_stats: dict | None = None) -> tuple[dict, dict, dict]:
        """Stats ajustados por meta + contexto campeões antes do analyzer."""
        t1 = match.get("team1", "")
        t2 = match.get("team2", "")
        lc = match.get("league_code", "_unknown")
        draft = self.fetch_draft_context(t1, t2)
        champion_ctx = ChampionMetaEngine().build_match_context(match, draft, live_stats)
        t1_stats = self.fetcher.get_team_stats(t1, lc)
        t2_stats = self.fetcher.get_team_stats(t2, lc)
        t1_adj, t2_adj, champ_adj = ChampionMetaEngine(
            region=champion_ctx.get("region", "GLOBAL"),
        ).apply_analyzer_adjustments(t1_stats, t2_stats, champion_ctx, t1, t2)
        match_ready = {
            **match,
            "_stats_t1_override": t1_adj,
            "_stats_t2_override": t2_adj,
        }
        return match_ready, champion_ctx, draft

    def summary_line(self) -> str:
        rows = self.layer_status()
        active = sum(1 for row in rows if row.get("ok"))
        return f"Stack {active}/{len(rows)} camadas ativas"
