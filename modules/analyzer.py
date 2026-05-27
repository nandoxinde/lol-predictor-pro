"""
modules/analyzer.py
Motor de análise estatística — calcula probabilidades, valor de aposta
e gera o pacote completo de contexto (forma + comentário do analista).
"""

import numpy as np
from scipy import stats
from datetime import datetime, timezone
import re
from modules.data_fetcher import DataFetcher, generate_analyst_comment


class MatchAnalyzer:
    def __init__(self):
        self.fetcher = DataFetcher()
        # Cache curto para evitar chamadas repetidas do LoLEsports em sequência.
        self._live_stats_cache: dict[str, tuple[datetime, dict]] = {}

    @staticmethod
    def _norm_team(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (name or "").lower()).strip()

    def _get_live_stats_cached(self, game_id: str | None) -> dict:
        if not game_id:
            return {}
        now = datetime.now(timezone.utc)
        cached = self._live_stats_cache.get(str(game_id))
        if cached:
            cached_at, data = cached
            if (now - cached_at).total_seconds() < 12:
                return dict(data)
        data = self.fetcher.fetch_lolesports_live_stats(game_id)
        self._live_stats_cache[str(game_id)] = (now, dict(data or {}))
        return data or {}

    def _parse_timestamp_to_elapsed_minutes(self, live_stats: dict) -> float | None:
        ts = live_stats.get("timestamp")
        if ts is None:
            return None

        try:
            if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.strip().isdigit()):
                v = float(ts)
                # Se for milissegundos, normaliza para segundos.
                if v > 1e12:
                    v /= 1000.0
                dt = datetime.fromtimestamp(v, tz=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0

            if isinstance(ts, str):
                s = ts.strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
        except Exception:
            return None
        return None

    def _compute_live_macro(self, match: dict, t1_name: str, t2_name: str, live_stats: dict) -> dict | None:
        if not live_stats or live_stats.get("status") != "ok":
            return None

        blue = live_stats.get("blue") or {}
        red = live_stats.get("red") or {}

        blue_team = match.get("blue_team") or ""
        red_team = match.get("red_team") or ""

        t1_is_blue = self._norm_team(blue_team) == self._norm_team(t1_name)
        t1_is_red = self._norm_team(red_team) == self._norm_team(t1_name)
        if not (t1_is_blue or t1_is_red):
            return None

        blue_gold = float(blue.get("total_gold") or 0)
        red_gold = float(red.get("total_gold") or 0)
        blue_towers = int(blue.get("towers") or 0)
        red_towers = int(red.get("towers") or 0)
        blue_dragons = len(blue.get("dragons") or [])
        red_dragons = len(red.get("dragons") or [])

        elapsed_min = self._parse_timestamp_to_elapsed_minutes(live_stats)

        # gold_diff positivo = vantagem do t1.
        if t1_is_blue:
            gold_diff = blue_gold - red_gold
        else:
            # t1 é red
            gold_diff = red_gold - blue_gold

        ahead_team = t1_name if gold_diff >= 0 else t2_name
        behind_team = t2_name if ahead_team == t1_name else t1_name

        if ahead_team == t1_name:
            towers_ahead = blue_towers if t1_is_blue else red_towers
            towers_behind = red_towers if t1_is_blue else blue_towers
            dragons_ahead = blue_dragons if t1_is_blue else red_dragons
            dragons_behind = red_dragons if t1_is_blue else blue_dragons
        else:
            towers_ahead = red_towers if t1_is_blue else blue_towers
            towers_behind = blue_towers if t1_is_blue else red_towers
            dragons_ahead = red_dragons if t1_is_blue else blue_dragons
            dragons_behind = blue_dragons if t1_is_blue else red_dragons

        return {
            "elapsed_minutes": elapsed_min,
            "gold_diff": int(gold_diff),
            "ahead_team": ahead_team,
            "behind_team": behind_team,
            "ahead_gold": abs(int(gold_diff)),
            "towers_ahead": towers_ahead,
            "towers_behind": towers_behind,
            "dragons_ahead": dragons_ahead,
            "dragons_behind": dragons_behind,
        }

    def _adjust_predictions_live_macro(
        self,
        match: dict,
        t1_name: str,
        t2_name: str,
        predictions: list[dict],
        live_macro: dict,
    ) -> tuple[list[dict], str | None]:
        if not live_macro:
            return predictions, None

        gold_diff = live_macro["gold_diff"]
        ahead_team = live_macro["ahead_team"]
        behind_team = live_macro["behind_team"]
        elapsed_min = live_macro.get("elapsed_minutes")

        abs_gold = abs(gold_diff)
        heat_gold = 0.0
        if abs_gold >= 2000:
            heat_gold = min(1.0, max(0.0, (abs_gold - 2000) / 5000.0))

        towers_span = max(0, int(live_macro.get("towers_ahead", 0)) - int(live_macro.get("towers_behind", 0)))
        heat_towers = min(1.0, towers_span / 4.0) if towers_span > 0 else 0.0
        dragons_span = max(0, int(live_macro.get("dragons_ahead", 0)) - int(live_macro.get("dragons_behind", 0)))
        heat_dragons = min(1.0, dragons_span / 2.0) if dragons_span > 0 else 0.0
        heat = min(1.0, 0.60 * heat_gold + 0.25 * heat_towers + 0.15 * heat_dragons)

        # Ouro > 2k antes de 15 min (requisito do usuário).
        trigger = abs_gold >= 2000 and (elapsed_min is not None and elapsed_min <= 15.0)
        delta = 0.03 + 0.12 * heat  # variação tipo "uma casa"

        def parse_favored_from_ml(pred: dict) -> str | None:
            s = str(pred.get("suggestion") or "")
            if "Vence" not in s:
                return None
            return s.split("Vence", 1)[0].replace("🏆", "").strip()

        def parse_favored_from_first_event(pred: dict) -> str | None:
            s = str(pred.get("suggestion") or "")
            if "→" in s:
                return s.split("→", 1)[1].strip()
            if "->" in s:
                return s.split("->", 1)[1].strip()
            return None

        ml_pred = next((p for p in predictions if p.get("market") == "Vitória (Moneyline)"), None)
        baron_pred = next((p for p in predictions if p.get("market") == "First Baron"), None)
        fd_pred = next((p for p in predictions if p.get("market") == "First Dragon"), None)

        # Ajuste do ML
        if ml_pred:
            favored = parse_favored_from_ml(ml_pred) or ""
            prob_favored = float(ml_pred.get("probability") or 0.5)

            prob_ahead = prob_favored
            if self._norm_team(favored) != self._norm_team(ahead_team):
                prob_ahead = 1.0 - prob_favored

            if trigger:
                prob_ahead = float(np.clip(prob_ahead + delta, 0.05, 0.95))

            new_favored = ahead_team if prob_ahead >= 0.5 else behind_team
            new_prob_favored = prob_ahead if new_favored == ahead_team else 1.0 - prob_ahead

            ml_pred["probability"] = round(new_prob_favored, 3)
            ml_pred["confidence"] = round(new_prob_favored * 100, 1)
            ml_pred["fair_odds"] = round(1 / max(new_prob_favored, 0.01), 2)

            k_gold = abs_gold / 1000.0
            lead_txt = f"(macro +{k_gold:.1f}k ouro)"
            ml_pred["suggestion"] = f"🏆 {new_favored} Vence {lead_txt}"
            if elapsed_min is not None:
                ml_pred["reason"] = (
                    f"Live: {ahead_team} com +{k_gold:.1f}k de ouro (Δ {gold_diff:+d}g) aos {elapsed_min:.0f} min. "
                    f"Ajuste {'aplicado' if trigger else 'parcial'} no ML."
                )

        # Ajuste do First Baron
        if baron_pred:
            side_probs = baron_pred.get("side_probabilities") or {}
            prob_ahead = None
            if ahead_team in side_probs:
                prob_ahead = float(side_probs[ahead_team])
            else:
                favored = parse_favored_from_first_event(baron_pred) or ""
                prob_favored = float(baron_pred.get("probability") or 0.5)
                prob_ahead = prob_favored if self._norm_team(favored) == self._norm_team(ahead_team) else 1.0 - prob_favored

            if trigger and prob_ahead is not None:
                prob_ahead = float(np.clip(prob_ahead + 0.90 * delta, 0.05, 0.95))

            prob_ahead = float(prob_ahead if prob_ahead is not None else 0.5)
            new_favored = ahead_team if prob_ahead >= 0.5 else behind_team
            new_prob_favored = prob_ahead if new_favored == ahead_team else 1.0 - prob_ahead

            if new_favored == t1_name:
                prob_t1 = new_prob_favored
            else:
                prob_t1 = 1.0 - new_prob_favored
            baron_pred["side_probabilities"] = {
                t1_name: round(prob_t1, 3),
                t2_name: round(1.0 - prob_t1, 3),
            }
            baron_pred["probability"] = round(new_prob_favored, 3)
            baron_pred["confidence"] = round(new_prob_favored * 100, 1)
            baron_pred["fair_odds"] = round(1 / max(new_prob_favored, 0.01), 2)

            k_gold = abs_gold / 1000.0
            lead_txt = f"(macro +{k_gold:.1f}k ouro)"
            baron_pred["suggestion"] = f"👑 First Baron → {new_favored} {lead_txt}"
            if elapsed_min is not None:
                baron_pred["reason"] = (
                    f"Live: vantagem de macro para {ahead_team} aos {elapsed_min:.0f} min "
                    f"(Δ {gold_diff:+d}g) com torres {live_macro['towers_ahead']}–{live_macro['towers_behind']}. "
                    f"Ajuste {'aplicado' if trigger else 'parcial'} no First Baron."
                )

        # Insights: compõe um comentário dinâmico com números reais.
        k_gold = abs_gold / 1000.0
        elapsed_txt = f"{elapsed_min:.0f} min" if elapsed_min is not None else "—"

        # ML prob ahead (se existir)
        ml_prob_ahead = None
        if ml_pred:
            favored = parse_favored_from_ml(ml_pred) or ""
            ml_prob_favored = float(ml_pred.get("probability") or 0.5)
            ml_prob_ahead = ml_prob_favored if self._norm_team(favored) == self._norm_team(ahead_team) else 1.0 - ml_prob_favored

        baron_prob_ahead = None
        if baron_pred:
            side_probs = baron_pred.get("side_probabilities") or {}
            if ahead_team in side_probs:
                baron_prob_ahead = float(side_probs[ahead_team])

        fd_prob_ahead = None
        if fd_pred:
            side_probs = fd_pred.get("side_probabilities") or {}
            if ahead_team in side_probs:
                fd_prob_ahead = float(side_probs[ahead_team])

        ml_txt = f"{(ml_prob_ahead or 0.0) * 100:.0f}%" if ml_prob_ahead is not None else "—"
        baron_txt = f"{(baron_prob_ahead or 0.0) * 100:.0f}%" if baron_prob_ahead is not None else "—"
        extra_fd = ""
        if fd_prob_ahead is not None:
            extra_fd = f" · Prob. de First Dragon para {ahead_team}: {fd_prob_ahead * 100:.0f}%"

        comment = (
            f"IA detectou vantagem de macro: {ahead_team} com +{k_gold:.1f}k de ouro aos {elapsed_txt}. "
            f"Torres {live_macro['towers_ahead']}–{live_macro['towers_behind']} e Dragões {live_macro['dragons_ahead']}–{live_macro['dragons_behind']}. "
            f"{'Recalculando' if trigger else 'Monitorando'}: ML para {ahead_team} em {ml_txt} "
            f"e First Baron em {baron_txt}.{extra_fd}"
        )

        return predictions, comment

    def analyze_match(self, match: dict, active_markets: dict, min_confidence: float = 75.0) -> dict:
        # Usa stats reais injetados pelo Confronto Direto se disponíveis
        lc = match.get("league_code", "_unknown")
        t1_name = match.get("team1", "")
        t2_name = match.get("team2", "")

        live_macro = None
        if match.get("state") == "inProgress":
            live_stats = self._get_live_stats_cached(match.get("lolesports_game_id"))
            if live_stats.get("status") == "ok":
                live_macro = self._compute_live_macro(match, t1_name, t2_name, live_stats)

        t1_stats = (
            match.get("_stats_t1_override")
            or self.fetcher.get_team_stats(t1_name, lc)
        )
        t2_stats = (
            match.get("_stats_t2_override")
            or self.fetcher.get_team_stats(t2_name, lc)
        )

        t1_form = t1_stats.get("form", {})
        t2_form = t2_stats.get("form", {})
        series_memory = self.fetcher.fetch_series_memory(match)
        t1_stats, t2_stats = self._apply_series_memory(
            match["team1"], t1_stats,
            match["team2"], t2_stats,
            series_memory,
        )
        t1_stats, t2_stats, regional_meta = self._apply_regional_meta(lc, t1_stats, t2_stats)

        # Ajuste ao vivo: quando há vantagem clara de macro cedo no jogo,
        # atualiza também os inputs (winrate/first_baron_rate) para que
        # `generate_decision_card()` mostre odds/sugestão mais dinâmicas.
        if live_macro and match.get("state") == "inProgress":
            abs_gold = int(live_macro.get("ahead_gold") or 0)
            elapsed_min = live_macro.get("elapsed_minutes")
            trigger = abs_gold >= 2000 and (elapsed_min is not None and elapsed_min <= 15.0)

            if trigger:
                heat_gold = min(1.0, max(0.0, (abs_gold - 2000) / 5000.0))
                towers_span = max(0, int(live_macro.get("towers_ahead", 0)) - int(live_macro.get("towers_behind", 0)))
                heat_towers = min(1.0, towers_span / 4.0) if towers_span > 0 else 0.0
                dragons_span = max(0, int(live_macro.get("dragons_ahead", 0)) - int(live_macro.get("dragons_behind", 0)))
                heat_dragons = min(1.0, dragons_span / 2.0) if dragons_span > 0 else 0.0
                heat = min(1.0, 0.60 * heat_gold + 0.25 * heat_towers + 0.15 * heat_dragons)

                delta_wr = 0.04 + 0.10 * heat
                delta_baron = 0.02 + 0.06 * heat
                delta_dragon = 0.01 + 0.04 * heat_dragons

                ahead_team = live_macro.get("ahead_team")
                if ahead_team == match.get("team1"):
                    t1_stats["winrate"] = float(np.clip(t1_stats.get("winrate", 0.5) + delta_wr, 0.20, 0.93))
                    t2_stats["winrate"] = float(np.clip(t2_stats.get("winrate", 0.5) - delta_wr * 0.85, 0.08, 0.88))

                    t1_stats["first_baron_rate"] = float(np.clip(t1_stats.get("first_baron_rate", 0.5) + delta_baron, 0.20, 0.88))
                    t2_stats["first_baron_rate"] = float(np.clip(t2_stats.get("first_baron_rate", 0.5) - delta_baron * 0.85, 0.20, 0.88))

                    t1_stats["first_dragon_rate"] = float(np.clip(t1_stats.get("first_dragon_rate", 0.5) + delta_dragon, 0.20, 0.88))
                    t2_stats["first_dragon_rate"] = float(np.clip(t2_stats.get("first_dragon_rate", 0.5) - delta_dragon * 0.85, 0.20, 0.88))
                else:
                    t2_stats["winrate"] = float(np.clip(t2_stats.get("winrate", 0.5) + delta_wr, 0.20, 0.93))
                    t1_stats["winrate"] = float(np.clip(t1_stats.get("winrate", 0.5) - delta_wr * 0.85, 0.08, 0.88))

                    t2_stats["first_baron_rate"] = float(np.clip(t2_stats.get("first_baron_rate", 0.5) + delta_baron, 0.20, 0.88))
                    t1_stats["first_baron_rate"] = float(np.clip(t1_stats.get("first_baron_rate", 0.5) - delta_baron * 0.85, 0.20, 0.88))

                    t2_stats["first_dragon_rate"] = float(np.clip(t2_stats.get("first_dragon_rate", 0.5) + delta_dragon, 0.20, 0.88))
                    t1_stats["first_dragon_rate"] = float(np.clip(t1_stats.get("first_dragon_rate", 0.5) - delta_dragon * 0.85, 0.20, 0.88))

        predictions = []
        alerts = []

        # Coleta alertas de forma
        for form in [t1_form, t2_form]:
            if form.get("alert"):
                alerts.append(form["alert"])

        if active_markets.get("Vitória (ML)"):
            pred = self._predict_winner(t1_name, t1_stats, t2_name, t2_stats)
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        if active_markets.get("First Blood"):
            pred = self._predict_first_event("First Blood",
                t1_name, t1_stats["first_blood_rate"],
                t2_name, t2_stats["first_blood_rate"], series_memory, "first_blood")
            if pred["confidence"] >= max(52, min_confidence - 15):
                predictions.append(pred)

        if active_markets.get("First Dragon"):
            pred = self._predict_first_event("First Dragon",
                t1_name, t1_stats["first_dragon_rate"],
                t2_name, t2_stats["first_dragon_rate"], series_memory, "first_dragon")
            if pred["confidence"] >= max(52, min_confidence - 15):
                predictions.append(pred)

        if active_markets.get("First Baron"):
            pred = self._predict_first_event("First Baron",
                t1_name, t1_stats["first_baron_rate"],
                t2_name, t2_stats["first_baron_rate"])
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        if active_markets.get("Total de Kills (O/U)"):
            pred = self._predict_total_kills(t1_stats, t2_stats)
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        if active_markets.get("Duração do Mapa"):
            pred = self._predict_game_duration(t1_stats, t2_stats)
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        if active_markets.get("Gold Diff @15min"):
            pred = self._predict_gold_diff(t1_name, t1_stats, t2_name, t2_stats)
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        # Gera comentário do analista
        analyst_comment = None
        if match.get("state") == "inProgress" and live_macro:
            predictions, live_comment = self._adjust_predictions_live_macro(
                match, t1_name, t2_name, predictions, live_macro
            )
            analyst_comment = live_comment

        if analyst_comment is None:
            analyst_comment = generate_analyst_comment(
                t1_name, t1_stats, t1_form,
                t2_name, t2_stats, t2_form,
                league_code=match.get("league_code", ""),
            )

        warnings = []
        if t1_stats.get("source", "").startswith("Demo"):
            warnings.append("⚠️ Dados de demonstração (Oracle's Elixir offline). Probabilidades são estimadas.")
        if series_memory.get("status") == "unavailable":
            warnings.append(f"Memória de série indisponível: {series_memory.get('reason', 'sem dados detalhados')}.")

        return {
            "team1_stats": t1_stats,
            "team2_stats": t2_stats,
            "team1_form": t1_form,
            "team2_form": t2_form,
            "predictions": predictions,
            "alerts": alerts,
            "warnings": warnings,
            "analyst_comment": analyst_comment,
            "series_memory": series_memory,
            "regional_meta": regional_meta,
        }

    def _apply_series_memory(self, t1_name: str, t1: dict, t2_name: str, t2: dict, memory: dict) -> tuple[dict, dict]:
        t1_adj = dict(t1)
        t2_adj = dict(t2)
        if memory.get("status") != "ok" or memory.get("maps_played", 0) <= 0:
            return t1_adj, t2_adj

        momentum = memory.get("momentum", {})
        mom_t1 = float(momentum.get("team1", 0.5))
        mom_t2 = float(momentum.get("team2", 0.5))
        event_rates = memory.get("event_rates", {})
        last_map = memory.get("last_map", {})
        boost_side = self._early_control_winner(last_map)

        for stat_key, memory_key in (("first_blood_rate", "first_blood"), ("first_dragon_rate", "first_dragon")):
            rates = event_rates.get(memory_key, {})
            live_t1 = float(rates.get("team1", 0.5))
            live_t2 = float(rates.get("team2", 0.5))
            base_t1 = t1.get(stat_key, 0.5) * 0.68 + live_t1 * 0.24 + mom_t1 * 0.08
            base_t2 = t2.get(stat_key, 0.5) * 0.68 + live_t2 * 0.24 + mom_t2 * 0.08
            if boost_side == "team1":
                base_t1 *= 1.15
            elif boost_side == "team2":
                base_t2 *= 1.15
            t1_adj[stat_key] = float(np.clip(base_t1, 0.25, 0.86))
            t2_adj[stat_key] = float(np.clip(base_t2, 0.25, 0.86))

        t1_adj["winrate"] = float(np.clip(t1.get("winrate", 0.5) + (mom_t1 - 0.5) * 0.10, 0.2, 0.9))
        t2_adj["winrate"] = float(np.clip(t2.get("winrate", 0.5) + (mom_t2 - 0.5) * 0.10, 0.2, 0.9))
        t1_adj["source"] = f'{t1.get("source", "Modelo")} + memória série'
        t2_adj["source"] = f'{t2.get("source", "Modelo")} + memória série'
        t1_adj["series_momentum"] = mom_t1
        t2_adj["series_momentum"] = mom_t2
        if boost_side:
            memory["momentum_boost"] = {
                "side": boost_side,
                "multiplier": 1.15,
                "reason": "Vencedor do último mapa controlou early game/objetivos.",
            }
        return t1_adj, t2_adj

    @staticmethod
    def _early_control_winner(last_map: dict) -> str | None:
        winner = last_map.get("winner")
        if winner not in {"team1", "team2"}:
            return None

        signals = 0
        if last_map.get("first_blood") == winner:
            signals += 1
        if last_map.get("first_dragon") == winner:
            signals += 1

        dragons = last_map.get("dragons") or {}
        kills = last_map.get("kills") or {}
        other = "team2" if winner == "team1" else "team1"
        if int(dragons.get(winner, 0) or 0) > int(dragons.get(other, 0) or 0):
            signals += 1
        if int(kills.get(winner, 0) or 0) >= int(kills.get(other, 0) or 0) + 3:
            signals += 1

        return winner if signals >= 2 else None

    def _apply_regional_meta(self, league_code: str, t1: dict, t2: dict) -> tuple[dict, dict, dict]:
        code = (league_code or "").lower()
        t1_adj = dict(t1)
        t2_adj = dict(t2)
        meta = {"code": code, "applied": False, "notes": []}

        if code == "lpl":
            self._scale_kill_projection(t1_adj, 1.15)
            self._scale_kill_projection(t2_adj, 1.15)
            self._boost_event_leader(t1_adj, t2_adj, "first_blood_rate", 1.10)
            meta.update({"applied": True, "style": "agressividade"})
            meta["notes"].append("LPL: projeção de kills +15% e maior peso para First Blood rápido.")
        elif code == "lck":
            self._scale_kill_projection(t1_adj, 0.90)
            self._scale_kill_projection(t2_adj, 0.90)
            t1_adj["avg_game_length"] = float(t1_adj.get("avg_game_length", 32) * 1.08)
            t2_adj["avg_game_length"] = float(t2_adj.get("avg_game_length", 32) * 1.08)
            self._boost_event_leader(t1_adj, t2_adj, "first_dragon_rate", 1.10)
            meta.update({"applied": True, "style": "controle"})
            meta["notes"].append("LCK: kills -10%, duração +8% e maior peso para First Dragon/macro.")

        if meta["applied"]:
            t1_adj["regional_meta"] = meta["style"]
            t2_adj["regional_meta"] = meta["style"]
        return t1_adj, t2_adj, meta

    @staticmethod
    def _scale_kill_projection(stats_dict: dict, multiplier: float) -> None:
        for key in ("avg_kills", "avg_deaths", "total_kills_avg"):
            if key in stats_dict:
                stats_dict[key] = float(max(0.0, stats_dict.get(key, 0) * multiplier))

    @staticmethod
    def _boost_event_leader(t1: dict, t2: dict, key: str, multiplier: float) -> None:
        t1_rate = float(t1.get(key, 0.5))
        t2_rate = float(t2.get(key, 0.5))
        if abs(t1_rate - t2_rate) < 0.01:
            t1_score = float(t1.get("winrate", 0.5)) + float(t1.get("avg_kills", 0)) / 40
            t2_score = float(t2.get("winrate", 0.5)) + float(t2.get("avg_kills", 0)) / 40
            leader = "team1" if t1_score >= t2_score else "team2"
        else:
            leader = "team1" if t1_rate > t2_rate else "team2"

        if leader == "team1":
            t1[key] = float(np.clip(t1_rate * multiplier, 0.25, 0.88))
            t2[key] = float(np.clip(t2_rate, 0.25, 0.82))
        else:
            t1[key] = float(np.clip(t1_rate, 0.25, 0.82))
            t2[key] = float(np.clip(t2_rate * multiplier, 0.25, 0.88))

    def _predict_winner(self, t1_name, t1, t2_name, t2):
        wr_weight, gd15_weight, kills_weight = 0.50, 0.25, 0.15
        gd_norm = np.tanh((t1["avg_golddiff15"] - t2["avg_golddiff15"]) / 1000)
        score_t1 = (
            wr_weight * t1["winrate"]
            + gd15_weight * (0.5 + gd_norm / 2)
            + kills_weight * (t1["avg_kills"] / (t1["avg_kills"] + t2["avg_kills"]))
            + 0.10 * 0.5
        )
        raw_prob = max(0.15, min(0.85, score_t1))
        favored = t1_name if raw_prob >= 0.5 else t2_name
        prob = raw_prob if raw_prob >= 0.5 else (1 - raw_prob)
        confidence = prob * 100
        gd_str = f"{t1['avg_golddiff15']:+.0f}g @15"
        reason = (
            f"{favored} com WR de {t1['winrate']*100:.0f}% nos últimos {t1['games_analyzed']} jogos "
            f"e {gd_str} de gold diff médio. Adversário tem WR de {t2['winrate']*100:.0f}%."
        )
        return {"market": "Vitória (Moneyline)", "suggestion": f"🏆 {favored} Vence",
                "confidence": round(confidence, 1), "probability": round(prob, 3),
                "fair_odds": round(1 / max(prob, 0.01), 2),
                "reason": reason, "icon": "🏆"}

    def _predict_first_event(self, event_name, t1_name, t1_rate, t2_name, t2_rate, series_memory=None, memory_key=""):
        total = t1_rate + t2_rate
        prob_t1 = t1_rate / total if total > 0 else 0.5
        favored = t1_name if prob_t1 >= 0.5 else t2_name
        prob = prob_t1 if prob_t1 >= 0.5 else (1 - prob_t1)
        confidence = prob * 100
        icons = {"First Blood": "🗡️", "First Dragon": "🐉", "First Baron": "👑"}
        memory_note = ""
        if series_memory and series_memory.get("status") == "ok" and memory_key:
            last = series_memory.get("last_map", {})
            last_owner = last.get(memory_key)
            if last_owner:
                owner_name = t1_name if last_owner == "team1" else t2_name
                memory_note = f" Último mapa: {owner_name} levou {event_name}."
        reason = (
            f"{favored} obtém {event_name} em {t1_rate*100:.0f}% dos jogos "
            f"vs {t2_name} em {t2_rate*100:.0f}%.{memory_note}"
        )
        return {"market": event_name, "suggestion": f"{icons.get(event_name,'📌')} {event_name} → {favored}",
                "confidence": round(confidence, 1), "probability": round(prob, 3),
                "fair_odds": round(1 / max(prob, 0.01), 2),
                "side_probabilities": {
                    t1_name: round(prob_t1, 3),
                    t2_name: round(1 - prob_t1, 3),
                },
                "reason": reason, "icon": icons.get(event_name, "📌")}

    def _predict_total_kills(self, t1, t2):
        expected_total = (t1["avg_kills"] + t1["avg_deaths"] + t2["avg_kills"] + t2["avg_deaths"]) / 2
        line = 27.5
        prob_over = 1 - stats.poisson.cdf(int(line), expected_total)
        prob_under = 1 - prob_over
        direction = "Over" if prob_over >= prob_under else "Under"
        prob = max(prob_over, prob_under)
        confidence = prob * 100
        reason = (
            f"Média combinada esperada: {expected_total:.1f} kills. "
            f"Linha {line}. Modelo Poisson indica {direction} com {confidence:.0f}%."
        )
        return {"market": f"Total Kills {direction} {line}", "suggestion": f"🎯 {direction} {line} Kills",
                "confidence": round(confidence, 1), "probability": round(prob, 3),
                "fair_odds": round(1 / max(prob, 0.01), 2),
                "reason": reason, "icon": "🎯"}

    def _predict_game_duration(self, t1, t2):
        avg_duration = (t1["avg_game_length"] + t2["avg_game_length"]) / 2
        threshold = 32.0
        direction = "Longa (>32min)" if avg_duration > threshold else "Curta (<32min)"
        prob = min(0.90, 0.5 + abs(avg_duration - threshold) / 20)
        confidence = prob * 100
        reason = (
            f"Duração média combinada: {avg_duration:.0f}min. "
            f"Histórico sugere jogo {direction}."
        )
        return {"market": "Duração do Mapa", "suggestion": f"⏱️ Jogo {direction}",
                "confidence": round(confidence, 1), "probability": round(prob, 3),
                "fair_odds": round(1 / max(prob, 0.01), 2),
                "reason": reason, "icon": "⏱️"}

    def _predict_gold_diff(self, t1_name, t1, t2_name, t2):
        diff = t1["avg_golddiff15"] - t2["avg_golddiff15"]
        favored = t1_name if diff >= 0 else t2_name
        abs_diff = abs(diff)
        prob = min(0.92, 0.5 + abs_diff / 8000)
        confidence = prob * 100
        reason = (
            f"{t1_name} GD@15 médio: {t1['avg_golddiff15']:+.0f}g vs "
            f"{t2_name}: {t2['avg_golddiff15']:+.0f}g. "
            f"Diferença de {abs_diff:.0f}g favorece {favored}."
        )
        return {"market": "Gold Diff @15min", "suggestion": f"💰 {favored} lidera @15min",
                "confidence": round(confidence, 1), "probability": round(prob, 3),
                "fair_odds": round(1 / max(prob, 0.01), 2),
                "reason": reason, "icon": "💰"}

    @staticmethod
    def calculate_value(probability: float, bookmaker_odds: float) -> dict:
        implied_prob = 1 / bookmaker_odds
        ev = (probability * bookmaker_odds) - 1
        edge = probability - implied_prob
        return {
            "implied_prob": round(implied_prob * 100, 1),
            "ev": round(ev * 100, 1),
            "edge": round(edge * 100, 1),
            "is_value": ev > 0.03,
        }
