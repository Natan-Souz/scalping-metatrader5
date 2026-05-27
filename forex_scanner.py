#!/usr/bin/env python3
"""
Forex Scanner Multi-Par — Triple Confirmation | MetaTrader5
Monitora todos os pares forex disponíveis e prioriza entradas via scoring 0–4.
"""

import time
import sys
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Filtro de spread (em pips)
SPREAD_MAX_MAJORS        = 2.5
SPREAD_MAX_MINORS        = 4.0
SPREAD_MAX_PCT_OF_SL     = 0.20   # spread não pode exceder 20% do SL

# Indicadores M5
EMA_FAST                 = 9
EMA_SLOW                 = 21
EMA_CROSSOVER_PIPS_THR   = 3.0   # distância < N pips para sinal de pré-crossover
RSI_PERIOD               = 7
RSI_BUY_MIN              = 50
RSI_BUY_MAX              = 70
RSI_SELL_MIN             = 30
RSI_SELL_MAX             = 50
MACD_FAST                = 12
MACD_SLOW                = 26
MACD_SIGNAL              = 9

# Filtro de tendência H1
EMA_TREND_H1             = 50

# Timeframes
TF_M5 = mt5.TIMEFRAME_M5
TF_H1 = mt5.TIMEFRAME_H1

# Gestão de risco
SL_PIPS                  = 12
TP_RATIO                 = 2.0    # RR 1:2 → TP = 24 pips
RISK_PCT                 = 0.01   # 1% do capital por trade

# Controle de posições
MAX_TOTAL_POSITIONS      = 3
MAX_POSITIONS_PER_SYMBOL = 1

# Operacional
LOOP_SECONDS             = 15
MAGIC                    = 654321
LOG_FILE                 = "forex_scanner.log"
BARS_M5                  = 300
BARS_H1                  = 150

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
# INDICADORES (cálculo manual)
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
    """Inicializa MT5 e loga informações da conta."""
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
    """Busca `count` candles e retorna DataFrame."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        log.debug("Sem dados: %s tf=%d", symbol, timeframe)
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_pip_info(symbol: str) -> Tuple[float, float]:
    """
    Retorna (pip_size, pip_value_por_lote).
    pip_value = (pip_size / tick_size) * tick_value
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol info não encontrado: {symbol}")
    pip_size   = info.point * 10
    tick_size  = info.trade_tick_size
    tick_value = info.trade_tick_value
    if tick_size > 0:
        pip_value = (pip_size / tick_size) * tick_value
    else:
        pip_value = info.trade_contract_size * pip_size
    return pip_size, pip_value


def calc_lot(capital: float, pip_value: float, symbol: str) -> float:
    """
    Calcula lote: (capital × RISK_PCT) / (SL_PIPS × pip_value).
    Respeita volume_min, volume_max e volume_step do símbolo.
    """
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
    symbol: str,
    order_type: int,
    lot: float,
    price: float,
    sl: float,
    tp: float,
    comment: str = "",
) -> bool:
    """Envia ordem a mercado com SL/TP usando ORDER_FILLING_IOC, deviation=10."""
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
        symbol,
        "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL",
        lot, price, sl, tp, result.order,
    )
    return True


