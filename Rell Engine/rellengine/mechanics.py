"""Traduce el campo 'mecánicas' de las tablas a datos que Foundry entiende.

Claves admitidas (separadas por ``;``):

  bono=1                     bonificador mágico (ataque/daño en armas, CA en armaduras)
  daño=1d6 fuego             daño adicional en cada impacto del arma
  ca=1                       +1 a la CA de quien lo lleva (efecto pasivo)
  salvaciones=1              +1 a todas las tiradas de salvación
  resistencia=fuego,frío     resistencia a tipos de daño
  inmunidad=veneno           inmunidad a tipos de daño
  vulnerabilidad=radiante    vulnerabilidad a tipos de daño
  velocidad=10               +10 pies de velocidad caminando
  propiedad=sutil            añade una propiedad al arma
  sintonizacion=si           el objeto requiere sintonización
  usos=1/amanecer            poder con usos limitados (dia, amanecer, anochecer,
                             descanso_largo, descanso_corto)
  activacion=adicional       accion (por defecto), adicional o reaccion
  poder=Nombre del poder     nombre del poder en la ficha
  ae=clave modo valor        efecto activo libre de Foundry (modo: add, override,
                             upgrade, downgrade, multiply)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .tables import TableError, norm, parse_bool, parse_kv_list

DAMAGE_TYPES = {
    "acido": "acid", "contundente": "bludgeoning", "frio": "cold", "fuego": "fire",
    "fuerza": "force", "relampago": "lightning", "rayo": "lightning", "necrotico": "necrotic",
    "perforante": "piercing", "veneno": "poison", "psiquico": "psychic", "radiante": "radiant",
    "cortante": "slashing", "trueno": "thunder",
}
DAMAGE_TYPES.update({v: v for v in list(DAMAGE_TYPES.values())})

WEAPON_PROPERTIES = {
    "municion": "amm", "sutil": "fin", "pesada": "hvy", "ligera": "lgt", "recarga": "lod",
    "alcance": "rch", "arrojadiza": "thr", "a_dos_manos": "two", "dos_manos": "two",
    "versatil": "ver", "especial": "spc", "plateada": "sil", "adamantina": "ada",
    "retorno": "ret", "magica": "mgc",
}
WEAPON_PROPERTIES.update({v: v for v in list(WEAPON_PROPERTIES.values())})

USE_PERIODS = {
    "dia": "day", "amanecer": "dawn", "anochecer": "dusk", "atardecer": "dusk",
    "descanso_largo": "lr", "descanso_corto": "sr", "day": "day", "dawn": "dawn",
    "dusk": "dusk", "lr": "lr", "sr": "sr",
}
ACTIVATIONS = {
    "accion": "action", "adicional": "bonus", "accion_adicional": "bonus",
    "reaccion": "reaction", "especial": "special", "action": "action",
    "bonus": "bonus", "reaction": "reaction",
}
AE_MODES = ("add", "override", "upgrade", "downgrade", "multiply")

KNOWN_KEYS = {
    "bono", "dano", "ca", "salvaciones", "resistencia", "inmunidad", "vulnerabilidad",
    "velocidad", "propiedad", "sintonizacion", "usos", "activacion", "poder", "ae",
}

PROPERTY_LABELS = {
    "amm": "munición", "fin": "sutil", "hvy": "pesada", "lgt": "ligera", "lod": "recarga",
    "rch": "alcance", "thr": "arrojadiza", "two": "a dos manos", "ver": "versátil",
    "spc": "especial", "sil": "plateada", "ada": "adamantina", "ret": "retorno", "mgc": "mágica",
}


def damage_type(raw: str) -> str:
    """'fuego', 'de fuego', 'Psíquico' o 'fire' -> id de dnd5e."""
    key = norm(raw)
    if key.startswith("de_"):
        key = key[3:]
    dtype = DAMAGE_TYPES.get(key)
    if not dtype:
        raise TableError(f"tipo de daño desconocido: '{raw.strip()}'")
    return dtype


DAMAGE_RE = re.compile(r"^(?:(\d+)d(\d+))?\s*([+-]?\s*\d+)?\s+(\S.*)$")


def parse_damage(value: str) -> Dict[str, Any]:
    """'1d6 fuego', '2d4+1 frío' o '2 radiante' -> parte de daño."""
    m = DAMAGE_RE.match(value.strip())
    if not m or (m.group(1) is None and m.group(3) is None):
        raise TableError(f"daño no reconocido: '{value}' (ejemplo válido: 1d6 fuego)")
    dtype = damage_type(m.group(4))
    bonus = (m.group(3) or "").replace(" ", "").lstrip("+")
    return {
        "number": int(m.group(1)) if m.group(1) else None,
        "denomination": int(m.group(2)) if m.group(2) else None,
        "bonus": bonus,
        "type": dtype,
    }


def _damage_types(value: str) -> List[str]:
    return [damage_type(raw) for raw in value.split(",")]


def _int(value: str, key: str) -> int:
    try:
        return int(value.replace(" ", ""))
    except ValueError:
        raise TableError(f"{key}= espera un número entero, no '{value}'") from None


def check_keys(mech: str) -> None:
    """Validación al cargar: solo comprueba que las claves existan."""
    for key, _ in parse_kv_list(mech):
        if key not in KNOWN_KEYS:
            raise TableError(f"mecánica desconocida: '{key}'")


def apply(mech: str, text: str, out: Dict[str, Any]) -> None:
    """Aplica una cadena de mecánicas (ya sin placeholders) sobre ``out``.

    ``out`` acumula: magicalBonus, attunement, extraDamage, changes,
    properties y activities.
    """
    pairs = parse_kv_list(mech)
    if not pairs:
        return
    uses = None
    activation = "action"
    power_name = ""
    for key, value in pairs:
        if key == "bono":
            out["magicalBonus"] = (out.get("magicalBonus") or 0) + _int(value, key)
        elif key == "dano":
            out.setdefault("extraDamage", []).append(parse_damage(value))
        elif key == "ca":
            _change(out, "system.attributes.ac.bonus", "add", f"{_int(value, key):+d}")
        elif key == "salvaciones":
            _change(out, "system.bonuses.abilities.save", "add", f"{_int(value, key):+d}")
        elif key == "velocidad":
            _change(out, "system.attributes.movement.walk", "add", str(_int(value, key)))
        elif key in ("resistencia", "inmunidad", "vulnerabilidad"):
            trait = {"resistencia": "dr", "inmunidad": "di", "vulnerabilidad": "dv"}[key]
            for dtype in _damage_types(value):
                _change(out, f"system.traits.{trait}.value", "add", dtype)
        elif key == "propiedad":
            for raw in value.split(","):
                prop = WEAPON_PROPERTIES.get(norm(raw))
                if not prop:
                    raise TableError(f"propiedad desconocida: '{raw.strip()}'")
                if prop not in out.setdefault("properties", []):
                    out["properties"].append(prop)
        elif key == "sintonizacion":
            out["attunement"] = out.get("attunement", False) or parse_bool(value)
        elif key == "usos":
            amount, _, period = value.partition("/")
            period_id = USE_PERIODS.get(norm(period or "dia"))
            if not period_id:
                raise TableError(f"periodo de usos desconocido: '{period}'")
            uses = {"max": _int(amount, key), "period": period_id}
        elif key == "activacion":
            activation = ACTIVATIONS.get(norm(value), "")
            if not activation:
                raise TableError(f"activación desconocida: '{value}'")
        elif key == "poder":
            power_name = value
        elif key == "ae":
            parts = value.split(None, 2)
            if len(parts) != 3 or parts[1] not in AE_MODES:
                raise TableError(f"ae= espera 'clave modo valor' (modo: {', '.join(AE_MODES)})")
            _change(out, parts[0], parts[1], parts[2])
        else:
            raise TableError(f"mecánica desconocida: '{key}'")

    if uses or power_name:
        out.setdefault("activities", []).append(
            {"name": power_name or "Poder", "text": text, "activation": activation, "uses": uses}
        )


def _change(out: Dict[str, Any], key: str, mode: str, value: str) -> None:
    out.setdefault("changes", []).append({"key": key, "mode": mode, "value": value})
