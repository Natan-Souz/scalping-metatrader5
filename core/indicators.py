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


def calc_adx(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Average Directional Index (Wilder) — mede a FORÇA da tendência.

    O ADX é direcionalmente neutro: alto = tendência forte (alta OU baixa),
    baixo = mercado lateral/sem tendência. +DI e -DI indicam a direção dominante.

    Cálculo:
        TR      = max(high-low, |high-close_ant|, |low-close_ant|)
        +DM     = up_move   se up_move > down_move e > 0, senão 0
        -DM     = down_move se down_move > up_move e > 0, senão 0
        ATR, +DM e -DM são suavizados por Wilder (período = `period`)
        +DI     = 100 * smooth(+DM) / ATR
        -DI     = 100 * smooth(-DM) / ATR
        DX      = 100 * |+DI - -DI| / (+DI + -DI)
        ADX     = Wilder(DX, period)

    O primeiro ADX válido surge em torno do índice 2*period (warmup duplo).
    Valores anteriores permanecem NaN.

    Returns:
        (adx, plus_di, minus_di) — arrays do mesmo tamanho de `close`.
    """
    n   = len(close)
    adx = np.full(n, np.nan)
    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    if n < 2 * period + 1:
        return adx, pdi, mdi

    tr       = np.zeros(n)
    plus_dm  = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move     = high[i] - high[i - 1]
        down_move   = low[i - 1] - low[i]
        plus_dm[i]  = up_move   if (up_move > down_move and up_move > 0)   else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i]  - close[i - 1]))

    # Suavização de Wilder (soma móvel: prev - prev/period + atual)
    atr      = np.full(n, np.nan)
    sm_plus  = np.full(n, np.nan)
    sm_minus = np.full(n, np.nan)
    atr[period]      = np.sum(tr[1:period + 1])
    sm_plus[period]  = np.sum(plus_dm[1:period + 1])
    sm_minus[period] = np.sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        atr[i]      = atr[i - 1]      - atr[i - 1] / period      + tr[i]
        sm_plus[i]  = sm_plus[i - 1]  - sm_plus[i - 1] / period  + plus_dm[i]
        sm_minus[i] = sm_minus[i - 1] - sm_minus[i - 1] / period + minus_dm[i]

    dx = np.full(n, np.nan)
    for i in range(period, n):
        if np.isnan(atr[i]) or atr[i] == 0:
            continue
        p = 100.0 * sm_plus[i]  / atr[i]
        m = 100.0 * sm_minus[i] / atr[i]
        pdi[i], mdi[i] = p, m
        denom = p + m
        dx[i] = 0.0 if denom == 0 else 100.0 * abs(p - m) / denom

    # ADX = média inicial de DX seguida de suavização de Wilder
    first = 2 * period
    adx[first] = np.nanmean(dx[period + 1:first + 1])
    for i in range(first + 1, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx, pdi, mdi


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
