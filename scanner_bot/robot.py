"""
scanner_bot.robot
Robô scanner multi-par — gerencia o loop de 15s e delega ao estado atual.

Execução:
    python forex_scanner.py
    python -m scanner_bot.robot
"""

import sys
import time
import logging

from core.logging_setup import setup_logging
from core.mt5_bridge import connect
from scanner_bot.config import (
    LOOP_SECONDS, LOG_FILE, MAGIC,
    RISK_PCT, SL_PIPS, TP_RATIO,
    MAX_TOTAL_POSITIONS, MAX_POSITIONS_PER_SYMBOL,
    SPREAD_MAX_MAJORS, SPREAD_MAX_MINORS, SPREAD_MAX_PCT_OF_SL,
    EMA_FAST, EMA_SLOW, RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL, EMA_TREND_H1,
)
from scanner_bot.states import EstadoAguardandoSinal, EstadoBase

log = logging.getLogger(__name__)


class ScannerRobot:
    """Gerencia o loop de 15s e delega toda a lógica ao estado atual."""

    def __init__(self, capital: float) -> None:
        self.capital         = capital
        self._estado: EstadoBase = EstadoAguardandoSinal()

    def run(self) -> None:
        log.info("=" * 70)
        log.info("Forex Scanner Multi-Par iniciando | Capital=%.2f USD", self.capital)
        log.info(
            "Risco=%.0f%% | SL=%d pips | TP=%d pips | Max posições=%d | Magic=%d",
            RISK_PCT * 100, SL_PIPS, int(SL_PIPS * TP_RATIO), MAX_TOTAL_POSITIONS, MAGIC,
        )
        log.info(
            "Spread: Majors≤%.1fp | Minors≤%.1fp | Exotics=bloqueado | spread/SL≤%.0f%%",
            SPREAD_MAX_MAJORS, SPREAD_MAX_MINORS, SPREAD_MAX_PCT_OF_SL * 100,
        )
        log.info("=" * 70)

        if not connect():
            sys.exit(1)

        iteration = 0
        while True:
            iteration += 1
            log.debug("=== Ciclo %d [%s] ===", iteration, type(self._estado).__name__)
            try:
                self._estado = self._estado.processar(self)
            except KeyboardInterrupt:
                log.info("Interrompido pelo usuário (Ctrl+C).")
                break
            except Exception as exc:
                log.error("Erro no ciclo %d: %s", iteration, exc, exc_info=True)

            time.sleep(LOOP_SECONDS)

        import MetaTrader5 as mt5
        mt5.shutdown()
        log.info("Conexão MT5 encerrada. Scanner finalizado.")


def main() -> None:
    """Entry point com input de capital e inicialização do logging."""
    print("=" * 70)
    print("  Forex Scanner Multi-Par — Triple Confirmation | MT5")
    print("=" * 70)
    print(f"  Estratégia : EMA {EMA_FAST}/{EMA_SLOW} M5 + RSI {RSI_PERIOD} + "
          f"MACD ({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + EMA {EMA_TREND_H1} H1")
    print(f"  Spread     : Majors≤{SPREAD_MAX_MAJORS}p | Minors≤{SPREAD_MAX_MINORS}p | "
          f"Spread/SL≤{SPREAD_MAX_PCT_OF_SL*100:.0f}% | Exotics=bloqueado")
    print(f"  Risco      : {RISK_PCT*100:.0f}% | SL={SL_PIPS}p | TP={int(SL_PIPS*TP_RATIO)}p")
    print(f"  Posições   : máx {MAX_TOTAL_POSITIONS} total | máx {MAX_POSITIONS_PER_SYMBOL} por par")
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

    ScannerRobot(capital_usd).run()


if __name__ == "__main__":
    main()
