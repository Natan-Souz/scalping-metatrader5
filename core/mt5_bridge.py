"""
core.mt5_bridge
Funções de baixo nível para comunicação com MetaTrader5.
Compartilhado por triple_bot e scanner_bot.

Todas as funções que dependem de constantes de configuração (MAGIC, RISK_PCT,
SL_PIPS) recebem esses valores como parâmetros explícitos — este módulo não
importa configs de nenhum bot.
"""

import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

log = logging.getLogger(__name__)


# ============================================================
# CONEXÃO
# ============================================================
def connect() -> bool:
    """Inicializa a conexão com o MT5 e loga informações da conta."""
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


# ============================================================
# DADOS DE MERCADO
# ============================================================
def get_bars(symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
    """Busca `count` candles do MT5 e retorna DataFrame com coluna 'time' em datetime."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        log.debug("Sem dados: %s tf=%d", symbol, timeframe)
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_pip_info(symbol: str) -> Tuple[float, float]:
    """
    Retorna (pip_size, pip_value_por_lote) para o símbolo.

    pip_size  = point * 10  (1 pip = 10 pontos em pares de 5 decimais)
    pip_value = (pip_size / tick_size) * tick_value  (valor em moeda da conta)
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol info não encontrado: {symbol}")
    pip_size   = info.point * 10
    tick_size  = info.trade_tick_size
    tick_value = info.trade_tick_value
    pip_value  = (pip_size / tick_size) * tick_value if tick_size > 0 else info.trade_contract_size * pip_size
    return pip_size, pip_value


# ============================================================
# GESTÃO DE RISCO
# ============================================================
def calc_lot(
    capital: float,
    pip_value: float,
    symbol: str,
    risk_pct: float,
    sl_pips: int,
) -> float:
    """
    Calcula o tamanho do lote baseado em risco percentual do capital.

        lote = (capital × risk_pct) / (sl_pips × pip_value)

    Arredonda para o volume_step do símbolo e respeita volume_min/max.

    Retorna 0.0 e loga um aviso se o lote mínimo do ativo gerar um
    risco real mais que 2× o risco configurado — protege contra a
    situação em que volume_min de ativos como BTC inviabiliza a gestão
    de risco com capital pequeno.
    """
    if pip_value <= 0:
        return 0.01

    target_risk = capital * risk_pct
    raw_lot     = target_risk / (sl_pips * pip_value)

    sym = mt5.symbol_info(symbol)
    if sym:
        step    = sym.volume_step if sym.volume_step > 0 else 0.01
        raw_lot = round(raw_lot / step) * step
        raw_lot = max(sym.volume_min, min(sym.volume_max, raw_lot))

        # Guarda: verifica se o arredondamento para volume_min explodiu o risco
        actual_risk = raw_lot * sl_pips * pip_value
        if actual_risk > target_risk * 2.0:
            min_capital = (sym.volume_min * sl_pips * pip_value) / risk_pct
            log.warning(
                "%s: capital insuficiente — risco real após arredondamento "
                "(%.2f USD) é %.0f× maior que o configurado (%.2f USD). "
                "Capital mínimo estimado para este ativo com SL=%d pips: "
                "~%.0f USD. Operação cancelada.",
                symbol, actual_risk, actual_risk / target_risk,
                target_risk, sl_pips, min_capital,
            )
            return 0.0

    log.debug("%s: lote=%.4f | risco_alvo=%.2f USD | risco_real=%.2f USD",
              symbol, raw_lot, target_risk, raw_lot * sl_pips * pip_value)

    return round(raw_lot, 2)


# ============================================================
# CÁLCULO E VALIDAÇÃO DE SL/TP
# ============================================================
def calc_sl_tp(
    symbol: str,
    direction: str,
    price: float,
    sl_pips: int,
    pip_size: float,
    tp_ratio: float,
) -> Tuple[float, float]:
    """
    Calcula SL e TP com arredondamento correto para o símbolo e valida
    se os valores são aceitos pelo MT5 antes de enviar a ordem.

    Verificações realizadas:
      1. Arredonda para `sym.digits` (não hardcoded 5) — evita preços inexistentes
      2. SL e TP > 0 — cripto baratos podem gerar TP negativo em SELL
      3. Distância mínima >= `trade_stops_level` do símbolo

    Returns:
        (sl, tp) válidos, ou (0.0, 0.0) se qualquer verificação falhar.
        Quando retorna (0.0, 0.0) a ordem deve ser cancelada.
    """
    sym = mt5.symbol_info(symbol)
    if sym is None:
        log.warning("%s: symbol_info indisponível para calcular SL/TP.", symbol)
        return 0.0, 0.0

    digits  = sym.digits
    sl_dist = sl_pips * pip_size
    tp_dist = sl_pips * tp_ratio * pip_size

    if direction == "BUY":
        sl = round(price - sl_dist, digits)
        tp = round(price + tp_dist, digits)
    else:
        sl = round(price + sl_dist, digits)
        tp = round(price - tp_dist, digits)

    # Verificação 1: SL e TP devem ser positivos
    if sl <= 0 or tp <= 0:
        log.warning(
            "%s: SL/TP inválido — sl=%.{d}f tp=%.{d}f. "
            "Preço (%.{d}f) muito baixo para o SL de %d pips configurado. "
            "Reduza SL_PIPS ou opere o ativo com preço maior.".format(d=digits),
            symbol, sl, tp, price, sl_pips,
        )
        return 0.0, 0.0

    # Verificação 2: distância mínima exigida pelo broker (stops_level)
    if sym.trade_stops_level > 0:
        min_dist    = sym.trade_stops_level * sym.point
        actual_sl   = abs(price - sl)
        actual_tp   = abs(price - tp)
        too_close   = actual_sl < min_dist or actual_tp < min_dist
        if too_close:
            log.warning(
                "%s: SL/TP muito próximos do preço — broker exige mínimo %.{d}f "
                "(stops_level=%d). SL_dist=%.{d}f TP_dist=%.{d}f. "
                "Operação cancelada.".format(d=digits),
                symbol, min_dist, sym.trade_stops_level, actual_sl, actual_tp,
            )
            return 0.0, 0.0

    log.debug("%s: sl=%.{d}f tp=%.{d}f (digits=%d stops_level=%d)".format(d=digits),
              symbol, sl, tp, digits, sym.trade_stops_level)

    return sl, tp


# ============================================================
# EXECUÇÃO DE ORDENS
# ============================================================
def place_order(
    symbol: str,
    order_type: int,
    lot: float,
    price: float,
    sl: float,
    tp: float,
    magic: int,
    comment: str = "",
) -> bool:
    """
    Envia ordem a mercado com SL/TP.

    Usa TRADE_ACTION_DEAL + ORDER_FILLING_IOC + deviation=10.
    O parâmetro `magic` identifica o bot dono da posição.
    """
    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    10,
        "magic":        magic,
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
