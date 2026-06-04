"""
bot.symbols
Descoberta e utilitários de símbolos para o scanner.
"""

import hashlib
import logging
from typing import List, Optional, Set

import MetaTrader5 as mt5

import config as cfg
from core.mt5_bridge import get_pip_info
from bot.models import CandidatoInfo

log = logging.getLogger(__name__)


def symbol_to_magic(symbol: str) -> int:
    """Gera magic number único e estável por símbolo para o modo worker."""
    return 700000 + (int(hashlib.md5(symbol.encode()).hexdigest()[:5], 16) % 100000)


def get_currencies(symbol: str) -> set:
    """Extrai o par de moedas dos primeiros 6 caracteres do símbolo."""
    clean = symbol[:6] if len(symbol) >= 6 else symbol
    return {clean[:3].upper(), clean[3:6].upper()}


def get_magic_positions(magic: int) -> list:
    """Retorna posições abertas para o magic number informado."""
    return [p for p in (mt5.positions_get() or []) if p.magic == magic]


def discover_symbols(
    filter_symbols: Optional[Set[str]] = None,
) -> List[CandidatoInfo]:
    """
    Descobre símbolos forex e cripto disponíveis na corretora.

    Categorias e SL derivados do path:
      crypto            → Crypto   | sl_pct = CRYPTO_SL_PCT (% do preço, dinâmico)
      forex + "major"   → Majors   | sl_pips = profile.sl_pips
      forex + "exotic"  → Exotics  | sl_pips = profile.sl_pips
      forex (demais)    → Minors   | sl_pips = profile.sl_pips

    Args:
        filter_symbols: se informado, retorna apenas esses símbolos.
    """
    from profiles import get_profile  # importação local para evitar circular

    all_symbols = mt5.symbols_get()
    if not all_symbols:
        log.warning("Nenhum símbolo retornado pelo MT5.")
        return []

    EXCLUDED = {"metals", "indices", "commodities", "cfd"}
    result: List[CandidatoInfo] = []
    skipped_path = skipped_excluded = skipped_mode = 0

    for sym in all_symbols:
        if filter_symbols and sym.name not in filter_symbols:
            continue

        path_lower = sym.path.replace("\\", "/").lower()
        is_forex   = "forex"  in path_lower
        is_crypto  = "crypto" in path_lower

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

        profile = get_profile(sym.name)

        candidato = CandidatoInfo(
            symbol=sym.name,
            category=category,
            pip_size=pip_size,
            pip_value=pip_value,
            profile=profile,
            sl_pct=cfg.CRYPTO_SL_PCT if category == "Crypto" else None,
        )
        result.append(candidato)

    if not result and filter_symbols is None:
        unique_paths = sorted({s.path for s in all_symbols})
        log.warning(
            "Nenhum símbolo encontrado após filtros! Paths disponíveis (%d): %s",
            len(unique_paths), unique_paths[:20],
        )
    else:
        log.debug(
            "Descartados: path=%d | excluídos=%d | trade_mode≠FULL=%d",
            skipped_path, skipped_excluded, skipped_mode,
        )
        crypto_count = sum(1 for c in result if c.category == "Crypto")
        log.debug("Símbolos descobertos: %d forex | %d cripto", len(result) - crypto_count, crypto_count)

    return result


def discover_forex_only_symbols(
    filter_symbols: Optional[Set[str]] = None,
) -> List[CandidatoInfo]:
    """Retorna apenas pares forex (Majors, Minors, Exotics) — exclui Crypto."""
    return [s for s in discover_symbols(filter_symbols) if s.category != "Crypto"]
