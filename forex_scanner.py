#!/usr/bin/env python3
"""
Forex Scanner Multi-Par — Triple Confirmation | MetaTrader5

Padrões de arquitetura:
  - State Pattern        : EstadoAguardandoSinal / EstadoGerenciandoPosicao
  - Chain of Responsibility: pipeline de filtros encadeados por símbolo
"""

from __future__ import annotations

import time
import sys
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

# ============================================================
# CONFIGURAÇÕES
# ============================================================
SPREAD_MAX_MAJORS        = 2.5
SPREAD_MAX_MINORS        = 4.0
SPREAD_MAX_PCT_OF_SL     = 0.20

EMA_FAST                 = 9
EMA_SLOW                 = 21
EMA_CROSSOVER_PIPS_THR   = 3.0
RSI_PERIOD               = 7
RSI_BUY_MIN              = 50
RSI_BUY_MAX              = 70
RSI_SELL_MIN             = 30
RSI_SELL_MAX             = 50
MACD_FAST                = 12
MACD_SLOW                = 26
MACD_SIGNAL              = 9
EMA_TREND_H1             = 50

TF_M5 = mt5.TIMEFRAME_M5
TF_H1 = mt5.TIMEFRAME_H1

SL_PIPS                  = 12
TP_RATIO                 = 2.0
RISK_PCT                 = 0.01

MAX_TOTAL_POSITIONS      = 3
MAX_POSITIONS_PER_SYMBOL = 1

LOOP_SECONDS             = 15
MAGIC                    = 654321
LOG_FILE                 = "forex_scanner.log"
BARS_M5                  = 300
BARS_H1                  = 150

# Sessões de mercado (horário UTC — imune a DST do servidor do broker)
SESSION_LONDON_START     = 7    # abertura Londres
SESSION_LONDON_END       = 17   # fechamento Londres
SESSION_NY_START         = 13   # abertura Nova York
SESSION_NY_END           = 22   # fechamento Nova York
SESSION_ASIAN_END        = 9    # fechamento Ásia (abre às 22h do dia anterior)

# ============================================================
# LOGGING
# ============================================================
def setup_logging() -> logging.Logger:
    fmt     = "%(asctime)s [%(levelname)-8s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logger  = logging.getLogger("forex_scanner")
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(fmt, datefmt))

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt, datefmt))

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


log = setup_logging()


# ============================================================
# MODELO DE DADOS
# ============================================================
@dataclass
class CandidatoInfo:
    """Representa um símbolo forex em avaliação, enriquecido a cada filtro."""
    symbol:      str
    category:    str
    pip_size:    float
    pip_value:   float
    spread_pips: float                = 0.0
    score:       int                  = 0
    direction:   str                  = "NEUTRAL"
    criterios:   Dict[str, str]       = field(default_factory=dict)


# ============================================================
# INDICADORES (cálculo manual com numpy — sem TA-Lib)
# ============================================================
def calc_ema(prices: np.ndarray, period: int) -> np.ndarray:
    """EMA pelo método multiplicador (k = 2 / (period+1))."""
    result = np.full(len(prices), np.nan)
    if len(prices) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(prices[:period])
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k)
    return result


def calc_rsi(prices: np.ndarray, period: int) -> np.ndarray:
    """RSI pelo método Wilder (suavização exponencial modificada)."""
    result = np.full(len(prices), np.nan)
    if len(prices) < period + 1:
        return result
    deltas   = np.diff(prices)
    gains    = np.where(deltas > 0, deltas, 0.0)
    losses   = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    result[period] = 100.0 if avg_loss == 0.0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i + 1] = 100.0 if avg_loss == 0.0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return result


