"""Motor de generación de Rell Engine (sin dependencias externas)."""
from __future__ import annotations

import html
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import mechanics
from .tables import (
    PLACEHOLDER_RE,
    BaseObject,
    Entry,
    Manifest,
    Rarity,
    TableError,
    norm,
    parse_entry,
    parse_kv,
    parse_manifest,
    parse_object,
    parse_rarity,
    read_lines,
)

Pools = Dict[str, List[Entry]]

# Nombres antiguos de tablas que se siguen aceptando.
POOL_ALIASES = {"bases": "efectos", "epiteto": "epitetos", "sobrenombre": "sobrenombres", "tema": "temas"}
MAX_DEPTH = 6


class GenerationError(Exception):
    """No se ha podido generar un objeto con las tablas actuales."""


class _DeadEnd(Exception):
    """Intento fallido (se reintenta con otra combinación)."""


@dataclass
class TypeInfo:
    id: str
    label: str
    tags: Set[str] = field(default_factory=set)
    objects: List[BaseObject] = field(default_factory=list)
    pools: Pools = field(default_factory=dict)


@dataclass
class ExpansionInfo:
    id: str
    name: str
    version: str
    folder: Path
    enabled: bool
    error: Optional[str] = None


@dataclass
class Rules:
    attempts: int = 400
    tag_preference: int = 25
    forbidden_mixes: List[Set[str]] = field(default_factory=list)
    appearance_chance: int = 60


@dataclass
class Effect:
    text: str
    cost: int
    mech: List[Tuple[str, str]]  # (mecánicas, texto de la línea que las aporta)
    sources: List[str]


@dataclass
class _Context:
    pools: Pools
    obj: BaseObject
    obj_tags: Set[str]
    rng: random.Random
    tags: Set[str] = field(default_factory=set)
    used: Set[str] = field(default_factory=set)
    strict_tags: bool = False  # en nombres: las entradas con tags deben coincidir


