# Relieve de Hidalgo en QGIS + PostGIS

Hidalgo en 3D, realista y detallado, para análisis confiables: dónde reforestar, dónde construir, por dónde trazar
un camino. Parte de los datos del visor web [RelieveHidalgo](../RelieveHidalgo) (three.js) y los lleva a un SIG con
relieve fino (1.5 m en Pachuca y su zona metropolitana, 5 m en la mitad del estado, 15 m en el resto).

## Requisitos

- PostgreSQL 17 con PostGIS 3.6 y pgRouting (los trae el instalador de PostGIS de StackBuilder)
- QGIS 3.44 LTR (su Python 3.12 trae GDAL, PROJ, psycopg, geopandas y PyQGIS: no se instala nada más)
- El proyecto web con sus datos crudos en `data-src` (ruta en `WEB_DATA`)

## Uso

```bat
copy .env.example .env               :: y llénalo
correr scripts\fase0.py              :: PostGIS, esquemas y capas (se puede repetir; ≈ 1 min)
correr scripts\fase1.py cem          :: CEM 4.0 de INEGI, 15 m (baja 7 GB una vez; ≈ 30 min)
correr scripts\fase1.py hojas        :: hojas de 1.5 m del piloto (2.4 GB; --zona=estado para todo Hidalgo, 16 GB)
correr scripts\fase1.py relieve      :: mosaico, fusión con el CEM, sombreado y pendiente
correr scripts\fase1.py calidad      :: control de calidad de cada hoja (terreno.hojas)
correr scripts\fase1.py registrar    :: rásters en PostGIS y terreno.altitud(punto) por SQL
correr scripts\fase2.py mg topo50 osm       :: calles y manzanas de INEGI 2025, cartas 1:50 000 y OpenStreetMap
correr scripts\fase2.py drenaje agua calles :: cauces y subcuencas (GRASS), cuerpos de agua y pendiente de calles
correr scripts\fase3.py edificios arboles  :: edificios con altura medida y árboles uno por uno (≈ 20 min)
correr scripts\proyecto_qgis.py --forzar   :: rehace qgis\RelieveHidalgo.qgz con el relieve y el terreno 3D
correr scripts\vista_previa.py       :: PNG del proyecto en datos\vistas, sin abrir QGIS
correr scripts\vista_3d.py pachuca 522000 2223000 6000 65 200   :: vista 3D a PNG
```

En QGIS: **Ver → Vista de mapa 3D** usa el terreno del proyecto (Propiedades del proyecto → Elevación): el relieve
de 1.5 m del piloto. Para ver todo el estado en 3D, cambia ahí la capa a «Altitud, Hidalgo (CEM 4.0, 15 m)».

`correr.bat` usa el Python de QGIS. No uses otro Python: el instalador de PostGIS dejó `PROJ_LIB` y `GDAL_DATA` de
Windows apuntando a copias viejas, y solo el lanzador de QGIS las corrige.

La fase 0 escribe la sección `[relieveqgis]` en `%APPDATA%\postgresql\.pg_service.conf`. Con ella el proyecto de
QGIS se conecta sin guardar la contraseña.

## Base de datos

| Esquema | Qué tiene | Quién lo escribe |
|---|---|---|
| `relieve` | Las 49 tablas del visor web (agua, población, riesgos, culturas…) con lon/lat o GeoJSON | El proyecto web (`pnpm data:db`). **No se toca aquí**: su carga lo borra con `DROP SCHEMA … CASCADE` |
| `base` | Fuentes oficiales tal cual: municipios, estado y entidades de INEGI (Marco Geoestadístico de dic. 2025), acuíferos y ordenamientos de CONAGUA | `scripts/fase0.py` |
| `qgis` | 30 capas listas: las de `relieve` con geometría PostGIS, índice espacial y comentarios, más uniones con `base` | `scripts/fase0.py` |
| `meta` | `meta.capas`: fuente, fecha, escala y detalle de cada capa (también los rásters, como `archivo:ruta`); funciones de apoyo | `scripts/fase0.py`, `scripts/fase1.py` |
| `terreno` | Zonas de trabajo, índice de hojas de INEGI con su control de calidad, cobertura por resolución, rásters registrados fuera de la base y `terreno.altitud(punto)` | `scripts/fase1.py` |

