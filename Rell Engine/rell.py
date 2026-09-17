
from __future__ import annotations

import random
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
from packaging.version import InvalidVersion, Version
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

SEP = "|"

CURLY_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_\-]+)\}")
SQUARE_PLACEHOLDER_RE = re.compile(r"\[([a-zA-Z0-9_\-]+)\]")

# Alias singular/plural: si el placeholder no existe como pool, busca alternativas.
PLACEHOLDER_ALIASES: Dict[str, List[str]] = {
    "epiteto": ["epiteto", "epitetos"],
    "epitetos": ["epitetos", "epiteto"],
    "sobrenombre": ["sobrenombre", "sobrenombres"],
    "sobrenombres": ["sobrenombres", "sobrenombre"],
    "tema": ["tema", "temas"],
    "temas": ["temas", "tema"],
    "names_base": ["names_base"],
    # puedes añadir más alias aquí si lo necesitas
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def is_comment_or_empty(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def safe_rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


@dataclass(frozen=True)
class Entry:
    cost: int
    tags: Tuple[str, ...]
    text: str
    source: str  # "expansion_id:relative_path:line_no"


def parse_int_cost(s: str) -> int:
    return int(s.strip())


def parse_line_A(line: str) -> Tuple[int, str]:
    parts = [p.strip() for p in line.split(SEP, 1)]
    if len(parts) != 2:
        raise ValueError("Formato esperado: coste|texto")
    return parse_int_cost(parts[0]), parts[1]


def parse_line_B(line: str) -> Tuple[int, Tuple[str, ...], str]:
    parts = [p.strip() for p in line.split(SEP, 2)]
    if len(parts) != 3:
        raise ValueError("Formato esperado: coste|tags|texto")
    cost = parse_int_cost(parts[0])
    tags_raw = parts[1].strip()
    tags = tuple(t.strip().lower() for t in tags_raw.split(",") if t.strip()) if tags_raw != "-" else tuple()
    return cost, tags, parts[2]


def parse_any_entry(line: str) -> Tuple[int, Tuple[str, ...], str]:
    parts = [p.strip() for p in line.split(SEP)]
    if len(parts) == 2:
        c, t = parse_line_A(line)
        return c, tuple(), t
    if len(parts) >= 3:
        return parse_line_B(SEP.join(parts[:3]))
    raise ValueError("Formato inválido")


# -----------------------------
# Manifest
# -----------------------------
@dataclass
class ManifestTypeDecl:
    type_id: str
    tags: Tuple[str, ...]


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    update_url: Optional[str]
    provides_types: bool
    provides_appearances: bool
    name_unique: bool
    name_unique_scope: str  # expansion|type|global
    name_list: str
    common_files: List[str]
    types: List[ManifestTypeDecl]
    raw: Dict[str, List[str]]


def parse_manifest(path: Path) -> Manifest:
    raw: Dict[str, List[str]] = {}
    for i, line in enumerate(read_text(path).splitlines(), start=1):
        if is_comment_or_empty(line):
            continue
        if "=" not in line:
            raise ValueError(f"Manifest inválido (sin '=') en {safe_rel(path, path.parent)}:{i}")
        k, v = line.split("=", 1)
        raw.setdefault(k.strip(), []).append(v.strip())

    def get1(key: str, default: Optional[str] = None) -> Optional[str]:
        vals = raw.get(key, [])
        return vals[0] if vals else default

    def get_bool(key: str, default: bool = False) -> bool:
        v = get1(key, None)
        if v is None:
            return default
        return v.strip().lower() in ("true", "1", "yes", "y", "on")

    exp_id = get1("id")
    name = get1("name")
    version = get1("version")
    if not exp_id or not name or not version:
        raise ValueError("Manifest debe incluir id=, name=, version=")

    update_url = get1("update_url", None)
    provides_types = get_bool("provides_types", False)
    provides_appearances = get_bool("provides_appearances", False)

    name_unique = get_bool("name_unique", False)
    name_unique_scope = (get1("name_unique_scope", "expansion") or "expansion").strip()
    if name_unique_scope not in ("expansion", "type", "global"):
        name_unique_scope = "expansion"

    name_list = (get1("name_list", "nombres.txt") or "nombres.txt").strip()
    common_files = raw.get("common", [])

    types: List[ManifestTypeDecl] = []
    for decl in raw.get("type", []):
        parts = [p.strip() for p in decl.split("|") if p.strip()]
        if not parts:
            continue
        type_id = parts[0]
        tags: Tuple[str, ...] = tuple()
        for p in parts[1:]:
            if p.startswith("tags="):
                tags = tuple(t.strip().lower() for t in p[len("tags=") :].split(",") if t.strip())
        types.append(ManifestTypeDecl(type_id=type_id, tags=tags))

    return Manifest(
        id=exp_id,
        name=name,
        version=version,
        update_url=update_url,
        provides_types=provides_types,
        provides_appearances=provides_appearances,
        name_unique=name_unique,
        name_unique_scope=name_unique_scope,
        name_list=name_list,
        common_files=common_files,
        types=types,
        raw=raw,
    )


@dataclass
class Rarity:
    rid: str
    name: str
    target: int
    tol: int
    max_good: int
    max_bad: int


@dataclass
class EngineConfig:
    language: str = "es-ES"
    fallback_when_unique_names_exhausted: bool = True


@dataclass
class RulesConfig:
    budget_tolerance: int = 1
    max_stat_adjustments: int = 2


@dataclass
class ExpansionInfo:
    folder: Path
    manifest_path: Path
    manifest: Manifest
    enabled: bool
    load_error: Optional[str] = None
    remote_version: Optional[str] = None
    update_status: str = "—"


class PoolIndex:
    def __init__(self) -> None:
        self.common: Dict[str, List[Entry]] = {}
        self.by_type: Dict[str, Dict[str, List[Entry]]] = {}
        self.tag_to_types: Dict[str, Set[str]] = {}
        self.type_tags: Dict[str, Set[str]] = {}


class RellEngine:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config_dir = root / "config"
        self.exp_dir = root / "expansions"
        self.state_dir = self.config_dir / "state"
        self.common_dir = root / "common"
        self.legacy_common_dir = self.config_dir / "common"

        self.engine_config = EngineConfig()
        self.rules = RulesConfig()
        self.rarities: List[Rarity] = []

        self.expansions: Dict[str, ExpansionInfo] = {}
        self.pool = PoolIndex()
        self.used_names: Set[str] = set()
        self.last_errors: List[str] = []

    # -----------------------------
    # Load config / expansions
    # -----------------------------
    def load_config_files(self) -> None:
        self.last_errors.clear()
        self.engine_config = EngineConfig()
        self.rules = RulesConfig()

        cfg_path = self.config_dir / "config.txt"
        if cfg_path.exists():
            for i, line in enumerate(read_text(cfg_path).splitlines(), start=1):
                if is_comment_or_empty(line):
                    continue
                if "=" not in line:
                    self.last_errors.append(f"config.txt línea {i}: sin '='")
                    continue
                k, v = [x.strip() for x in line.split("=", 1)]
                if k == "language":
                    self.engine_config.language = v
                elif k == "fallback_when_unique_names_exhausted":
                    self.engine_config.fallback_when_unique_names_exhausted = v.lower() in (
                        "true",
                        "1",
                        "yes",
                        "y",
                        "on",
                    )

        rules_path = self.config_dir / "rules.txt"
        if rules_path.exists():
            for i, line in enumerate(read_text(rules_path).splitlines(), start=1):
                if is_comment_or_empty(line):
                    continue
                if "=" not in line:
                    self.last_errors.append(f"rules.txt línea {i}: sin '='")
                    continue
                k, v = [x.strip() for x in line.split("=", 1)]
                if k == "budget_tolerance":
                    self.rules.budget_tolerance = int(v)
                elif k == "max_stat_adjustments":
                    self.rules.max_stat_adjustments = int(v)

        # Used unique tokens
        used_path = self.state_dir / "used_lines.txt"
        self.used_names.clear()
        if used_path.exists():
            for line in read_text(used_path).splitlines():
                if is_comment_or_empty(line):
                    continue
                self.used_names.add(line.strip())

        self.rarities = self._load_merged_rarities()

    def _read_enabled_expansions(self) -> Set[str]:
        p = self.config_dir / "enabled_expansions.txt"
        if not p.exists():
            return set()
        enabled = set()
        for line in read_text(p).splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            enabled.add(s)
        return enabled

    def save_enabled_expansions(self) -> None:
        p = self.config_dir / "enabled_expansions.txt"
        lines = [eid for eid, e in self.expansions.items() if e.enabled and e.load_error is None]
        write_text(p, "\n".join(lines) + ("\n" if lines else ""))

    def _iter_common_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        for d in (self.common_dir, self.legacy_common_dir):
            if d.exists() and d.is_dir() and d not in dirs:
                dirs.append(d)
        return dirs

    def load_expansions(self) -> None:
        self.expansions.clear()
        enabled = self._read_enabled_expansions()

        if not self.exp_dir.exists():
            self.last_errors.append("No existe la carpeta expansions/")
            return

        for folder in sorted(self.exp_dir.iterdir()):
            if not folder.is_dir():
                continue
            manifest_path = folder / "manifest.txt"
            if not manifest_path.exists():
                continue
            try:
                m = parse_manifest(manifest_path)
                self.expansions[m.id] = ExpansionInfo(
                    folder=folder, manifest_path=manifest_path, manifest=m, enabled=(m.id in enabled)
                )
            except Exception as e:
                err_id = folder.name
                dummy = Manifest(
                    id=err_id,
                    name=err_id,
                    version="0.0.0",
                    update_url=None,
                    provides_types=False,
                    provides_appearances=False,
                    name_unique=False,
                    name_unique_scope="expansion",
                    name_list="nombres.txt",
                    common_files=[],
                    types=[],
                    raw={},
                )
                self.expansions[err_id] = ExpansionInfo(
                    folder=folder, manifest_path=manifest_path, manifest=dummy, enabled=False, load_error=str(e)
                )

        self.rebuild_pool_index()
        self.rarities = self._load_merged_rarities()

    # -----------------------------
    # Pools
    # -----------------------------
    def rebuild_pool_index(self) -> None:
        self.pool = PoolIndex()

        self._load_common_pools()

        # type pools
        for eid, info in self.expansions.items():
            if info.load_error or not info.enabled:
                continue
            for td in info.manifest.types:
                type_dir = info.folder / td.type_id
                if type_dir.exists() and type_dir.is_dir():
                    self._load_type_dir_pools(eid, info.manifest, td.type_id, type_dir)
                    self.pool.type_tags.setdefault(td.type_id, set()).update(td.tags)
                    for tg in td.tags:
                        self.pool.tag_to_types.setdefault(tg, set()).add(td.type_id)
                else:
                    self.last_errors.append(f"{safe_rel(type_dir, self.root)}: carpeta de tipo no existe")

    def _load_pool_file(
        self,
        expansion_id: str,
        pool_dict: Dict[str, List[Entry]],
        pool_key: str,
        file_path: Path,
        allow_format_b: bool,
    ) -> None:
        out = pool_dict.setdefault(pool_key, [])
        for i, line in enumerate(read_text(file_path).splitlines(), start=1):
            if is_comment_or_empty(line):
                continue
            try:
                if allow_format_b:
                    cost, tags, text = parse_any_entry(line)
                else:
                    cost, text = parse_line_A(line)
                    tags = tuple()
                src = f"{expansion_id}:{safe_rel(file_path, self.root)}:{i}"
                out.append(Entry(cost=cost, tags=tags, text=text, source=src))
            except Exception as e:
                self.last_errors.append(f"{safe_rel(file_path, self.root)} línea {i}: {e}")

    def _load_common_pools(self) -> None:
        # common/*.txt -> pool name = stem
        skip_files = {"rareza.txt", "tags.txt", "balance_profiles.txt"}
        for common_dir in self._iter_common_dirs():
            for fp in sorted(common_dir.glob("*.txt")):
                if fp.name in skip_files:
                    continue
                self._load_pool_file("__config__", self.pool.common, fp.stem, fp, allow_format_b=True)

        # manifest common=<relpath> -> añadidos a common pool con su stem
        for eid, info in self.expansions.items():
            if info.load_error or not info.enabled:
                continue
            for rel in info.manifest.common_files:
                fp = info.folder / rel
                if fp.exists() and fp.is_file():
                    self._load_pool_file(eid, self.pool.common, fp.stem, fp, allow_format_b=True)

    def _load_type_dir_pools(self, expansion_id: str, manifest: Manifest, type_id: str, type_dir: Path) -> None:
        self.pool.by_type.setdefault(type_id, {})

        always = {
            "bases": ("bases.txt", False),
            "cosas_buenas": ("cosas_buenas.txt", True),
            "cosas_malas": ("cosas_malas.txt", True),
            # nombres (aceptamos ambos nombres)
            "plantillas_nombres": ("plantillas_nombres.txt", False),
            "plantillas_nombre": ("plantillas_nombre.txt", False),
            # nombres cerrados
            "nombres": (manifest.name_list, False),
            # ajustes stats
            "adjustments_stats": ("adjustments_stats.txt", False),
            # stats base del ítem
            "stats": ("stats.txt", False),
            # opcional: names_base por tipo (si lo usas)
            "names_base": ("names_base.txt", False),
        }
        gated = {
            "tipos": ("tipos.txt", manifest.provides_types),
            "apariencias": ("apariencias.txt", manifest.provides_appearances),
        }

        # cargar known always
        for key, (fname, allow_b) in always.items():
            fp = type_dir / fname
            if fp.exists() and fp.is_file():
                self._load_pool_file(expansion_id, self.pool.by_type[type_id], key, fp, allow_format_b=allow_b)

        # cargar extras *.txt como pools con su stem
        known_files = set([v[0] for v in always.values()] + [v[0] for v in gated.values()])
        for fp in sorted(type_dir.glob("*.txt")):
            if fp.name in known_files:
                continue
            stem = fp.stem
            if stem in self.pool.by_type[type_id]:
                continue
            self._load_pool_file(expansion_id, self.pool.by_type[type_id], stem, fp, allow_format_b=True)

        # cargar gated
        for key, (fname, enabled) in gated.items():
            if not enabled:
                continue
            fp = type_dir / fname
            if fp.exists() and fp.is_file():
                self._load_pool_file(expansion_id, self.pool.by_type[type_id], key, fp, allow_format_b=True)

    def _load_merged_rarities(self) -> List[Rarity]:
        rar: List[Rarity] = []
        sources: List[Path] = []

        for common_dir in self._iter_common_dirs():
            base = common_dir / "rareza.txt"
            if base.exists() and base not in sources:
                sources.append(base)

        # allow expansions to contribute rareza via common_files
        for info in self.expansions.values():
            if info.load_error or not info.enabled:
                continue
            for rel in info.manifest.common_files:
                fp = info.folder / rel
                if fp.exists() and fp.stem == "rareza":
                    sources.append(fp)

        for fp in sources:
            for i, line in enumerate(read_text(fp).splitlines(), start=1):
                if is_comment_or_empty(line):
                    continue
                parts = [x.strip() for x in line.split(SEP)]
                if len(parts) < 6:
                    self.last_errors.append(f"{safe_rel(fp, self.root)} línea {i}: formato rareza inválido")
                    continue
                rid, name, target, tol, mg, mb = parts[:6]
                try:
                    rar.append(Rarity(rid, name, int(target), int(tol), int(mg), int(mb)))
                except Exception:
                    self.last_errors.append(f"{safe_rel(fp, self.root)} línea {i}: valores numéricos inválidos")

        # dedupe by rid
        dedup: Dict[str, Rarity] = {r.rid: r for r in rar}
        return list(dedup.values())

    # -----------------------------
    # Updates
    # -----------------------------
    def check_update_for(self, exp_id: str, timeout: float = 8.0) -> Tuple[Optional[str], Optional[str]]:
        info = self.expansions.get(exp_id)
        if not info or info.load_error:
            return None, "Expansión inválida"
        url = info.manifest.update_url
        if not url:
            return None, "Sin URL"
        try:
            manifest_url = url if url.rstrip("/").lower().endswith("manifest.txt") else url.rstrip("/") + "/manifest.txt"
            r = requests.get(manifest_url, timeout=timeout)
            r.raise_for_status()
            txt = r.text
            remote_version = None
            for line in txt.splitlines():
                if line.strip().startswith("version="):
                    remote_version = line.split("=", 1)[1].strip()
                    break
            if not remote_version:
                return None, "Manifest remoto sin version="
            return remote_version, None
        except Exception as e:
            return None, str(e)

    def update_expansion(self, exp_id: str, timeout: float = 15.0) -> Optional[str]:
        info = self.expansions.get(exp_id)
        if not info or info.load_error:
            return "Expansión inválida"
        url = info.manifest.update_url
        if not url:
            return "Sin URL"
        try:
            base_url = url.rsplit("/", 1)[0] if url.rstrip("/").lower().endswith("manifest.txt") else url.rstrip("/")
            zip_url = base_url + "/expansion.zip"

            tmp = self.root / "_tmp_update"
            tmp.mkdir(parents=True, exist_ok=True)
            zip_path = tmp / f"{exp_id}.zip"

            r = requests.get(zip_url, timeout=timeout, stream=True)
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            extract_dir = tmp / f"{exp_id}_new"
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            candidate = extract_dir / exp_id
            src_dir = candidate if candidate.exists() else extract_dir
            if not (src_dir / "manifest.txt").exists():
                return "El ZIP no contiene manifest.txt (ni carpeta esperada)"

            target = info.folder
            tmp_old = tmp / f"{exp_id}_old"
            if tmp_old.exists():
                shutil.rmtree(tmp_old, ignore_errors=True)

            target.rename(tmp_old)
            shutil.copytree(src_dir, target)
            shutil.rmtree(tmp_old, ignore_errors=True)
            return None
        except Exception as e:
            return str(e)

    # -----------------------------
    # Unique names
    # -----------------------------
    def _unique_token(self, scope: str, type_id: str, value: str) -> str:
        if scope == "global":
            return f"global|||{value}"
        if scope == "type":
            return f"type|{type_id}||{value}"
        return f"expansion|{type_id}||{value}"

    def _pick_unique_name_if_needed(self, type_id: str, tpool: Dict[str, List[Entry]]) -> str:
        pool = tpool.get("nombres", [])
        if not pool:
            return type_id

        unique = False
        scope = "expansion"
        for info in self.expansions.values():
            if info.load_error or not info.enabled:
                continue
            if (info.folder / type_id).exists() and info.manifest.name_unique:
                unique = True
                scope = info.manifest.name_unique_scope
                break

        if not unique:
            return random.choice(pool).text

        candidates: List[Tuple[str, str]] = []
        for e in pool:
            token = self._unique_token(scope=scope, type_id=type_id, value=e.text)
            if token not in self.used_names:
                candidates.append((token, e.text))

        if not candidates:
            if self.engine_config.fallback_when_unique_names_exhausted:
                return random.choice(pool).text
            return "SIN_NOMBRE_UNICO"

        token, val = random.choice(candidates)
        self.used_names.add(token)

        used_path = self.state_dir / "used_lines.txt"
        if not used_path.exists():
            write_text(used_path, "# tokens\n")
        with open(used_path, "a", encoding="utf-8") as f:
            f.write(token + "\n")

        return val

    # -----------------------------
    # Generation
    # -----------------------------
    def generate(
        self,
        mode: str,  # "TAG" or "TIPO"
        tag: Optional[str],
        type_id: Optional[str],
        rarity_id: Optional[str],
        manual_target: Optional[int],
        manual_tol: Optional[int],
        n_effects: int,
        force_last: bool,
        allow_stats_adjust: bool,
        debug: bool = False,
    ) -> Tuple[str, str]:
        # choose type
        chosen_type: str
        chosen_tag: Optional[str] = None

        if mode == "TAG":
            if not tag:
                raise ValueError("Debes elegir un tag")
            chosen_tag = tag.lower()
            candidates = sorted(self.pool.tag_to_types.get(chosen_tag, set()))
            if not candidates:
                raise ValueError(f"No hay tipos disponibles para el tag '{tag}'")
            chosen_type = random.choice(candidates)
        else:
            if not type_id:
                raise ValueError("Debes elegir un tipo")
            chosen_type = type_id

        # target/tolerance
        target = 0
        tol = self.rules.budget_tolerance

        if rarity_id:
            r = next((x for x in self.rarities if x.rid == rarity_id), None)
            if r:
                target = r.target
                tol = r.tol

        if manual_target is not None:
            target = manual_target
        if manual_tol is not None:
            tol = manual_tol

        # pools
        tpool = self.pool.by_type.get(chosen_type, {})
        if not tpool.get("bases"):
            raise ValueError(f"El tipo '{chosen_type}' no tiene bases.txt (pool 'bases' vacío).")

        # stats line (always if exists)
        chosen_stats: Optional[Entry] = None
        if tpool.get("stats"):
            chosen_stats = random.choice(tpool["stats"])

        # --- helper: get pool for placeholder with aliases ---
        def get_pool_for_placeholder(ph: str) -> List[Entry]:
            if ph == "nombre":
                return []  # handled separately
            keys = PLACEHOLDER_ALIASES.get(ph, [ph])

            # 1) type pools
            for k in keys:
                if k in tpool and tpool[k]:
                    return tpool[k]
            # 2) common pools
            for k in keys:
                if k in self.pool.common and self.pool.common[k]:
                    return self.pool.common[k]

            return []

        # --- expand text: same for names and traits ---
        def expand_text(template: str, depth: int = 0) -> Tuple[str, int, List[str]]:
            if depth > 6:
                return template, 0, []

            cost_acc = 0
            srcs: List[str] = []

            # [x] -> {x}
            template2 = SQUARE_PLACEHOLDER_RE.sub(r"{\1}", template)

            def replace_one(match: re.Match) -> str:
                nonlocal cost_acc, srcs
                ph = match.group(1)

                # {nombre} -> unique/normal name list from tpool["nombres"]
                if ph == "nombre":
                    return self._pick_unique_name_if_needed(chosen_type, tpool)

                pool = get_pool_for_placeholder(ph)
                if not pool:
                    return "{" + ph + "}"  # visible if missing
                e = random.choice(pool)
                cost_acc += e.cost
                srcs.append(e.source)

                txt2, c2, s2 = expand_text(e.text, depth + 1)
                cost_acc += c2
                srcs.extend(s2)
                return txt2

            out = CURLY_PLACEHOLDER_RE.sub(replace_one, template2)
            return out, cost_acc, srcs

        # pick effects
        picked_effects: List[Tuple[str, int, List[str]]] = []
        total_cost = 0

        def generate_one_effect(force_adjust: bool, remaining_delta: int) -> Tuple[str, int, List[str]]:
            base = random.choice(tpool["bases"])
            base_cost = base.cost
            base_src = [base.source]

            if not force_adjust:
                txt, c, srcs = expand_text(base.text, 0)
                return txt, base_cost + c, base_src + srcs

            best: Optional[Tuple[int, str, int, List[str]]] = None
            for _ in range(50):
                txt, c, srcs = expand_text(base.text, 0)
                cost = base_cost + c
                score = abs(remaining_delta - cost)
                cand = (score, txt, cost, base_src + srcs)
                if best is None or cand[0] < best[0]:
                    best = cand
                if best[0] == 0:
                    break
            assert best is not None
            return best[1], best[2], best[3]

        count_to_free = (n_effects - 1) if (force_last and n_effects >= 2) else n_effects
        for _ in range(count_to_free):
            txt, c, srcs = generate_one_effect(False, 0)
            total_cost += c
            picked_effects.append((txt, c, srcs))

        if force_last and n_effects >= 1:
            remaining = target - total_cost
            txt, c, srcs = generate_one_effect(True, remaining)
            total_cost += c
            picked_effects.append((txt, c, srcs))

        # adjustments_stats (optional)
        adjustments_applied: List[Tuple[str, int, List[str]]] = []
        if allow_stats_adjust:
            delta = target - total_cost
            if abs(delta) > tol and tpool.get("adjustments_stats"):
                remaining = delta
                for _ in range(self.rules.max_stat_adjustments):
                    best = None
                    for e in tpool["adjustments_stats"]:
                        score = abs(remaining - e.cost)
                        if best is None or score < best[0]:
                            best = (score, e)
                    if best is None:
                        break
                    e = best[1]
                    adjustments_applied.append((e.text, e.cost, [e.source]))
                    total_cost += e.cost
                    remaining = target - total_cost
                    if abs(remaining) <= tol:
                        break

        # name: pick template and expand like traits
        name, name_sources = self._generate_name(chosen_type, tpool, expand_text)

        # output
        lines: List[str] = []
        lines.append(f"Nombre: {name}")
        if chosen_tag:
            lines.append(f"Categoría: {chosen_tag}")
        lines.append(f"Tipo: {chosen_type}")

        if chosen_stats is not None:
            lines.append(f"Estadísticas: {chosen_stats.text}")

        if rarity_id:
            r = next((x for x in self.rarities if x.rid == rarity_id), None)
            if r:
                lines.append(f"Rareza: {r.name} [{r.rid}]")

        lines.append("")
        lines.append("Rasgos:")
        for txt, c, _ in picked_effects:
            lines.append(f"- {txt}  ({c:+d})")

        if adjustments_applied:
            lines.append("")
            lines.append("Ajustes de características:")
            for txt, c, _ in adjustments_applied:
                lines.append(f"- {txt}  ({c:+d})")

        lines.append("")
        lines.append(f"Coste total: {total_cost:+d} | Objetivo: {target:+d} | Tolerancia: ±{tol} | Delta: {(target-total_cost):+d}")

        dbg = ""
        if debug:
            dbg_lines = ["=== DEBUG / FUENTES ==="]
            dbg_lines.append("[Nombre]")
            for s in name_sources:
                dbg_lines.append(f"  - {s}")
            if chosen_stats is not None:
                dbg_lines.append(f"[Stats] {chosen_stats.source}")
            for idx, (txt, c, srcs) in enumerate(picked_effects, start=1):
                dbg_lines.append(f"[Rasgo {idx}] {c:+d}: {txt}")
                for s in srcs:
                    dbg_lines.append(f"  - {s}")
            if adjustments_applied:
                dbg_lines.append("Ajustes:")
                for (txt, c, srcs) in adjustments_applied:
                    dbg_lines.append(f"  {c:+d}: {txt}")
                    for s in srcs:
                        dbg_lines.append(f"    - {s}")
            dbg = "\n".join(dbg_lines)

        return "\n".join(lines), dbg

    def _generate_name(self, type_id: str, tpool: Dict[str, List[Entry]], expand_text_fn) -> Tuple[str, List[str]]:
        templates: List[Entry] = []
        if tpool.get("plantillas_nombres"):
            templates += tpool["plantillas_nombres"]
        if tpool.get("plantillas_nombre"):
            templates += tpool["plantillas_nombre"]
        if self.pool.common.get("plantillas_nombres"):
            templates += self.pool.common["plantillas_nombres"]
        if self.pool.common.get("plantillas_nombre"):
            templates += self.pool.common["plantillas_nombre"]

        if templates:
            tpl = random.choice(templates)
            template = tpl.text
            sources = [tpl.source]
        else:
            # fallback mínimo si no hay plantillas
            template = "{names_base} {epiteto}"
            sources = ["__internal__:fallback_name_template:1"]

        expanded, _, srcs = expand_text_fn(template, 0)
        expanded = re.sub(r"\s{2,}", " ", expanded).strip()
        if not expanded:
            expanded = type_id

        return expanded, sources + srcs


# -----------------------------
# UI
# -----------------------------
@dataclass
class HistoryItem:
    title: str
    content: str
    debug: str


class MainWindow(QMainWindow):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

        icon_path = root / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setWindowTitle("Rell Engine")
        self.resize(1200, 720)

        self.engine = RellEngine(root=root)
        self.engine.load_config_files()
        self.engine.load_expansions()

        self.history: List[HistoryItem] = []

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tab_generate = QWidget()
        self.tab_history = QWidget()
        self.tab_content = QWidget()
        self.tab_system = QWidget()

        self.tabs.addTab(self.tab_generate, "Generador")
        self.tabs.addTab(self.tab_history, "Historial")
        self.tabs.addTab(self.tab_content, "Contenido")
        self.tabs.addTab(self.tab_system, "Sistema")

        self._build_generate_tab()
        self._build_history_tab()
        self._build_content_tab()
        self._build_system_tab()

        self._refresh_all_ui()

    # -------- Generate tab --------
    def _build_generate_tab(self) -> None:
        layout = QVBoxLayout(self.tab_generate)
        top = QHBoxLayout()

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["TAG", "TIPO"])
        self.mode_combo.currentIndexChanged.connect(self._refresh_type_tag_controls)

        self.tag_combo = QComboBox()
        self.type_combo = QComboBox()

        self.rarity_combo = QComboBox()
        self.rarity_combo.setMinimumWidth(260)
        self.manual_check = QCheckBox("Modo manual")
        self.manual_check.stateChanged.connect(self._refresh_manual_controls)

        self.manual_target = QSpinBox()
        self.manual_target.setRange(-999, 999)
        self.manual_tol = QSpinBox()
        self.manual_tol.setRange(0, 50)

        self.effects_spin = QSpinBox()
        self.effects_spin.setRange(1, 10)
        self.force_last = QCheckBox("Forzar último efecto (ajuste)")
        self.allow_stats = QCheckBox("Permitir ajustes de características")
        self.debug_check = QCheckBox("Debug (fuentes)")

        form = QFormLayout()
        form.addRow("Modo:", self.mode_combo)
        form.addRow("Tag:", self.tag_combo)
        form.addRow("Tipo:", self.type_combo)
        form.addRow("Rareza:", self.rarity_combo)
        form.addRow("", self.manual_check)
        form.addRow("Manual objetivo:", self.manual_target)
        form.addRow("Manual tolerancia:", self.manual_tol)
        form.addRow("Nº efectos:", self.effects_spin)
        form.addRow("", self.force_last)
        form.addRow("", self.allow_stats)
        form.addRow("", self.debug_check)

        left_box = QGroupBox("Parámetros")
        left_box.setLayout(form)

        self.out_text = QPlainTextEdit()
        self.out_text.setReadOnly(True)
        self.debug_text = QPlainTextEdit()
        self.debug_text.setReadOnly(True)

        btn_row = QHBoxLayout()
        self.btn_generate = QPushButton("Generar")
        self.btn_generate.clicked.connect(self.on_generate)

        self.btn_random_all = QPushButton("Aleatorio total")
        self.btn_random_all.clicked.connect(self.on_generate_random_all)

        self.btn_copy = QPushButton("Copiar")
        self.btn_copy.clicked.connect(self.on_copy)

        self.btn_save = QPushButton("Guardar .txt")
        self.btn_save.clicked.connect(self.on_save_result)

        btn_row.addWidget(self.btn_generate)
        btn_row.addWidget(self.btn_random_all)
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch(1)

        right = QVBoxLayout()
        right.addLayout(btn_row)

        splitter = QSplitter(Qt.Vertical)

        out_container = QWidget()
        out_l = QVBoxLayout(out_container)
        out_l.setContentsMargins(0, 0, 0, 0)
        out_l.addWidget(QLabel("Resultado"))
        out_l.addWidget(self.out_text)

        dbg_container = QWidget()
        dbg_l = QVBoxLayout(dbg_container)
        dbg_l.setContentsMargins(0, 0, 0, 0)
        dbg_l.addWidget(QLabel("Debug"))
        dbg_l.addWidget(self.debug_text)

        splitter.addWidget(out_container)
        splitter.addWidget(dbg_container)
        splitter.setSizes([450, 200])

        right.addWidget(splitter)

        top.addWidget(left_box, 0)
        top.addLayout(right, 1)
        layout.addLayout(top)

        self._refresh_manual_controls()
        self._refresh_type_tag_controls()

    def _refresh_manual_controls(self) -> None:
        manual = self.manual_check.isChecked()
        self.manual_target.setEnabled(manual)
        self.manual_tol.setEnabled(manual)
        self.rarity_combo.setEnabled(not manual)

    def _refresh_type_tag_controls(self) -> None:
        mode = self.mode_combo.currentText()
        self.tag_combo.setEnabled(mode == "TAG")
        self.type_combo.setEnabled(mode == "TIPO")

    # -------- History tab --------
    def _build_history_tab(self) -> None:
        layout = QVBoxLayout(self.tab_history)
        top = QHBoxLayout()

        self.hist_table = QTableWidget(0, 2)
        self.hist_table.setHorizontalHeaderLabels(["#", "Título"])
        self.hist_table.horizontalHeader().setStretchLastSection(True)
        self.hist_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.hist_table.setSelectionMode(QTableWidget.SingleSelection)
        self.hist_table.itemSelectionChanged.connect(self.on_history_select)

        right = QVBoxLayout()
        self.hist_view = QPlainTextEdit()
        self.hist_view.setReadOnly(True)
        self.hist_debug = QPlainTextEdit()
        self.hist_debug.setReadOnly(True)

        btns = QHBoxLayout()
        self.btn_hist_copy = QPushButton("Copiar")
        self.btn_hist_copy.clicked.connect(self.on_history_copy)
        self.btn_hist_save = QPushButton("Guardar .txt")
        self.btn_hist_save.clicked.connect(self.on_history_save)
        self.btn_hist_clear = QPushButton("Vaciar historial")
        self.btn_hist_clear.clicked.connect(self.on_history_clear)
        btns.addWidget(self.btn_hist_copy)
        btns.addWidget(self.btn_hist_save)
        btns.addWidget(self.btn_hist_clear)
        btns.addStretch(1)

        splitter = QSplitter(Qt.Vertical)
        c1 = QWidget()
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.addWidget(QLabel("Resultado"))
        l1.addWidget(self.hist_view)

        c2 = QWidget()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.addWidget(QLabel("Debug"))
        l2.addWidget(self.hist_debug)

        splitter.addWidget(c1)
        splitter.addWidget(c2)
        splitter.setSizes([450, 200])

        right.addLayout(btns)
        right.addWidget(splitter)

        top.addWidget(self.hist_table, 0)
        top.addLayout(right, 1)
        layout.addLayout(top)

    def _refresh_history_table(self) -> None:
        self.hist_table.setRowCount(len(self.history))
        for i, item in enumerate(self.history):
            self.hist_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.hist_table.setItem(i, 1, QTableWidgetItem(item.title))

    def on_history_select(self) -> None:
        row = self.hist_table.currentRow()
        if row < 0 or row >= len(self.history):
            self.hist_view.setPlainText("")
            self.hist_debug.setPlainText("")
            return
        it = self.history[row]
        self.hist_view.setPlainText(it.content)
        self.hist_debug.setPlainText(it.debug)

    def on_history_copy(self) -> None:
        QApplication.clipboard().setText(self.hist_view.toPlainText())

    def on_history_save(self) -> None:
        row = self.hist_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Historial", "Selecciona un elemento del historial.")
            return
        it = self.history[row]
        path, _ = QFileDialog.getSaveFileName(self, "Guardar resultado", "rell_item.txt", "Text (*.txt)")
        if not path:
            return
        write_text(Path(path), it.content)

    def on_history_clear(self) -> None:
        self.history.clear()
        self._refresh_history_table()
        self.hist_view.setPlainText("")
        self.hist_debug.setPlainText("")

    # -------- Content tab --------
    def _build_content_tab(self) -> None:
        layout = QVBoxLayout(self.tab_content)

        self.exp_table = QTableWidget(0, 9)
        self.exp_table.setHorizontalHeaderLabels(
            ["Activa", "ID", "Nombre", "Versión local", "Versión remota", "Estado", "Update URL", "Comprobar", "Actualizar"]
        )
        self.exp_table.horizontalHeader().setStretchLastSection(True)

        btn_row = QHBoxLayout()
        self.btn_check_all = QPushButton("Comprobar actualizaciones")
        self.btn_check_all.clicked.connect(self.on_check_updates_all)
        self.btn_update_all = QPushButton("Actualizar todo")
        self.btn_update_all.clicked.connect(self.on_update_all)

        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_check_all)
        btn_row.addWidget(self.btn_update_all)

        self.err_text = QPlainTextEdit()
        self.err_text.setReadOnly(True)
        self.err_text.setMaximumHeight(180)

        layout.addLayout(btn_row)
        layout.addWidget(self.exp_table)
        layout.addWidget(QLabel("Avisos/errores de carga"))
        layout.addWidget(self.err_text)

    # -------- System tab --------
    def _build_system_tab(self) -> None:
        layout = QVBoxLayout(self.tab_system)

        box = QGroupBox("Gestión")
        bl = QVBoxLayout(box)

        row1 = QHBoxLayout()
        self.root_edit = QLineEdit()
        self.root_edit.setReadOnly(True)
        self.btn_change_root = QPushButton("Cambiar carpeta del motor...")
        self.btn_change_root.clicked.connect(self.on_choose_root)
        row1.addWidget(QLabel("Carpeta:"))
        row1.addWidget(self.root_edit, 1)
        row1.addWidget(self.btn_change_root)

        row2 = QHBoxLayout()
        self.btn_save_enabled = QPushButton("Guardar expansiones activas")
        self.btn_save_enabled.clicked.connect(self.on_save_enabled)
        self.btn_reload = QPushButton("Recargar contenido")
        self.btn_reload.clicked.connect(self.on_reload)
        row2.addWidget(self.btn_save_enabled)
        row2.addWidget(self.btn_reload)
        row2.addStretch(1)

        bl.addLayout(row1)
        bl.addLayout(row2)
        layout.addWidget(box)

        man_box = QGroupBox("Creador de manifest (para expansiones)")
        ml = QVBoxLayout(man_box)

        pick_row = QHBoxLayout()
        self.man_folder_edit = QLineEdit()
        self.man_folder_edit.setReadOnly(True)
        self.btn_pick_exp_folder = QPushButton("Seleccionar carpeta de expansión...")
        self.btn_pick_exp_folder.clicked.connect(self.on_pick_manifest_folder)
        pick_row.addWidget(QLabel("Carpeta:"))
        pick_row.addWidget(self.man_folder_edit, 1)
        pick_row.addWidget(self.btn_pick_exp_folder)
        ml.addLayout(pick_row)

        form = QFormLayout()
        self.man_id = QLineEdit()
        self.man_name = QLineEdit()
        self.man_version = QLineEdit("1.0.0")
        self.man_update_url = QLineEdit()

        self.man_provides_types = QCheckBox("provides_types=true")
        self.man_provides_appear = QCheckBox("provides_appearances=true")

        self.man_name_unique = QCheckBox("name_unique=true")
        self.man_name_unique_scope = QComboBox()
        self.man_name_unique_scope.addItems(["expansion", "type", "global"])
        self.man_name_list = QLineEdit("nombres.txt")

        form.addRow("id:", self.man_id)
        form.addRow("name:", self.man_name)
        form.addRow("version:", self.man_version)
        form.addRow("update_url (opcional):", self.man_update_url)
        form.addRow("", self.man_provides_types)
        form.addRow("", self.man_provides_appear)
        form.addRow("", self.man_name_unique)
        form.addRow("name_unique_scope:", self.man_name_unique_scope)
        form.addRow("name_list:", self.man_name_list)
        ml.addLayout(form)

        ml.addWidget(QLabel("Tipos detectados (marca cuáles incluir y añade tags separados por coma):"))

        self.man_types_table = QTableWidget(0, 3)
        self.man_types_table.setHorizontalHeaderLabels(["Incluir", "Tipo (carpeta)", "Tags (opcional)"])
        self.man_types_table.horizontalHeader().setStretchLastSection(True)
        ml.addWidget(self.man_types_table)

        btn_row = QHBoxLayout()
        self.btn_scan = QPushButton("Revisar carpeta")
        self.btn_scan.clicked.connect(self.on_scan_manifest_folder)
        self.btn_write_manifest = QPushButton("Generar manifest.txt")
        self.btn_write_manifest.clicked.connect(self.on_write_manifest)
        btn_row.addWidget(self.btn_scan)
        btn_row.addWidget(self.btn_write_manifest)
        btn_row.addStretch(1)
        ml.addLayout(btn_row)

        self.man_log = QPlainTextEdit()
        self.man_log.setReadOnly(True)
        self.man_log.setMaximumHeight(140)
        ml.addWidget(QLabel("Salida:"))
        ml.addWidget(self.man_log)

        layout.addWidget(man_box)
        layout.addStretch(1)

    # -------- refresh UI --------
    def _refresh_all_ui(self) -> None:
        self.root_edit.setText(str(self.engine.root))

        self.tag_combo.clear()
        self.tag_combo.addItems(sorted(self.engine.pool.tag_to_types.keys()))

        self.type_combo.clear()
        self.type_combo.addItems(sorted(self.engine.pool.by_type.keys()))

        self.rarity_combo.clear()
        for r in sorted(self.engine.rarities, key=lambda x: x.target):
            self.rarity_combo.addItem(f"{r.name} ({r.rid})  objetivo={r.target:+d}", r.rid)

        self._refresh_exp_table()
        self.err_text.setPlainText("\n".join(self.engine.last_errors) if self.engine.last_errors else "—")
        self._refresh_history_table()

    def _refresh_exp_table(self) -> None:
        exps = list(self.engine.expansions.values())
        exps.sort(key=lambda e: (e.load_error is not None, e.manifest.id))
        self.exp_table.setRowCount(len(exps))

        for row, info in enumerate(exps):
            chk = QCheckBox()
            chk.setChecked(info.enabled and info.load_error is None)
            chk.setEnabled(info.load_error is None)
            chk.stateChanged.connect(lambda st, eid=info.manifest.id: self.on_toggle_expansion(eid, st))
            self.exp_table.setCellWidget(row, 0, chk)

            self.exp_table.setItem(row, 1, QTableWidgetItem(info.manifest.id))
            self.exp_table.setItem(row, 2, QTableWidgetItem(info.manifest.name))
            self.exp_table.setItem(row, 3, QTableWidgetItem(info.manifest.version))
            self.exp_table.setItem(row, 4, QTableWidgetItem(info.remote_version or "—"))
            self.exp_table.setItem(row, 5, QTableWidgetItem(info.update_status))

            url_item = QTableWidgetItem(info.manifest.update_url or "—")
            url_item.setFlags(url_item.flags() ^ Qt.ItemIsEditable)
            self.exp_table.setItem(row, 6, url_item)

            btn_check = QPushButton("Comprobar")
            btn_check.setEnabled(bool(info.manifest.update_url) and info.load_error is None)
            btn_check.clicked.connect(lambda _, eid=info.manifest.id: self.on_check_update_one(eid))
            self.exp_table.setCellWidget(row, 7, btn_check)

            btn_upd = QPushButton("Actualizar")
            btn_upd.setEnabled(bool(info.manifest.update_url) and info.load_error is None)
            btn_upd.clicked.connect(lambda _, eid=info.manifest.id: self.on_update_one(eid))
            self.exp_table.setCellWidget(row, 8, btn_upd)

    # -------- actions --------
    def on_toggle_expansion(self, exp_id: str, state: int) -> None:
        info = self.engine.expansions.get(exp_id)
        if info:
            info.enabled = (state == Qt.Checked)

    def on_save_enabled(self) -> None:
        self.engine.save_enabled_expansions()
        QMessageBox.information(self, "OK", "enabled_expansions.txt actualizado.")

    def on_reload(self) -> None:
        self.engine.load_config_files()
        self.engine.load_expansions()
        self._refresh_all_ui()

    def on_choose_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta raíz de Rell Engine")
        if not d:
            return
        new_root = Path(d)
        self.engine = RellEngine(new_root)
        self.engine.load_config_files()
        self.engine.load_expansions()
        icon_path = new_root / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self._refresh_all_ui()

    def _push_history(self, content: str, debug: str) -> None:
        title = content.splitlines()[0] if content else "Item"
        self.history.insert(0, HistoryItem(title=title, content=content, debug=debug))
        if len(self.history) > 200:
            self.history = self.history[:200]
        self._refresh_history_table()

    def on_generate(self) -> None:
        try:
            mode = self.mode_combo.currentText()
            tag = self.tag_combo.currentText() if mode == "TAG" else None
            type_id = self.type_combo.currentText() if mode == "TIPO" else None

            rarity_id = None if self.manual_check.isChecked() else self.rarity_combo.currentData()
            manual_target = self.manual_target.value() if self.manual_check.isChecked() else None
            manual_tol = self.manual_tol.value() if self.manual_check.isChecked() else None

            text, dbg = self.engine.generate(
                mode=mode,
                tag=tag,
                type_id=type_id,
                rarity_id=rarity_id,
                manual_target=manual_target,
                manual_tol=manual_tol,
                n_effects=self.effects_spin.value(),
                force_last=self.force_last.isChecked(),
                allow_stats_adjust=self.allow_stats.isChecked(),
                debug=self.debug_check.isChecked(),
            )
            self.out_text.setPlainText(text)
            self.debug_text.setPlainText(dbg if self.debug_check.isChecked() else "")
            self._push_history(text, dbg if self.debug_check.isChecked() else "")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_generate_random_all(self) -> None:
        tags = sorted(self.engine.pool.tag_to_types.keys())
        if not tags:
            QMessageBox.warning(self, "Aleatorio total", "No hay tags disponibles.")
            return
        chosen_tag = random.choice(tags)
        self.mode_combo.setCurrentText("TAG")
        idx = self.tag_combo.findText(chosen_tag)
        if idx >= 0:
            self.tag_combo.setCurrentIndex(idx)
        self.on_generate()

    def on_copy(self) -> None:
        QApplication.clipboard().setText(self.out_text.toPlainText())

    def on_save_result(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Guardar resultado", "rell_item.txt", "Text (*.txt)")
        if not path:
            return
        write_text(Path(path), self.out_text.toPlainText())
        QMessageBox.information(self, "OK", "Guardado.")

    # -------- updates --------
    def on_check_update_one(self, exp_id: str) -> None:
        info = self.engine.expansions.get(exp_id)
        if not info or not info.manifest.update_url:
            return
        remote, err = self.engine.check_update_for(exp_id)
        if err:
            info.remote_version = None
            info.update_status = "Error al comprobar"
            self.err_text.setPlainText((self.err_text.toPlainText() + "\n" + f"[{exp_id}] {err}").strip())
        else:
            info.remote_version = remote
            info.update_status = self._compare_versions(info.manifest.version, remote)
        self._refresh_exp_table()

    def on_check_updates_all(self) -> None:
        for exp_id, info in self.engine.expansions.items():
            if info.load_error or not info.manifest.update_url:
                continue
            remote, err = self.engine.check_update_for(exp_id)
            if err:
                info.remote_version = None
                info.update_status = "Error al comprobar"
            else:
                info.remote_version = remote
                info.update_status = self._compare_versions(info.manifest.version, remote)
        self._refresh_exp_table()

    def on_update_one(self, exp_id: str) -> None:
        info = self.engine.expansions.get(exp_id)
        if not info or not info.manifest.update_url:
            QMessageBox.information(self, "Actualizar", "La expansión no tiene update_url o es inválida.")
            return
        err = self.engine.update_expansion(exp_id)
        if err:
            QMessageBox.critical(self, "Actualizar", f"Falló la actualización:\n{err}")
        else:
            QMessageBox.information(self, "Actualizar", "Actualización aplicada. Recargando contenido...")
            self.on_reload()

    def on_update_all(self) -> None:
        updated = 0
        failed = 0
        for exp_id, info in self.engine.expansions.items():
            if info.load_error or not info.manifest.update_url:
                continue
            if info.remote_version is None:
                remote, err = self.engine.check_update_for(exp_id)
                if err:
                    failed += 1
                    continue
                info.remote_version = remote
                info.update_status = self._compare_versions(info.manifest.version, remote)
            if info.update_status != "Actualización disponible":
                continue
            err = self.engine.update_expansion(exp_id)
            if err:
                failed += 1
            else:
                updated += 1
        self.on_reload()
        QMessageBox.information(self, "Actualizar todo", f"Actualizadas: {updated}\nFallidas: {failed}")

    def _compare_versions(self, local: str, remote: str) -> str:
        try:
            lv = Version(local)
            rv = Version(remote)
            return "Actualización disponible" if rv > lv else "Actualizada"
        except InvalidVersion:
            return "Actualización disponible" if remote != local else "Actualizada"

    # -------- Manifest creator --------
    def on_pick_manifest_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Selecciona carpeta de expansión (donde irá manifest.txt)")
        if not d:
            return
        folder = Path(d)
        self.man_folder_edit.setText(str(folder))

        suggested_id = folder.name.strip().replace(" ", "_")
        if not self.man_id.text().strip():
            self.man_id.setText(suggested_id)
        if not self.man_name.text().strip():
            self.man_name.setText(folder.name)

        self.on_scan_manifest_folder()

    def on_scan_manifest_folder(self) -> None:
        folder_txt = self.man_folder_edit.text().strip()
        if not folder_txt:
            QMessageBox.information(self, "Creador de manifest", "Selecciona una carpeta primero.")
            return
        folder = Path(folder_txt)
        if not folder.exists() or not folder.is_dir():
            QMessageBox.warning(self, "Creador de manifest", "La carpeta seleccionada no existe.")
            return

        type_folders: List[str] = []
        for sub in sorted(folder.iterdir()):
            if sub.is_dir() and (sub / "bases.txt").exists():
                type_folders.append(sub.name)

        self.man_types_table.setRowCount(len(type_folders))
        for r, tname in enumerate(type_folders):
            chk = QCheckBox()
            chk.setChecked(True)
            self.man_types_table.setCellWidget(r, 0, chk)
            self.man_types_table.setItem(r, 1, QTableWidgetItem(tname))
            self.man_types_table.setItem(r, 2, QTableWidgetItem(""))

        self.man_log.setPlainText(
            f"Detectados {len(type_folders)} tipos (subcarpetas con bases.txt).\n"
            "Añade tags separados por coma en la tercera columna."
        )

    def on_write_manifest(self) -> None:
        folder_txt = self.man_folder_edit.text().strip()
        if not folder_txt:
            QMessageBox.information(self, "Creador de manifest", "Selecciona una carpeta primero.")
            return
        folder = Path(folder_txt)
        if not folder.exists() or not folder.is_dir():
            QMessageBox.warning(self, "Creador de manifest", "La carpeta seleccionada no existe.")
            return

        exp_id = self.man_id.text().strip()
        name = self.man_name.text().strip()
        version = (self.man_version.text().strip() or "1.0.0").strip()
        update_url = self.man_update_url.text().strip()

        if not exp_id or not name:
            QMessageBox.warning(self, "Creador de manifest", "id y name son obligatorios.")
            return

        provides_types = self.man_provides_types.isChecked()
        provides_appear = self.man_provides_appear.isChecked()
        name_unique = self.man_name_unique.isChecked()
        name_unique_scope = self.man_name_unique_scope.currentText().strip()
        name_list = (self.man_name_list.text().strip() or "nombres.txt").strip()

        lines: List[str] = []
        lines.append(f"id={exp_id}")
        lines.append(f"name={name}")
        lines.append(f"version={version}")
        if update_url:
            lines.append(f"update_url={update_url}")
        if provides_types:
            lines.append("provides_types=true")
        if provides_appear:
            lines.append("provides_appearances=true")
        if name_unique:
            lines.append("name_unique=true")
            lines.append(f"name_unique_scope={name_unique_scope}")
        if name_list != "nombres.txt":
            lines.append(f"name_list={name_list}")

        types_added = 0
        for r in range(self.man_types_table.rowCount()):
            w = self.man_types_table.cellWidget(r, 0)
            include = bool(w and isinstance(w, QCheckBox) and w.isChecked())
            type_item = self.man_types_table.item(r, 1)
            tags_item = self.man_types_table.item(r, 2)
            if not include or not type_item:
                continue
            tname = type_item.text().strip()
            tags = (tags_item.text().strip() if tags_item else "").strip()
            if tags:
                lines.append(f"type={tname}|tags={tags}")
            else:
                lines.append(f"type={tname}")
            types_added += 1

        if types_added == 0:
            lines.append("# Nota: no se han incluido tipos. Esta expansión será solo common/ u otras utilidades.")

        manifest_path = folder / "manifest.txt"
        write_text(manifest_path, "\n".join(lines) + "\n")

        self.man_log.setPlainText(
            f"manifest.txt generado en:\n{manifest_path}\n\n"
            f"Tipos incluidos: {types_added}\n"
            f"Opciones: provides_types={provides_types}, provides_appearances={provides_appear}, name_unique={name_unique}\n"
        )
        QMessageBox.information(self, "Creador de manifest", "manifest.txt generado correctamente.")


def main() -> None:
    root = Path(__file__).resolve().parent
    app = QApplication([])
    w = MainWindow(root=root)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