def calc_macd(
    prices: np.ndarray, fast: int, slow: int, signal: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Retorna (macd_line, signal_line, histogram)."""
    ema_fast    = calc_ema(prices, fast)
    ema_slow    = calc_ema(prices, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = np.full(len(prices), np.nan)
    valid_mask  = ~np.isnan(macd_line)
    if np.sum(valid_mask) >= signal:
        valid_idxs = np.where(valid_mask)[0]
        sig_vals   = calc_ema(macd_line[valid_mask], signal)
        for j, idx in enumerate(valid_idxs):
            signal_line[idx] = sig_vals[j]
    return macd_line, signal_line, macd_line - signal_line


# ============================================================
# FUNÇÕES MT5
# ============================================================
def connect() -> bool:
    if not mt5.initialize():
        log.error("Falha ao inicializar MT5: %s", mt5.last_error())
        return False
    info = mt5.account_info()
    if info is None:
        log.error("Sem informações da conta.")
        mt5.shutdown()
        return False
    log.info(
        "Conectado | Login: %s | Servidor: %s | Saldo: %.2f %s | Alavancagem: 1:%d",
        info.login, info.server, info.balance, info.currency, info.leverage,
    )
    return True


def get_bars(symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        log.debug("Sem dados: %s tf=%d", symbol, timeframe)
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_pip_info(symbol: str) -> Tuple[float, float]:
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol info não encontrado: {symbol}")
    pip_size   = info.point * 10
    tick_size  = info.trade_tick_size
    tick_value = info.trade_tick_value
    pip_value  = (pip_size / tick_size) * tick_value if tick_size > 0 else info.trade_contract_size * pip_size
    return pip_size, pip_value


def calc_lot(capital: float, pip_value: float, symbol: str) -> float:
    if pip_value <= 0:
        return 0.01
    raw_lot = (capital * RISK_PCT) / (SL_PIPS * pip_value)
    sym = mt5.symbol_info(symbol)
    if sym:
        step    = sym.volume_step if sym.volume_step > 0 else 0.01
        raw_lot = round(raw_lot / step) * step
        raw_lot = max(sym.volume_min, min(sym.volume_max, raw_lot))
    return round(raw_lot, 2)


def place_order(
    symbol: str, order_type: int, lot: float,
    price: float, sl: float, tp: float, comment: str = "",
) -> bool:
    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    10,
        "magic":        MAGIC,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        log.error("[%s] order_send None | erro: %s", symbol, mt5.last_error())
        return False
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error("[%s] Ordem rejeitada | retcode=%d | %s", symbol, result.retcode, result.comment)
        return False
    log.info(
        "ENTRADA | %s %s | lote=%.2f | price=%.5f | sl=%.5f | tp=%.5f | ticket=%d",
        symbol, "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL",
        lot, price, sl, tp, result.order,
    )
    return True


def discover_forex_symbols() -> List[CandidatoInfo]:
    """Descobre todos os pares forex disponíveis e retorna como CandidatoInfo."""
    all_symbols = mt5.symbols_get()
    if not all_symbols:
        log.warning("Nenhum símbolo retornado pelo MT5.")
        return []

    EXCLUDED = {"crypto", "metals", "indices", "commodities", "cfd"}
    result: List[CandidatoInfo] = []
    skipped_path = skipped_excluded = skipped_mode = 0

    for sym in all_symbols:
        path       = sym.path.replace("\\", "/").strip("/")
        path_lower = path.lower()

        if "forex" not in path_lower:
            skipped_path += 1
            continue
        if any(kw in path_lower for kw in EXCLUDED):
            skipped_excluded += 1
            continue
        if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            skipped_mode += 1
            continue

        if "major" in path_lower:
            category = "Majors"
        elif "exotic" in path_lower:
            category = "Exotics"
        else:
            category = "Minors"

        mt5.symbol_select(sym.name, True)

        try:
            pip_size, pip_value = get_pip_info(sym.name)
        except RuntimeError:
            continue

        if pip_size <= 0 or pip_value <= 0:
            continue

        result.append(CandidatoInfo(
            symbol=sym.name,
            category=category,
            pip_size=pip_size,
            pip_value=pip_value,
        ))

    log.debug(
        "Descartados: path=%d | excluídos=%d | trade_mode≠FULL=%d",
        skipped_path, skipped_excluded, skipped_mode,
    )

    if not result:
        unique_paths = sorted({s.path for s in all_symbols})
        log.warning(
            "Nenhum símbolo forex após filtros! Paths disponíveis (%d): %s",
            len(unique_paths), unique_paths[:20],
        )

    log.debug("Símbolos forex descobertos: %d", len(result))
    return result


def get_currencies(symbol: str) -> set:
    """Extrai o par de moedas dos primeiros 6 caracteres do símbolo."""
    clean = symbol[:6] if len(symbol) >= 6 else symbol
    return {clean[:3].upper(), clean[3:6].upper()}


def get_magic_positions() -> list:
    """Retorna lista de posições abertas pelo magic number deste scanner."""
    return [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]


# Mapeamento: moeda → sessões em que tem liquidez primária
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
    if hora_utc >= 22 or hora_utc < SESSION_ASIAN_END:   # janela overnight
        ativas.add("asian")
    return frozenset(ativas)


# ============================================================
# PIPELINE — CHAIN OF RESPONSIBILITY
# ============================================================
class FiltroBase(ABC):
    """Contrato de todos os filtros do pipeline."""
    @abstractmethod
    def executar(self, candidato: CandidatoInfo) -> Optional[CandidatoInfo]:
        ...


class FiltroExoticos(FiltroBase):
    """Descarta Exotics antes de qualquer chamada ao MT5."""
    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.category == "Exotics":
            log.debug("SKIP Exotic: %s", c.symbol)
            return None
        return c


class FiltroSessao(FiltroBase):
    """
    Bloqueia pares fora do horário de liquidez das suas moedas.

    Lógica: um par é negociável se CADA moeda possui ao menos uma sessão
    ativa no momento. Moeda não mapeada (exótica remanescente) → permissivo.

    Exemplos de janelas resultantes (UTC):
      EUR/USD → 07h–22h  (Londres + NY)
      USD/JPY → 13h–22h  (só overlap NY)
      AUD/NZD → 22h–09h + 13h–22h  (Ásia + NY)
      EUR/JPY → 13h–22h  (só overlap NY — EUR tem Londres, JPY não)
    """
    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        hora_utc = datetime.now(timezone.utc).hour
        ativas   = _sessoes_ativas(hora_utc)

        for moeda in get_currencies(c.symbol):
            sessoes_moeda = _SESSIONS_BY_CURRENCY.get(moeda, ativas)  # desconhecida → permissivo
            if not (sessoes_moeda & ativas):
                log.debug(
                    "SKIP sessão %s | UTC %02dh | %s fora de sessão (ativas=%s)",
                    c.symbol, hora_utc, moeda, set(ativas),
                )
                return None
        return c


class FiltroSpread(FiltroBase):
    """Descarta se spread excede o limite da categoria ou 20% do SL."""
    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        tick = mt5.symbol_info_tick(c.symbol)
        if tick is None or tick.ask == 0 or tick.bid == 0:
            log.debug("SKIP sem tick: %s", c.symbol)
            return None

        spread_pips = (tick.ask - tick.bid) / c.pip_size
        max_spread  = SPREAD_MAX_MAJORS if c.category == "Majors" else SPREAD_MAX_MINORS

        if spread_pips > max_spread:
            log.debug("SKIP spread %s: %.2fp > %.2fp", c.symbol, spread_pips, max_spread)
            return None
        if (spread_pips / SL_PIPS) > SPREAD_MAX_PCT_OF_SL:
            log.debug("SKIP spread/SL %s: %.1f%%", c.symbol, spread_pips / SL_PIPS * 100)
            return None

        c.spread_pips = round(spread_pips, 2)
        return c


class FiltroIndicadores(FiltroBase):
    """Busca barras, calcula indicadores e avalia os 4 critérios Triple Confirmation."""
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

        idx = -2  # último candle fechado
        ef, es         = ema_fast[idx],     ema_slow[idx]
        ef_p1, es_p1   = ema_fast[idx - 1], ema_slow[idx - 1]
        ef_p2, es_p2   = ema_fast[idx - 2], ema_slow[idx - 2]
        rsi_val        = rsi[idx]
        macd_val       = macd_line[idx]
        sig_val        = sig_line[idx]
        h1_ema         = ema_h1[-1]
        price          = close_m5[idx]

        if any(np.isnan(v) for v in [ef, es, ef_p1, es_p1, ef_p2, es_p2,
                                      rsi_val, macd_val, sig_val, h1_ema]):
            log.debug("%s: NaN nos indicadores — ignorado.", c.symbol)
            return None

        # C1: crossover ou pré-crossover convergindo
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

        # C2: RSI na faixa
        if RSI_BUY_MIN <= rsi_val <= RSI_BUY_MAX:
            c2 = "BUY"
        elif RSI_SELL_MIN <= rsi_val <= RSI_SELL_MAX:
            c2 = "SELL"
        else:
            c2 = "NEUTRAL"

        # C3: MACD alinhado com signal
        if macd_val > sig_val:
            c3 = "BUY"
        elif macd_val < sig_val:
            c3 = "SELL"
        else:
            c3 = "NEUTRAL"

        # C4: preço vs EMA50 H1
        if price > h1_ema:
            c4 = "BUY"
        elif price < h1_ema:
            c4 = "SELL"
        else:
            c4 = "NEUTRAL"

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


class FiltroValidacaoEntrada(FiltroBase):
    """
    Exige score = 4: todos os critérios devem alinhar na mesma direção.

    Regra de execução (alinhada ao CLAUDE.md):
      score 4 (C1+C2+C3+C4 na mesma direção) → passa para execução
      score 3 (apenas 3 critérios alinhados)  → WARNING, sem entrada
      score ≤ 2 ou NEUTRAL                    → descartado silenciosamente

    Semântica dos critérios:
      C1 EMA 9/21 crossover  : gatilho de entrada (timing)
      C2 RSI na faixa         : confirmação de momentum (timing)
      C3 MACD > Signal        : confirmação de direção
      C4 Preço vs EMA50 H1    : filtro de tendência macro (obrigatório)
    """
    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        if c.direction == "NEUTRAL":
            return None

        d  = c.direction
        cr = c.criterios

        # Score 4: todos os critérios devem apontar para a mesma direção
        todos_ok = cr["c1"] == d and cr["c2"] == d and cr["c3"] == d and cr["c4"] == d

        if todos_ok:
            return c

        # Score 3: loga alerta mas não opera
        if c.score == 3:
            log.warning(
                "[ALERTA] %s score=3 dir=%s spread=%.1fp cat=%s"
                " | c1=%s c2=%s c3=%s c4=%s — aguardando critério faltante",
                c.symbol, d, c.spread_pips, c.category,
                cr["c1"], cr["c2"], cr["c3"], cr["c4"],
            )

        return None


class FiltroCorrelacao(FiltroBase):
    """Bloqueia entrada se par compartilha moeda base ou cotada com posição aberta."""
    def __init__(self, open_positions: list) -> None:
        self._positions = open_positions

    def executar(self, c: CandidatoInfo) -> Optional[CandidatoInfo]:
        cand_currencies = get_currencies(c.symbol)
        for pos in self._positions:
            shared = cand_currencies & get_currencies(pos.symbol)
            if shared:
                log.debug("CORRELAÇÃO: %s bloqueado por %s (moeda: %s)", c.symbol, pos.symbol, shared)
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


class Pipeline:
    """Executa filtros em cadeia; para imediatamente no primeiro None."""
    def __init__(self, *filtros: FiltroBase) -> None:
        self._filtros = filtros

    def processar(self, candidato: CandidatoInfo) -> Optional[CandidatoInfo]:
        atual: Optional[CandidatoInfo] = candidato
        for filtro in self._filtros:
            atual = filtro.executar(atual)
            if atual is None:
                return None
        return atual


# ============================================================
# STATE PATTERN
# ============================================================
class EstadoBase(ABC):
    @abstractmethod
    def processar(self, robo: ScannerRobot) -> EstadoBase:
        ...


class EstadoAguardandoSinal(EstadoBase):
    """
    Varre o mercado, avalia sinais via pipeline e executa entradas.

    Pipeline estático (construído uma vez por ciclo):
      FiltroExoticos → FiltroSessao → FiltroSpread → FiltroIndicadores → FiltroValidacaoEntrada

    Validação dinâmica (reconstruída após cada entrada para capturar
    posições abertas no mesmo ciclo):
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

        # Fase 1: pipeline estático — avalia todos os símbolos
        candidatos    = discover_forex_symbols()
        static_pipe   = Pipeline(
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

        # Fase 2: validação dinâmica e execução — posições atualizadas a cada entrada
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

            lot = calc_lot(robo.capital, c.pip_value, c.symbol)
            if lot <= 0:
                log.warning("%s: lote inválido (%.2f) — pulando.", c.symbol, lot)
                continue

            tick = mt5.symbol_info_tick(c.symbol)
            if tick is None:
                log.warning("%s: sem tick disponível.", c.symbol)
                continue

            if c.direction == "BUY":
                price = tick.ask
                sl    = round(price - SL_PIPS * c.pip_size, 5)
                tp    = round(price + SL_PIPS * TP_RATIO * c.pip_size, 5)
                otype = mt5.ORDER_TYPE_BUY
            else:
                price = tick.bid
                sl    = round(price + SL_PIPS * c.pip_size, 5)
                tp    = round(price - SL_PIPS * TP_RATIO * c.pip_size, 5)
                otype = mt5.ORDER_TYPE_SELL

            log.info(
                "CANDIDATO score=4 | %s %s | lote=%.2f | spread=%.2fp | c1=%s c2=%s c3=%s c4=%s",
                c.symbol, c.direction, lot, c.spread_pips,
                c.criterios["c1"], c.criterios["c2"], c.criterios["c3"], c.criterios["c4"],
            )

            if place_order(c.symbol, otype, lot, price, sl, tp, f"SCAN_{c.direction}_{c.symbol}"):
                entries_done += 1
                magic_pos = get_magic_positions()  # atualiza para o próximo candidato

        log.info(
            "[SCAN] %d pares | %d passaram filtros | %d entrada(s) executada(s)",
            len(candidatos), len(aprovados), entries_done,
        )

        if len(magic_pos) >= MAX_TOTAL_POSITIONS:
            return EstadoGerenciandoPosicao()
        return self


class EstadoGerenciandoPosicao(EstadoBase):
    """
    Monitora posições abertas. Retorna a EstadoAguardandoSinal
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


# ============================================================
# ROBÔ SCANNER
# ============================================================
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

        mt5.shutdown()
        log.info("Conexão MT5 encerrada. Scanner finalizado.")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
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

    print(f"\n  Capital confirmado  : USD {capital_usd:,.2f}")
    print(f"  Risco por trade     : USD {capital_usd * RISK_PCT:,.2f}")
    print(f"  Score mínimo entrada: 4/4 (Triple Confirmation completa)")
    print()

    ScannerRobot(capital_usd).run()
