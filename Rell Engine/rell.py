#!/usr/bin/env python3
"""Rell Engine: generador de objetos para D&D 5e.

Sin argumentos abre la aplicación de escritorio. Con argumentos funciona
por línea de comandos (ver ``python rell.py --help``).
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from rellengine.cli import main
    else:
        from rellengine.gui import main
    sys.exit(main())