# ============================================================
# DESCOBERTA DE SÍMBOLOS FOREX
# ============================================================
def discover_forex_symbols() -> List[Dict[str, Any]]:
    """
    Retorna lista de dicts {symbol, category, pip_size, pip_value} para
    todos os pares forex (Majors, Minors, Exotics) disponíveis na corretora.
    Filtra: somente path que contém "forex", trade_mode == FULL.
    Exclui: Crypto, Metals, Indices, Commodities, CFD.
    """
    all_symbols = mt5.symbols_get()
    if not all_symbols:
        log.warning("Nenhum símbolo retornado pelo MT5.")
        return []

    log.debug("Total de símbolos no MT5: %d", len(all_symbols))

    EXCLUDED = {"crypto", "metals", "indices", "commodities", "cfd"}
    result   = []
    skipped_path = skipped_excluded = skipped_mode = 0

    for sym in all_symbols:
        # Normaliza separadores e remove barras iniciais/finais
        path       = sym.path.replace("\\", "/").strip("/")
        path_lower = path.lower()

        # Aceita qualquer path que contenha "forex" (ex: "Forex/Majors", "Forex", "/Forex/Minors")
        if "forex" not in path_lower:
            skipped_path += 1
            continue
        if any(kw in path_lower for kw in EXCLUDED):
            skipped_excluded += 1
            continue
        if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            skipped_mode += 1
            continue

        # Subcategoria pelo path; fallback → Minors
        if "major" in path_lower:
            category = "Majors"
        elif "minor" in path_lower:
            category = "Minors"
        elif "exotic" in path_lower:
            category = "Exotics"
        else:
            category = "Minors"

        # Garantir visibilidade no Market Watch para obter ticks
        mt5.symbol_select(sym.name, True)

        try:
            pip_size, pip_value = get_pip_info(sym.name)
        except RuntimeError:
            continue

        if pip_size <= 0 or pip_value <= 0:
            continue

        result.append({
            "symbol":    sym.name,
            "category":  category,
            "pip_size":  pip_size,
            "pip_value": pip_value,
        })

    log.debug(
        "Descartados: sem 'forex' no path=%d | excluídos=%d | trade_mode≠FULL=%d",
        skipped_path, skipped_excluded, skipped_mode,
    )

    # Diagnóstico visível no terminal quando nenhum par é encontrado
    if not result:
        unique_paths = sorted({s.path for s in all_symbols})
        log.warning(
            "Nenhum símbolo forex encontrado após filtros! "
            "Paths disponíveis na corretora (%d únicos): %s",
            len(unique_paths),
            unique_paths[:20],
        )

    log.debug("Símbolos forex descobertos: %d", len(result))
    return result


