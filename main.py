"""
main.py — Inicializador Principal
===================================
Ponto de entrada único para todos os bots do projeto.
Todos os parâmetros são configurados em config.py.

Execução:
    python main.py
"""

import sys
from config import (
    TRIPLE_SYMBOL, TRIPLE_TF_ENTRY, TRIPLE_MAGIC,
    TRIPLE_RISK_PCT, TRIPLE_SL_PIPS, TP_RATIO, TRIPLE_MAX_POSITIONS,
    TRIPLE_LOG_FILE, LOOP_SECONDS,
    FOREX_MAGIC, FOREX_LOG_FILE, FOREX_RISK_PCT, FOREX_SL_PIPS,
    FOREX_MAX_TOTAL_POSITIONS, SPREAD_MAX_MAJORS, SPREAD_MAX_MINORS,
    CRYPTO_MAGIC, CRYPTO_LOG_FILE, CRYPTO_RISK_PCT, CRYPTO_SL_PIPS,
    CRYPTO_MAX_TOTAL_POSITIONS, SPREAD_MAX_CRYPTO,
    EMA_FAST, EMA_SLOW, RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL, EMA_TREND_H1,
)

# Mapa de timeframe → nome legível
_TF_NAMES = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 16385: "M5", 16388: "H1"}


def _tf_name(tf: int) -> str:
    return _TF_NAMES.get(tf, str(tf))


def _ask_capital() -> float:
    while True:
        try:
            raw     = input("\n  Capital base em USD: ").strip().replace(",", ".")
            capital = float(raw)
            if capital <= 0:
                raise ValueError
            return capital
        except ValueError:
            print("  Valor inválido. Digite um número positivo.")


def _header(title: str) -> None:
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)


# ──────────────────────────────────────────────────────────────────
# LANÇADORES POR BOT
# ──────────────────────────────────────────────────────────────────
def _run_triple(capital: float) -> None:
    _header(f"Triple Confirmation — {TRIPLE_SYMBOL}")
    print(f"  Timeframe  : {_tf_name(TRIPLE_TF_ENTRY)} (entrada) + H1 (tendência)")
    print(f"  Estratégia : EMA {EMA_FAST}/{EMA_SLOW} + RSI {RSI_PERIOD} + "
          f"MACD ({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + EMA {EMA_TREND_H1} H1")
    print(f"  Risco      : {TRIPLE_RISK_PCT*100:.0f}% | "
          f"SL={TRIPLE_SL_PIPS}p | TP={int(TRIPLE_SL_PIPS*TP_RATIO)}p")
    print(f"  Posições   : máx {TRIPLE_MAX_POSITIONS} | Loop: {LOOP_SECONDS}s | Magic: {TRIPLE_MAGIC}")
    print(f"  Capital    : USD {capital:,.2f} | Risco/trade: USD {capital*TRIPLE_RISK_PCT:,.2f}")
    print("=" * 65 + "\n")

    from core.logging_setup import setup_logging
    from triple_bot.bot import run
    setup_logging(TRIPLE_LOG_FILE)
    run(capital)


def _run_forex(capital: float) -> None:
    _header("Forex Scanner Multi-Par")
    print(f"  Estratégia : EMA {EMA_FAST}/{EMA_SLOW} M5 + RSI {RSI_PERIOD} + "
          f"MACD ({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + EMA {EMA_TREND_H1} H1")
    print(f"  Spread     : Majors≤{SPREAD_MAX_MAJORS}p | Minors≤{SPREAD_MAX_MINORS}p | Exotics=bloqueado")
    print(f"  Risco      : {FOREX_RISK_PCT*100:.0f}% | "
          f"SL={FOREX_SL_PIPS}p | TP={int(FOREX_SL_PIPS*TP_RATIO)}p")
    print(f"  Posições   : máx {FOREX_MAX_TOTAL_POSITIONS} | Loop: {LOOP_SECONDS}s | Magic: {FOREX_MAGIC}")
    print(f"  Capital    : USD {capital:,.2f} | Risco/trade: USD {capital*FOREX_RISK_PCT:,.2f}")
    print("=" * 65 + "\n")

    from core.logging_setup import setup_logging
    from scanner_bot.robot import ScannerRobot
    from scanner_bot.symbols import discover_forex_only_symbols
    setup_logging(FOREX_LOG_FILE)
    ScannerRobot(capital, FOREX_MAGIC, discover_forex_only_symbols, FOREX_LOG_FILE).run()


def _run_crypto(capital: float) -> None:
    _header("Crypto Scanner")
    print(f"  Estratégia : EMA {EMA_FAST}/{EMA_SLOW} M5 + RSI {RSI_PERIOD} + "
          f"MACD ({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + EMA {EMA_TREND_H1} H1")
    print(f"  Spread max : {SPREAD_MAX_CRYPTO:.0f} pips | Sessão: 24/7 (sem filtro)")
    print(f"  Risco      : {CRYPTO_RISK_PCT*100:.0f}% | "
          f"SL={CRYPTO_SL_PIPS}p | TP={int(CRYPTO_SL_PIPS*TP_RATIO)}p")
    print(f"  Posições   : máx {CRYPTO_MAX_TOTAL_POSITIONS} | Loop: {LOOP_SECONDS}s | Magic: {CRYPTO_MAGIC}")
    print(f"  Capital    : USD {capital:,.2f} | Risco/trade: USD {capital*CRYPTO_RISK_PCT:,.2f}")
    print("=" * 65 + "\n")

    from core.logging_setup import setup_logging
    from scanner_bot.robot import ScannerRobot
    from scanner_bot.symbols import discover_crypto_symbols
    setup_logging(CRYPTO_LOG_FILE)
    ScannerRobot(capital, CRYPTO_MAGIC, discover_crypto_symbols, CRYPTO_LOG_FILE).run()


# ──────────────────────────────────────────────────────────────────
# MENU PRINCIPAL
# ──────────────────────────────────────────────────────────────────
_BOTS = {
    "1": ("Triple Confirmation",  f"par único ({TRIPLE_SYMBOL})",   _run_triple),
    "2": ("Forex Scanner",        "todos os pares forex",            _run_forex),
    "3": ("Crypto Scanner",       "todos os pares cripto",           _run_crypto),
}


def main() -> None:
    print("\n" + "=" * 65)
    print("  Scalping MT5 — Triple Confirmation")
    print("  Configuração: config.py")
    print("=" * 65)
    print("\n  Bots disponíveis:\n")
    for key, (name, desc, _) in _BOTS.items():
        print(f"    [{key}]  {name:<25}  {desc}")
    print()

    while True:
        choice = input("  Escolha (1/2/3): ").strip()
        if choice in _BOTS:
            break
        print("  Opção inválida. Digite 1, 2 ou 3.")

    capital = _ask_capital()

    _, _, launcher = _BOTS[choice]
    launcher(capital)


if __name__ == "__main__":
    main()
