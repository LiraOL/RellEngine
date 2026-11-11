/**
 * Conversión de un objeto exportado por Rell Engine a datos de Item de dnd5e.
 * No usa ninguna API de Foundry, así que puede probarse fuera de él.
 */

export const FORMAT_ID = "rell-engine";
export const FORMAT_VERSION = 1;
export const MODULE_ID = "rell-engine-importer";

/** Modos numéricos de los efectos activos anteriores a Foundry v14. */
const LEGACY_MODES = { custom: 0, multiply: 1, add: 2, downgrade: 3, upgrade: 4, override: 5 };

const FALLBACK_ICONS = {
  weapon: "icons/svg/sword.svg",
  armor: "icons/svg/shield.svg",
  shield: "icons/svg/shield.svg",
  wondrous: "icons/svg/item-bag.svg"
};

/**
 * Comprueba y extrae la lista de objetos de un archivo exportado.
 * @param {object} payload  JSON ya interpretado.
 * @returns {object[]}
 * @throws {Error} con `code` "format" o "version".
 */
export function readPayload(payload) {
  if ( payload?.format !== FORMAT_ID || !Array.isArray(payload.items) ) {
    throw Object.assign(new Error("format"), { code: "format" });
  }
  if ( Number(payload.version) > FORMAT_VERSION ) throw Object.assign(new Error("version"), { code: "version" });
  return payload.items;
}

function price(value) {
  const gp = Number(value) || 0;
  if ( gp > 0 && !Number.isInteger(gp) ) {
    const cp = Math.round(gp * 100);
    return (cp % 10 === 0) ? { value: cp / 10, denomination: "sp" } : { value: cp, denomination: "cp" };
  }
  return { value: gp, denomination: "gp" };
}

function damagePart(dmg) {
  const part = {
    number: dmg.number ?? null,
    denomination: dmg.denomination ?? null,
    bonus: dmg.bonus ? String(dmg.bonus) : "",
    types: dmg.type ? [dmg.type] : [],
    custom: { enabled: false, formula: "" }
  };
  // Daño fijo sin dados (p. ej. "2 radiante"): se expresa como fórmula.
  if ( !part.number || !part.denomination ) {
    part.number = null;
    part.denomination = null;
    part.custom = { enabled: true, formula: part.bonus || "0" };
    part.bonus = "";
  }
  return part;
}

function attackActivity(id, ranged) {
  return {
    _id: id,
    type: "attack",
    activation: { type: "action", value: 1 },
    attack: { ability: "", bonus: "", flat: false, type: { value: ranged ? "ranged" : "melee", classification: "weapon" } },
    damage: { includeBase: true, parts: [] }
  };
}

/** Datos mínimos cuando el objeto base no existe en los compendios de dnd5e. */
function skeleton(src, randomID) {
  const base = src.base ?? {};
  const system = {
    quantity: 1,
    weight: { value: Number(base.weight) || 0, units: "lb" },
    price: price(base.price),
    properties: [],
    activities: {}
  };
  if ( src.kind === "weapon" ) {
    const dmg = base.damage ?? {};
    system.type = { value: base.weaponType ?? "simpleM", baseItem: "" };
    system.damage = {
      base: {
        number: dmg.number ?? null,
        denomination: dmg.denomination ?? null,
        bonus: dmg.bonus ? String(dmg.bonus) : "",
        types: dmg.type ? [dmg.type] : []
      }
    };
    if ( !dmg.number && dmg.bonus ) {
      system.damage.base = { ...system.damage.base, bonus: "", custom: { enabled: true, formula: String(dmg.bonus) } };
    }
    if ( base.versatile ) {
      system.damage.versatile = {
        number: base.versatile.number ?? null,
        denomination: base.versatile.denomination ?? null,
        types: []
      };
    }
    system.properties = [...(base.properties ?? [])];
    system.range = { value: base.range?.value ?? null, long: base.range?.long ?? null, reach: null, units: "ft" };
    const id = randomID();
    system.activities[id] = attackActivity(id, String(system.type.value).endsWith("R"));
    return { type: "weapon", img: FALLBACK_ICONS.weapon, system };
  }
  if ( (src.kind === "armor") || (src.kind === "shield") ) {
    system.type = { value: (src.kind === "shield") ? "shield" : (base.armorType ?? "light"), baseItem: "" };
    system.armor = { value: base.ac ?? null, dex: base.dexCap ?? null, magicalBonus: null };
    system.strength = base.strength ?? null;
    if ( base.stealthDisadvantage ) system.properties.push("stealthDisadvantage");
    return { type: "equipment", img: FALLBACK_ICONS[src.kind], system };
  }
  system.type = { value: base.equipmentType ?? "trinket", baseItem: "" };
  return { type: "equipment", img: FALLBACK_ICONS.wondrous, system };
}

