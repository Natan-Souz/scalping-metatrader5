"""
core.logging_setup
Configura o logger root com handlers de console (INFO) e arquivo (DEBUG).
Todos os módulos do projeto usam logging.getLogger(__name__) e propagam
automaticamente para os handlers configurados aqui.
"""

import sys
import logging


def setup_logging(log_file: str) -> None:
    """
    Configura o logger root uma única vez.
    Chamadas subsequentes são ignoradas (handlers já existentes).

    Args:
        log_file: caminho do arquivo .log a ser criado/aberto em modo append.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # já configurado — evita duplicação em re-imports

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
