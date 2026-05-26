"""
modules/bankroll.py
Gestão de banca — Critério de Kelly e estratégias fixas.
"""

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