class Engine:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.errors: List[str] = []
        self.rules = Rules()
        self.rarities: Dict[str, Rarity] = {}
        self.expansions: Dict[str, ExpansionInfo] = {}
        self.types: Dict[str, TypeInfo] = {}
        self.shared: Dict[str, Pools] = {}  # carpetas _tag
        self.common: Pools = {}
        self.load()

    # ------------------------------------------------------------------ carga
    def load(self) -> None:
        self.errors = []
        self.rules = Rules()
        self.rarities = {}
        self.expansions = {}
        self.types = {}
        self.shared = {}
        self.common = {}

        self._load_rules()
        self._load_common_dir(self.root / "common")

        enabled = self._read_enabled()
        exp_dir = self.root / "expansions"
        if not exp_dir.is_dir():
            self.errors.append("No existe la carpeta expansions/")
            return
        for folder in sorted(p for p in exp_dir.iterdir() if p.is_dir()):
            manifest_path = folder / "manifest.txt"
            if not manifest_path.exists():
                continue
            try:
                manifest = parse_manifest(manifest_path)
            except TableError as e:
                self.errors.append(f"{self._rel(manifest_path)}: {e}")
                self.expansions[folder.name] = ExpansionInfo(folder.name, folder.name, "?", folder, False, str(e))
                continue
            is_on = enabled is None or manifest.id in enabled
            self.expansions[manifest.id] = ExpansionInfo(manifest.id, manifest.name, manifest.version, folder, is_on)
            if is_on:
                self._load_expansion(folder, manifest)

        if not self.rarities:
            self.errors.append("No hay rarezas: falta common/rareza.txt")
        self._check_placeholders()

    def _check_placeholders(self) -> None:
        """Avisa de los {placeholders} que no tienen tabla."""
        reported: Set[str] = set()

        def check(pools: Pools, available: Set[str]) -> None:
            for entries in pools.values():
                for entry in entries:
                    for raw in PLACEHOLDER_RE.findall(entry.text + " " + entry.mech):
                        key = POOL_ALIASES.get(norm(raw), norm(raw))
                        if key not in available and entry.source not in reported:
                            reported.add(entry.source)
                            self.errors.append(f"{entry.source}: el placeholder {{{raw}}} no tiene tabla '{key}.txt'")

        common = set(self.common) | {"objeto", "objeto_min"}
        for info in self.types.values():
            if info.objects:
                pools = self._pools_for(info)
                check(pools, common | set(pools))
        check(self.common, common | {k for t in self.types.values() for k in self._pools_for(t)})

    def _rel(self, p: Path) -> str:
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return p.as_posix()

    def _load_rules(self) -> None:
        path = self.root / "config" / "rules.txt"
        if not path.exists():
            return
        for i, line in read_lines(path):
            try:
                for k, v in parse_kv(line).items():
                    if k == "intentos":
                        self.rules.attempts = max(1, int(v))
                    elif k == "preferencia_tags":
                        self.rules.tag_preference = max(1, int(v))
                    elif k == "probabilidad_apariencia":
                        self.rules.appearance_chance = min(100, max(0, int(v)))
                    elif k == "mezclas_prohibidas":
                        self.rules.forbidden_mixes = [
                            {norm(t) for t in combo.split("+") if t.strip()} for combo in v.split(",") if combo.strip()
                        ]
                    else:
                        self.errors.append(f"{self._rel(path)}:{i}: regla desconocida '{k}'")
            except (TableError, ValueError) as e:
                self.errors.append(f"{self._rel(path)}:{i}: {e}")

    def _read_enabled(self) -> Optional[Set[str]]:
        """None = no hay archivo, todas las expansiones activas."""
        path = self.root / "config" / "enabled_expansions.txt"
        if not path.exists():
            return None
        return {norm(line) for _, line in read_lines(path)}

    def save_enabled(self, enabled_ids: List[str]) -> None:
        path = self.root / "config" / "enabled_expansions.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = "# Expansiones activas, una por línea\n"
        path.write_text(header + "".join(f"{e}\n" for e in enabled_ids), encoding="utf-8")

    def _load_pool_file(self, path: Path, pools: Pools) -> None:
        key = norm(path.stem)
        key = POOL_ALIASES.get(key, key)
        out = pools.setdefault(key, [])
        for i, line in read_lines(path):
            source = f"{self._rel(path)}:{i}"
            try:
                entry = parse_entry(line, source)
                if entry.mech:
                    mechanics.check_keys(entry.mech)
                out.append(entry)
            except TableError as e:
                self.errors.append(f"{source}: {e}")

    def _load_common_dir(self, folder: Path) -> None:
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.txt")):
            if norm(path.stem) == "rareza":
                for i, line in read_lines(path):
                    try:
                        r = parse_rarity(line)
                        self.rarities[r.id] = r
                    except TableError as e:
                        self.errors.append(f"{self._rel(path)}:{i}: {e}")
            else:
                self._load_pool_file(path, self.common)

    def _load_expansion(self, folder: Path, manifest: Manifest) -> None:
        self._load_common_dir(folder / "common")

        for sub in sorted(p for p in folder.iterdir() if p.is_dir() and p.name.startswith("_")):
            pools = self.shared.setdefault(norm(sub.name[1:]), {})
            for path in sorted(sub.glob("*.txt")):
                self._load_pool_file(path, pools)

        for decl in manifest.types:
            info = self.types.setdefault(decl.type_id, TypeInfo(decl.type_id, decl.label))
            info.tags.update(decl.tags)
            type_dir = folder / decl.type_id
            if not type_dir.is_dir():
                self.errors.append(f"{self._rel(folder)}: el tipo '{decl.type_id}' no tiene carpeta")
                continue
            for path in sorted(type_dir.glob("*.txt")):
                if norm(path.stem) == "objetos":
                    for i, line in read_lines(path):
                        source = f"{self._rel(path)}:{i}"
                        try:
                            info.objects.append(parse_object(line, decl.type_id, source))
                        except TableError as e:
                            self.errors.append(f"{source}: {e}")
                else:
                    self._load_pool_file(path, info.pools)

    # --------------------------------------------------------------- consulta
    def all_tags(self) -> List[str]:
        return sorted({t for info in self.types.values() if info.objects for t in info.tags})

    def types_for_tag(self, tag: Optional[str]) -> List[TypeInfo]:
        return [
            t for t in sorted(self.types.values(), key=lambda t: t.label.lower())
            if t.objects and (not tag or tag in t.tags)
        ]

    def _pools_for(self, info: TypeInfo) -> Pools:
        merged: Pools = {k: list(v) for k, v in info.pools.items()}
        for tag in sorted(info.tags):
            for key, entries in self.shared.get(tag, {}).items():
                merged.setdefault(key, []).extend(entries)
        return merged

    @staticmethod
    def kind_of(info: TypeInfo) -> str:
        if "escudo" in info.tags:
            return "shield"
        if "armadura" in info.tags:
            return "armor"
        if "arma" in info.tags:
            return "weapon"
        return "wondrous"

    # ------------------------------------------------------------- generación
    def generate(
        self,
        rarity_id: str,
        tag: Optional[str] = None,
        type_id: Optional[str] = None,
        object_id: Optional[str] = None,
        cursed: Optional[bool] = None,
        rng: Optional[random.Random] = None,
    ) -> Dict[str, Any]:
        """Genera un objeto. ``cursed``: None = lo que permita la rareza,
        True = al menos un efecto negativo, False = ninguno."""
        rng = rng or random.Random()
        rarity = self.rarities.get(norm(rarity_id))
        if not rarity:
            raise GenerationError(f"Rareza desconocida: '{rarity_id}'")

        if type_id:
            info = self.types.get(norm(type_id))
            if not info or not info.objects:
                raise GenerationError(f"El tipo '{type_id}' no existe o no tiene objetos.txt")
        else:
            candidates = self.types_for_tag(norm(tag) if tag else None)
            if not candidates:
                raise GenerationError(f"No hay tipos con objetos para la categoría '{tag}'")
            # Se pondera por nº de objetos para que cada objeto base sea igual de probable.
            info = rng.choices(candidates, weights=[len(t.objects) for t in candidates])[0]

        if object_id:
            obj = next((o for o in info.objects if o.id == norm(object_id)), None)
            if not obj:
                raise GenerationError(f"El objeto '{object_id}' no existe en el tipo '{info.id}'")
        else:
            obj = rng.choice(info.objects)

        pools = self._pools_for(info)
        obj_tags = set(info.tags) | set(obj.tags) | {info.id, obj.id}

        effects: List[Effect] = []
        tags: Set[str] = set()
        balanced = True
        if rarity.max_effects > 0:
            if not pools.get("efectos"):
                raise GenerationError(f"El tipo '{info.id}' no tiene ninguna tabla efectos.txt")
            effects, tags, balanced = self._roll_effects(pools, obj, obj_tags, rarity, cursed, rng)

        ctx = _Context(pools=pools, obj=obj, obj_tags=obj_tags, rng=rng, tags=set(tags), strict_tags=True)
        if effects:
            name = self._roll_name(ctx)
        else:
            name = obj.name
        appearance = ""
        if self._pool(ctx, "apariencias") and rng.randrange(100) < self.rules.appearance_chance:
            try:
                appearance = _capitalize(self._expand("{apariencias}", "", ctx, 0)[0])
            except _DeadEnd:
                appearance = ""

        return self._build_item(info, obj, rarity, name, appearance, effects, tags, balanced)

    def _roll_effects(
        self, pools: Pools, obj: BaseObject, obj_tags: Set[str], rarity: Rarity, cursed: Optional[bool], rng: random.Random
    ) -> Tuple[List[Effect], Set[str], bool]:
        max_bad = 0 if cursed is False else max(rarity.max_bad, 1 if cursed else 0)
        min_bad = 1 if cursed else 0
        max_effects = max(rarity.max_effects, min_bad + 1)
        best: Optional[Tuple[int, List[Effect], Set[str]]] = None

        for _ in range(self.rules.attempts):
            ctx = _Context(pools=pools, obj=obj, obj_tags=obj_tags, rng=rng)
            n = rng.randint(min(max(rarity.min_effects, min_bad + 1), max_effects), max_effects)
            effects: List[Effect] = []
            try:
                for _i in range(n):
                    effects.append(self._roll_effect(ctx))
            except _DeadEnd:
                continue
            n_bad = sum(1 for e in effects if e.cost < 0)
            if not (min_bad <= n_bad <= max_bad) or n_bad == len(effects):
                continue
            if sum(1 for e in effects for m, _ in e.mech if "bono=" in norm(m)) > 1:
                continue
            total = sum(e.cost for e in effects)
            diff = abs(total - rarity.budget)
            if diff <= rarity.tolerance:
                return effects, ctx.tags, True
            if best is None or diff < best[0]:
                best = (diff, effects, ctx.tags)

        if best is None:
            raise GenerationError(
                f"No se pudo generar '{obj.name}' con rareza '{rarity.name}': "
                "las tablas no tienen combinaciones válidas (revisa efectos.txt y los placeholders)."
            )
        return best[1], best[2], False

    def _roll_effect(self, ctx: _Context) -> Effect:
        entry = self._pick(self._pool(ctx, "efectos"), ctx)
        ctx.used.add(entry.source)
        ctx.tags.update(entry.theme_tags)
        text, mech, cost, sources = self._expand(entry.text, entry.mech, ctx, 0)
        return Effect(text=_capitalize(text), cost=entry.cost + cost, mech=mech, sources=[entry.source] + sources)

    def _pool(self, ctx: _Context, name: str) -> List[Entry]:
        key = POOL_ALIASES.get(norm(name), norm(name))
        return ctx.pools.get(key) or self.common.get(key) or []

    def _allowed(self, entry: Entry, ctx: _Context) -> bool:
        if entry.source in ctx.used:
            return False
        if any(req not in ctx.obj_tags for req in entry.requirements):
            return False
        theme = set(entry.theme_tags)
        if ctx.strict_tags and theme and not (theme & ctx.tags):
            return False
        combined = ctx.tags | theme
        for mix in self.rules.forbidden_mixes:
            if mix <= combined and not mix <= ctx.tags:
                return False
        return True

    def _pick(self, pool: List[Entry], ctx: _Context) -> Entry:
        options = [e for e in pool if self._allowed(e, ctx)]
        if not options:
            raise _DeadEnd()
        weights = [self.rules.tag_preference if set(e.theme_tags) & ctx.tags else 1 for e in options]
        return ctx.rng.choices(options, weights=weights)[0]

    def _expand(self, text: str, mech: str, ctx: _Context, depth: int) -> Tuple[str, List[Tuple[str, str]], int, List[str]]:
        """Rellena los {placeholders}. Dentro de una misma línea, un placeholder
        repetido (también en las mecánicas) vale siempre lo mismo."""
        if depth > MAX_DEPTH:
            raise _DeadEnd()
        memo: Dict[str, str] = {}
        cost = 0
        nested: List[Tuple[str, str]] = []
        sources: List[str] = []

        def resolve(match: Any) -> str:
            nonlocal cost
            raw = match.group(1)
            key = norm(raw)
            if key in memo:
                return memo[key]
            if key == "objeto":
                value = ctx.obj.name
            elif key == "objeto_min":
                value = ctx.obj.name[:1].lower() + ctx.obj.name[1:]
            else:
                pool = self._pool(ctx, key)
                if not pool:
                    raise GenerationError(f"El placeholder {{{raw}}} no tiene ninguna tabla '{key}.txt'")
                entry = self._pick(pool, ctx)
                if entry.cost != 0:  # los rellenos de coste 0 (p. ej. {elemento}) sí pueden repetirse
                    ctx.used.add(entry.source)
                ctx.tags.update(entry.theme_tags)
                value, sub_mech, sub_cost, sub_sources = self._expand(entry.text, entry.mech, ctx, depth + 1)
                cost += entry.cost + sub_cost
                nested.extend(sub_mech)
                sources.append(entry.source)
                sources.extend(sub_sources)
            memo[key] = value
            return value

        out_text = PLACEHOLDER_RE.sub(resolve, text)
        out_mech: List[Tuple[str, str]] = []
        if mech:
            out_mech.append((PLACEHOLDER_RE.sub(resolve, mech), out_text))
        return out_text, out_mech + nested, cost, sources

    def _roll_name(self, ctx: _Context) -> str:
        if not self._pool(ctx, "plantillas_nombres"):
            return ctx.obj.name
        for _ in range(30):
            saved_used, saved_tags = set(ctx.used), set(ctx.tags)
            try:
                return _capitalize(self._expand("{plantillas_nombres}", "", ctx, 0)[0])
            except _DeadEnd:
                ctx.used, ctx.tags = saved_used, saved_tags
        return ctx.obj.name

    # ------------------------------------------------------------ resultado
    def _build_item(
        self,
        info: TypeInfo,
        obj: BaseObject,
        rarity: Rarity,
        name: str,
        appearance: str,
        effects: List[Effect],
        tags: Set[str],
        balanced: bool,
    ) -> Dict[str, Any]:
        kind = self.kind_of(info)
        mech: Dict[str, Any] = {}
        warnings: List[str] = []
        for eff in effects:
            for mech_str, mech_text in eff.mech:
                try:
                    mechanics.apply(mech_str, _capitalize(mech_text), mech)
                except TableError as e:
                    warnings.append(f"{eff.sources[0]}: {e}")
        if not balanced:
            warnings.append("No se encontró una combinación dentro del presupuesto; se usó la más cercana.")

        magical = bool(effects)
        base = _base_data(obj, info, kind, warnings)
        price = base.get("price", 0) + (rarity.price if magical else 0)
        item: Dict[str, Any] = {
            "name": name,
            "kind": kind,
            "typeId": info.id,
            "typeLabel": info.label,
            "base": base,
            "magical": magical,
            "rarity": rarity.foundry if magical else "",
            "rarityLabel": rarity.name,
            "attunement": bool(mech.get("attunement")),
            "magicalBonus": mech.get("magicalBonus"),
            "appearance": appearance,
            "effects": [{"text": e.text, "cost": e.cost, "sources": e.sources} for e in effects],
            "extraDamage": mech.get("extraDamage", []),
            "changes": mech.get("changes", []),
            "properties": mech.get("properties", []),
            "activities": mech.get("activities", []),
            "price": price,
            "tags": sorted(tags),
            "budget": {"target": rarity.budget, "total": sum(e.cost for e in effects), "balanced": balanced},
            "warnings": warnings,
        }
        item["descriptionHtml"] = render_html(item)
        return item


