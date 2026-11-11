import { MODULE_ID, buildItemData, readPayload } from "./convert.mjs";

const FOLDER_NAME = "Rell Engine";
const t = (key, data) => (data ? game.i18n.format(`RELL.${key}`, data) : game.i18n.localize(`RELL.${key}`));

/* -------------------------------------------- */
/*  Objeto base de dnd5e                        */
/* -------------------------------------------- */

/**
 * Busca en los compendios de dnd5e el objeto base (p. ej. "longsword").
 * @param {object} src  Objeto exportado por Rell Engine.
 * @returns {Promise<object|null>}
 */
async function findBase(src) {
  const id = src.base?.foundry;
  if ( !id ) return null;
  const cfg = CONFIG.DND5E ?? {};
  const ref = cfg.weaponIds?.[id] ?? cfg.armorIds?.[id] ?? cfg.shieldIds?.[id];
  if ( !ref ) return null;
  try {
    let uuid = ref;
    if ( !ref.startsWith("Compendium.") ) {
      const parts = ref.split(".");
      const pack = (parts.length === 3) ? `${parts[0]}.${parts[1]}` : cfg.sourcePacks?.ITEMS;
      uuid = `Compendium.${pack}.Item.${parts.at(-1)}`;
    }
    const doc = await fromUuid(uuid);
    return doc?.toObject() ?? null;
  } catch(err) {
    console.warn(`${MODULE_ID} | no se pudo cargar el objeto base "${id}"`, err);
    return null;
  }
}

/* -------------------------------------------- */
/*  Importación                                 */
/* -------------------------------------------- */

async function getFolder() {
  const existing = game.folders.find(f => (f.type === "Item") && (f.name === FOLDER_NAME) && !f.folder);
  if ( existing ) return existing;
  return getDocumentClass("Folder").create({ name: FOLDER_NAME, type: "Item" });
}

/**
 * Crea en el mundo los objetos de una o varias exportaciones de Rell Engine.
 * @param {object[]} sources                Objetos exportados (el contenido de `items`).
 * @param {object} [options]
 * @param {boolean} [options.folder=true]   Guardarlos en la carpeta "Rell Engine".
 * @returns {Promise<Item[]>}
 */
export async function importItems(sources, { folder=true }={}) {
  const generation = game.release?.generation ?? 13;
  const randomID = () => foundry.utils.randomID();
  const toCreate = [];
  for ( const src of sources ) {
    try {
      const base = await findBase(src);
      if ( !base && src.base?.foundry ) {
        ui.notifications.warn(t("NoBase", { name: src.name, base: src.base.foundry }));
      }
      toCreate.push(buildItemData(src, base, { generation, randomID }));
    } catch(err) {
      console.error(`${MODULE_ID} |`, err);
      ui.notifications.error(t("ItemError", { name: src?.name ?? "?", error: err.message }));
    }
  }
  if ( !toCreate.length ) {
    ui.notifications.warn(t("NoneImported"));
    return [];
  }
  if ( folder ) {
    const target = await getFolder();
    for ( const data of toCreate ) data.folder = target.id;
  }
  const created = await getDocumentClass("Item").createDocuments(toCreate);
  ui.notifications.info(t("Done", { count: created.length }));
  return created;
}

/**
 * Interpreta textos JSON (archivos o texto pegado) y devuelve los objetos que contienen.
 * @param {{name: string, text: string}[]} texts
 * @returns {object[]}
 */
function parseTexts(texts) {
  const sources = [];
  for ( const { name, text } of texts ) {
    let payload;
    try {
      payload = JSON.parse(text);
    } catch(err) {
      ui.notifications.error(t("BadJson", { source: name, error: err.message }));
      continue;
    }
    try {
      sources.push(...readPayload(payload));
    } catch(err) {
      ui.notifications.error(t((err.code === "version") ? "NewerFormat" : "BadFormat", { source: name }));
    }
  }
  return sources;
}

/* -------------------------------------------- */
/*  Diálogo                                     */
/* -------------------------------------------- */

export async function openImportDialog() {
  const content = `
    <div class="form-group stacked">
      <label for="rell-files">${t("Files")}</label>
      <input id="rell-files" type="file" name="files" accept=".json,application/json" multiple>
    </div>
    <div class="form-group stacked">
      <label for="rell-json">${t("Paste")}</label>
      <textarea id="rell-json" name="json" rows="6" spellcheck="false"></textarea>
    </div>
    <div class="form-group">
      <label for="rell-folder">${t("Folder")}</label>
      <input id="rell-folder" type="checkbox" name="folder" checked>
    </div>`;

  const result = await foundry.applications.api.DialogV2.wait({
    window: { title: t("Title"), icon: "fa-solid fa-hammer" },
    position: { width: 480 },
    content,
    rejectClose: false,
    buttons: [
      {
        action: "import",
        label: t("Import"),
        icon: "fa-solid fa-file-import",
        default: true,
        callback: (event, button) => {
          const el = button.form.elements;
          return { files: Array.from(el.files.files ?? []), text: el.json.value.trim(), folder: el.folder.checked };
        }
      },
      { action: "cancel", label: t("Cancel"), icon: "fa-solid fa-xmark", callback: () => null }
    ]
  });
  if ( !result || (typeof result !== "object") ) return [];

  const texts = [];
  for ( const file of result.files ) texts.push({ name: file.name, text: await file.text() });
  if ( result.text ) texts.push({ name: t("Paste"), text: result.text });
  if ( !texts.length ) {
    ui.notifications.warn(t("Nothing"));
    return [];
  }
  const sources = parseTexts(texts);
  if ( !sources.length ) return [];
  return importItems(sources, { folder: result.folder });
}

/* -------------------------------------------- */
/*  Hooks                                       */
/* -------------------------------------------- */

Hooks.once("ready", () => {
  if ( game.system.id !== "dnd5e" ) {
    if ( game.user.isGM ) ui.notifications.warn(t("WrongSystem"));
    return;
  }
  game.modules.get(MODULE_ID).api = { importItems, openImportDialog };
});

Hooks.on("renderItemDirectory", (app, html) => {
  if ( game.system.id !== "dnd5e" ) return;
  if ( !getDocumentClass("Item").canUserCreate(game.user) ) return;
  const root = (html instanceof HTMLElement) ? html : html[0];
  if ( !root || root.querySelector(".rell-engine-import") ) return;

  const button = document.createElement("button");
  button.type = "button";
  button.classList.add("rell-engine-import");
  button.innerHTML = `<i class="fa-solid fa-hammer" inert></i> ${t("Button")}`;
  button.addEventListener("click", () => openImportDialog());

  let actions = root.querySelector(".header-actions");
  if ( !actions ) {
    actions = document.createElement("div");
    actions.className = "header-actions action-buttons flexrow";
    (root.querySelector(":scope > header") ?? root).insertAdjacentElement("afterbegin", actions);
  }
  actions.append(button);
});
