"""Lectura de las tablas de texto de Rell Engine.

Formatos admitidos (una entrada por línea, ``#`` para comentarios):

* Tablas normales:   ``coste|texto``
                     ``coste|tags|texto``
                     ``coste|tags|texto|mecánicas``
* objetos.txt:       ``id|Nombre|clave=valor;clave=valor``
* rareza.txt:        ``id|Nombre|presupuesto|tolerancia|efectos|max_malos|foundry|precio``
* manifest/config:   ``clave=valor``
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

SEP = "|"
PLACEHOLDER_RE = re.compile(r"\{([^{}|]+)\}")


class TableError(ValueError):
    """Línea de tabla mal formada."""


def norm(s: str) -> str:
    """Normaliza un identificador: minúsculas, sin tildes, espacios -> '_'."""
    s = unicodedata.normalize("NFD", s.strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", "_", s)


def read_lines(path: Path) -> List[Tuple[int, str]]:
    """Devuelve (nº de línea, texto) ignorando comentarios y líneas vacías."""
    out: List[Tuple[int, str]] = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if s and not s.startswith("#"):
            out.append((i, s))
    return out


def parse_kv(s: str, sep: str = ";") -> Dict[str, str]:
    """``a=1;b=2`` -> {"a": "1", "b": "2"} (claves normalizadas)."""
    out: Dict[str, str] = {}
    for part in s.split(sep):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise TableError(f"se esperaba clave=valor en '{part}'")
        k, v = part.split("=", 1)
        out[norm(k)] = v.strip()
    return out


def parse_kv_list(s: str, sep: str = ";") -> List[Tuple[str, str]]:
    """Como parse_kv pero conserva claves repetidas y el orden."""
    out: List[Tuple[str, str]] = []
    for part in s.split(sep):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise TableError(f"se esperaba clave=valor en '{part}'")
        k, v = part.split("=", 1)
        out.append((norm(k), v.strip()))
    return out


def parse_bool(v: str) -> bool:
    return norm(v) in ("true", "1", "si", "yes", "y", "on", "verdadero")


def parse_tags(raw: str) -> Tuple[str, ...]:
    raw = raw.strip()
    if raw in ("", "-"):
        return tuple()
    return tuple(norm(t) for t in raw.split(",") if t.strip())


@dataclass(frozen=True)
class Entry:
    cost: int
    tags: Tuple[str, ...]
    text: str
    mech: str
    source: str  # "ruta/relativa.txt:línea"

    @property
    def theme_tags(self) -> Tuple[str, ...]:
        return tuple(t for t in self.tags if not t.startswith("solo:"))

    @property
    def requirements(self) -> Tuple[str, ...]:
        return tuple(t[5:] for t in self.tags if t.startswith("solo:"))


def parse_entry(line: str, source: str) -> Entry:
    parts = [p.strip() for p in line.split(SEP)]
    if len(parts) == 2:
        cost, tags, text, mech = parts[0], "", parts[1], ""
    elif len(parts) == 3:
        cost, tags, text = parts
        mech = ""
    elif len(parts) == 4:
        cost, tags, text, mech = parts
    else:
        raise TableError("formato esperado: coste|texto, coste|tags|texto o coste|tags|texto|mecánicas")
    try:
        cost_i = int(cost)
    except ValueError:
        raise TableError(f"el coste '{cost}' no es un número entero") from None
    if not text:
        raise TableError("el texto está vacío")
    return Entry(cost=cost_i, tags=parse_tags(tags), text=text, mech=mech, source=source)


@dataclass
class BaseObject:
    """Objeto base (p. ej. 'espada larga') sobre el que se aplican los efectos."""

    id: str
    name: str
    type_id: str
    data: Dict[str, str]
    tags: Tuple[str, ...]
    source: str


def parse_object(line: str, type_id: str, source: str) -> BaseObject:
    parts = [p.strip() for p in line.split(SEP, 2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise TableError("formato esperado: id|Nombre|clave=valor;clave=valor")
    data = parse_kv(parts[2]) if len(parts) == 3 else {}
    tags = list(parse_tags(data.get("tags", "")))
    # Las propiedades del arma también cuentan como tags (para 'solo:arrojadiza', etc.)
    tags += [norm(p) for p in data.get("propiedades", "").split(",") if p.strip()]
    return BaseObject(id=norm(parts[0]), name=parts[1], type_id=type_id, data=data, tags=tuple(tags), source=source)


@dataclass
class Rarity:
    id: str
    name: str
    budget: int
    tolerance: int
    min_effects: int
    max_effects: int
    max_bad: int
    foundry: str
    price: int


def parse_rarity(line: str) -> Rarity:
    parts = [p.strip() for p in line.split(SEP)]
    if len(parts) < 6:
        raise TableError("formato esperado: id|Nombre|presupuesto|tolerancia|efectos|max_malos|foundry|precio")
    parts += [""] * (8 - len(parts))
    rid, name, budget, tol, effects, max_bad, foundry, price = parts[:8]
    try:
        if "-" in effects:
            lo, hi = (int(x) for x in effects.split("-", 1))
        else:
            lo = hi = int(effects)
        return Rarity(norm(rid), name, int(budget), int(tol), lo, hi, int(max_bad), foundry, int(price or 0))
    except ValueError:
        raise TableError("presupuesto, tolerancia, efectos, max_malos y precio deben ser números") from None


@dataclass
class TypeDecl:
    type_id: str
    tags: Tuple[str, ...]
    label: str


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    types: List[TypeDecl] = field(default_factory=list)


def parse_manifest(path: Path) -> Manifest:
    raw: Dict[str, List[str]] = {}
    for i, line in read_lines(path):
        if "=" not in line:
            raise TableError(f"manifest.txt línea {i}: falta '='")
        k, v = line.split("=", 1)
        raw.setdefault(norm(k), []).append(v.strip())

    def get1(key: str) -> str:
        return (raw.get(key) or [""])[0]

    if not get1("id") or not get1("name"):
        raise TableError("manifest.txt debe incluir id= y name=")

    types: List[TypeDecl] = []
    for decl in raw.get("type", []) + raw.get("tipo", []):
        parts = [p.strip() for p in decl.split(SEP) if p.strip()]
        if not parts:
            continue
        tags: Tuple[str, ...] = tuple()
        label = parts[0]
        for p in parts[1:]:
            k, _, v = p.partition("=")
            if norm(k) == "tags":
                tags = parse_tags(v)
            elif norm(k) in ("nombre", "name"):
                label = v.strip()
        types.append(TypeDecl(type_id=norm(parts[0]), tags=tags, label=label))
    return Manifest(id=norm(get1("id")), name=get1("name"), version=get1("version") or "1.0.0", types=types)
