"""
triple_bot.config — re-exporta de config.py (raiz).
Para alterar parâmetros, edite config.py.
"""

from config import (
    # Símbolo e timeframes
    TRIPLE_SYMBOL        as SYMBOL,
    TRIPLE_TF_ENTRY      as TF_M5,   # alias interno — atualmente TF_M1
    TF_H1,

    # Indicadores
    EMA_FAST, EMA_SLOW,
    EMA_TREND_H1         as EMA_TREND,
    RSI_PERIOD, RSI_BUY_MIN, RSI_BUY_MAX, RSI_SELL_MIN, RSI_SELL_MAX,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,

    # Candles
    BARS_ENTRY           as BARS_M5,
    BARS_H1,

    # Risco e operacional
    TRIPLE_RISK_PCT      as RISK_PCT,
    TRIPLE_SL_PIPS       as SL_PIPS,
    TP_RATIO,
    TRIPLE_MAX_POSITIONS as MAX_POSITIONS,
    LOOP_SECONDS,

    # Identificação
    TRIPLE_MAGIC         as MAGIC,
    TRIPLE_LOG_FILE      as LOG_FILE,
)
