"""
scanner_bot.models
Modelo de dados compartilhado pelo pipeline do scanner.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class CandidatoInfo:
    """
    Representa um símbolo forex em avaliação.
    É criado em discover_forex_symbols() e enriquecido progressivamente
    por cada filtro do pipeline (spread_pips, score, direction, criterios).
    """
    symbol:      str
    category:    str            # "Majors", "Minors" ou "Exotics"
    pip_size:    float
    pip_value:   float          # pip value por lote em USD
    spread_pips: float          = 0.0
    score:       int            = 0
    direction:   str            = "NEUTRAL"
    criterios:   Dict[str, str] = field(default_factory=dict)
