"""
scanner_bot.filters
Pipeline Chain of Responsibility — todos os filtros do scanner.

Ordem de execução no pipeline estático (do mais barato ao mais caro):
  FiltroExoticos → FiltroSessao → FiltroSpread → FiltroIndicadores → FiltroValidacaoEntrada

Filtros dinâmicos (reconstruídos a cada entrada no mesmo ciclo):
  FiltroPosicaoPorSimbolo → FiltroCorrelacao
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, FrozenSet, Optional

import numpy as np
import MetaTrader5 as mt5

from core.indicators import calc_ema, calc_rsi, calc_macd
from core.mt5_bridge import get_bars
from scanner_bot.config import (
    TF_M5, TF_H1, BARS_M5, BARS_H1,
    EMA_FAST, EMA_SLOW, EMA_CROSSOVER_PIPS_THR,
    RSI_PERIOD, RSI_BUY_MIN, RSI_BUY_MAX, RSI_SELL_MIN, RSI_SELL_MAX,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL, EMA_TREND_H1,
    SPREAD_MAX_MAJORS, SPREAD_MAX_MINORS, SPREAD_MAX_CRYPTO, SPREAD_MAX_PCT_OF_SL,
    MAX_POSITIONS_PER_SYMBOL,
    SESSION_LONDON_START, SESSION_LONDON_END,
    SESSION_NY_START, SESSION_NY_END, SESSION_ASIAN_END,
)
from scanner_bot.models import CandidatoInfo
from scanner_bot.symbols import get_currencies

log = logging.getLogger(__name__)

# ============================================================
# HELPERS DE SESSÃO
# ============================================================
_SESSIONS_BY_CURRENCY: Dict[str, FrozenSet[str]] = {
    "EUR": frozenset({"london", "new_york"}),
    "GBP": frozenset({"london", "new_york"}),
    "CHF": frozenset({"london", "new_york"}),
    "USD": frozenset({"london", "new_york"}),
    "CAD": frozenset({"new_york"}),
    "JPY": frozenset({"asian", "new_york"}),
    "AUD": frozenset({"asian", "new_york"}),
    "NZD": frozenset({"asian", "new_york"}),
}


def _sessoes_ativas(hora_utc: int) -> FrozenSet[str]:
    """Retorna o conjunto de sessões abertas para a hora UTC informada."""
    ativas: set = set()
    if SESSION_LONDON_START <= hora_utc < SESSION_LONDON_END:
        ativas.add("london")
    if SESSION_NY_START <= hora_utc < SESSION_NY_END:
        ativas.add("new_york")
    if hora_utc >= 22 or hora_utc < SESSION_ASIAN_END:
        ativas.add("asian")
    return frozenset(ativas)


# ============================================================
# CONTRATO BASE
# ============================================================
class FiltroBase(ABC):
    """Interface de todos os filtros do pipeline."""

    @abstractmethod
    def executar(self, candidato: CandidatoInfo) -> Optional[CandidatoInfo]:
        ...


# ============================================================
# FILTROS BARATOS (sem chamadas de dados de mercado)
# ============================================================
class FiltroExoticos(FiltroBase):
    """Descarta pares Exotics antes de qualquer chamada ao MT5."""

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.category == "Exotics":
            log.debug("SKIP Exotic: %s", c.symbol)
            return None
        return c


class FiltroSessao(FiltroBase):
    """
    Bloqueia pares fora do horário de liquidez das suas moedas.

    Cripto opera 24/7 — passa diretamente sem verificação.

    Lógica para forex: um par é negociável se CADA uma de suas moedas
    tem ao menos uma sessão ativa no momento. Moeda não mapeada → permissivo.

    Janelas resultantes (UTC):
      EUR/USD → 07h–22h  (Londres + NY)
      USD/JPY → 13h–22h  (só overlap NY)
      AUD/NZD → 22h–09h + 13h–22h  (Ásia + NY)
    """

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.category == "Crypto":
            return c  # mercado cripto opera 24/7 — sem restrição de sessão

        hora_utc = datetime.now(timezone.utc).hour
        ativas   = _sessoes_ativas(hora_utc)

        for moeda in get_currencies(c.symbol):
            sessoes_moeda = _SESSIONS_BY_CURRENCY.get(moeda, ativas)
            if not (sessoes_moeda & ativas):
                log.debug(
                    "SKIP sessão %s | UTC %02dh | %s fora de sessão (ativas=%s)",
                    c.symbol, hora_utc, moeda, set(ativas),
                )
                return None
        return c


# ============================================================
# FILTRO DE SPREAD
# ============================================================
class FiltroSpread(FiltroBase):
    """
    Descarta se spread atual excede o limite da categoria ou 20% do SL.
    Usa o sl_pips do próprio candidato no cálculo relativo — garantindo que
    o threshold de 20% seja proporcional ao SL real de cada categoria.
    Preenche c.spread_pips nos candidatos aprovados.
    """

    _SPREAD_LIMITS = {
        "Majors": SPREAD_MAX_MAJORS,
        "Minors": SPREAD_MAX_MINORS,
        "Exotics": SPREAD_MAX_MINORS,  # exotics já filtrados antes, mas cobre edge cases
        "Crypto": SPREAD_MAX_CRYPTO,
    }

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        tick = mt5.symbol_info_tick(c.symbol)
        if tick is None or tick.ask == 0 or tick.bid == 0:
            log.debug("SKIP sem tick: %s", c.symbol)
            return None

        spread_pips = (tick.ask - tick.bid) / c.pip_size
        max_spread  = self._SPREAD_LIMITS.get(c.category, SPREAD_MAX_MINORS)

        if spread_pips > max_spread:
            log.debug("SKIP spread %s (%s): %.2fp > %.2fp",
                      c.symbol, c.category, spread_pips, max_spread)
            return None
        if (spread_pips / c.sl_pips) > SPREAD_MAX_PCT_OF_SL:
            log.debug("SKIP spread/SL %s: %.1f%%", c.symbol, spread_pips / c.sl_pips * 100)
            return None

        c.spread_pips = round(spread_pips, 2)
        return c


# ============================================================
# FILTRO DE INDICADORES (pesado — só executa após os filtros baratos)
# ============================================================
class FiltroIndicadores(FiltroBase):
    """
    Busca 300 candles M5 + 150 H1, calcula os 4 indicadores e avalia
    os critérios Triple Confirmation no candle fechado (índice -2).

    Preenche c.score, c.direction e c.criterios.
    """

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        df_m5 = get_bars(c.symbol, TF_M5, BARS_M5)
        df_h1 = get_bars(c.symbol, TF_H1, BARS_H1)
        if df_m5 is None or df_h1 is None:
            return None

        close_m5 = df_m5["close"].values
        close_h1 = df_h1["close"].values

        ema_fast               = calc_ema(close_m5, EMA_FAST)
        ema_slow               = calc_ema(close_m5, EMA_SLOW)
        rsi                    = calc_rsi(close_m5, RSI_PERIOD)
        macd_line, sig_line, _ = calc_macd(close_m5, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        ema_h1                 = calc_ema(close_h1, EMA_TREND_H1)

        idx = -2   # último candle fechado
        ef, es       = ema_fast[idx],     ema_slow[idx]
        ef_p1, es_p1 = ema_fast[idx - 1], ema_slow[idx - 1]
        ef_p2, es_p2 = ema_fast[idx - 2], ema_slow[idx - 2]
        rsi_val  = rsi[idx]
        macd_val = macd_line[idx]
        sig_val  = sig_line[idx]
        h1_ema   = ema_h1[-1]
        price    = close_m5[idx]

        if any(np.isnan(v) for v in [ef, es, ef_p1, es_p1, ef_p2, es_p2,
                                      rsi_val, macd_val, sig_val, h1_ema]):
            log.debug("%s: NaN nos indicadores — ignorado.", c.symbol)
            return None

        # C1: crossover exato ou pré-crossover convergindo
        cross_up   = ef_p1 < es_p1 and ef > es
        cross_down = ef_p1 > es_p1 and ef < es
        converging = abs(ef - es) < abs(ef_p1 - es_p1) < abs(ef_p2 - es_p2)
        near       = (abs(ef - es) / c.pip_size) < EMA_CROSSOVER_PIPS_THR

        if cross_up:
            c1 = "BUY"
        elif cross_down:
            c1 = "SELL"
        elif converging and near:
            c1 = "BUY" if ef < es else "SELL"
        else:
            c1 = "NEUTRAL"

        # C2: RSI na faixa correta
        if RSI_BUY_MIN <= rsi_val <= RSI_BUY_MAX:
            c2 = "BUY"
        elif RSI_SELL_MIN <= rsi_val <= RSI_SELL_MAX:
            c2 = "SELL"
        else:
            c2 = "NEUTRAL"

        # C3: MACD alinhado com signal line
        c3 = "BUY" if macd_val > sig_val else ("SELL" if macd_val < sig_val else "NEUTRAL")

        # C4: preço vs EMA50 H1
        c4 = "BUY" if price > h1_ema else ("SELL" if price < h1_ema else "NEUTRAL")

        criterios  = {"c1": c1, "c2": c2, "c3": c3, "c4": c4}
        buy_count  = sum(1 for v in criterios.values() if v == "BUY")
        sell_count = sum(1 for v in criterios.values() if v == "SELL")

        if buy_count > sell_count:
            c.direction, c.score = "BUY",     buy_count
        elif sell_count > buy_count:
            c.direction, c.score = "SELL",    sell_count
        else:
            c.direction, c.score = "NEUTRAL", max(buy_count, sell_count)

        c.criterios = criterios

        log.debug(
            "%s | score=%d dir=%-7s | c1=%-7s c2=%-7s c3=%-7s c4=%-7s | RSI=%.1f MACD=%.5f",
            c.symbol, c.score, c.direction, c1, c2, c3, c4, rsi_val, macd_val,
        )
        return c


# ============================================================
# FILTRO DE VALIDAÇÃO DE ENTRADA
# ============================================================
class FiltroValidacaoEntrada(FiltroBase):
    """
    Exige score = 4: todos os critérios devem alinhar na mesma direção.

    score 4 → passa para execução
    score 3 → log WARNING (alerta), sem entrada
    score ≤ 2 ou NEUTRAL → descartado silenciosamente
    """

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.direction == "NEUTRAL":
            return None

        d  = c.direction
        cr = c.criterios
        todos_ok = cr["c1"] == d and cr["c2"] == d and cr["c3"] == d and cr["c4"] == d

        if todos_ok:
            return c

        if c.score == 3:
            log.warning(
                "[ALERTA] %s score=3 dir=%s spread=%.1fp cat=%s"
                " | c1=%s c2=%s c3=%s c4=%s — aguardando critério faltante",
                c.symbol, d, c.spread_pips, c.category,
                cr["c1"], cr["c2"], cr["c3"], cr["c4"],
            )
        return None


# ============================================================
# FILTROS DINÂMICOS (reconstruídos a cada entrada)
# ============================================================
class FiltroCorrelacao(FiltroBase):
    """Bloqueia se o par compartilha moeda base ou cotada com posição aberta."""

    def __init__(self, open_positions: list) -> None:
        self._positions = open_positions

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        cand_currencies = get_currencies(c.symbol)
        for pos in self._positions:
            shared = cand_currencies & get_currencies(pos.symbol)
            if shared:
                log.debug("CORRELAÇÃO: %s bloqueado por %s (moeda: %s)",
                          c.symbol, pos.symbol, shared)
                return None
        return c


class FiltroPosicaoPorSimbolo(FiltroBase):
    """Bloqueia se o símbolo já atingiu MAX_POSITIONS_PER_SYMBOL."""

    def __init__(self, open_positions: list) -> None:
        self._positions = open_positions

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        count = sum(1 for p in self._positions if p.symbol == c.symbol)
        if count >= MAX_POSITIONS_PER_SYMBOL:
            log.debug("%s: limite por símbolo atingido (%d).", c.symbol, count)
            return None
        return c


# ============================================================
# PIPELINE
# ============================================================
class Pipeline:
    """Executa filtros em cadeia; interrompe imediatamente no primeiro None."""

    def __init__(self, *filtros: FiltroBase) -> None:
        self._filtros = filtros

    def processar(self, candidato: CandidatoInfo) -> Optional[CandidatoInfo]:
        atual: Optional[CandidatoInfo] = candidato
        for filtro in self._filtros:
            atual = filtro.executar(atual)
            if atual is None:
                return None
        return atual
