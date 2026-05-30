"""
scanner_bot.models
Modelo de dados compartilhado pelo pipeline do scanner.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class CandidatoInfo:
    """
    Representa um símbolo em avaliação (forex ou cripto).
    É criado em discover_symbols() e enriquecido progressivamente
    por cada filtro do pipeline (spread_pips, score, direction, criterios).

    O campo sl_pips é definido por categoria na descoberta:
      Forex (Majors/Minors/Exotics) → SL_PIPS
      Crypto                        → SL_PIPS_CRYPTO
    """
    symbol:      str
    category:    str            # "Majors", "Minors", "Exotics" ou "Crypto"
    pip_size:    float
    pip_value:   float          # pip value por lote em USD
    sl_pips:     int            = 12    # override por categoria — não editar manualmente
    spread_pips: float          = 0.0
    score:       int            = 0
    direction:   str            = "NEUTRAL"
    criterios:   Dict[str, str] = field(default_factory=dict)