# ---------------------------------------------------------------- utilidades
def _capitalize(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:]


def _num(data: Dict[str, str], key: str, warnings: List[str], obj: BaseObject) -> Optional[float]:
    raw = data.get(key, "").strip()
    if not raw:
        return None
    try:
        value = float(raw.replace(",", "."))
        return int(value) if value.is_integer() else value
    except ValueError:
        warnings.append(f"{obj.source}: '{key}={raw}' no es un número")
        return None


def _base_data(obj: BaseObject, info: TypeInfo, kind: str, warnings: List[str]) -> Dict[str, Any]:
    d = obj.data
    base: Dict[str, Any] = {
        "id": obj.id,
        "name": obj.name,
        "foundry": d.get("foundry", ""),
        "weight": _num(d, "peso", warnings, obj) or 0,
        "price": _num(d, "precio", warnings, obj) or 0,
    }
    if kind == "weapon":
        ranged = "a_distancia" in info.tags
        martial = norm(d.get("categoria", "simple")) in ("marcial", "martial")
        base["weaponType"] = ("martial" if martial else "simple") + ("R" if ranged else "M")
        if d.get("dano"):
            try:
                base["damage"] = mechanics.parse_damage(d["dano"])
            except TableError as e:
                warnings.append(f"{obj.source}: {e}")
        if d.get("versatil"):
            try:
                base["versatile"] = mechanics.parse_damage(d["versatil"] + " " + d.get("dano", "x x").split()[-1])
            except TableError as e:
                warnings.append(f"{obj.source}: {e}")
        props = []
        for raw in d.get("propiedades", "").split(","):
            if raw.strip():
                prop = mechanics.WEAPON_PROPERTIES.get(norm(raw))
                if prop:
                    props.append(prop)
                else:
                    warnings.append(f"{obj.source}: propiedad desconocida '{raw.strip()}'")
        base["properties"] = props
        if d.get("alcance"):
            short, _, long = d["alcance"].partition("/")
            try:
                base["range"] = {"value": int(short), "long": int(long) if long else None}
            except ValueError:
                warnings.append(f"{obj.source}: alcance no válido '{d['alcance']}'")
    elif kind in ("armor", "shield"):
        base["ac"] = _num(d, "ca", warnings, obj)
        armor_class = norm(d.get("clase", "escudo" if kind == "shield" else "ligera"))
        base["armorType"] = {"ligera": "light", "media": "medium", "pesada": "heavy", "escudo": "shield"}.get(
            armor_class, "light"
        )
        base["dexCap"] = _num(d, "des", warnings, obj)  # None = sin límite
        base["strength"] = _num(d, "fuerza", warnings, obj)
        base["stealthDisadvantage"] = norm(d.get("sigilo", "")) == "desventaja"
    else:
        base["equipmentType"] = d.get("foundry_tipo", "trinket")
    return base


