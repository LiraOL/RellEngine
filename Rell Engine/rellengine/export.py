"""Exportación al formato que lee el módulo de Foundry 'Rell Engine Importer'."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

FORMAT_ID = "rell-engine"
FORMAT_VERSION = 1

# Campos internos del generador que no hacen falta en Foundry.
_SKIP = {"budget", "warnings", "typeLabel"}


def export_payload(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    clean = []
    for item in items:
        out = {k: v for k, v in item.items() if k not in _SKIP}
        out["effects"] = [e["text"] for e in item["effects"]]
        clean.append(out)
    return {"format": FORMAT_ID, "version": FORMAT_VERSION, "items": clean}


def export_json(items: List[Dict[str, Any]]) -> str:
    return json.dumps(export_payload(items), ensure_ascii=False, indent=2)


def export_file(items: List[Dict[str, Any]], path: Path) -> None:
    Path(path).write_text(export_json(items), encoding="utf-8")
