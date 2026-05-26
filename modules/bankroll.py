"""
modules/bankroll.py
Gestão de banca — Critério de Kelly, exposição e liquidação local.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

import numpy as np


class BankrollManager:
    """
    Calcula o stake ideal para cada aposta baseado na estratégia escolhida.
    """

    def __init__(self, bankroll: float, target: float, strategy: str):
        self.bankroll = bankroll
        self.target = target
        self.strategy = strategy

    def calculate_stake(
        self,
        probability: float,
        odds: float,
        fixed_value: float = None,
    ) -> dict:
        """
        Retorna o stake recomendado e métricas de gestão.

        Args:
            probability: Probabilidade estimada (0-1)
            odds: Odd decimal da casa de apostas
            fixed_value: Valor fixo (usado apenas em modo "Fixo por Entrada")
        """
        if self.strategy == "Kelly (Recomendado)":
            return self._kelly(probability, odds)
        elif self.strategy == "Flat (Fixo 2%)":
            return self._flat_percentage(0.02)
        else:
            return self._fixed(fixed_value or 5.0)

    def _kelly(self, probability: float, odds: float) -> dict:
        """
        Critério de Kelly completo:
          f* = (b*p - q) / b
          onde b = odds - 1, p = probabilidade, q = 1 - p

        Usa Kelly Fracionário (25%) para segurança.
        """
        if self.bankroll <= 0:
            return {"stake": 0.0, "stake_pct": 0.0, "ev": 0.0, "method": "kelly", "warning": "Banca zerada"}

        b = odds - 1
        p = probability
        q = 1 - p

        kelly_full = (b * p - q) / b
        kelly_frac = kelly_full * 0.25  # Kelly Fracionário (25%)

        # Garante que o stake seja positivo e razoável
        kelly_frac = max(0, min(kelly_frac, 0.10))  # cap 10% da banca

        stake = self.bankroll * kelly_frac
        profit_potential = stake * (odds - 1)

        ruin_prob = self._ruin_probability(kelly_frac, probability)
        bets_to_target = self._bets_to_target(kelly_frac, probability, odds)

        return {
            "method": "Kelly Fracionário (25%)",
            "stake": round(stake, 2),
            "stake_pct": round(kelly_frac * 100, 1),
            "kelly_full_pct": round(kelly_full * 100, 1),
            "profit_potential": round(profit_potential, 2),
            "ruin_probability": round(ruin_prob * 100, 1),
            "bets_to_target": bets_to_target,
            "ev": round((probability * odds - 1) * 100, 1),
        }

    def _flat_percentage(self, pct: float) -> dict:
        """Aposta um percentual fixo da banca (ex: 2%)."""
        stake = self.bankroll * pct
        return {
            "method": f"Flat {pct*100:.0f}%",
            "stake": round(stake, 2),
            "stake_pct": round(pct * 100, 1),
            "kelly_full_pct": None,
            "profit_potential": None,
            "ruin_probability": None,
            "bets_to_target": None,
            "ev": None,
        }

    def _fixed(self, value: float) -> dict:
        """Valor fixo por aposta."""
        pct = (value / self.bankroll) * 100 if self.bankroll > 0 else 0
        return {
            "method": "Valor Fixo",
            "stake": round(value, 2),
            "stake_pct": round(pct, 1),
            "kelly_full_pct": None,
            "profit_potential": None,
            "ruin_probability": None,
            "bets_to_target": None,
            "ev": None,
        }

    def _ruin_probability(self, kelly_fraction: float, win_prob: float) -> float:
        """
        Estimativa de probabilidade de ruína usando fórmula simplificada.
        P(ruína) ≈ ((1-p)/p)^(banca_inicial/aposta)
        """
        if win_prob <= 0 or kelly_fraction <= 0:
            return 1.0
        q = 1 - win_prob
        ratio = q / win_prob
        exponent = 1 / kelly_fraction if kelly_fraction > 0 else 100
        return min(1.0, ratio ** exponent)

    def _bets_to_target(
        self, kelly_fraction: float, win_prob: float, odds: float
    ) -> int:
        """
        Estima quantidade de apostas necessárias para atingir a meta.
        Usa crescimento esperado por aposta.
        """
        if kelly_fraction <= 0 or win_prob <= 0:
            return 999

        # Crescimento esperado por aposta (geométrico)
        expected_growth = (
            win_prob * np.log(1 + kelly_fraction * (odds - 1))
            + (1 - win_prob) * np.log(1 - kelly_fraction)
        )

        if expected_growth <= 0:
            return 999

        if self.bankroll <= 0:
            return 999

        multiplier = self.target / self.bankroll
        bets = int(np.ceil(np.log(multiplier) / expected_growth))
        return min(bets, 999)


def match_bet_id(match: dict) -> str:
    raw = (
        match.get("lolesports_event_id")
        or match.get("panda_id")
        or match.get("id")
        or f'{match.get("team1", "")}|{match.get("team2", "")}|{match.get("datetime", "")}'
    )
    return hashlib.md5(str(raw).encode("utf-8")).hexdigest()[:16]


def pending_exposure(history: list[dict]) -> float:
    return round(
        sum(
            float(item.get("stake", 0) or 0)
            for item in history
            if item.get("status") == "Pendente" or item.get("result") == "PENDING"
        ),
        2,
    )


def register_pending_bet(
    history: list[dict],
    match: dict,
    pick: dict,
    stake_info: dict,
    odds: float,
    bet_url: str,
) -> tuple[list[dict], dict, bool]:
    bet_id = match_bet_id(match)
    market = pick.get("market", "Mercado")
    suggestion = pick.get("suggestion") or pick.get("entry") or ""
    unique_key = f"{bet_id}|{market}|{suggestion}"

    for item in history:
        if item.get("unique_key") == unique_key and item.get("status") == "Pendente":
            return history, item, False

    stake = round(float(stake_info.get("stake", 0) or 0), 2)
    probability = float(pick.get("probability", 0) or 0)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bet = {
        "unique_key": unique_key,
        "bet_id": bet_id,
        "match_id": bet_id,
        "date": now,
        "settled_at": "",
        "match": f'{match.get("team1", "Time 1")} vs {match.get("team2", "Time 2")}',
        "team1": match.get("team1", ""),
        "team2": match.get("team2", ""),
        "market": market,
        "suggestion": suggestion,
        "predicted_side": _extract_predicted_side(pick, match),
        "odds": round(float(odds or pick.get("fair_odds", 1.8) or 1.8), 2),
        "fair_odds": round(float(pick.get("fair_odds", 0) or 0), 2),
        "probability": round(probability, 3),
        "stake": stake,
        "stake_pct": stake_info.get("stake_pct", 0),
        "status": "Pendente",
        "result": "PENDING",
        "profit": -stake,
        "return_amount": 0.0,
        "bet_url": bet_url,
        "source": "Auto BetBoom",
    }
    history.append(bet)
    return history, bet, True


def settle_pending_bets(history: list[dict], matches: list[dict]) -> tuple[list[dict], float, list[dict]]:
    by_id = {match_bet_id(match): match for match in matches}
    balance_delta = 0.0
    settled: list[dict] = []

    for item in history:
        if item.get("status") != "Pendente" and item.get("result") != "PENDING":
            continue
        match = by_id.get(item.get("match_id") or item.get("bet_id"))
        if not match or not _is_completed(match):
            continue

        outcome = _resolve_outcome(item, match)
        if outcome is None:
            continue

        stake = float(item.get("stake", 0) or 0)
        odds = float(item.get("odds", 1) or 1)
        item["settled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["status"] = "Liquidada"
        if outcome:
            return_amount = round(stake * odds, 2)
            item["result"] = "WIN"
            item["return_amount"] = return_amount
            item["profit"] = round(return_amount - stake, 2)
            balance_delta += item["profit"]
        else:
            item["result"] = "LOSS"
            item["return_amount"] = 0.0
            item["profit"] = -stake
            balance_delta -= stake
        settled.append(dict(item))

    return history, round(balance_delta, 2), settled


def _extract_predicted_side(pick: dict, match: dict) -> str:
    text = f'{pick.get("suggestion", "")} {pick.get("entry", "")}'.lower()
    team1 = str(match.get("team1", "")).lower()
    team2 = str(match.get("team2", "")).lower()
    if team1 and team1 in text:
        return "team1"
    if team2 and team2 in text:
        return "team2"
    return ""


def _is_completed(match: dict) -> bool:
    state = str(match.get("state") or match.get("status") or "").lower()
    return state in {"completed", "finished", "complete"}


def _resolve_outcome(bet: dict, match: dict) -> bool | None:
    market = str(bet.get("market", "")).lower()
    if any(key in market for key in ("vitória", "moneyline", "winner", "ml")):
        winner = _winner_side(match)
        predicted = bet.get("predicted_side")
        if winner and predicted:
            return winner == predicted
    return None


def _winner_side(match: dict) -> str:
    winner = str(match.get("winner") or match.get("winner_team") or match.get("winning_team") or "").lower()
    team1 = str(match.get("team1", "")).lower()
    team2 = str(match.get("team2", "")).lower()
    if winner:
        if winner in {"team1", "1", "home"} or (team1 and team1 in winner):
            return "team1"
        if winner in {"team2", "2", "away"} or (team2 and team2 in winner):
            return "team2"

    t1_score = match.get("team1_score", match.get("score_team1"))
    t2_score = match.get("team2_score", match.get("score_team2"))
    try:
        if t1_score is not None and t2_score is not None:
            score1 = float(t1_score)
            score2 = float(t2_score)
            if score1 == score2:
                return ""
            return "team1" if score1 > score2 else "team2"
    except (TypeError, ValueError):
        return ""
    return ""
