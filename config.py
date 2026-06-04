"""
config.py — Configuração Unificada
===================================
Parâmetros globais do projeto. Edite aqui para ajustar qualquer configuração.
Para personalização por símbolo, edite profiles.py.
"""

import MetaTrader5 as mt5

# ──────────────────────────────────────────────────────────────────
# TIMEFRAMES
# ──────────────────────────────────────────────────────────────────
TF_M5 = mt5.TIMEFRAME_M5
TF_H1 = mt5.TIMEFRAME_H1

# ──────────────────────────────────────────────────────────────────
# INDICADORES  (compartilhados por todos os bots)
# ──────────────────────────────────────────────────────────────────
EMA_FAST               = 9
EMA_SLOW               = 21
EMA_TREND_H1           = 50    # EMA de tendência no H1
EMA_CROSSOVER_PIPS_THR = 3  # distância mínima EMA9/21 para pré-crossover (scanner)

RSI_PERIOD   = 7
RSI_BUY_MIN  = 50
RSI_BUY_MAX  = 70
RSI_SELL_MIN = 30
RSI_SELL_MAX = 50

MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

BARS_ENTRY = 300   # candles no timeframe de entrada (M5)
BARS_H1    = 150   # candles H1 para o filtro de tendência

# ──────────────────────────────────────────────────────────────────
# OPERACIONAL  (compartilhado)
# ──────────────────────────────────────────────────────────────────
TP_RATIO     = 2.0   # RR 1:2  →  TP = SL × TP_RATIO
LOOP_SECONDS = 15    # intervalo do loop principal (segundos)

# ──────────────────────────────────────────────────────────────────
# SCANNER: Forex  →  python main.py
# ──────────────────────────────────────────────────────────────────
FOREX_MAGIC               = 654321
FOREX_LOG_FILE            = "logs/forex_scanner.log"
FOREX_RISK_PCT            = 0.025   # 2,5% do capital por trade
FOREX_SL_PIPS             = 3
FOREX_MAX_TOTAL_POSITIONS = 4
FOREX_MAX_POS_PER_SYMBOL  = 1

SPREAD_MAX_MAJORS    = 2.5
SPREAD_MAX_MINORS    = 4.0
SPREAD_MAX_PCT_OF_SL = 0.20   # spread / SL ≤ 20%

# Sessões de mercado (UTC — não ajustar por DST)
SESSION_LONDON_START = 7
SESSION_LONDON_END   = 17
SESSION_NY_START     = 13
SESSION_NY_END       = 22
SESSION_ASIAN_END    = 9

# ──────────────────────────────────────────────────────────────────
# SCANNER: Cripto  →  python crypto_scanner.py
# ──────────────────────────────────────────────────────────────────
CRYPTO_MAGIC               = 765432
CRYPTO_LOG_FILE            = "logs/crypto_scanner.log"
CRYPTO_RISK_PCT            = 0.025   # 2,5% do capital por trade
CRYPTO_SL_PCT              = 0.01    # SL = 2% do preço de entrada (ex: BTC $30k → SL $600)
                                     
CRYPTO_MAX_TOTAL_POSITIONS = 2
CRYPTO_MAX_POS_PER_SYMBOL  = 5
SPREAD_MAX_CRYPTO          = 500.0   # cripto tem spreads muito mais amplos
