"""
Ponto de entrada do scanner de criptomoedas — Triple Confirmation.
Toda a lógica reutiliza scanner_bot/ com parâmetros de cripto.

Execução:
    python crypto_scanner.py
    python -m crypto_bot.scanner   (futuramente, se extraído)

Diferenças em relação ao forex_scanner.py:
  - Varre apenas símbolos com path "Crypto" na corretora
  - Magic number separado (765432)
  - SL/TP dimensionados para cripto (SL_PIPS_CRYPTO = 2000)
  - Sem filtro de sessão (mercado 24/7)
  - Log em crypto_scanner.log
"""

import sys

from core.logging_setup import setup_logging
from scanner_bot.robot import ScannerRobot
from scanner_bot.symbols import discover_crypto_symbols
from scanner_bot.config import (
    RISK_PCT, TP_RATIO, MAX_TOTAL_POSITIONS, MAX_POSITIONS_PER_SYMBOL,
    LOOP_SECONDS, EMA_FAST, EMA_SLOW, RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL, EMA_TREND_H1,
)
from crypto_bot.config import MAGIC, LOG_FILE, SL_PIPS_CRYPTO, SPREAD_MAX_CRYPTO


def main() -> None:
    print("=" * 70)
    print("  Crypto Scanner — Triple Confirmation | MT5")
    print("=" * 70)
    print(f"  Estratégia : EMA {EMA_FAST}/{EMA_SLOW} M5 + RSI {RSI_PERIOD} + "
          f"MACD ({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + EMA {EMA_TREND_H1} H1")
    print(f"  SL         : {SL_PIPS_CRYPTO} pips | TP: {int(SL_PIPS_CRYPTO * TP_RATIO)} pips (RR 1:2)")
    print(f"  Spread max : {SPREAD_MAX_CRYPTO:.0f} pips | Sessão: 24/7 (sem filtro)")
    print(f"  Risco      : {RISK_PCT*100:.0f}% por trade")
    print(f"  Posições   : máx {MAX_TOTAL_POSITIONS} total | máx {MAX_POSITIONS_PER_SYMBOL} por símbolo")
    print(f"  Loop       : {LOOP_SECONDS}s | Magic: {MAGIC}")
    print("=" * 70)

    while True:
        try:
            raw = input("\nCapital base em USD que o scanner deve usar: ").strip().replace(",", ".")
            capital_usd = float(raw)
            if capital_usd <= 0:
                raise ValueError("O capital deve ser positivo.")
            break
        except ValueError as exc:
            print(f"  Entrada inválida: {exc}. Tente novamente.")

    setup_logging(LOG_FILE)

    print(f"\n  Capital confirmado  : USD {capital_usd:,.2f}")
    print(f"  Risco por trade     : USD {capital_usd * RISK_PCT:,.2f}")
    print(f"  Score mínimo entrada: 4/4 (Triple Confirmation completa)")
    print()

    ScannerRobot(
        capital=capital_usd,
        magic=MAGIC,
        discover_fn=discover_crypto_symbols,
        log_file=LOG_FILE,
    ).run()


if __name__ == "__main__":
    main()
