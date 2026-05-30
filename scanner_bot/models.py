"""
scanner_bot.models
Modelo de dados compartilhado pelo pipeline do scanner.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class CandidatoInfo:
    """
    Representa um símbolo em avaliação (forex ou cripto).
    É criado em discover_symbols() e enriquecido progressivamente
    por cada filtro do pipeline (spread_pips, score, direction, criterios).

    Gestão de risco por categoria:
      Forex (Majors/Minors/Exotics) → sl_pips fixo (ex: 6 pips)
      Crypto                        → sl_pct % do preço de entrada (ex: 0.02 = 2%)
                                      sl_pips é ignorado quando sl_pct está definido
    """
    symbol:      str
    category:    str             # "Majors", "Minors", "Exotics" ou "Crypto"
    pip_size:    float
    pip_value:   float           # pip value por lote em USD
    sl_pips:     int             = 12     # forex: SL fixo em pips
    sl_pct:      Optional[float] = None  # cripto: SL como % do preço (prioridade sobre sl_pips)
    spread_pips: float           = 0.0
    score:       int             = 0
    direction:   str             = "NEUTRAL"
    criterios:   Dict[str, str]  = field(default_factory=dict)
