# Guía para editar tablas y crear expansiones

No hace falta saber programar: todo son carpetas y archivos de texto (`.txt`, en UTF-8).
Tras editar, pulsa **Recargar tablas** en la pestaña *Expansiones* de la aplicación, o ejecuta
`python rell.py --comprobar`. Los errores se muestran indicando archivo y línea.

En todos los archivos, las líneas vacías y las que empiezan por `#` se ignoran.

## Cómo se genera un objeto

1. Se elige un **objeto base** (por ejemplo, *espada larga*) de un **tipo** (*espada*).
2. Según la **rareza** se decide cuántos efectos lleva y qué **presupuesto** deben sumar.
3. El motor prueba combinaciones de líneas de `efectos.txt` hasta que la suma de costes
   cuadra con el presupuesto (± la tolerancia).
4. Se le pone nombre y, a veces, una frase de apariencia.

Un objeto de rareza *mundano* no lleva efectos: es el objeto base tal cual.

## Estructura de carpetas

```
common/                      Tablas generales (rarezas, nombres, colores...)
config/rules.txt             Reglas del generador
config/enabled_expansions.txt  Expansiones activas
expansions/
  base/
    manifest.txt             Qué tipos añade la expansión
    common/                  Tablas generales que añade la expansión
    _arma/                   Tablas compartidas por todos los tipos con el tag "arma"
    _armadura/  _joya/ ...
    espada/                  Un tipo
      objetos.txt            Objetos base del tipo
      efectos.txt            (opcional) efectos exclusivos del tipo
      apariencias.txt        (opcional)
```

Cuando el motor necesita una tabla (por ejemplo `efectos`), junta las líneas de la carpeta del
tipo con las de las carpetas `_<tag>` de cada uno de sus tags. Si no la encuentra ahí, la busca
en `common/`. Varias expansiones pueden añadir líneas a la misma tabla o al mismo tipo.

## manifest.txt

```
id=mi_expansion
name=Mi expansión
version=1.0.0
type=espada|tags=arma,cuerpo_a_cuerpo|nombre=Espada
type=anillo|tags=joya|nombre=Anillo
```

Cada `type=` debe tener una carpeta con el mismo nombre. Tags con significado especial:

| Tag | Efecto |
| --- | --- |
| `arma` | En Foundry se crea como arma |
| `a_distancia` | El arma es a distancia (si no, cuerpo a cuerpo) |
| `armadura` | En Foundry se crea como armadura |
| `escudo` | En Foundry se crea como escudo |
| cualquier otro | Objeto maravilloso; sirve como categoría y para cargar `_<tag>` |

Para añadir líneas a un tipo que ya existe en otra expansión, decláralo igual en tu manifest
y crea su carpeta con solo los archivos nuevos.

## objetos.txt

```
id|Nombre|clave=valor;clave=valor
espada_larga|Espada larga|foundry=longsword;categoria=marcial;daño=1d8 cortante;versatil=1d10;propiedades=versatil;peso=3;precio=15
```

| Clave | Para | Significado |
| --- | --- | --- |
| `foundry` | armas, armaduras | Id del objeto base en dnd5e (`longsword`, `plate`, `shield`...). Foundry copia de él estadísticas e icono. Varios objetos pueden usar el mismo, p. ej. una *katana* con `foundry=longsword`. Si se omite, se usan los datos de esta línea |
| `categoria` | armas | `simple` o `marcial` |
| `daño` | armas | `1d8 cortante` |
| `versatil` | armas | Dado a dos manos: `1d10` |
| `propiedades` | armas | `sutil, ligera, pesada, alcance, arrojadiza, a_dos_manos, versatil, municion, recarga` |
| `alcance` | armas | `20/60` (en pies) |
| `clase` | armaduras | `ligera`, `media`, `pesada` o `escudo` |
| `ca` | armaduras | CA base (en escudos, el bonificador) |
| `des` | armaduras | Máximo de mod. de Destreza (`2`; `0` = no suma; sin poner = sin límite) |
| `fuerza`, `sigilo` | armaduras | Fuerza mínima; `sigilo=desventaja` |
| `foundry_tipo` | otros | Tipo de equipo en dnd5e: `ring`, `wondrous`, `trinket`, `rod`, `wand`, `clothing` |
| `peso`, `precio` | todos | En libras y piezas de oro |
| `tags` | todos | Tags extra del objeto, para usar con `solo:` |

