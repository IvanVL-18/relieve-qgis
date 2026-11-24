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
correr scripts\proyecto_qgis.py      :: arma qgis\RelieveHidalgo.qgz (--forzar para rehacerlo)
correr scripts\vista_previa.py       :: PNG del proyecto en datos\vistas, sin abrir QGIS
```

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
| `meta` | `meta.capas`: fuente, fecha, escala y detalle de cada capa; funciones de apoyo | `scripts/fase0.py` |

Todo está en **EPSG:6369** (México ITRF2008 / UTM 14N, en metros; Hidalgo cabe entero en la zona 14). Las áreas
(`area_km2`, `area_ha`) se calculan sobre el elipsoide. Las capas de `qgis` son tablas y no vistas, para que
sobrevivan a una recarga de `relieve`. Si `relieve` se recarga, basta con volver a correr la fase 0.

## Regla de confiabilidad

Un cálculo no es más preciso que su dato más grueso. Cada capa declara en `meta.capas.detalle_m` el tamaño más chico
que distingue. Ejemplo: el uso de suelo 1:250 000 tiene un polígono mínimo de 50 ha (≈ 707 m), así que no sirve para
decidir sobre un predio. Cada análisis reporta el mayor `detalle_m` de lo que usa.

## Fases

0. **Base** (lista): PostGIS, límites oficiales, capas con geometría, catálogo de capas y proyecto de QGIS.
1. **Relieve**: CEM 3.0 de 15 m para todo el estado y modelos de 1.5 m de INEGI en el piloto (Pachuca, Mineral de la
   Reforma, Mineral del Monte y Mineral del Chico). Mosaico con transiciones, control de calidad contra vértices
   geodésicos y vista 3D.
2. **Agua y calles**: ríos y cuencas recalculados del relieve fino, cuerpos de agua, calles y manzanas de INEGI, OSM.
3. **Edificios y árboles**: altura medida (superficie − terreno) de cada edificio y árboles uno por uno.
4. **Análisis**: reforestación, aptitud para construir, trazos de caminos con cortes y rellenos.

## Estructura

```
correr.bat               lanza un script con el Python de QGIS
scripts/comun.py         configuración, conexión, descargas, carga con GDAL, servicio de PostgreSQL
scripts/fase0.py         fase 0 completa con validación
scripts/proyecto_qgis.py arma el proyecto de QGIS
scripts/vista_previa.py  renderiza el proyecto a PNG
sql/fase0/               SQL de la fase 0, en orden
qgis/                    proyecto de QGIS
datos/                   descargas y productos (no se versiona)
```
