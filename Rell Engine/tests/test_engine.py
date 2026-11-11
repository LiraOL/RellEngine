"""Pruebas del motor. Ejecutar desde la carpeta 'Rell Engine':  python -m unittest discover tests"""
import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rellengine import mechanics  # noqa: E402
from rellengine.engine import Engine, render_text  # noqa: E402
from rellengine.export import export_json  # noqa: E402
from rellengine.tables import TableError, parse_entry  # noqa: E402


class TablesTest(unittest.TestCase):
    def test_entry_formats(self):
        self.assertEqual(parse_entry("+2|texto", "x").cost, 2)
        e = parse_entry("-3|Fuego, solo:arrojadiza|texto|daño=1d4 fuego", "x")
        self.assertEqual((e.cost, e.theme_tags, e.requirements), (-3, ("fuego",), ("arrojadiza",)))
        with self.assertRaises(TableError):
            parse_entry("abc|texto", "x")
        with self.assertRaises(TableError):
            parse_entry("solo un campo", "x")

    def test_mechanics(self):
        out = {}
        mechanics.apply("bono=1;daño=2d6+1 de frío;resistencia=fuego,ácido;sintonizacion=si", "t", out)
        self.assertEqual(out["magicalBonus"], 1)
        self.assertEqual(out["extraDamage"], [{"number": 2, "denomination": 6, "bonus": "1", "type": "cold"}])
        self.assertEqual([c["value"] for c in out["changes"]], ["fire", "acid"])
        self.assertTrue(out["attunement"])
        out = {}
        mechanics.apply("usos=2/descanso_largo;activacion=reaccion;poder=Parada", "Texto", out)
        self.assertEqual(out["activities"][0],
                         {"name": "Parada", "text": "Texto", "activation": "reaction", "uses": {"max": 2, "period": "lr"}})
        with self.assertRaises(TableError):
            mechanics.apply("daño=mucho", "t", {})
        with self.assertRaises(TableError):
            mechanics.check_keys("inventada=1")


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Engine(ROOT)

    def test_tables_load_without_errors(self):
        self.assertEqual(self.engine.errors, [])
        self.assertGreaterEqual(len(self.engine.types), 15)

    def test_every_type_and_rarity_generates(self):
        rng = random.Random(1234)
        total = unbalanced = 0
        for rarity in self.engine.rarities.values():
            for info in self.engine.types_for_tag(None):
                for obj in info.objects:
                    item = self.engine.generate(rarity.id, type_id=info.id, object_id=obj.id, rng=rng)
                    total += 1
                    unbalanced += not item["budget"]["balanced"]
                    self.assertEqual(item["warnings"][: 0 if item["budget"]["balanced"] else 1], item["warnings"])
                    self.assertTrue(rarity.min_effects <= len(item["effects"]) <= rarity.max_effects)
                    self.assertNotIn("{", render_text(item))
                    self.assertEqual(item["magical"], rarity.max_effects > 0)
                    if not item["magical"]:
                        self.assertEqual(item["name"], obj.name)
                    texts = [e["text"] for e in item["effects"]]
                    self.assertEqual(len(texts), len(set(texts)))
                    self.assertLessEqual(item["magicalBonus"] or 0, 3)
        self.assertEqual(unbalanced, 0, f"{unbalanced} de {total} objetos fuera de presupuesto")

    def test_cursed_options(self):
        rng = random.Random(7)
        for _ in range(40):
            item = self.engine.generate("raro", tag="arma", cursed=True, rng=rng)
            self.assertTrue(any(e["cost"] < 0 for e in item["effects"]))
            self.assertTrue(any(e["cost"] > 0 for e in item["effects"]))
            item = self.engine.generate("raro", tag="armadura", cursed=False, rng=rng)
            self.assertFalse(any(e["cost"] < 0 for e in item["effects"]))

    def test_forbidden_mixes_and_requirements(self):
        rng = random.Random(99)
        for _ in range(300):
            item = self.engine.generate("legendario", rng=rng)
            tags = set(item["tags"])
            self.assertFalse({"fuego", "hielo"} <= tags)
            self.assertFalse({"sagrado", "profano"} <= tags)
            if "ret" in item["properties"]:
                self.assertIn("thr", item["base"]["properties"])

    def test_seed_is_reproducible_and_export_is_json(self):
        a = [self.engine.generate("raro", rng=random.Random(5)) for _ in range(3)]
        b = [self.engine.generate("raro", rng=random.Random(5)) for _ in range(3)]
        self.assertEqual(a, b)
        payload = json.loads(export_json(a))
        self.assertEqual(payload["format"], "rell-engine")
        self.assertEqual(len(payload["items"]), 3)
        self.assertIsInstance(payload["items"][0]["effects"][0], str)


if __name__ == "__main__":
    unittest.main()
