"""
triple_bot.bot
Loop principal do bot single-pair Triple Confirmation (GBPUSD).

Execução:
    python triple_confirmation.py
    python -m triple_bot.bot
"""

import sys
import time
import logging

import MetaTrader5 as mt5

from core.logging_setup import setup_logging
from core.mt5_bridge import connect, get_pip_info, calc_lot, place_order
from triple_bot.config import (
    SYMBOL, MAGIC, LOG_FILE,
    RISK_PCT, SL_PIPS, TP_RATIO,
    LOOP_SECONDS, MAX_POSITIONS,
    EMA_FAST, EMA_SLOW, RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL, EMA_TREND,
)
from triple_bot.signal import get_signal, count_open_positions

log = logging.getLogger(__name__)


def run(capital: float) -> None:
    """Loop principal: avalia sinal a cada LOOP_SECONDS e envia ordens."""
    log.info("=" * 60)
    log.info("Triple Confirmation Scalping iniciando")
    log.info(
        "Capital: %.2f USD | Risco: %.0f%% | SL: %d pips | TP: %d pips",
        capital, RISK_PCT * 100, SL_PIPS, int(SL_PIPS * TP_RATIO),
    )
    log.info("Símbolo: %s | Loop: %ds | Magic: %d", SYMBOL, LOOP_SECONDS, MAGIC)
    log.info("=" * 60)

    if not connect():
        sys.exit(1)

    try:
        pip_size, pip_value = get_pip_info(SYMBOL)
    except RuntimeError as exc:
        log.error("%s", exc)
        mt5.shutdown()
        sys.exit(1)

    log.info("pip_size=%.5f | pip_value/lote=%.4f USD", pip_size, pip_value)
    lot = calc_lot(capital, pip_value, SYMBOL, RISK_PCT, SL_PIPS)
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
                            place_order(SYMBOL, mt5.ORDER_TYPE_BUY, lot, price, sl, tp,
                                        MAGIC, "TC_BUY")
                        else:
                            price = tick.bid
                            sl    = round(price + SL_PIPS * pip_size, 5)
                            tp    = round(price - SL_PIPS * TP_RATIO * pip_size, 5)
                            place_order(SYMBOL, mt5.ORDER_TYPE_SELL, lot, price, sl, tp,
                                        MAGIC, "TC_SELL")
                else:
                    log.debug("Sem sinal — condições Triple Confirmation não atendidas.")
            else:
                log.debug("Posição já aberta, aguardando encerramento.")

        except KeyboardInterrupt:
            log.info("Interrompido pelo usuário (Ctrl+C).")
            break
        except Exception as exc:
            log.error("Erro no loop: %s", exc, exc_info=True)

        time.sleep(LOOP_SECONDS)

    mt5.shutdown()
    log.info("Conexão MT5 encerrada.")


def main() -> None:
    """Entry point com input de capital e inicialização do logging."""
    print("=" * 60)
    print("  Triple Confirmation Scalping — GBPUSD | MT5")
    print("=" * 60)
    print(f"  Estratégia : EMA {EMA_FAST}/{EMA_SLOW} M5 + RSI {RSI_PERIOD} + "
          f"MACD ({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + EMA {EMA_TREND} H1")
    print(f"  Risco      : {RISK_PCT*100:.0f}% | SL={SL_PIPS}p | TP={int(SL_PIPS*TP_RATIO)}p")
    print(f"  Loop       : {LOOP_SECONDS}s | Magic: {MAGIC}")
    print("=" * 60)

    while True:
        try:
            raw = input("\nCapital base em USD que o robô deve usar: ").strip().replace(",", ".")
            capital_usd = float(raw)
            if capital_usd <= 0:
                raise ValueError("O capital deve ser positivo.")
            break
        except ValueError as exc:
            print(f"  Entrada inválida: {exc}. Tente novamente.")

    setup_logging(LOG_FILE)

    print(f"\n  Capital confirmado: USD {capital_usd:,.2f}")
    print(f"  Risco por trade   : USD {capital_usd * RISK_PCT:,.2f}")
    print()

    run(capital_usd)


if __name__ == "__main__":
    main()
