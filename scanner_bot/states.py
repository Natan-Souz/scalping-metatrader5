"""
scanner_bot.states
State Pattern — ciclo de vida do scanner.

EstadoAguardandoSinal   → varre o mercado e executa entradas
EstadoGerenciandoPosicao → monitora posições; volta ao sinal quando há slot livre

O import circular (states ↔ robot) é resolvido via TYPE_CHECKING:
ScannerRobot aparece apenas como type hint e não é importado em runtime.

Ambos os estados recebem e preservam `discover_fn` nas transições,
permitindo que forex e cripto usem o mesmo código com funções de
descoberta diferentes.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List, Optional

import MetaTrader5 as mt5

from core.mt5_bridge import calc_lot, calc_sl_tp, place_order
from scanner_bot.config import MAX_TOTAL_POSITIONS, TP_RATIO, RISK_PCT
from scanner_bot.filters import (
    Pipeline,
    FiltroExoticos, FiltroSessao, FiltroSpread,
    FiltroIndicadores, FiltroValidacaoEntrada,
    FiltroCorrelacao, FiltroPosicaoPorSimbolo,
)
from scanner_bot.models import CandidatoInfo
from scanner_bot.symbols import discover_forex_only_symbols, get_magic_positions

if TYPE_CHECKING:
    from scanner_bot.robot import ScannerRobot

log = logging.getLogger(__name__)

# Tipo para a função de descoberta de símbolos
DiscoverFn = Callable[[], List[CandidatoInfo]]


class EstadoBase(ABC):
    @abstractmethod
    def processar(self, robo: ScannerRobot) -> EstadoBase:
        ...


class EstadoAguardandoSinal(EstadoBase):
    """
    Varre o mercado com a `discover_fn` configurada, avalia sinais
    via pipeline e executa entradas.

    Fase 1 — pipeline estático (uma vez por ciclo):
      FiltroExoticos → FiltroSessao → FiltroSpread
        → FiltroIndicadores → FiltroValidacaoEntrada

      Nota: FiltroSessao já passa símbolos Crypto sem checagem (24/7).

    Fase 2 — validação dinâmica (reconstruída após cada entrada):
      FiltroPosicaoPorSimbolo → FiltroCorrelacao
    """

    def __init__(self, discover_fn: Optional[DiscoverFn] = None) -> None:
        self._discover_fn: DiscoverFn = discover_fn or discover_forex_only_symbols

    def processar(self, robo: ScannerRobot) -> EstadoBase:
        magic_pos = get_magic_positions(robo.magic)

        if len(magic_pos) >= MAX_TOTAL_POSITIONS:
            log.debug(
                "Limite global atingido (%d/%d) → gerenciando posições.",
                len(magic_pos), MAX_TOTAL_POSITIONS,
            )
            return EstadoGerenciandoPosicao(self._discover_fn)

        # Fase 1: pipeline estático
        candidatos  = self._discover_fn()
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

            # SL efetivo: cripto usa % do preço (dinâmico); forex usa pips fixos
            if c.sl_pct is not None:
                eff_sl_pips = max(1, round(price * c.sl_pct / c.pip_size))
                log.debug("%s: SL %.0f%% do preço → %d pips equiv. (preço=%.5f)",
                          c.symbol, c.sl_pct * 100, eff_sl_pips, price)
            else:
                eff_sl_pips = c.sl_pips

            lot = calc_lot(robo.capital, c.pip_value, c.symbol, RISK_PCT, eff_sl_pips)
            if lot <= 0:
                log.warning("%s: lote inválido (%.2f) — pulando.", c.symbol, lot)
                continue

            sl, tp = calc_sl_tp(c.symbol, c.direction, price,
                                eff_sl_pips, c.pip_size, TP_RATIO)
            if sl == 0.0 or tp == 0.0:
                continue

            log.info(
                "CANDIDATO score=4 | %s %s | lote=%.2f | spread=%.2fp"
                " | c1=%s c2=%s c3=%s c4=%s",
                c.symbol, c.direction, lot, c.spread_pips,
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

        if len(magic_pos) >= MAX_TOTAL_POSITIONS:
            return EstadoGerenciandoPosicao(self._discover_fn)
        return self


class EstadoGerenciandoPosicao(EstadoBase):
    """
    Monitora posições abertas e retorna a EstadoAguardandoSinal
    assim que um slot fica disponível.
    Preserva `discover_fn` para a transição de volta.
    """

    def __init__(self, discover_fn: Optional[DiscoverFn] = None) -> None:
        self._discover_fn: DiscoverFn = discover_fn or discover_forex_only_symbols

    def processar(self, robo: ScannerRobot) -> EstadoBase:
        magic_pos = get_magic_positions(robo.magic)
        log.debug(
            "Posições abertas: %d/%d — aguardando fechamento.",
            len(magic_pos), MAX_TOTAL_POSITIONS,
        )

        if len(magic_pos) < MAX_TOTAL_POSITIONS:
            log.info(
                "Slot disponível (%d/%d) → retornando à busca de sinais.",
                len(magic_pos), MAX_TOTAL_POSITIONS,
            )
            return EstadoAguardandoSinal(self._discover_fn)
        return self
