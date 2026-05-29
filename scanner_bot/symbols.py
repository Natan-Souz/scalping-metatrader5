"""
scanner_bot.symbols
Descoberta e utilitários de símbolos forex para o scanner.
"""

import logging
from typing import List

import MetaTrader5 as mt5

from core.mt5_bridge import get_pip_info
from scanner_bot.config import MAGIC
from scanner_bot.models import CandidatoInfo

log = logging.getLogger(__name__)


def get_currencies(symbol: str) -> set:
    """Extrai o par de moedas dos primeiros 6 caracteres do símbolo."""
    clean = symbol[:6] if len(symbol) >= 6 else symbol
    return {clean[:3].upper(), clean[3:6].upper()}


def get_magic_positions() -> list:
    """Retorna lista de posições abertas com o magic number do scanner."""
    return [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]


def discover_forex_symbols() -> List[CandidatoInfo]:
    """
    Descobre todos os pares forex disponíveis na corretora.

    Critérios de inclusão:
      - path contém "forex" (case-insensitive)
      - path não contém: crypto, metals, indices, commodities, cfd
      - trade_mode == SYMBOL_TRADE_MODE_FULL (4)

    Categorias derivadas do path:
      "major" → Majors | "exotic" → Exotics | demais → Minors (fallback)

    Returns:
        Lista de CandidatoInfo com pip_size e pip_value calculados.
    """
    all_symbols = mt5.symbols_get()
    if not all_symbols:
        log.warning("Nenhum símbolo retornado pelo MT5.")
        return []

    EXCLUDED = {"crypto", "metals", "indices", "commodities", "cfd"}
    result: List[CandidatoInfo] = []
    skipped_path = skipped_excluded = skipped_mode = 0

    for sym in all_symbols:
        path       = sym.path.replace("\\", "/").strip("/")
        path_lower = path.lower()

        if "forex" not in path_lower:
            skipped_path += 1
            continue
        if any(kw in path_lower for kw in EXCLUDED):
            skipped_excluded += 1
            continue
        if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            skipped_mode += 1
            continue

        if "major" in path_lower:
            category = "Majors"
        elif "exotic" in path_lower:
            category = "Exotics"
        else:
            category = "Minors"

        mt5.symbol_select(sym.name, True)

        try:
            pip_size, pip_value = get_pip_info(sym.name)
        except RuntimeError:
            continue

        if pip_size <= 0 or pip_value <= 0:
            continue

        result.append(CandidatoInfo(
            symbol=sym.name,
            category=category,
            pip_size=pip_size,
            pip_value=pip_value,
        ))

    log.debug(
        "Descartados: path=%d | excluídos=%d | trade_mode≠FULL=%d",
        skipped_path, skipped_excluded, skipped_mode,
    )

    if not result:
        unique_paths = sorted({s.path for s in all_symbols})
        log.warning(
            "Nenhum símbolo forex após filtros! Paths disponíveis (%d): %s",
            len(unique_paths), unique_paths[:20],
        )

    log.debug("Símbolos forex descobertos: %d", len(result))
    return result
