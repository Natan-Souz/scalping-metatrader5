"""
core.logging_setup
Configura o logger root com handlers de console (INFO) e arquivo (DEBUG).
Todos os módulos do projeto usam logging.getLogger(__name__) e propagam
automaticamente para os handlers configurados aqui.
"""

import sys
import logging
from pathlib import Path


def setup_logging(log_file: str) -> None:
    """
    Configura o logger root uma única vez.
    Chamadas subsequentes são ignoradas (handlers já existentes).
    Cria a pasta do arquivo de log se ela não existir.

    Args:
        log_file: caminho do arquivo .log (ex: "logs/forex_scanner.log").
    """
    root = logging.getLogger()
    if root.handlers:
        return  # já configurado — evita duplicação em re-imports

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    root.setLevel(logging.DEBUG)
    fmt     = logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s", "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    root.addHandler(ch)
    root.addHandler(fh)
