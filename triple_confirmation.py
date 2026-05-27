#!/usr/bin/env python3
"""
Triple Confirmation Scalping — EUR/USD | MetaTrader5
Estratégia: EMA 9/21 M5 + RSI 7 + MACD (12,26,9) + EMA 50 H1
"""

import time
import sys
import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

# ============================================================
# CONFIGURAÇÕES
# ============================================================
SYMBOL        = "GBPUSD"
TF_M5         = mt5.TIMEFRAME_M5
TF_H1         = mt5.TIMEFRAME_H1

# Indicadores M5
EMA_FAST      = 9
EMA_SLOW      = 21
RSI_PERIOD    = 7
RSI_BUY_MIN   = 50       # RSI mínimo para BUY
RSI_BUY_MAX   = 70       # RSI máximo para BUY
RSI_SELL_MIN  = 30       # RSI mínimo para SELL
RSI_SELL_MAX  = 50       # RSI máximo para SELL
MACD_FAST     = 12
MACD_SLOW     = 26
MACD_SIGNAL   = 9

# Filtro de tendência H1
EMA_TREND     = 50

# Gestão de risco
RISK_PCT      = 0.01     # 1% do capital por trade
SL_PIPS       = 12
TP_RATIO      = 2.0      # RR 1:2 → TP = 24 pips

# Operacional
LOOP_SECONDS  = 15
MAX_POSITIONS = 1
MAGIC         = 123456
LOG_FILE      = "triple_confirmation.log"

# Quantidade de candles para cálculo dos indicadores
BARS_M5       = 300
BARS_H1       = 150

