"""
bot.models
Modelos de dados do pipeline do scanner.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SymbolProfile:
    """
    Perfil de configuração por símbolo.
    Editável em profiles.py — define indicadores, risco e execução.

    score_min=3 → permissivo (entra com 3/4 critérios alinhados)
    score_min=4 → estrito (exige todos os 4 critérios, padrão)
    magic=None  → gerado automaticamente por símbolo no modo worker
    """
    score_min:         int           = 4
    sl_pips:           int           = 3
    risk_pct:          float         = 0.025
    ema_fast:          int           = 9
    ema_slow:          int           = 21
    rsi_period:        int           = 7
    ema_crossover_thr: float         = 1.5     # pips para pré-crossover
    magic:             Optional[int] = None    # None → auto-gerado por símbolo


@dataclass
class CandidatoInfo:
    """
    Representa um símbolo em avaliação.
    Criado em discover_symbols() e enriquecido por cada filtro do pipeline.

    Gestão de risco:
      Forex → sl_pips fixo (via perfil)
      Crypto → sl_pct % do preço de entrada (sl_pips ignorado quando sl_pct definido)
    """
    symbol:      str
    category:    str             # "Majors", "Minors", "Exotics" ou "Crypto"
    pip_size:    float
    pip_value:   float           # pip value por lote em USD
    profile:     SymbolProfile   = field(default_factory=SymbolProfile)
    sl_pct:      Optional[float] = None   # cripto: SL como % do preço
    spread_pips: float           = 0.0
    score:       int             = 0
    direction:   str             = "NEUTRAL"
    criterios:   Dict[str, str]  = field(default_factory=dict)

    @property
    def sl_pips(self) -> int:
        return self.profile.sl_pips
