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

# Perfil de SCALPING recomendado para validar UM ativo com filtro de ciclo.
#
# Lógica: com o FiltroRegime (ADX H1 >= 25) cortando os trades de
# lateralização, a rejeição de ruído deixa de ser trabalho do score. Por
# isso score_min=3 passa a ser viável E mais seguro — captura mais do leg
# de tendência sem o whipsaw que o score_min=4 tentava evitar de forma crua.
# risk_pct reduzido a 1% enquanto o ativo ainda está em validação

SCALPING_REGIME_PROFILE_USDJPY = SymbolProfile(
    score_min=3,            # regime já filtra o ruído → 3 captura mais da tendência
    sl_pips=3,              # scalping curto (mantido)
    risk_pct=0.01,          # 1% por trade durante a validação do ativo
    ema_fast=9,
    ema_slow=21,
    rsi_period=7,
    ema_crossover_thr=7.5,
    use_regime_filter=True,
    adx_period=14,
    adx_min=25.0,           # tendência clara; suba p/ 30 se quiser ainda mais seletivo
)
SCALPING_REGIME_PROFILE_EURUSD = SymbolProfile(
    score_min=3,            # regime já filtra o ruído → 3 captura mais da tendência
    sl_pips=3,              # scalping curto (mantido)
    risk_pct=0.01,          # 1% por trade durante a validação do ativo
    ema_fast=9,
    ema_slow=21,
    rsi_period=7,
    ema_crossover_thr=5.4,
    use_regime_filter=True,
    adx_period=14,
    adx_min=25.0,           # tendência clara; suba p/ 30 se quiser ainda mais seletivo
)

SCALPING_REGIME_PROFILE_GBPJPY = SymbolProfile(
    score_min=3,            # regime já filtra o ruído → 3 captura mais da tendência
    sl_pips=3,              # ⚠️ provável estreito demais p/ a volatilidade do GBPJPY — ver nota
    risk_pct=0.01,          # 1% por trade durante a validação do ativo
    ema_fast=9,
    ema_slow=21,
    rsi_period=7,
    ema_crossover_thr=19.0, # 0,10% @ ~190 — "the beast" precisa de threshold mais largo
    use_regime_filter=True,
    adx_period=14,
    adx_min=25.0,           # tendência clara; suba p/ 30 se quiser ainda mais seletivo
)


# Adicione entradas para personalizar por símbolo.
# Parâmetros omitidos herdam os valores de DEFAULT_PROFILE.
# Cada ativo usa seu perfil de scalping calibrado (ema_crossover_thr por % do preço).
SYMBOL_PROFILES: dict[str, SymbolProfile] = {
    "USDJPY": SCALPING_REGIME_PROFILE_USDJPY,
    "EURUSD": SCALPING_REGIME_PROFILE_EURUSD,
    #"GBPJPY": SCALPING_REGIME_PROFILE_GBPJPY,
}


def get_profile(symbol: str) -> SymbolProfile:
    """Retorna o perfil do símbolo, ou DEFAULT_PROFILE se não houver específico."""
    return SYMBOL_PROFILES.get(symbol, DEFAULT_PROFILE)
