"""
core.indicators
Funções de cálculo de indicadores técnicos — puro numpy, sem TA-Lib.
Compartilhado por todos os módulos do projeto.
"""

from typing import Tuple

import numpy as np


def calc_ema(prices: np.ndarray, period: int) -> np.ndarray:
    """
    Média Móvel Exponencial pelo método multiplicador (k = 2 / (period + 1)).

    O primeiro valor válido (índice period-1) é inicializado com a SMA dos
    primeiros `period` preços. Os valores anteriores permanecem NaN.
    """
    result = np.full(len(prices), np.nan)
    if len(prices) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(prices[:period])
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k)
    return result


def calc_rsi(prices: np.ndarray, period: int) -> np.ndarray:
    """
    Índice de Força Relativa pelo método Wilder (suavização exponencial modificada).

    Média inicial via SMA; as seguintes usam:
        avg = (prev_avg * (period - 1) + current) / period
    """
    result = np.full(len(prices), np.nan)
    if len(prices) < period + 1:
        return result
    deltas   = np.diff(prices)
    gains    = np.where(deltas > 0, deltas, 0.0)
    losses   = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    result[period] = 100.0 if avg_loss == 0.0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i + 1] = 100.0 if avg_loss == 0.0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return result


def calc_macd(
    prices: np.ndarray, fast: int, slow: int, signal: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    MACD clássico (Moving Average Convergence Divergence).

    Returns:
        (macd_line, signal_line, histogram)
        macd_line  = EMA(fast) - EMA(slow)
        signal_line = EMA(macd_line, signal)
        histogram  = macd_line - signal_line
    """
    ema_fast    = calc_ema(prices, fast)
    ema_slow    = calc_ema(prices, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = np.full(len(prices), np.nan)
    valid_mask  = ~np.isnan(macd_line)
    if np.sum(valid_mask) >= signal:
        valid_idxs = np.where(valid_mask)[0]
        sig_vals   = calc_ema(macd_line[valid_mask], signal)
        for j, idx in enumerate(valid_idxs):
            signal_line[idx] = sig_vals[j]
    return macd_line, signal_line, macd_line - signal_line