Ids de `foundry` para armas: battleaxe, blowgun, club, dagger, dart, flail, glaive, greataxe,
greatclub, greatsword, halberd, handaxe, handcrossbow, heavycrossbow, javelin, lance,
lightcrossbow, lighthammer, longbow, longsword, mace, maul, morningstar, musket, pike, pistol,
quarterstaff, rapier, scimitar, shortsword, sickle, spear, shortbow, sling, trident, warpick,
warhammer, whip. Armaduras: padded, leather, studded, hide, chainshirt, scalemail, breastplate,
halfplate, ringmail, chainmail, splint, plate. Escudo: shield.

## Tablas normales (efectos y todo lo demás)

```
coste|texto
coste|tags|texto
coste|tags|texto|mecánicas
```

- **coste**: número entero. Positivo = ventaja, negativo = inconveniente, 0 = neutro.
- **tags**: separados por comas, o `-` si no hay.
  - Un tag normal (`fuego`) marca el tema del objeto. Las líneas que comparten tema con lo ya
    elegido salen con más frecuencia, y las combinaciones de `mezclas_prohibidas` nunca salen.
  - `solo:x` restringe la línea a objetos con ese tag, tipo, id o propiedad:
    `solo:arrojadiza`, `solo:espada`, `solo:municion`.
- **texto**: lo que se lee en el objeto. Puede llevar `{placeholders}`.
- **mecánicas**: opcional; lo que Foundry aplicará automáticamente (ver más abajo).

El texto no puede contener el carácter `|`.

### Placeholders

`{nombre}` se sustituye por una línea al azar de la tabla `nombre.txt`, y su coste se suma.

```
# _arma/efectos.txt
0|-|Los ataques con esta arma infligen {dano_extra} adicional.

# _arma/dano_extra.txt
3|-|1d4 de daño {elemento}|daño=1d4 {elemento}
5|-|1d6 de daño {elemento}|daño=1d6 {elemento}

# common/elemento.txt
0|fuego|de fuego
0|mente|psíquico
```

Resultado posible: «Los ataques con esta arma infligen 1d6 de daño de fuego adicional», con
coste 5, tag `fuego` y, en Foundry, +1d6 de fuego en la tirada de daño.

- Dentro de una misma línea, un placeholder repetido vale siempre lo mismo, también en las
  mecánicas. Por eso `{elemento}` coincide en el texto y en `daño=`.
- Placeholders especiales: `{objeto}` (nombre del objeto base) y `{objeto_min}` (en minúscula).
- Una línea de `efectos.txt` no se repite en el mismo objeto, ni tampoco las líneas con coste
  distinto de 0. Las de coste 0 (como `{elemento}`) sí pueden repetirse.
- En los nombres de archivo y placeholders se ignoran mayúsculas y tildes.

### Mecánicas

Varias mecánicas se separan con `;`.

