"""
scanner_bot.robot
Robô scanner genérico — gerencia o loop de 15s e delega ao estado atual.

Pode operar em modo forex ou cripto conforme os parâmetros recebidos.

Execução direta (forex):
    python forex_scanner.py
    python -m scanner_bot.robot

Execução cripto (via crypto_scanner.py):
    python crypto_scanner.py
"""

import sys
import time
import logging
from typing import Callable, List, Optional

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
from scanner_bot.models import CandidatoInfo
from scanner_bot.states import EstadoAguardandoSinal, EstadoBase
from scanner_bot.symbols import discover_forex_only_symbols

log = logging.getLogger(__name__)

DiscoverFn = Callable[[], List[CandidatoInfo]]


class ScannerRobot:
    """
    Gerencia o loop de 15s e delega toda a lógica ao estado atual.

    Args:
        capital:     capital em USD para cálculo de lote
        magic:       magic number das ordens (padrão: MAGIC do scanner forex)
        discover_fn: função que retorna os símbolos a varrer
                     (padrão: discover_forex_only_symbols)
        log_file:    arquivo de log (padrão: LOG_FILE do scanner forex)
    """

    def __init__(
        self,
        capital: float,
        magic: int = MAGIC,
        discover_fn: Optional[DiscoverFn] = None,
        log_file: str = LOG_FILE,
    ) -> None:
        self.capital      = capital
        self.magic        = magic
        self._log_file    = log_file
        self._discover_fn = discover_fn or discover_forex_only_symbols
        self._estado: EstadoBase = EstadoAguardandoSinal(self._discover_fn)

    def run(self) -> None:
        log.info("=" * 70)
        log.info("Scanner iniciando | Capital=%.2f USD | Magic=%d", self.capital, self.magic)
        log.info(
            "Risco=%.0f%% | SL=%d pips | TP=%d pips | Max posições=%d",
            RISK_PCT * 100, SL_PIPS, int(SL_PIPS * TP_RATIO), MAX_TOTAL_POSITIONS,
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
    """Entry point do scanner FOREX (forex_scanner.py)."""
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

    ScannerRobot(
        capital=capital_usd,
        magic=MAGIC,
        discover_fn=discover_forex_only_symbols,
        log_file=LOG_FILE,
    ).run()


if __name__ == "__main__":
    main()