# ============================================================
# FILTRO DE SPREAD
# ============================================================
def filter_by_spread(symbols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Descarta símbolos cujo spread atual excede o limite da categoria ou
    20% do SL em pips. Exotics são sempre descartados.
    Retorna lista filtrada com spread_pips adicionado a cada entry.
    """
    result = []

    for s in symbols:
        sym_name = s["symbol"]
        category = s["category"]
        pip_size = s["pip_size"]

        if category == "Exotics":
            log.debug("SPREAD SKIP (Exotic): %s", sym_name)
            continue

        tick = mt5.symbol_info_tick(sym_name)
        if tick is None or tick.ask == 0 or tick.bid == 0:
            log.debug("SPREAD SKIP (sem tick): %s", sym_name)
            continue

        spread_pips = (tick.ask - tick.bid) / pip_size

        max_spread = SPREAD_MAX_MAJORS if category == "Majors" else SPREAD_MAX_MINORS
        if spread_pips > max_spread:
            log.debug(
                "SPREAD SKIP (%s): %s spread=%.2fp > %.2fp",
                category, sym_name, spread_pips, max_spread,
            )
            continue

        if (spread_pips / SL_PIPS) > SPREAD_MAX_PCT_OF_SL:
            log.debug(
                "SPREAD SKIP (rel.SL): %s spread/SL=%.1f%%",
                sym_name, spread_pips / SL_PIPS * 100,
            )
            continue

        entry = dict(s)
        entry["spread_pips"] = round(spread_pips, 2)
        result.append(entry)

    return result


# ============================================================
# CÁLCULO DE SCORE
# ============================================================
def calc_score(sym_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Avalia os 4 critérios Triple Confirmation no candle fechado (índice -2).

    Critério 1 — EMA crossover ou proximidade (max 1 pt):
      +1 se EMA9 cruzou EMA21 no candle atual
      +1 se distância está diminuindo nos últimos 3 candles E dist < EMA_CROSSOVER_PIPS_THR

    Critério 2 — RSI na faixa: BUY [50-70] | SELL [30-50]
    Critério 3 — MACD alinhado: BUY = MACD > Signal | SELL = MACD < Signal
    Critério 4 — H1 filter: BUY = preço > EMA50 H1 | SELL = preço < EMA50 H1

    Direção: maioria dos critérios não-neutros. Empate → NEUTRAL.
    Score: quantidade de critérios alinhados com a direção vencedora.
    """
    symbol   = sym_info["symbol"]
    pip_size = sym_info["pip_size"]

    df_m5 = get_bars(symbol, TF_M5, BARS_M5)
    df_h1 = get_bars(symbol, TF_H1, BARS_H1)
    if df_m5 is None or df_h1 is None:
        return None

    close_m5 = df_m5["close"].values
    close_h1 = df_h1["close"].values

    ema_fast              = calc_ema(close_m5, EMA_FAST)
    ema_slow              = calc_ema(close_m5, EMA_SLOW)
    rsi                   = calc_rsi(close_m5, RSI_PERIOD)
    macd_line, sig_line, _ = calc_macd(close_m5, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    ema_h1                = calc_ema(close_h1, EMA_TREND_H1)

    idx = -2  # último candle fechado

    ef      = ema_fast[idx]
    es      = ema_slow[idx]
    ef_p1   = ema_fast[idx - 1]
    es_p1   = ema_slow[idx - 1]
    ef_p2   = ema_fast[idx - 2]
    es_p2   = ema_slow[idx - 2]
    rsi_val  = rsi[idx]
    macd_val = macd_line[idx]
    sig_val  = sig_line[idx]
    h1_ema   = ema_h1[-1]
    price    = close_m5[idx]

    if any(
        np.isnan(v) for v in [ef, es, ef_p1, es_p1, ef_p2, es_p2, rsi_val, macd_val, sig_val, h1_ema]
    ):
        log.debug("%s: NaN nos indicadores — ignorado.", symbol)
        return None

    # --- Critério 1: EMA crossover ou pré-crossover ---
    cross_up   = ef_p1 < es_p1 and ef > es
    cross_down = ef_p1 > es_p1 and ef < es

    dist_curr = abs(ef - es)
    dist_p1   = abs(ef_p1 - es_p1)
    dist_p2   = abs(ef_p2 - es_p2)
    converging = dist_curr < dist_p1 < dist_p2
    near       = (dist_curr / pip_size) < EMA_CROSSOVER_PIPS_THR

    if cross_up:
        c1 = "BUY"
    elif cross_down:
        c1 = "SELL"
    elif converging and near:
        # EMA9 abaixo do EMA21 e convergindo → aproxima de cima → sinal de BUY iminente
        c1 = "BUY" if ef < es else "SELL"
    else:
        c1 = "NEUTRAL"

    # --- Critério 2: RSI ---
    if RSI_BUY_MIN <= rsi_val <= RSI_BUY_MAX:
        c2 = "BUY"
    elif RSI_SELL_MIN <= rsi_val <= RSI_SELL_MAX:
        c2 = "SELL"
    else:
        c2 = "NEUTRAL"

    # --- Critério 3: MACD ---
    if macd_val > sig_val:
        c3 = "BUY"
    elif macd_val < sig_val:
        c3 = "SELL"
    else:
        c3 = "NEUTRAL"

    # --- Critério 4: Filtro H1 ---
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
        direction = "BUY"
        score     = buy_count
    elif sell_count > buy_count:
        direction = "SELL"
        score     = sell_count
    else:
        direction = "NEUTRAL"
        score     = max(buy_count, sell_count)

    log.debug(
        "%s | score=%d dir=%-7s | c1=%-7s c2=%-7s c3=%-7s c4=%-7s | "
        "RSI=%.1f MACD=%.5f SIG=%.5f",
        symbol, score, direction, c1, c2, c3, c4, rsi_val, macd_val, sig_val,
    )

    return {
        "symbol":      symbol,
        "score":       score,
        "direction":   direction,
        "criterios":   criterios,
        "spread_pips": sym_info.get("spread_pips", 0.0),
        "category":    sym_info["category"],
        "pip_size":    pip_size,
        "pip_value":   sym_info["pip_value"],
    }


# ============================================================
# CONTROLE DE CORRELAÇÃO
# ============================================================
def get_currencies(symbol: str) -> set:
    """Extrai o par de moedas dos primeiros 6 caracteres do símbolo."""
    clean = symbol[:6] if len(symbol) >= 6 else symbol
    return {clean[:3].upper(), clean[3:6].upper()}


def check_correlation(candidate: str, open_positions) -> bool:
    """
    Retorna True (bloquear) se alguma posição aberta compartilha
    moeda base ou cotada com o candidato.
    Ex.: EUR/USD aberto → bloqueia EUR/JPY (EUR), GBP/USD (USD).
    """
    cand_currencies = get_currencies(candidate)
    for pos in open_positions:
        shared = cand_currencies & get_currencies(pos.symbol)
        if shared:
            log.debug(
                "CORRELAÇÃO: %s bloqueado por %s (moeda: %s)",
                candidate, pos.symbol, shared,
            )
            return True
    return False


# ============================================================
# LOOP PRINCIPAL DO SCANNER
# ============================================================
def run_scanner(capital: float) -> None:
    log.info("=" * 70)
    log.info("Forex Scanner Multi-Par iniciando | Capital=%.2f USD", capital)
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
        log.debug("=== Ciclo %d ===", iteration)

        try:
            # 1. Descobrir e filtrar símbolos
            all_forex = discover_forex_symbols()
            filtered  = filter_by_spread(all_forex)

            # 2. Calcular scores
            scored = []
            for sym_info in filtered:
                result = calc_score(sym_info)
                if result is not None:
                    scored.append(result)

            # 3. Ordenar: score desc, spread asc (desempate)
            scored.sort(key=lambda x: (-x["score"], x["spread_pips"]))

            # 4. Separar por nível de score (excluir NEUTRAL da fila de ação)
            actionable = [s for s in scored if s["score"] == 4 and s["direction"] != "NEUTRAL"]
            alerts     = [s for s in scored if s["score"] == 3 and s["direction"] != "NEUTRAL"]

            # 5. Logar alertas score=3 (WARNING)
            for alert in alerts:
                log.warning(
                    "[ALERTA] %s score=%d dir=%s spread=%.1fp cat=%s "
                    "| c1=%s c2=%s c3=%s c4=%s — aguardando critério faltante",
                    alert["symbol"], alert["score"], alert["direction"],
                    alert["spread_pips"], alert["category"],
                    alert["criterios"]["c1"], alert["criterios"]["c2"],
                    alert["criterios"]["c3"], alert["criterios"]["c4"],
                )

            # 6. Obter posições abertas pelo magic number
            all_open  = mt5.positions_get() or []
            magic_pos = [p for p in all_open if p.magic == MAGIC]
            entries_done = 0

            if len(magic_pos) >= MAX_TOTAL_POSITIONS:
                log.debug(
                    "Limite global atingido (%d/%d posições) — sem novas entradas.",
                    len(magic_pos), MAX_TOTAL_POSITIONS,
                )
            else:
                for candidate in actionable:
                    if len(magic_pos) >= MAX_TOTAL_POSITIONS:
                        break

                    sym       = candidate["symbol"]
                    direction = candidate["direction"]

                    # Verificar limite por símbolo
                    sym_count = sum(1 for p in magic_pos if p.symbol == sym)
                    if sym_count >= MAX_POSITIONS_PER_SYMBOL:
                        log.debug("%s: limite por símbolo atingido (%d).", sym, sym_count)
                        continue

                    # Verificar correlação
                    if check_correlation(sym, magic_pos):
                        log.info("CORRELAÇÃO BLOQUEOU: %s", sym)
                        continue

                    # Calcular lote
                    lot = calc_lot(capital, candidate["pip_value"], sym)
                    if lot <= 0:
                        log.warning("%s: lote inválido (%.2f) — pulando.", sym, lot)
                        continue

                    # Obter preço atual
                    tick = mt5.symbol_info_tick(sym)
                    if tick is None:
                        log.warning("%s: sem tick disponível.", sym)
                        continue

                    pip_size = candidate["pip_size"]

                    if direction == "BUY":
                        price  = tick.ask
                        sl     = round(price - SL_PIPS * pip_size, 5)
                        tp     = round(price + SL_PIPS * TP_RATIO * pip_size, 5)
                        otype  = mt5.ORDER_TYPE_BUY
                    else:
                        price  = tick.bid
                        sl     = round(price + SL_PIPS * pip_size, 5)
                        tp     = round(price - SL_PIPS * TP_RATIO * pip_size, 5)
                        otype  = mt5.ORDER_TYPE_SELL

                    comment = f"SCAN_{direction}_{sym}"

                    log.info(
                        "CANDIDATO score=4 | %s %s | lote=%.2f | spread=%.2fp | "
                        "c1=%s c2=%s c3=%s c4=%s",
                        sym, direction, lot, candidate["spread_pips"],
                        candidate["criterios"]["c1"], candidate["criterios"]["c2"],
                        candidate["criterios"]["c3"], candidate["criterios"]["c4"],
                    )

                    if place_order(sym, otype, lot, price, sl, tp, comment):
                        entries_done += 1
                        # Atualiza lista local para verificar correlação no próximo candidato
                        magic_pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]

            # 7. Resumo do ciclo
            log.info(
                "[SCAN] %d pares | %d passaram spread | %d score≥3 | %d entrada(s) executada(s)",
                len(all_forex), len(filtered), len(alerts) + len(actionable), entries_done,
            )

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

    run_scanner(capital_usd)
