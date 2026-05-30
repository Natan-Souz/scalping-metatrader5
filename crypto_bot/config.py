"""
crypto_bot.config
Constantes específicas do scanner de criptomoedas.

Parâmetros compartilhados com o scanner forex (indicadores, RISK_PCT, TP_RATIO,
LOOP_SECONDS, etc.) são herdados de scanner_bot.config para evitar duplicação.
Apenas o que é diferente para cripto é definido aqui.
"""

# Magic number separado — não conflita com forex (654321) nem com triple_bot (123456)
MAGIC    = 765432
LOG_FILE = "crypto_scanner.log"

# Stop loss em pips para cripto.
# Referência: se point = 0.01 para BTC (preço com 2 casas decimais),
# então 1 pip = 0.10 USD e SL_PIPS_CRYPTO = 2000 → SL ≈ $200 no BTC.
# Ajuste conforme o point real do par na sua corretora.
SL_PIPS_CRYPTO   = 2000

# Spread máximo tolerado para cripto (em pips)
SPREAD_MAX_CRYPTO = 500.0