KIND_LABELS = {"weapon": "Arma", "armor": "Armadura", "shield": "Escudo", "wondrous": "Objeto maravilloso"}


def stats_line(item: Dict[str, Any]) -> str:
    base = item["base"]
    parts: List[str] = []
    if item["kind"] == "weapon":
        dmg = base.get("damage")
        if dmg:
            raw = _damage_text(dmg)
            if base.get("versatile"):
                v = base["versatile"]
                raw += f" (versátil {v['number']}d{v['denomination']})"
            parts.append(f"Daño: {raw}")
        if base.get("range"):
            r = base["range"]
            parts.append("Alcance: " + (f"{r['value']}/{r['long']} pies" if r.get("long") else f"{r['value']} pies"))
        if base.get("properties"):
            parts.append("Propiedades: " + ", ".join(mechanics.PROPERTY_LABELS.get(p, p) for p in base["properties"]))
    elif item["kind"] in ("armor", "shield"):
        if base.get("ac") is not None:
            if item["kind"] == "shield":
                parts.append(f"CA: +{base['ac']}")
            else:
                cap = base.get("dexCap")
                mod = "" if cap == 0 else (" + mod. Des" if cap is None else f" + mod. Des (máx. {cap})")
                parts.append(f"CA: {base['ac']}{mod}")
        if base.get("strength"):
            parts.append(f"Fuerza mínima: {base['strength']}")
        if base.get("stealthDisadvantage"):
            parts.append("Sigilo: desventaja")
    if base.get("weight"):
        parts.append(f"Peso: {base['weight']} lb")
    if item.get("price"):
        parts.append(f"Precio: {item['price']} po")
    return " · ".join(parts)


