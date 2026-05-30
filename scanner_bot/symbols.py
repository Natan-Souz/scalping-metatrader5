"""
scanner_bot.symbols
Descoberta e utilitários de símbolos para o scanner (forex + cripto).
"""

import logging
from typing import List

import MetaTrader5 as mt5

from core.mt5_bridge import get_pip_info
from scanner_bot.config import MAGIC, SL_PIPS, CRYPTO_SL_PCT
from scanner_bot.models import CandidatoInfo

log = logging.getLogger(__name__)


def get_currencies(symbol: str) -> set:
    """Extrai o par de moedas dos primeiros 6 caracteres do símbolo."""
    clean = symbol[:6] if len(symbol) >= 6 else symbol
    return {clean[:3].upper(), clean[3:6].upper()}


def get_magic_positions(magic: int) -> list:
    """Retorna lista de posições abertas para o magic number informado."""
    return [p for p in (mt5.positions_get() or []) if p.magic == magic]


def discover_symbols() -> List[CandidatoInfo]:
    """
    Descobre todos os símbolos forex e cripto disponíveis na corretora.

    Critérios de inclusão:
      - path contém "forex" OU "crypto" (case-insensitive)
      - path não contém: metals, indices, commodities, cfd
      - trade_mode == SYMBOL_TRADE_MODE_FULL (4)

    Categorias e SL derivados do path:
      crypto          → Crypto   | sl_pct = CRYPTO_SL_PCT (% do preço, dinâmico)
      forex + "major" → Majors   | sl_pips = SL_PIPS (fixo em pips)
      forex + "exotic"→ Exotics  | sl_pips = SL_PIPS
      forex (demais)  → Minors   | sl_pips = SL_PIPS

    Returns:
        Lista de CandidatoInfo com pip_size, pip_value e sl configurados.
    """
    all_symbols = mt5.symbols_get()
    if not all_symbols:
        log.warning("Nenhum símbolo retornado pelo MT5.")
        return []

    EXCLUDED = {"metals", "indices", "commodities", "cfd"}
    result: List[CandidatoInfo] = []
    skipped_path = skipped_excluded = skipped_mode = 0

    for sym in all_symbols:
        path       = sym.path.replace("\\", "/").strip("/")
        path_lower = path.lower()

        is_forex  = "forex"  in path_lower
        is_crypto = "crypto" in path_lower

        if not (is_forex or is_crypto):
            skipped_path += 1
            continue
        if any(kw in path_lower for kw in EXCLUDED):
            skipped_excluded += 1
            continue
        if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            skipped_mode += 1
            continue

        if is_crypto:
            category = "Crypto"
        elif "major" in path_lower:
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

        if category == "Crypto":
            result.append(CandidatoInfo(
                symbol=sym.name, category=category,
                pip_size=pip_size, pip_value=pip_value,
                sl_pct=CRYPTO_SL_PCT,   # SL dinâmico: % do preço de entrada
            ))
        else:
            result.append(CandidatoInfo(
                symbol=sym.name, category=category,
                pip_size=pip_size, pip_value=pip_value,
                sl_pips=SL_PIPS,        # SL fixo em pips (forex)
            ))

    log.debug(
        "Descartados: path=%d | excluídos=%d | trade_mode≠FULL=%d",
        skipped_path, skipped_excluded, skipped_mode,
    )

    if not result:
        unique_paths = sorted({s.path for s in all_symbols})
        log.warning(
            "Nenhum símbolo encontrado após filtros! Paths disponíveis (%d): %s",
            len(unique_paths), unique_paths[:20],
        )

    crypto_count = sum(1 for c in result if c.category == "Crypto")
    forex_count  = len(result) - crypto_count
    log.debug("Símbolos descobertos: %d forex | %d cripto", forex_count, crypto_count)
    return result


def discover_forex_only_symbols() -> List[CandidatoInfo]:
    """Retorna apenas pares forex (Majors, Minors, Exotics) — exclui Crypto."""
    return [s for s in discover_symbols() if s.category != "Crypto"]


def discover_crypto_symbols() -> List[CandidatoInfo]:
    """Retorna apenas pares cripto."""
    return [s for s in discover_symbols() if s.category == "Crypto"]


# Alias para compatibilidade com código legado
discover_forex_symbols = discover_forex_only_symbols
