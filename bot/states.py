"""
bot.states
State Pattern — ciclo de vida do scanner.

EstadoAguardandoSinal    → varre o mercado, avalia sinais, executa entradas
EstadoGerenciandoPosicao → monitora posições; retorna ao sinal quando há slot livre

O import circular (states ↔ robot) é resolvido via TYPE_CHECKING.
Ambos os estados preservam discover_fn e max_positions nas transições.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List, Optional

import MetaTrader5 as mt5

import config as cfg
from core.mt5_bridge import calc_lot, calc_sl_tp, place_order
from bot.filters import (
    Pipeline,
    FiltroExoticos, FiltroSessao, FiltroSpread, FiltroRegime,
    FiltroIndicadores, FiltroValidacaoEntrada,
    FiltroCorrelacao, FiltroPosicaoPorSimbolo,
)
from bot.models import CandidatoInfo
from bot.symbols import discover_forex_only_symbols, get_magic_positions

if TYPE_CHECKING:
    from bot.robot import ScannerRobot

log = logging.getLogger(__name__)

DiscoverFn = Callable[[], List[CandidatoInfo]]


class EstadoBase(ABC):
    @abstractmethod
    def processar(self, robo: ScannerRobot) -> EstadoBase:
        ...


class EstadoAguardandoSinal(EstadoBase):
    """
    Varre o mercado com a discover_fn configurada, avalia sinais via pipeline
    e executa entradas.

    Fase 1 — pipeline estático (uma vez por ciclo):
      FiltroExoticos → FiltroSessao → FiltroSpread
        → FiltroRegime → FiltroIndicadores → FiltroValidacaoEntrada

    Fase 2 — validação dinâmica (reconstruída após cada entrada):
      FiltroPosicaoPorSimbolo → FiltroCorrelacao
    """

    def __init__(
        self,
        discover_fn: Optional[DiscoverFn] = None,
        max_positions: int = cfg.FOREX_MAX_TOTAL_POSITIONS,
    ) -> None:
        self._discover_fn   = discover_fn or discover_forex_only_symbols
        self._max_positions = max_positions

    def processar(self, robo: ScannerRobot) -> EstadoBase:
        magic_pos = get_magic_positions(robo.magic)

        if len(magic_pos) >= self._max_positions:
            log.debug(
                "Limite global atingido (%d/%d) → gerenciando posições.",
                len(magic_pos), self._max_positions,
            )
            return EstadoGerenciandoPosicao(self._discover_fn, self._max_positions)

        # Fase 1: pipeline estático
        candidatos  = self._discover_fn()
        static_pipe = Pipeline(
            FiltroExoticos(),
            FiltroSessao(),
            FiltroSpread(),
            FiltroRegime(),
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
            if len(magic_pos) >= self._max_positions:
                break

            entry_pipe = Pipeline(
                FiltroPosicaoPorSimbolo(magic_pos),
                FiltroCorrelacao(magic_pos),
            )
            if entry_pipe.processar(c) is None:
                continue

            tick = mt5.symbol_info_tick(c.symbol)
            if tick is None:
                log.warning("%s: sem tick disponível.", c.symbol)
                continue

            if c.direction == "BUY":
                price = tick.ask
                otype = mt5.ORDER_TYPE_BUY
            else:
                price = tick.bid
                otype = mt5.ORDER_TYPE_SELL

            if c.sl_pct is not None:
                eff_sl_pips = max(1, round(price * c.sl_pct / c.pip_size))
                log.debug("%s: SL %.0f%% do preço → %d pips equiv.",
                          c.symbol, c.sl_pct * 100, eff_sl_pips)
            else:
                eff_sl_pips = c.sl_pips  # vem do perfil

            lot = calc_lot(robo.capital, c.pip_value, c.symbol,
                           c.profile.risk_pct, eff_sl_pips)
            if lot <= 0:
                log.warning("%s: lote inválido (%.2f) — pulando.", c.symbol, lot)
                continue

            sl, tp = calc_sl_tp(c.symbol, c.direction, price,
                                eff_sl_pips, c.pip_size, cfg.TP_RATIO)
            if sl == 0.0 or tp == 0.0:
                continue

            log.info(
                "CANDIDATO score=%d | %s %s | lote=%.2f | spread=%.2fp | ADX=%.1f"
                " | c1=%s c2=%s c3=%s c4=%s",
                c.score, c.symbol, c.direction, lot, c.spread_pips, c.adx,
                c.criterios["c1"], c.criterios["c2"],
                c.criterios["c3"], c.criterios["c4"],
            )

            if place_order(c.symbol, otype, lot, price, sl, tp,
                           robo.magic, f"SCAN_{c.direction}_{c.symbol}"):
                entries_done += 1
                magic_pos = get_magic_positions(robo.magic)

        log.info(
            "[SCAN] %d símbolos | %d passaram filtros | %d entrada(s) executada(s)",
            len(candidatos), len(aprovados), entries_done,
        )

        if len(magic_pos) >= self._max_positions:
            return EstadoGerenciandoPosicao(self._discover_fn, self._max_positions)
        return self


class EstadoGerenciandoPosicao(EstadoBase):
    """
    Monitora posições abertas e retorna a EstadoAguardandoSinal
    assim que um slot fica disponível.
    """

    def __init__(
        self,
        discover_fn: Optional[DiscoverFn] = None,
        max_positions: int = cfg.FOREX_MAX_TOTAL_POSITIONS,
    ) -> None:
        self._discover_fn   = discover_fn or discover_forex_only_symbols
        self._max_positions = max_positions

    def processar(self, robo: ScannerRobot) -> EstadoBase:
        magic_pos = get_magic_positions(robo.magic)
        log.debug(
            "Posições abertas: %d/%d — aguardando fechamento.",
            len(magic_pos), self._max_positions,
        )

        if len(magic_pos) < self._max_positions:
            log.info(
                "Slot disponível (%d/%d) → retornando à busca de sinais.",
                len(magic_pos), self._max_positions,
            )
            return EstadoAguardandoSinal(self._discover_fn, self._max_positions)
        return self
