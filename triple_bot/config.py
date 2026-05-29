"""
triple_bot.config
Todas as constantes de configuração do bot single-pair (GBPUSD).
Alterar qualquer valor aqui requer aprovação do fluxo Tech Lead → Analista → Dev Senior.
"""

import MetaTrader5 as mt5

# Símbolo e timeframes
SYMBOL   = "GBPUSD"
TF_M5    = mt5.TIMEFRAME_M5
TF_H1    = mt5.TIMEFRAME_H1

# Indicadores M5
EMA_FAST     = 9
EMA_SLOW     = 21
RSI_PERIOD   = 7
RSI_BUY_MIN  = 50
RSI_BUY_MAX  = 70
RSI_SELL_MIN = 30
RSI_SELL_MAX = 50
MACD_FAST    = 12
MACD_SLOW    = 26
MACD_SIGNAL  = 9

# Filtro de tendência H1
EMA_TREND = 50

# Gestão de risco (Configuração de Referência — não alterar sem aprovação)
RISK_PCT  = 0.01   # 1% do capital por trade
SL_PIPS   = 12
TP_RATIO  = 2.0    # RR 1:2 → TP = 24 pips

# Operacional
LOOP_SECONDS  = 15
MAX_POSITIONS = 1
MAGIC         = 123456
LOG_FILE      = "triple_confirmation.log"

# Candles para cálculo dos indicadores
BARS_M5 = 300
BARS_H1 = 150
