"""
main.py — Ponto de entrada unificado do Scalping Bot MT5.

Modos de uso:
    python main.py                           Scanner completo (todos os pares forex)
    python main.py --symbols EURUSD GBPUSD   Scanner com pares específicos (mesmo terminal)
    python main.py --launch EURUSD GBPUSD    Abre terminal PowerShell separado por par
    python main.py --worker EURUSD           Worker individual (usado pelo launcher)
    python main.py --worker EURUSD --capital 10000  Worker sem prompt de capital

Personalização por símbolo: edite profiles.py.
MetaTrader5 deve estar aberto e logado antes de iniciar.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import config as cfg


def _prompt_capital() -> float:
    while True:
        try:
            raw = input("\nCapital base em USD: ").strip().replace(",", ".")
            capital = float(raw)
            if capital <= 0:
                raise ValueError("Capital deve ser positivo.")
            return capital
        except ValueError as exc:
            print(f"  Entrada inválida: {exc}. Tente novamente.")


def _print_banner(mode: str, symbols: Optional[List[str]] = None) -> None:
    print("=" * 70)
    print(f"  Scalping Bot MT5 — Triple Confirmation | {mode}")
    print("=" * 70)
    print(
        f"  Estratégia : EMA {cfg.EMA_FAST}/{cfg.EMA_SLOW} M5 + RSI {cfg.RSI_PERIOD} + "
        f"MACD ({cfg.MACD_FAST},{cfg.MACD_SLOW},{cfg.MACD_SIGNAL}) + EMA {cfg.EMA_TREND_H1} H1"
    )
    if symbols:
        print(f"  Símbolos   : {', '.join(symbols)}")
    else:
        print("  Símbolos   : todos os pares forex")
    print(
        f"  Risco      : {cfg.FOREX_RISK_PCT * 100:.1f}% | "
        f"SL={cfg.FOREX_SL_PIPS}p | TP={int(cfg.FOREX_SL_PIPS * cfg.TP_RATIO)}p"
    )
    print(f"  Loop       : {cfg.LOOP_SECONDS}s | MaxPos: {cfg.FOREX_MAX_TOTAL_POSITIONS}")
    print("=" * 70)


def run_scanner(capital: float, symbols: Optional[List[str]] = None) -> None:
    """Roda o scanner no processo atual (todos os pares ou selecionados)."""
    from core.logging_setup import setup_logging
    from bot.robot import ScannerRobot
    from bot.symbols import discover_forex_only_symbols

    setup_logging(cfg.FOREX_LOG_FILE)

    if symbols:
        sym_set     = set(symbols)
        discover_fn = lambda: discover_forex_only_symbols(filter_symbols=sym_set)
    else:
        discover_fn = discover_forex_only_symbols

    print(f"\n  Capital confirmado  : USD {capital:,.2f}")
    print(f"  Risco por trade     : USD {capital * cfg.FOREX_RISK_PCT:,.2f}")
    print(f"  Score mín entrada   : 4/4 (Triple Confirmation completa)\n")

    ScannerRobot(
        capital=capital,
        magic=cfg.FOREX_MAGIC,
        discover_fn=discover_fn,
        max_positions=cfg.FOREX_MAX_TOTAL_POSITIONS,
    ).run()


def run_worker(symbol: str, capital: float) -> None:
    """Roda um único símbolo com perfil próprio (magic único, max_positions=1)."""
    from core.logging_setup import setup_logging
    from bot.robot import ScannerRobot
    from bot.symbols import discover_forex_only_symbols, symbol_to_magic
    from profiles import get_profile

    profile  = get_profile(symbol)
    magic    = profile.magic if profile.magic is not None else symbol_to_magic(symbol)
    log_file = f"logs/worker_{symbol}.log"

    setup_logging(log_file)

    sym_set     = {symbol}
    discover_fn = lambda: discover_forex_only_symbols(filter_symbols=sym_set)

    _print_banner(f"Worker [{symbol}]", [symbol])
    print(f"  Magic      : {magic}")
    print(f"  Score mín  : {profile.score_min}/4")
    print(f"  SL/TP      : {profile.sl_pips}p / {int(profile.sl_pips * cfg.TP_RATIO)}p")
    print(f"  Risco      : {profile.risk_pct * 100:.1f}%")
    print(f"  Log        : {log_file}")
    print("=" * 70)
    print(f"\n  Capital confirmado  : USD {capital:,.2f}")
    print(f"  Risco por trade     : USD {capital * profile.risk_pct:,.2f}\n")

    ScannerRobot(
        capital=capital,
        magic=magic,
        discover_fn=discover_fn,
        max_positions=1,
    ).run()


def launch_terminals(symbols: List[str], capital: float) -> None:
    """Abre um terminal PowerShell separado para cada símbolo."""
    python = sys.executable
    script = str(Path(__file__).resolve())

    print(f"\n  Abrindo {len(symbols)} terminal(is)...")
    for sym in symbols:
        cmd = f'& "{python}" "{script}" --worker {sym} --capital {capital}'
        opened = False

        # Tenta Windows Terminal primeiro (disponível no Windows 11)
        try:
            subprocess.Popen(
                ["wt.exe", "new-tab", "--title", sym, "--",
                 "powershell", "-NoExit", "-Command", cmd],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            opened = True
        except (FileNotFoundError, OSError):
            pass

        if not opened:
            subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command", cmd],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )

        print(f"  OK Terminal aberto: {sym}")

    print(f"\n  {len(symbols)} worker(s) iniciado(s).")
    print("  Este processo pode ser encerrado (os workers continuam rodando).\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scalping Bot MT5 — Triple Confirmation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
exemplos:
  python main.py
  python main.py --symbols EURUSD GBPUSD
  python main.py --launch EURUSD GBPUSD
        """,
    )
    parser.add_argument(
        "--symbols", nargs="+", metavar="SYM",
        help="Pares específicos para o scanner (mesmo terminal)",
    )
    parser.add_argument(
        "--launch", nargs="+", metavar="SYM",
        help="Abre um terminal PowerShell por símbolo",
    )
    parser.add_argument(
        "--worker", metavar="SYM",
        help="Modo worker — chamado pelo launcher",
    )
    parser.add_argument(
        "--capital", type=float, metavar="USD",
        help="Capital em USD (evita prompt interativo no modo worker)",
    )
    args = parser.parse_args()

    if args.worker:
        capital = args.capital if args.capital else _prompt_capital()
        run_worker(args.worker, capital)

    elif args.launch:
        _print_banner("Launcher", args.launch)
        capital = _prompt_capital()
        launch_terminals(args.launch, capital)

    else:
        mode = "Scanner Seletivo" if args.symbols else "Scanner Completo"
        _print_banner(mode, args.symbols)
        capital = _prompt_capital()
        run_scanner(capital, symbols=args.symbols)


if __name__ == "__main__":
    main()
