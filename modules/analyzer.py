"""
modules/analyzer.py
Motor de análise estatística — calcula probabilidades, valor de aposta
e gera o pacote completo de contexto (forma + comentário do analista).
"""

import numpy as np
from scipy import stats
from modules.data_fetcher import DataFetcher, generate_analyst_comment


class MatchAnalyzer:
    def __init__(self):
        self.fetcher = DataFetcher()

    def analyze_match(self, match: dict, active_markets: dict, min_confidence: float = 75.0) -> dict:
        # Usa stats reais injetados pelo Confronto Direto se disponíveis
        lc = match.get("league_code", "_unknown")
        t1_stats = (
            match.get("_stats_t1_override")
            or self.fetcher.get_team_stats(match["team1"], lc)
        )
        t2_stats = (
            match.get("_stats_t2_override")
            or self.fetcher.get_team_stats(match["team2"], lc)
        )

        t1_form = t1_stats.get("form", {})
        t2_form = t2_stats.get("form", {})

        predictions = []
        alerts = []

        # Coleta alertas de forma
        for form in [t1_form, t2_form]:
            if form.get("alert"):
                alerts.append(form["alert"])

        if active_markets.get("Vitória (ML)"):
            pred = self._predict_winner(match["team1"], t1_stats, match["team2"], t2_stats)
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        if active_markets.get("First Blood"):
            pred = self._predict_first_event("First Blood",
                match["team1"], t1_stats["first_blood_rate"],
                match["team2"], t2_stats["first_blood_rate"])
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        if active_markets.get("First Dragon"):
            pred = self._predict_first_event("First Dragon",
                match["team1"], t1_stats["first_dragon_rate"],
                match["team2"], t2_stats["first_dragon_rate"])
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        if active_markets.get("First Baron"):
            pred = self._predict_first_event("First Baron",
                match["team1"], t1_stats["first_baron_rate"],
                match["team2"], t2_stats["first_baron_rate"])
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
            pred = self._predict_gold_diff(match["team1"], t1_stats, match["team2"], t2_stats)
            if pred["confidence"] >= min_confidence:
                predictions.append(pred)

        # Gera comentário do analista
        analyst_comment = generate_analyst_comment(
            match["team1"], t1_stats, t1_form,
            match["team2"], t2_stats, t2_form,
            league_code=match.get("league_code", ""),
        )

        warnings = []
        if t1_stats.get("source", "").startswith("Demo"):
            warnings.append("⚠️ Dados de demonstração (Oracle's Elixir offline). Probabilidades são estimadas.")

        return {
            "team1_stats": t1_stats,
            "team2_stats": t2_stats,
            "team1_form": t1_form,
            "team2_form": t2_form,
            "predictions": predictions,
            "alerts": alerts,
            "warnings": warnings,
            "analyst_comment": analyst_comment,
        }

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
                "reason": reason, "icon": "🏆"}

    def _predict_first_event(self, event_name, t1_name, t1_rate, t2_name, t2_rate):
        total = t1_rate + t2_rate
        prob_t1 = t1_rate / total if total > 0 else 0.5
        favored = t1_name if prob_t1 >= 0.5 else t2_name
        prob = prob_t1 if prob_t1 >= 0.5 else (1 - prob_t1)
        confidence = prob * 100
        icons = {"First Blood": "🗡️", "First Dragon": "🐉", "First Baron": "👑"}
        reason = (
            f"{favored} obtém {event_name} em {t1_rate*100:.0f}% dos jogos "
            f"vs {t2_name} em {t2_rate*100:.0f}%."
        )
        return {"market": event_name, "suggestion": f"{icons.get(event_name,'📌')} {event_name} → {favored}",
                "confidence": round(confidence, 1), "probability": round(prob, 3),
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
