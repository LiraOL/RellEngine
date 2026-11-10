# Rell Engine

Generador de armas, armaduras y joyas para **D&D 5e**, mágicas y no mágicas, a partir de
tablas de texto que puedes editar y ampliar. Incluye un módulo de **Foundry VTT** para
importar los objetos a la partida con un botón.

```
Rell Engine/                     Generador (aplicación de escritorio y línea de comandos)
  rell.py                        Punto de entrada
  rellengine/                    Código del motor
  common/  config/               Rarezas, nombres y reglas generales
  expansions/base/               Tablas: objetos base de 5e y efectos
  GUIA_EXPANSIONES.md            Cómo editar y crear tablas
foundry-module/rell-engine-importer/   Módulo de Foundry
```

## Generador

Necesita Python 3.9 o superior. La interfaz usa PySide6; la línea de comandos no necesita nada más.

```bash
cd "Rell Engine"
pip install -r requirements.txt     # solo para la interfaz
python rell.py                      # abre la aplicación
```

En la aplicación eliges categoría, tipo, objeto base, rareza y cantidad, y pulsas **Generar**.
Selecciona en la lista los objetos que te gusten y usa **Exportar para Foundry…** (archivo
`.json`) o **Copiar para Foundry** (portapapeles).

Por línea de comandos:

```bash
python rell.py --listar                                # rarezas, categorías y tipos
python rell.py -r raro -c arma -n 5                    # 5 armas raras
python rell.py -r legendario -t espada -o espada_larga --maldito
python rell.py -r mundano -c armadura                  # objeto no mágico
python rell.py -r poco_comun -n 10 --exportar botin.json
python rell.py --comprobar                             # revisa las tablas
```

Cada rareza tiene un presupuesto de puntos. Cada línea de las tablas tiene un coste (positivo
si es una ventaja, negativo si es un inconveniente) y el motor combina efectos hasta cuadrar
el presupuesto. Todo se explica en [`Rell Engine/GUIA_EXPANSIONES.md`](Rell%20Engine/GUIA_EXPANSIONES.md).

## Módulo de Foundry

Requiere Foundry v13 o v14 y el sistema **dnd5e** 5.0 o superior.

1. Copia la carpeta `foundry-module/rell-engine-importer` dentro de `Data/modules/` de tu
   instalación de Foundry (debe quedar `Data/modules/rell-engine-importer/module.json`).
2. Reinicia Foundry y activa **Rell Engine Importer** en *Gestionar módulos* de tu mundo.
3. En la pestaña **Objetos** de la barra lateral aparece el botón **Importar de Rell Engine**.
   Elige el archivo `.json` exportado, o pega lo copiado con «Copiar para Foundry», y pulsa
   **Importar**. Los objetos se crean en la carpeta «Rell Engine».

Qué queda automatizado en la ficha del objeto:

- Estadísticas, icono y maestría del objeto base, tomadas del compendio de dnd5e.
- Rareza, sintonización, precio y propiedad «mágico».
- Bonificador mágico (+1/+2/+3) al ataque y daño o a la CA.
- Daño adicional permanente (p. ej. +1d6 de fuego) en la tirada de daño del arma.
- Efectos pasivos: resistencias, vulnerabilidades, CA, salvaciones y velocidad.
- Poderes con usos limitados (p. ej. «una vez por amanecer»), como actividades con sus usos.

Los efectos puramente narrativos o condicionales aparecen como texto en la descripción.

Desde una macro también puedes usar
`game.modules.get("rell-engine-importer").api.openImportDialog()`.

## Pruebas

```bash
cd "Rell Engine" && python -m unittest discover tests
node --test foundry-module/rell-engine-importer/tests/convert.test.mjs
```
