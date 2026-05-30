"""
scanner_bot.states
State Pattern — ciclo de vida do scanner.

EstadoAguardandoSinal   → varre o mercado e executa entradas
EstadoGerenciandoPosicao → monitora posições; volta ao sinal quando há slot livre

O import circular (states ↔ robot) é resolvido via TYPE_CHECKING:
ScannerRobot aparece apenas como type hint e não é importado em runtime.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

import MetaTrader5 as mt5

from core.mt5_bridge import calc_lot, place_order
from scanner_bot.config import (
    MAX_TOTAL_POSITIONS, TP_RATIO, MAGIC, RISK_PCT,
)
from scanner_bot.filters import (
    Pipeline,
    FiltroExoticos, FiltroSessao, FiltroSpread,
    FiltroIndicadores, FiltroValidacaoEntrada,
    FiltroCorrelacao, FiltroPosicaoPorSimbolo,
)
from scanner_bot.models import CandidatoInfo
from scanner_bot.symbols import discover_symbols, get_magic_positions

if TYPE_CHECKING:
    from scanner_bot.robot import ScannerRobot

log = logging.getLogger(__name__)


class EstadoBase(ABC):
    @abstractmethod
    def processar(self, robo: ScannerRobot) -> EstadoBase:
        ...


class EstadoAguardandoSinal(EstadoBase):
    """
    Varre o mercado, avalia sinais via pipeline e executa entradas.

    Fase 1 — pipeline estático (uma vez por ciclo):
      FiltroExoticos → FiltroSessao → FiltroSpread
        → FiltroIndicadores → FiltroValidacaoEntrada

    Fase 2 — validação dinâmica (reconstruída após cada entrada):
      FiltroPosicaoPorSimbolo → FiltroCorrelacao
    """

    def processar(self, robo: ScannerRobot) -> EstadoBase:
        magic_pos = get_magic_positions()

        if len(magic_pos) >= MAX_TOTAL_POSITIONS:
            log.debug(
                "Limite global atingido (%d/%d) → gerenciando posições.",
                len(magic_pos), MAX_TOTAL_POSITIONS,
            )
            return EstadoGerenciandoPosicao()

        # Fase 1: pipeline estático
        candidatos  = discover_symbols()
        static_pipe = Pipeline(
            FiltroExoticos(),
            FiltroSessao(),
            FiltroSpread(),
            FiltroIndicadores(),
            FiltroValidacaoEntrada(),
        )
        aprovados: List[CandidatoInfo] = []
        for raw in candidatos:
            resultado = static_pipe.processar(raw)
            if resultado is not None:
                aprovados.append(resultado)

        aprovados.sort(key=lambda x: (-x.score, x.spread_pips))

        # Fase 2: validação dinâmica e execução
        entries_done = 0
        for c in aprovados:
            if len(magic_pos) >= MAX_TOTAL_POSITIONS:
                break

            entry_pipe = Pipeline(
                FiltroPosicaoPorSimbolo(magic_pos),
                FiltroCorrelacao(magic_pos),
            )
            if entry_pipe.processar(c) is None:
                continue

            lot = calc_lot(robo.capital, c.pip_value, c.symbol, RISK_PCT, c.sl_pips)
            if lot <= 0:
                log.warning("%s: lote inválido (%.2f) — pulando.", c.symbol, lot)
                continue

            tick = mt5.symbol_info_tick(c.symbol)
            if tick is None:
                log.warning("%s: sem tick disponível.", c.symbol)
                continue

            if c.direction == "BUY":
                price = tick.ask
                sl    = round(price - c.sl_pips * c.pip_size, 5)
                tp    = round(price + c.sl_pips * TP_RATIO * c.pip_size, 5)
                otype = mt5.ORDER_TYPE_BUY
            else:
                price = tick.bid
                sl    = round(price + c.sl_pips * c.pip_size, 5)
                tp    = round(price - c.sl_pips * TP_RATIO * c.pip_size, 5)
                otype = mt5.ORDER_TYPE_SELL

            log.info(
                "CANDIDATO score=4 | %s %s | lote=%.2f | spread=%.2fp"
                " | c1=%s c2=%s c3=%s c4=%s",
                c.symbol, c.direction, lot, c.spread_pips,
                c.criterios["c1"], c.criterios["c2"],
                c.criterios["c3"], c.criterios["c4"],
            )

            if place_order(c.symbol, otype, lot, price, sl, tp,
                           MAGIC, f"SCAN_{c.direction}_{c.symbol}"):
                entries_done += 1
                magic_pos = get_magic_positions()

        log.info(
            "[SCAN] %d pares | %d passaram filtros | %d entrada(s) executada(s)",
            len(candidatos), len(aprovados), entries_done,
        )

        if len(magic_pos) >= MAX_TOTAL_POSITIONS:
            return EstadoGerenciandoPosicao()
        return self


class EstadoGerenciandoPosicao(EstadoBase):
    """
    Monitora posições abertas e retorna a EstadoAguardandoSinal
    assim que um slot fica disponível.
    """

    def processar(self, robo: ScannerRobot) -> EstadoBase:
        magic_pos = get_magic_positions()
        log.debug(
            "Posições abertas: %d/%d — aguardando fechamento.",
            len(magic_pos), MAX_TOTAL_POSITIONS,
        )

        if len(magic_pos) < MAX_TOTAL_POSITIONS:
            log.info(
                "Slot disponível (%d/%d) → retornando à busca de sinais.",
                len(magic_pos), MAX_TOTAL_POSITIONS,
            )
            return EstadoAguardandoSinal()
        return self
