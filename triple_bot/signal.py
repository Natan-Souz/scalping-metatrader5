"""
triple_bot.signal
Lógica de sinal Triple Confirmation para o bot single-pair.

Avalia os 4 critérios no candle fechado (índice -2) e retorna
'BUY', 'SELL' ou None.
"""

import logging
from typing import Optional

import numpy as np
import MetaTrader5 as mt5

from core.indicators import calc_ema, calc_rsi, calc_macd
from core.mt5_bridge import get_bars
from triple_bot.config import (
    SYMBOL, TF_M5, TF_H1, BARS_M5, BARS_H1,
    EMA_FAST, EMA_SLOW, EMA_TREND,
    RSI_PERIOD, RSI_BUY_MIN, RSI_BUY_MAX, RSI_SELL_MIN, RSI_SELL_MAX,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    MAGIC,
)

log = logging.getLogger(__name__)


def get_signal() -> Optional[str]:
    """
    Avalia os 4 critérios Triple Confirmation no candle fechado (índice -2).

    Critérios BUY  : EMA9 cruza acima EMA21 | RSI [50-70] | MACD > Signal | preço > EMA50 H1
    Critérios SELL : EMA9 cruza abaixo EMA21 | RSI [30-50] | MACD < Signal | preço < EMA50 H1

    Returns:
        'BUY', 'SELL' ou None se nenhuma condição for atendida.
    """
    df_m5 = get_bars(SYMBOL, TF_M5, BARS_M5)
    df_h1 = get_bars(SYMBOL, TF_H1, BARS_H1)
    if df_m5 is None or df_h1 is None:
        return None

    close_m5 = df_m5["close"].values
    close_h1 = df_h1["close"].values

    ema_fast               = calc_ema(close_m5, EMA_FAST)
    ema_slow               = calc_ema(close_m5, EMA_SLOW)
    rsi                    = calc_rsi(close_m5, RSI_PERIOD)
    macd_line, sig_line, _ = calc_macd(close_m5, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    ema_h1                 = calc_ema(close_h1, EMA_TREND)

    idx     = -2   # último candle fechado
    ef      = ema_fast[idx]
    es      = ema_slow[idx]
    ef_prev = ema_fast[idx - 1]
    es_prev = ema_slow[idx - 1]
    rsi_val  = rsi[idx]
    macd_val = macd_line[idx]
    sig_val  = sig_line[idx]
    h1_ema50 = ema_h1[-1]
    price    = close_m5[idx]

    if any(np.isnan(v) for v in [ef, es, ef_prev, es_prev, rsi_val, macd_val, sig_val, h1_ema50]):
        log.debug("Indicadores ainda em aquecimento (NaN) — aguardando.")
        return None

    cross_up   = ef_prev < es_prev and ef > es
    cross_down = ef_prev > es_prev and ef < es

    log.debug(
        "EMA%d=%.5f EMA%d=%.5f | RSI=%.2f | MACD=%.6f SIG=%.6f | H1_EMA%d=%.5f | PRICE=%.5f",
        EMA_FAST, ef, EMA_SLOW, es, rsi_val, macd_val, sig_val, EMA_TREND, h1_ema50, price,
    )

    # --- BUY ---
    if (
        cross_up
        and RSI_BUY_MIN <= rsi_val <= RSI_BUY_MAX
        and macd_val > sig_val
        and price > h1_ema50
    ):
        log.info(
            "SINAL BUY | crossover=OK | RSI=%.2f (%.0f-%.0f) | MACD>SIG=OK | price>H1_EMA%d=OK",
            rsi_val, RSI_BUY_MIN, RSI_BUY_MAX, EMA_TREND,
        )
        return "BUY"

    # --- SELL ---
    if (
        cross_down
        and RSI_SELL_MIN <= rsi_val <= RSI_SELL_MAX
        and macd_val < sig_val
        and price < h1_ema50
    ):
        log.info(
            "SINAL SELL | crossover=OK | RSI=%.2f (%.0f-%.0f) | MACD<SIG=OK | price<H1_EMA%d=OK",
            rsi_val, RSI_SELL_MIN, RSI_SELL_MAX, EMA_TREND,
        )
        return "SELL"

    return None


def count_open_positions() -> int:
    """Conta posições abertas no símbolo com o magic number do bot."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return 0
    return sum(1 for p in positions if p.magic == MAGIC)