_DAMAGE_ES = {v: k for k, v in mechanics.DAMAGE_TYPES.items() if k != v and k != "rayo"}


def _damage_text(dmg: Dict[str, Any]) -> str:
    dice = f"{dmg['number']}d{dmg['denomination']}" if dmg.get("number") else ""
    bonus = str(dmg.get("bonus") or "")
    if dice and bonus:
        dice += bonus if bonus.startswith("-") else f"+{bonus}"
    return f"{dice or bonus} {_DAMAGE_ES.get(dmg['type'], dmg['type'])}"


def subtitle(item: Dict[str, Any]) -> str:
    line = f"{KIND_LABELS[item['kind']]} ({item['base']['name'].lower()})"
    if item["magical"]:
        line += f" · Rareza: {item['rarityLabel'].lower()}"
        if item["attunement"]:
            line += " · Requiere sintonización"
    else:
        line += " · Objeto no mágico"
    return line


def render_text(item: Dict[str, Any], debug: bool = False) -> str:
    lines = [item["name"], subtitle(item)]
    stats = stats_line(item)
    if stats:
        lines.append(stats)
    if item["appearance"]:
        lines += ["", item["appearance"]]
    if item["effects"]:
        lines.append("")
        lines += [f"• {e['text']}" for e in item["effects"]]
    if debug:
        b = item["budget"]
        lines += ["", f"[Presupuesto: {b['total']} de {b['target']}]"]
        for e in item["effects"]:
            lines.append(f"[{e['cost']:+d}] " + ", ".join(e["sources"]))
    for w in item["warnings"]:
        lines.append(f"⚠ {w}")
    return "\n".join(lines)


def render_html(item: Dict[str, Any]) -> str:
    """Descripción que verá el jugador en la ficha del objeto en Foundry."""
    esc = html.escape
    parts = [f"<p><em>{esc(subtitle(item))}</em></p>"]
    if item["appearance"]:
        parts.append(f"<p>{esc(item['appearance'])}</p>")
    parts += [f"<p>{esc(e['text'])}</p>" for e in item["effects"]]
    return "".join(parts)