Los rásters viven en `datos/terreno` como GeoTIFF optimizados (COG) y PostGIS solo guarda teselas que apuntan a
ellos. El servicio de PostgreSQL corre como NetworkService. Por eso la fase 1 le da permiso de solo lectura sobre esa
carpeta; se quita con `icacls datos\terreno /remove *S-1-5-20`.

Todo está en **EPSG:6369** (México ITRF2008 / UTM 14N, en metros; Hidalgo cabe entero en la zona 14). Las áreas
(`area_km2`, `area_ha`) se calculan sobre el elipsoide. Las capas de `qgis` son tablas y no vistas, para que
sobrevivan a una recarga de `relieve`. Si `relieve` se recarga, basta con volver a correr la fase 0.

## Regla de confiabilidad

Un cálculo no es más preciso que su dato más grueso. Cada capa declara en `meta.capas.detalle_m` el tamaño más chico
que distingue. Ejemplo: el uso de suelo 1:250 000 tiene un polígono mínimo de 50 ha (≈ 707 m), así que no sirve para
decidir sobre un predio. Cada análisis reporta el mayor `detalle_m` de lo que usa.

## Lo que dijo el control de calidad del relieve (fase 1, piloto)

- **Cobertura fina de INEGI en Hidalgo:** 1.5 m en el 24 % del estado, 5 m en el 29 % y solo el CEM de 15 m en el
  47 % (Sierra Gorda y Sierra Alta). Está en `terreno.cobertura`.
- **El CEM 4.0 queda arriba del terreno de las hojas de 1.5 m:** ≈ 3.8 m en terreno abierto y de 6 a 10 m bajo
  bosque. Las dos fuentes son de INEGI y usan el mismo geoide; el CEM sale de radar y ve en parte copas y techos.
  Dentro del piloto se ajusta localmente (`ajuste_cem_piloto_15m.tif`). Fuera, úsese el CEM para la forma del
  relieve y no para alturas absolutas finas.
- **Hojas vecinas difieren ≈ 1.1 m donde se enciman,** incluso en terreno abierto. En el mosaico se mezclan en 60 m,
  sin escalones.
- **Bajo bosque, el terreno de 1.5 m se ve en triángulos:** INEGI lo interpoló de pocos puntos del suelo, así que ahí
  el detalle real es menor.
- **Los metadatos de INEGI no traen la exactitud de las hojas,** e INEGI no publica en su catálogo vértices geodésicos
  descargables. El control es propio (`terreno.hojas`), más un cotejo con la altitud del ITER 2020: en el piloto
  difiere 5.4 m (mediana), lo esperable para un dato aproximado.

## Agua y calles (fase 2, piloto)

- **Calles oficiales:** ejes de vialidad del Marco Geoestadístico 2025 de INEGI (266 468 en Hidalgo, con nombre, tipo
  y sentido). Del zip nacional de 2.7 GB se baja solo el de Hidalgo (106 MB). INEGI mezcla codificaciones de texto
  sin declararlas; se detectan por archivo.
- **Pendiente de cada calle** (`terreno.calles`, 42 684 segmentos en el piloto): perfil cada 1.5 m sobre el relieve
  fino, con la pendiente máxima en 20 y en 60 m. El relieve no tiene puentes: los tramos junto a un puente o paso a
  desnivel de OSM (1 138) y los de perfil con un escalón corto (70) quedan «por revisar».
- **Cauces calculados** del relieve a 5 m con GRASS (`terreno.cauces`: 4 883 tramos, ≈ 3 030 km, desde 0.1 km²
  drenados) y 628 subcuencas de 2 km² o más. Coinciden con los ríos de las cartas 1:50 000 de INEGI: distancia
  mediana 8.5 m; 74 % a ≤ 20 m y 84 % a ≤ 50 m (perennes: 82 % y 92 %). Detalle en `terreno.control_cauces`.