| Mecánica | Efecto en Foundry |
| --- | --- |
| `bono=1` | Bonificador mágico: ataque y daño en armas, CA en armaduras y escudos |
| `daño=1d6 fuego` | Daño adicional en cada impacto del arma |
| `ca=1` | +1 a la CA de quien lo lleva (para joyas y similares) |
| `salvaciones=1` | +1 a todas las tiradas de salvación |
| `resistencia=fuego` | Resistencia (admite varios: `fuego,frío`) |
| `inmunidad=veneno` / `vulnerabilidad=radiante` | Inmunidad / vulnerabilidad |
| `velocidad=10` | +10 pies de velocidad (admite negativos) |
| `propiedad=plateada` | Añade una propiedad al arma (`plateada`, `adamantina`, `retorno`, `sutil`...) |
| `sintonizacion=si` | El objeto requiere sintonización |
| `usos=1/amanecer` | Crea un poder con usos. Periodos: `dia`, `amanecer`, `anochecer`, `descanso_largo`, `descanso_corto` |
| `activacion=adicional` | Con `usos`: `accion` (por defecto), `adicional`, `reaccion` o `especial` |
| `poder=Nombre` | Con `usos`: nombre del poder en la ficha |
| `ae=clave modo valor` | Efecto activo libre, p. ej. `ae=system.abilities.str.value upgrade 19`. Modos: `add`, `override`, `upgrade`, `downgrade`, `multiply` |

Tipos de daño: ácido, contundente, cortante, frío, fuego, fuerza, necrótico, perforante,
psíquico, radiante, relámpago, trueno, veneno.

Importante: todas las mecánicas de una línea (y de sus placeholders) se aplican de forma
**permanente**. Si un efecto es condicional o de usos limitados («una vez al día infliges
2d6…»), describe el daño solo en el texto y no pongas `daño=`.

## Rarezas: common/rareza.txt

```
id|Nombre|presupuesto|tolerancia|efectos|max_malos|foundry|precio
raro|Raro|8|1|1-3|1|rare|4000
```

Un objeto raro tendrá de 1 a 3 efectos que sumen entre 7 y 9 puntos, con un efecto negativo
como máximo. `foundry` es la rareza en Foundry (`common`, `uncommon`, `rare`, `veryRare`,
`legendary`, `artifact`) y `precio` se suma al del objeto base.

Como referencia, en las tablas base un +1 cuesta 4, un +2 cuesta 8 y un +3 cuesta 12; +1d4 de
daño cuesta 3 y +1d6 cuesta 5; una resistencia cuesta 6; los inconvenientes van de -1 a -4.

## Nombres y apariencia

- `common/plantillas_nombres.txt`: plantillas como `0|{objeto} {epitetos}` o `0|{sobrenombres}`.
- `epitetos.txt`, `sobrenombres.txt`, `temas.txt`: piezas del nombre. En estas tablas, una
  línea **con tags solo se usa si el objeto tiene alguno de ellos**, de modo que «de las
  Brasas» solo aparece en objetos de fuego. Las líneas sin tags valen para cualquiera.
- `apariencias.txt` (en `_arma`, `_armadura`, en un tipo...): frases descriptivas sin coste.
  Siguen la misma regla de tags que los nombres.

Puedes poner estas tablas dentro de la carpeta de un tipo para darle nombres propios.

## config/rules.txt

| Regla | Significado |
| --- | --- |
| `intentos` | Combinaciones que prueba el motor para cuadrar el presupuesto |
| `preferencia_tags` | Cuánto más probable es una línea que coincide con el tema del objeto (1 = nada) |
| `mezclas_prohibidas` | Tags incompatibles: `hielo+fuego,sagrado+profano` |
| `probabilidad_apariencia` | Probabilidad (0-100) de añadir una frase de apariencia |

## Ejemplo: añadir una katana y un efecto nuevo

En `expansions/base/espada/objetos.txt`:

```
katana|Katana|foundry=longsword;categoria=marcial;daño=1d8 cortante;versatil=1d10;propiedades=versatil;peso=3;precio=30
```

En `expansions/base/espada/efectos.txt` (créalo si no existe):

```
3|rayo|Una vez por amanecer, puedes usar una acción adicional para desenvainar con un destello cegador: una criatura a 5 pies debe superar una salvación de Constitución CD 13 o quedar cegada hasta el final de tu siguiente turno.|usos=1/amanecer;activacion=adicional;poder=Destello
```
