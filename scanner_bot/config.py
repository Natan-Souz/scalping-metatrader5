"""
scanner_bot.config — re-exporta de config.py (raiz).
Para alterar parâmetros, edite config.py.
"""

from config import (
    # Timeframes
    TF_M5, TF_H1,

    # Indicadores
    EMA_FAST, EMA_SLOW, EMA_TREND_H1, EMA_CROSSOVER_PIPS_THR,
    RSI_PERIOD, RSI_BUY_MIN, RSI_BUY_MAX, RSI_SELL_MIN, RSI_SELL_MAX,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,

    # Candles
    BARS_ENTRY           as BARS_M5,
    BARS_H1,

    # Spread
    SPREAD_MAX_MAJORS, SPREAD_MAX_MINORS, SPREAD_MAX_CRYPTO, SPREAD_MAX_PCT_OF_SL,

    # Risco e operacional — forex
    FOREX_RISK_PCT            as RISK_PCT,
    FOREX_SL_PIPS             as SL_PIPS,
    CRYPTO_SL_PCT,
    TP_RATIO,
    FOREX_MAX_TOTAL_POSITIONS as MAX_TOTAL_POSITIONS,
    FOREX_MAX_POS_PER_SYMBOL  as MAX_POSITIONS_PER_SYMBOL,
    LOOP_SECONDS,

    # Identificação
    FOREX_MAGIC               as MAGIC,
    FOREX_LOG_FILE            as LOG_FILE,

    # Sessões de mercado
    SESSION_LONDON_START, SESSION_LONDON_END,
    SESSION_NY_START, SESSION_NY_END, SESSION_ASIAN_END,
)
