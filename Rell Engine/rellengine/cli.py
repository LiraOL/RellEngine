"""Línea de comandos de Rell Engine."""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import List, Optional

from .engine import Engine, GenerationError, render_text
from .export import export_file


def main(argv: Optional[List[str]] = None) -> int:
    root_default = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(prog="rell.py", description="Generador de objetos para D&D 5e")
    p.add_argument("--root", type=Path, default=root_default, help="carpeta con common/, config/ y expansions/")
    p.add_argument("-r", "--rareza", default="raro", help="id de la rareza (ver --listar)")
    p.add_argument("-c", "--categoria", help="tag de categoría: arma, armadura, joya...")
    p.add_argument("-t", "--tipo", help="tipo concreto: espada, arco, escudo...")
    p.add_argument("-o", "--objeto", help="objeto base concreto (requiere --tipo): espada_larga...")
    p.add_argument("-n", "--cantidad", type=int, default=1, help="nº de objetos a generar")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--maldito", action="store_true", help="fuerza al menos un efecto negativo")
    group.add_argument("--sin-malos", action="store_true", help="no permite efectos negativos")
    p.add_argument("--semilla", type=int, help="semilla para repetir resultados")
    p.add_argument("--exportar", type=Path, metavar="ARCHIVO.json", help="guarda los objetos para Foundry")
    p.add_argument("--debug", action="store_true", help="muestra costes y líneas de origen")
    p.add_argument("--listar", action="store_true", help="muestra rarezas, categorías y tipos disponibles")
    p.add_argument("--comprobar", action="store_true", help="revisa las tablas y muestra los errores")
    args = p.parse_args(argv)

    engine = Engine(args.root)
    if engine.errors:
        print(f"Se encontraron {len(engine.errors)} problemas en las tablas:", file=sys.stderr)
        for err in engine.errors:
            print(f"  - {err}", file=sys.stderr)
    if args.comprobar:
        if not engine.errors:
            print("Tablas correctas.")
        return 1 if engine.errors else 0

    if args.listar:
        print("Rarezas:    " + ", ".join(engine.rarities))
        print("Categorías: " + ", ".join(engine.all_tags()))
        print("Tipos:")
        for t in engine.types_for_tag(None):
            print(f"  {t.id:18} {t.label} [{', '.join(sorted(t.tags))}]: " + ", ".join(o.id for o in t.objects))
        return 0

    if args.objeto and not args.tipo:
        p.error("--objeto requiere --tipo")
    cursed = True if args.maldito else (False if args.sin_malos else None)
    rng = random.Random(args.semilla)
    items = []
    for i in range(max(1, args.cantidad)):
        try:
            item = engine.generate(args.rareza, tag=args.categoria, type_id=args.tipo,
                                   object_id=args.objeto, cursed=cursed, rng=rng)
        except GenerationError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        items.append(item)
        if i:
            print("\n" + "-" * 60 + "\n")
        print(render_text(item, debug=args.debug))

    if args.exportar:
        export_file(items, args.exportar)
        print(f"\nExportado para Foundry: {args.exportar}")
    return 0
