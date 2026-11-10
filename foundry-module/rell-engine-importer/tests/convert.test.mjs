// Ejecutar con:  node --test foundry-module/rell-engine-importer/tests/convert.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { buildItemData, readPayload } from "../scripts/convert.mjs";

let counter = 0;
const options = generation => ({ generation, randomID: () => `id${String(++counter).padStart(14, "0")}` });

const longsword = {
  _id: "phbwepLongsword0", name: "Longsword", type: "weapon", folder: "abc", img: "icons/weapons/swords/greatsword-guard.webp",
  effects: [], flags: {}, _stats: { systemVersion: "6.0.6" },
  system: {
    identifier: "longsword", rarity: "", attunement: "", magicalBonus: null, properties: ["ver"],
    price: { value: 15, denomination: "gp" }, type: { value: "martialM", baseItem: "longsword" },
    damage: { base: { number: 1, denomination: 8, types: ["slashing"] } },
    activities: { BFZXotvvF4YaAKeT: { _id: "BFZXotvvF4YaAKeT", type: "attack", damage: { includeBase: true, parts: [] } } }
  }
};

const magicSword = {
  name: "Lengua de Ascuas", kind: "weapon", magical: true, rarity: "rare", attunement: true, magicalBonus: 1,
  base: { id: "espada_larga", name: "Espada larga", foundry: "longsword", price: 15 },
  descriptionHtml: "<p>Texto</p>", price: 4015, tags: ["fuego"], properties: ["sil"],
  extraDamage: [{ number: 1, denomination: 6, bonus: "", type: "fire" }],
  changes: [{ key: "system.traits.dr.value", mode: "add", value: "fire" }],
  activities: [{ name: "Estallido", text: "Una vez por amanecer…", activation: "bonus", uses: { max: 1, period: "dawn" } }]
};

test("readPayload valida el formato", () => {
  assert.deepEqual(readPayload({ format: "rell-engine", version: 1, items: [1] }), [1]);
  assert.throws(() => readPayload({ items: [] }), { code: "format" });
  assert.throws(() => readPayload({ format: "rell-engine", version: 99, items: [] }), { code: "version" });
});

test("arma mágica sobre el objeto base de dnd5e (Foundry v14)", () => {
  const data = buildItemData(magicSword, longsword, options(14));
  assert.equal(data.name, "Lengua de Ascuas");
  assert.equal(data.type, "weapon");
  assert.equal(data._id, undefined);
  assert.equal(data.folder, undefined);
  assert.equal(data.system.identifier, undefined);
  assert.equal(data.system.type.baseItem, "longsword");
  assert.equal(data.system.rarity, "rare");
  assert.equal(data.system.attunement, "required");
  assert.equal(data.system.magicalBonus, "1");
  assert.deepEqual(data.system.price, { value: 4015, denomination: "gp" });
  assert.deepEqual(data.system.properties, ["ver", "mgc", "sil"]);
  assert.equal(data.system.description.value, "<p>Texto</p>");

  const attack = data.system.activities.BFZXotvvF4YaAKeT;
  assert.equal(attack.damage.parts.length, 1);
  assert.deepEqual(attack.damage.parts[0].types, ["fire"]);
  assert.equal(attack.damage.parts[0].denomination, 6);

  const power = Object.values(data.system.activities).find(a => a.type === "utility");
  assert.equal(power.name, "Estallido");
  assert.equal(power.activation.type, "bonus");
  assert.deepEqual(power.uses.recovery, [{ period: "dawn", type: "recoverAll" }]);
  assert.equal(power.consumption.targets[0].type, "activityUses");
  assert.equal(data.system.activities[power._id], power);

  assert.equal(data.effects.length, 1);
  assert.equal(data.effects[0].transfer, true);
  assert.deepEqual(data.effects[0].system.changes[0],
    { key: "system.traits.dr.value", type: "add", value: "fire", phase: "initial", priority: null });
  assert.equal(data.effects[0].changes, undefined);

  // El objeto base original no se modifica.
  assert.equal(longsword.system.activities.BFZXotvvF4YaAKeT.damage.parts.length, 0);
  assert.equal(longsword.name, "Longsword");
});

test("los efectos usan el formato antiguo en Foundry v13", () => {
  const data = buildItemData(magicSword, longsword, options(13));
  assert.deepEqual(data.effects[0].changes, [{ key: "system.traits.dr.value", mode: 2, value: "fire", priority: null }]);
  assert.equal(data.effects[0].system, undefined);
});

test("objeto no mágico conserva los datos del objeto base", () => {
  const src = { name: "Espada larga", kind: "weapon", magical: false, rarity: "", base: { foundry: "longsword" }, price: 15 };
  const data = buildItemData(src, longsword, options(14));
  assert.equal(data.system.rarity, "");
  assert.deepEqual(data.system.properties, ["ver"]);
  assert.deepEqual(data.system.price, { value: 15, denomination: "gp" });
  assert.deepEqual(data.effects, []);
});

test("sin objeto base se construye con las estadísticas de la tabla", () => {
  const weapon = buildItemData({
    name: "Katana", kind: "weapon", magical: false, price: 0.2,
    base: {
      weaponType: "martialM", weight: 3, price: 0.2, properties: ["ver"],
      damage: { number: 1, denomination: 8, bonus: "", type: "slashing" }, versatile: { number: 1, denomination: 10 }
    }
  }, null, options(14));
  assert.equal(weapon.type, "weapon");
  assert.deepEqual(weapon.system.damage.base.types, ["slashing"]);
  assert.equal(weapon.system.damage.versatile.denomination, 10);
  assert.deepEqual(weapon.system.price, { value: 2, denomination: "sp" });
  const [attack] = Object.values(weapon.system.activities);
  assert.equal(attack.attack.type.value, "melee");

  const armor = buildItemData({
    name: "Coraza +1", kind: "armor", magical: true, rarity: "rare", magicalBonus: 1, price: 4400,
    base: { armorType: "medium", ac: 14, dexCap: 2, stealthDisadvantage: true, weight: 20 }
  }, null, options(14));
  assert.equal(armor.type, "equipment");
  assert.deepEqual(armor.system.armor, { value: 14, dex: 2, magicalBonus: "1" });
  assert.deepEqual(armor.system.properties, ["stealthDisadvantage", "mgc"]);

  const ring = buildItemData({
    name: "Anillo", kind: "wondrous", magical: true, rarity: "uncommon", magicalBonus: 1, base: { equipmentType: "ring" },
    changes: [{ key: "system.attributes.ac.bonus", mode: "add", value: "+1" }]
  }, null, options(14));
  assert.equal(ring.system.type.value, "ring");
  assert.equal(ring.effects[0].system.changes[0].value, "+1");

  assert.throws(() => buildItemData({ name: "" }, null, options(14)));
});