- **Cuerpos de agua** de INEGI (137) y OSM (64) con su nivel (mediana de la altura en la orilla): en 3D se dibujan
  planos a ese nivel.
- El proyecto trae **marcadores** (Todo Hidalgo, zona piloto, Pachuca, Mineral del Monte, Mineral del Chico,
  Pachuquilla): panel «Marcadores espaciales».

## Edificios y árboles (fase 3, piloto)

- **Altura sobre el suelo** (superficie − terreno de INEGI, 1.5 m): `altura_suelo_piloto_1p5m.tif`.
- **Edificios** (`terreno.edificios`, 168 375 en la zona): contornos de Microsoft con la altura **medida** del techo
  (mediana de los píxeles de más de 2 m). 83 102 con confianza alta (mediana 4.4 m), 44 875 media y 40 398 sin
  medida (el modelo no los distingue del suelo; en 3D se dibujan con 3 m). Contra los niveles de OpenStreetMap
  (1 320 edificios): los mismos pisos en el 49 % y ±1 piso en el 89 %. En 3D se extruyen a su altura.
- **Árboles** (`terreno.arboles`): 865 267 árboles de 3 m o más con su altura y su copa, más 44 281 «posibles
  construcciones» (techos planos dentro de localidades sin contorno de Microsoft) y 3 122 «picos dudosos», que
  quedan aparte para revisar. Dosel en `dosel_piloto_1p5m.tif`.
- **Control contra el dosel de Meta y WRI** (`terreno.control_dosel`): en bosque cerrado vemos ≈ la mitad del
  dosel que Meta (El Chico: 45 % contra 82 %) porque bajo bosque el terreno de INEGI es una interpolación; ahí el
  conteo y las alturas son un mínimo. En ciudad y campo vemos más dosel que Meta (árboles chicos que Meta no ve).

## Fases

0. **Base** (lista): PostGIS, límites oficiales, capas con geometría, catálogo de capas y proyecto de QGIS.
1. **Relieve**: CEM 4.0 de INEGI (15 m, 2025) para todo el estado y modelos de 1.5 m en el piloto (Pachuca, Mineral
   de la Reforma, Mineral del Monte y Mineral del Chico). Mosaico con transición de 150 m hacia el CEM, control de
   calidad de cada hoja y terreno 3D del proyecto.
2. **Agua y calles** (lista en el piloto): cauces y subcuencas del relieve fino, cuerpos de agua con su nivel, calles
   y manzanas de INEGI 2025 con la pendiente de cada calle, OpenStreetMap.
3. **Edificios y árboles** (lista en el piloto): altura medida de cada edificio y árboles uno por uno, en 3D.
4. **Análisis**: reforestación, aptitud para construir, trazos de caminos con cortes y rellenos.

## Estructura

```
correr.bat               lanza un script con el Python de QGIS
scripts/comun.py         configuración, conexión, descargas, carga con GDAL, servicio de PostgreSQL
scripts/fase0.py         fase 0 completa con validación
scripts/fase1.py         fase 1 por pasos: cem, hojas, relieve, calidad, registrar
scripts/fase2.py         fase 2 por pasos: mg, topo50, osm, drenaje, agua, calles
scripts/fase3.py         fase 3 por pasos: altura, edificios, arboles
scripts/inegi.py         catálogo de INEGI, zips remotos por rangos y descargas en paralelo
scripts/proyecto_qgis.py arma el proyecto de QGIS
scripts/vista_previa.py  renderiza el proyecto a PNG
scripts/vista_3d.py      renderiza una vista 3D a PNG
sql/fase0/ … sql/fase3/  SQL de cada fase, en orden
qgis/                    proyecto de QGIS
datos/                   descargas y productos (no se versiona)
```