function powerActivity(id, power) {
  const timed = ["action", "bonus", "reaction"].includes(power.activation);
  const activity = {
    _id: id,
    type: "utility",
    name: power.name || "",
    activation: { type: power.activation || "action", value: timed ? 1 : null, override: false },
    description: { chatFlavor: power.text || "" },
    roll: { formula: "", name: "", prompt: false, visible: false }
  };
  if ( power.uses ) {
    activity.uses = {
      spent: 0,
      max: String(power.uses.max),
      recovery: [{ period: power.uses.period, type: "recoverAll" }]
    };
    activity.consumption = {
      scaling: { allowed: false },
      spellSlot: true,
      targets: [{ type: "activityUses", target: "", value: "1" }]
    };
  }
  return activity;
}

function passiveEffect(src, img, generation, randomID) {
  const effect = { _id: randomID(), name: src.name, img, transfer: true, disabled: false };
  if ( generation >= 14 ) {
    effect.type = "base";
    effect.system = {
      magical: true,
      changes: src.changes.map(c => ({
        key: c.key, type: c.mode, value: String(c.value), phase: "initial", priority: null
      }))
    };
  } else {
    effect.changes = src.changes.map(c => ({
      key: c.key, mode: LEGACY_MODES[c.mode] ?? LEGACY_MODES.add, value: String(c.value), priority: null
    }));
  }
  return effect;
}

/**
 * Construye los datos de un Item de dnd5e.
 * @param {object} src                    Objeto exportado por Rell Engine.
 * @param {object|null} base              Datos (`toObject()`) del objeto base de dnd5e, si se encontró.
 * @param {object} options
 * @param {number} options.generation     Generación de Foundry (13, 14...).
 * @param {() => string} options.randomID Generador de IDs de 16 caracteres.
 * @returns {object}
 */
export function buildItemData(src, base, { generation, randomID }) {
  if ( !src?.name || !src.kind ) throw new Error("faltan 'name' o 'kind'");
  const data = base ? structuredClone(base) : skeleton(src, randomID);
  for ( const key of ["_id", "folder", "sort", "ownership", "_stats", "_key"] ) delete data[key];

  data.name = src.name;
  data.effects = [];
  data.flags = { [MODULE_ID]: { base: src.base?.id ?? "", tags: src.tags ?? [] } };

  const system = data.system ??= {};
  delete system.identifier; // dnd5e genera uno nuevo a partir del nombre
  system.description = { value: src.descriptionHtml ?? "", chat: "" };
  system.properties = Array.from(system.properties ?? []);
  system.activities ??= {};
  system.quantity = 1;

  if ( src.magical ) {
    system.rarity = src.rarity ?? "";
    system.attunement = src.attunement ? "required" : "";
    system.attuned = false;
    system.price = price(src.price);
    if ( !system.properties.includes("mgc") ) system.properties.push("mgc");
  } else if ( !base ) {
    system.price = price(src.price);
  }

  for ( const prop of src.properties ?? [] ) {
    if ( !system.properties.includes(prop) ) system.properties.push(prop);
  }

  if ( src.magicalBonus ) {
    if ( data.type === "weapon" ) system.magicalBonus = String(src.magicalBonus);
    else if ( system.armor ) system.armor.magicalBonus = String(src.magicalBonus);
  }

  if ( (data.type === "weapon") && src.extraDamage?.length ) {
    const attacks = Object.values(system.activities).filter(a => a.type === "attack");
    for ( const activity of attacks ) {
      activity.damage ??= { includeBase: true, parts: [] };
      activity.damage.parts = [...(activity.damage.parts ?? []), ...src.extraDamage.map(damagePart)];
    }
  }

  for ( const power of src.activities ?? [] ) {
    const id = randomID();
    system.activities[id] = powerActivity(id, power);
  }

  if ( src.changes?.length ) data.effects.push(passiveEffect(src, data.img, generation, randomID));
  return data;
}
