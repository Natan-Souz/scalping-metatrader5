"""
profiles.py — Perfis por símbolo.

Edite SYMBOL_PROFILES para personalizar parâmetros de um ativo específico.
Símbolos sem perfil explícito usam DEFAULT_PROFILE (baseado em config.py).

Modos de uso:
    python main.py                          # scanner: todos os pares forex
    python main.py --symbols EURUSD GBPUSD  # scanner: pares escolhidos
    python main.py --launch EURUSD GBPUSD   # abre terminal separado por par

Exemplos de perfis personalizados:
    "EURUSD": SymbolProfile(score_min=3, risk_pct=0.03)
    "GBPUSD": SymbolProfile(sl_pips=5, risk_pct=0.015, ema_fast=7)
    "USDJPY": SymbolProfile(score_min=4, ema_crossover_thr=2.0)
"""

import config as cfg
from bot.models import SymbolProfile

DEFAULT_PROFILE = SymbolProfile(
    score_min=4,
    sl_pips=cfg.FOREX_SL_PIPS,
    risk_pct=cfg.FOREX_RISK_PCT,
    ema_fast=cfg.EMA_FAST,
    ema_slow=cfg.EMA_SLOW,
    rsi_period=cfg.RSI_PERIOD,
    ema_crossover_thr=cfg.EMA_CROSSOVER_PIPS_THR,
    magic=None,  # None = gerado automaticamente por símbolo no modo worker
)

# Adicione entradas para personalizar por símbolo.
# Parâmetros omitidos herdam os valores de DEFAULT_PROFILE.
SYMBOL_PROFILES: dict[str, SymbolProfile] = {
    # "EURUSD": SymbolProfile(score_min=3, risk_pct=0.03),
    # "GBPUSD": SymbolProfile(sl_pips=5, risk_pct=0.015),
}


def get_profile(symbol: str) -> SymbolProfile:
    """Retorna o perfil do símbolo, ou DEFAULT_PROFILE se não houver específico."""
    return SYMBOL_PROFILES.get(symbol, DEFAULT_PROFILE)