# ============================================================
# LOGGING
# ============================================================
def setup_logging() -> logging.Logger:
    fmt     = "%(asctime)s [%(levelname)-8s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger("triple_conf")
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

    deltas = np.diff(prices)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Médias iniciais via SMA
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    if avg_loss == 0.0:
        result[period] = 100.0
    else:
        result[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            result[i + 1] = 100.0
        else:
            result[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    return result


def calc_macd(
    prices: np.ndarray, fast: int, slow: int, signal: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Retorna (macd_line, signal_line, histogram)."""
    ema_fast  = calc_ema(prices, fast)
    ema_slow  = calc_ema(prices, slow)
    macd_line = ema_fast - ema_slow

    signal_line = np.full(len(prices), np.nan)
    valid_mask  = ~np.isnan(macd_line)

    if np.sum(valid_mask) >= signal:
        valid_idxs = np.where(valid_mask)[0]
        sig_vals   = calc_ema(macd_line[valid_mask], signal)
        for j, idx in enumerate(valid_idxs):
            signal_line[idx] = sig_vals[j]

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ============================================================
# FUNÇÕES MT5
# ============================================================
def connect() -> bool:
    """Inicializa o MT5 e loga informações da conta."""
    if not mt5.initialize():
        log.error("Falha ao inicializar MT5: %s", mt5.last_error())
        return False
    info = mt5.account_info()
    if info is None:
        log.error("Não foi possível obter informações da conta.")
        mt5.shutdown()
        return False
    log.info(
        "Conectado | Login: %s | Servidor: %s | Saldo: %.2f %s | Alavancagem: 1:%d",
        info.login, info.server, info.balance, info.currency, info.leverage,
    )
    return True


def get_bars(symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
    """Busca `count` candles do MT5 e retorna DataFrame."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        log.warning("Sem dados para %s tf=%s", symbol, timeframe)
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_pip_info(symbol: str) -> Tuple[float, float]:
    """
    Retorna (pip_size, pip_value_por_lote) para o símbolo.
    Para pares XYZ/USD de 5 decimais: pip_size = point*10; pip_value = contract * pip_size.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol info não encontrado: {symbol}")
    pip_size          = info.point * 10
    pip_value_per_lot = info.trade_contract_size * pip_size
    return pip_size, pip_value_per_lot


def calc_lot(capital: float, pip_value_per_lot: float) -> float:
    """
    Calcula o tamanho do lote conforme gestão de risco:
        lote = (capital × RISK_PCT) / (SL_PIPS × pip_value_por_lote)
    """
    risk_amount = capital * RISK_PCT
    raw_lot     = risk_amount / (SL_PIPS * pip_value_per_lot)

    sym = mt5.symbol_info(SYMBOL)
    if sym:
        step    = sym.volume_step
        raw_lot = round(raw_lot / step) * step
        raw_lot = max(sym.volume_min, min(sym.volume_max, raw_lot))

    return round(raw_lot, 2)


def place_order(
    order_type: int,
    lot: float,
    price: float,
    sl: float,
    tp: float,
    comment: str = "",
) -> bool:
    """Envia ordem a mercado com SL/TP usando ORDER_FILLING_IOC."""
    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
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
        log.error("order_send retornou None | erro: %s", mt5.last_error())
        return False
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(
            "Ordem rejeitada | retcode=%d | msg=%s", result.retcode, result.comment
        )
        return False
    log.info(
        "Ordem executada | ticket=%d | vol=%.2f | price=%.5f | sl=%.5f | tp=%.5f",
        result.order, lot, price, sl, tp,
    )
    return True


def count_open_positions() -> int:
    """Conta posições abertas no símbolo com o magic number configurado."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return 0
    return sum(1 for p in positions if p.magic == MAGIC)


# ============================================================
# SINAL TRIPLE CONFIRMATION
# ============================================================
def get_signal() -> Optional[str]:
    """
    Avalia os 4 critérios da Triple Confirmation no candle fechado (índice -2).
    Retorna 'BUY', 'SELL' ou None.

    Critérios BUY  : EMA9 cruza acima EMA21 | RSI [50-70] | MACD > Signal | preço > EMA50 H1
    Critérios SELL : EMA9 cruza abaixo EMA21 | RSI [30-50] | MACD < Signal | preço < EMA50 H1
    """
    df_m5 = get_bars(SYMBOL, TF_M5, BARS_M5)
    df_h1 = get_bars(SYMBOL, TF_H1, BARS_H1)
    if df_m5 is None or df_h1 is None:
        return None

    close_m5 = df_m5["close"].values
    close_h1 = df_h1["close"].values

    # --- Indicadores M5 ---
    ema_fast                    = calc_ema(close_m5, EMA_FAST)
    ema_slow                    = calc_ema(close_m5, EMA_SLOW)
    rsi                         = calc_rsi(close_m5, RSI_PERIOD)
    macd_line, signal_line, _   = calc_macd(close_m5, MACD_FAST, MACD_SLOW, MACD_SIGNAL)

    # --- EMA 50 no H1 ---
    ema_h1 = calc_ema(close_h1, EMA_TREND)

    # Candle fechado = índice -2 (último completo); -3 é o anterior para crossover
    idx = -2

    ef      = ema_fast[idx]
    es      = ema_slow[idx]
    ef_prev = ema_fast[idx - 1]
    es_prev = ema_slow[idx - 1]
    rsi_val  = rsi[idx]
    macd_val = macd_line[idx]
    sig_val  = signal_line[idx]
    h1_ema50 = ema_h1[-1]
    price    = close_m5[idx]

    if any(np.isnan(v) for v in [ef, es, ef_prev, es_prev, rsi_val, macd_val, sig_val, h1_ema50]):
        log.debug("Indicadores ainda em aquecimento (NaN detectado) — aguardando.")
        return None

    cross_up   = ef_prev < es_prev and ef > es   # EMA9 cruzou acima EMA21
    cross_down = ef_prev > es_prev and ef < es   # EMA9 cruzou abaixo EMA21

    log.debug(
        "EMA%d=%.5f EMA%d=%.5f | RSI=%.2f | MACD=%.6f SIG=%.6f | "
        "H1_EMA%d=%.5f | PRICE=%.5f | cross_up=%s cross_down=%s",
        EMA_FAST, ef, EMA_SLOW, es, rsi_val, macd_val, sig_val,
        EMA_TREND, h1_ema50, price, cross_up, cross_down,
    )

    # --- BUY ---
    if (
        cross_up
        and RSI_BUY_MIN <= rsi_val <= RSI_BUY_MAX
        and macd_val > sig_val
        and price > h1_ema50
    ):
        log.info(
            "SINAL BUY | crossover=OK | RSI=%.2f (%.0f-%.0f) | MACD>SIG=OK | price>H1_EMA50=OK",
            rsi_val, RSI_BUY_MIN, RSI_BUY_MAX,
        )
        return "BUY"

    # --- SELL ---
    if (
        cross_down
        and RSI_SELL_MIN <= rsi_val <= RSI_SELL_MAX
        and macd_val < sig_val
        and price < h1_ema50
    ):
        log.info(
            "SINAL SELL | crossover=OK | RSI=%.2f (%.0f-%.0f) | MACD<SIG=OK | price<H1_EMA50=OK",
            rsi_val, RSI_SELL_MIN, RSI_SELL_MAX,
        )
        return "SELL"

    return None


# ============================================================
# LOOP PRINCIPAL
# ============================================================
def run(capital: float) -> None:
    """Loop principal: avalia sinal a cada LOOP_SECONDS e envia ordens."""
    log.info("=" * 60)
    log.info("Triple Confirmation Scalping iniciando")
    log.info("Capital: %.2f USD | Risco: %.0f%% | SL: %d pips | TP: %d pips",
             capital, RISK_PCT * 100, SL_PIPS, int(SL_PIPS * TP_RATIO))
    log.info("Símbolo: %s | Loop: %ds | Magic: %d", SYMBOL, LOOP_SECONDS, MAGIC)
    log.info("=" * 60)

    if not connect():
        sys.exit(1)

    try:
        pip_size, pip_value_per_lot = get_pip_info(SYMBOL)
    except RuntimeError as exc:
        log.error("%s", exc)
        mt5.shutdown()
        sys.exit(1)

    log.info("pip_size=%.5f | pip_value/lote=%.4f USD", pip_size, pip_value_per_lot)

    lot = calc_lot(capital, pip_value_per_lot)
    log.info("Lote calculado: %.2f (risco=%.2f USD)", lot, capital * RISK_PCT)

    iteration = 0
    while True:
        iteration += 1
        log.debug("--- Iteração %d ---", iteration)
        try:
            open_count = count_open_positions()
            log.debug("Posições abertas (magic=%d): %d/%d", MAGIC, open_count, MAX_POSITIONS)

            if open_count < MAX_POSITIONS:
                signal = get_signal()
                if signal:
                    tick = mt5.symbol_info_tick(SYMBOL)
                    if tick is None:
                        log.warning("Sem tick disponível para %s", SYMBOL)
                    else:
                        if signal == "BUY":
                            price = tick.ask
                            sl    = round(price - SL_PIPS * pip_size, 5)
                            tp    = round(price + SL_PIPS * TP_RATIO * pip_size, 5)
                            place_order(mt5.ORDER_TYPE_BUY, lot, price, sl, tp, "TC_BUY")
                        else:
                            price = tick.bid
                            sl    = round(price + SL_PIPS * pip_size, 5)
                            tp    = round(price - SL_PIPS * TP_RATIO * pip_size, 5)
                            place_order(mt5.ORDER_TYPE_SELL, lot, price, sl, tp, "TC_SELL")
                else:
                    log.debug("Sem sinal — condições Triple Confirmation não atendidas.")
            else:
                log.debug("Limite de posições atingido (%d/%d) — aguardando.", open_count, MAX_POSITIONS)

        except KeyboardInterrupt:
            log.info("Interrompido pelo usuário (Ctrl+C).")
            break
        except Exception as exc:
            log.error("Erro inesperado no loop: %s", exc, exc_info=True)

        time.sleep(LOOP_SECONDS)

    mt5.shutdown()
    log.info("Conexão MT5 encerrada. Bot finalizado.")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  Triple Confirmation Scalping — EUR/USD | MT5")
    print("=" * 60)
    print(f"  Estratégia : EMA {EMA_FAST}/{EMA_SLOW} M5 + RSI {RSI_PERIOD} + MACD ({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + EMA {EMA_TREND} H1")
    print(f"  Risco      : {RISK_PCT*100:.0f}% | SL: {SL_PIPS} pips | TP: {int(SL_PIPS*TP_RATIO)} pips")
    print(f"  Loop       : {LOOP_SECONDS}s | Magic: {MAGIC}")
    print("=" * 60)

    while True:
        try:
            raw = input("\nCapital base em USD que o robô deve usar: ").strip().replace(",", ".")
            capital_usd = float(raw)
            if capital_usd <= 0:
                raise ValueError("O capital deve ser um valor positivo.")
            break
        except ValueError as exc:
            print(f"  Entrada inválida: {exc}. Tente novamente.")

    print(f"\n  Capital confirmado: USD {capital_usd:,.2f}")
    print(f"  Risco por trade   : USD {capital_usd * RISK_PCT:,.2f}")
    print()

    run(capital_usd)
