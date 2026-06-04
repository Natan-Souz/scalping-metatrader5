"""
bot.robot
Robô scanner — gerencia o loop de 15s e delega ao estado atual.
"""

import sys
import time
import logging
from typing import Callable, List, Optional

import MetaTrader5 as mt5

import config as cfg
from core.mt5_bridge import connect
from bot.models import CandidatoInfo
from bot.states import EstadoAguardandoSinal, EstadoBase
from bot.symbols import discover_forex_only_symbols

log = logging.getLogger(__name__)

DiscoverFn = Callable[[], List[CandidatoInfo]]


class ScannerRobot:
    """
    Gerencia o loop de 15s e delega toda a lógica ao estado atual.

    Args:
        capital:       capital em USD para cálculo de lote
        magic:         magic number das ordens
        discover_fn:   função que retorna os símbolos a varrer
        max_positions: limite global de posições simultâneas
    """

    def __init__(
        self,
        capital: float,
        magic: int = cfg.FOREX_MAGIC,
        discover_fn: Optional[DiscoverFn] = None,
        max_positions: int = cfg.FOREX_MAX_TOTAL_POSITIONS,
    ) -> None:
        self.capital      = capital
        self.magic        = magic
        self._discover_fn = discover_fn or discover_forex_only_symbols
        self._estado: EstadoBase = EstadoAguardandoSinal(
            self._discover_fn, max_positions=max_positions
        )

    def run(self) -> None:
        log.info("=" * 70)
        log.info(
            "Scanner iniciando | Capital=%.2f USD | Magic=%d | MaxPos=%d",
            self.capital, self.magic,
            self._estado._max_positions,  # type: ignore[union-attr]
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

            time.sleep(cfg.LOOP_SECONDS)

        mt5.shutdown()
        log.info("Conexão MT5 encerrada.")
