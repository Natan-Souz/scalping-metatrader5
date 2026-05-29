"""
scanner_bot.config
Todas as constantes de configuração do scanner multi-par.
Alterar qualquer valor aqui requer aprovação do fluxo Tech Lead → Analista → Dev Senior.
"""

import MetaTrader5 as mt5

# Timeframes
TF_M5 = mt5.TIMEFRAME_M5
TF_H1 = mt5.TIMEFRAME_H1

# Filtro de spread (pips)
SPREAD_MAX_MAJORS      = 2.5
SPREAD_MAX_MINORS      = 4.0
SPREAD_MAX_PCT_OF_SL   = 0.20   # spread / SL ≤ 20%

# Indicadores M5
EMA_FAST              = 9
EMA_SLOW              = 21
EMA_CROSSOVER_PIPS_THR = 3.0   # threshold de proximidade para pré-crossover
RSI_PERIOD            = 7
RSI_BUY_MIN           = 50
RSI_BUY_MAX           = 70
RSI_SELL_MIN          = 30
RSI_SELL_MAX          = 50
MACD_FAST             = 12
MACD_SLOW             = 26
MACD_SIGNAL           = 9

# Filtro de tendência H1
EMA_TREND_H1          = 50

# Gestão de risco (Configuração de Referência — não alterar sem aprovação)
RISK_PCT              = 0.01   # 1% do capital por trade
SL_PIPS               = 12
TP_RATIO              = 2.0    # RR 1:2 → TP = 24 pips

# Controle de posições
MAX_TOTAL_POSITIONS      = 3
MAX_POSITIONS_PER_SYMBOL = 1

# Operacional
LOOP_SECONDS          = 15
MAGIC                 = 654321
LOG_FILE              = "forex_scanner.log"
BARS_M5               = 300
BARS_H1               = 150

# Sessões de mercado (horário UTC — imune a DST do servidor do broker)
SESSION_LONDON_START  = 7    # abertura Londres
SESSION_LONDON_END    = 17   # fechamento Londres
SESSION_NY_START      = 13   # abertura Nova York
SESSION_NY_END        = 22   # fechamento Nova York
SESSION_ASIAN_END     = 9    # fechamento Ásia (abre às 22h do dia anterior)
