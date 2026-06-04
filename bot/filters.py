"""
bot.filters
Pipeline Chain of Responsibility — filtros do scanner.

Ordem de execução no pipeline estático (mais barato ao mais caro):
  FiltroExoticos → FiltroSessao → FiltroSpread
    → FiltroIndicadores → FiltroValidacaoEntrada

Filtros dinâmicos (reconstruídos a cada entrada no mesmo ciclo):
  FiltroPosicaoPorSimbolo → FiltroCorrelacao
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional

import numpy as np
import MetaTrader5 as mt5

import config as cfg
from core.indicators import calc_ema, calc_rsi, calc_macd
from core.mt5_bridge import get_bars
from bot.models import CandidatoInfo
from bot.symbols import get_currencies

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# HELPERS DE SESSÃO
# ──────────────────────────────────────────────────────────────
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
    ativas: set = set()
    if cfg.SESSION_LONDON_START <= hora_utc < cfg.SESSION_LONDON_END:
        ativas.add("london")
    if cfg.SESSION_NY_START <= hora_utc < cfg.SESSION_NY_END:
        ativas.add("new_york")
    if hora_utc >= 22 or hora_utc < cfg.SESSION_ASIAN_END:
        ativas.add("asian")
    return frozenset(ativas)


# ──────────────────────────────────────────────────────────────
# CONTRATO BASE
# ──────────────────────────────────────────────────────────────
class FiltroBase(ABC):
    @abstractmethod
    def executar(self, candidato: CandidatoInfo) -> Optional[CandidatoInfo]:
        ...


# ──────────────────────────────────────────────────────────────
# FILTROS BARATOS (sem chamadas de dados de mercado)
# ──────────────────────────────────────────────────────────────
class FiltroExoticos(FiltroBase):
    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.category == "Exotics":
            log.debug("SKIP Exotic: %s", c.symbol)
            return None
        return c


class FiltroSessao(FiltroBase):
    """
    Bloqueia pares fora do horário de liquidez das suas moedas.
    Cripto opera 24/7 — passa diretamente.
    """

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.category == "Crypto":
            return c
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


# ──────────────────────────────────────────────────────────────
# FILTRO DE SPREAD
# ──────────────────────────────────────────────────────────────
_SPREAD_LIMITS: Dict[str, float] = {
    "Majors":  cfg.SPREAD_MAX_MAJORS,
    "Minors":  cfg.SPREAD_MAX_MINORS,
    "Exotics": cfg.SPREAD_MAX_MINORS,
    "Crypto":  cfg.SPREAD_MAX_CRYPTO,
}


class FiltroSpread(FiltroBase):
    """
    Descarta se spread atual excede o limite da categoria ou 20% do SL.
    Preenche c.spread_pips nos candidatos aprovados.
    """

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        tick = mt5.symbol_info_tick(c.symbol)
        if tick is None or tick.ask == 0 or tick.bid == 0:
            log.debug("SKIP sem tick: %s", c.symbol)
            return None

        spread_pips = (tick.ask - tick.bid) / c.pip_size
        max_spread  = _SPREAD_LIMITS.get(c.category, cfg.SPREAD_MAX_MINORS)

        if spread_pips > max_spread:
            log.debug("SKIP spread %s (%s): %.2fp > %.2fp",
                      c.symbol, c.category, spread_pips, max_spread)
            return None

        if c.sl_pct is not None:
            mid_price   = (tick.ask + tick.bid) / 2
            eff_sl_pips = max(1, round(mid_price * c.sl_pct / c.pip_size))
        else:
            eff_sl_pips = c.sl_pips

        if (spread_pips / eff_sl_pips) > cfg.SPREAD_MAX_PCT_OF_SL:
            log.debug("SKIP spread/SL %s: %.1f%%", c.symbol, spread_pips / eff_sl_pips * 100)
            return None

        c.spread_pips = round(spread_pips, 2)
        return c


# ──────────────────────────────────────────────────────────────
# FILTRO DE INDICADORES (pesado — só executa após os filtros baratos)
# ──────────────────────────────────────────────────────────────
class FiltroIndicadores(FiltroBase):
    """
    Calcula EMA, RSI, MACD e EMA H1 usando os parâmetros do perfil do símbolo.
    Preenche c.score, c.direction e c.criterios.
    """

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        p = c.profile
        df_m5 = get_bars(c.symbol, cfg.TF_M5, cfg.BARS_ENTRY)
        df_h1 = get_bars(c.symbol, cfg.TF_H1, cfg.BARS_H1)
        if df_m5 is None or df_h1 is None:
            return None

        close_m5 = df_m5["close"].values
        close_h1 = df_h1["close"].values

        ema_fast               = calc_ema(close_m5, p.ema_fast)
        ema_slow               = calc_ema(close_m5, p.ema_slow)
        rsi                    = calc_rsi(close_m5, p.rsi_period)
        macd_line, sig_line, _ = calc_macd(close_m5, cfg.MACD_FAST, cfg.MACD_SLOW, cfg.MACD_SIGNAL)
        ema_h1                 = calc_ema(close_h1, cfg.EMA_TREND_H1)

        idx = -2  # último candle fechado
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
        near       = (abs(ef - es) / c.pip_size) < p.ema_crossover_thr

        if cross_up:
            c1 = "BUY"
        elif cross_down:
            c1 = "SELL"
        elif converging and near:
            c1 = "BUY" if ef < es else "SELL"
        else:
            c1 = "NEUTRAL"

        # C2: RSI na faixa correta
        if cfg.RSI_BUY_MIN <= rsi_val <= cfg.RSI_BUY_MAX:
            c2 = "BUY"
        elif cfg.RSI_SELL_MIN <= rsi_val <= cfg.RSI_SELL_MAX:
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


# ──────────────────────────────────────────────────────────────
# FILTRO DE VALIDAÇÃO DE ENTRADA
# ──────────────────────────────────────────────────────────────
class FiltroValidacaoEntrada(FiltroBase):
    """
    Exige score >= profile.score_min.

    score_min=4 → todos os 4 critérios alinhados (padrão estrito)
    score_min=3 → 3 critérios alinhados (permissivo)

    Quando score_min=4 e score=3: log WARNING sem entrada.
    """

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.direction == "NEUTRAL":
            return None

        if c.score >= c.profile.score_min:
            return c

        if c.score == 3 and c.profile.score_min == 4:
            cr = c.criterios
            log.warning(
                "[ALERTA] %s score=3 dir=%s spread=%.1fp"
                " | c1=%s c2=%s c3=%s c4=%s — aguardando critério faltante",
                c.symbol, c.direction, c.spread_pips,
                cr["c1"], cr["c2"], cr["c3"], cr["c4"],
            )
        return None


# ──────────────────────────────────────────────────────────────
# FILTROS DINÂMICOS (reconstruídos a cada entrada)
# ──────────────────────────────────────────────────────────────
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
    """Bloqueia se o símbolo já atingiu cfg.FOREX_MAX_POS_PER_SYMBOL."""

    def __init__(self, open_positions: list) -> None:
        self._positions = open_positions

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        count = sum(1 for p in self._positions if p.symbol == c.symbol)
        if count >= cfg.FOREX_MAX_POS_PER_SYMBOL:
            log.debug("%s: limite por símbolo atingido (%d).", c.symbol, count)
            return None
        return c


# ──────────────────────────────────────────────────────────────
# PIPELINE
# ──────────────────────────────────────────────────────────────
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
