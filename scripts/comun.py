"""Utilidades comunes de los scripts: configuración (.env), conexión a PostgreSQL, SQL por archivo, descargas,
carga de vectores con GDAL y el servicio de PostgreSQL para QGIS.

Se corre con el Python de QGIS (correr.bat), que trae GDAL, PROJ, psycopg y PyQGIS ya configurados. Ojo: el instalador
de PostGIS dejó PROJ_LIB y GDAL_DATA de Windows apuntando a sus copias viejas; el lanzador de QGIS fija PROJ_DATA y
GDAL_DATA propios, por eso los scripts no se corren con otro Python.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS = RAIZ / 'datos'
FUENTES = DATOS / 'fuentes'
SQL = RAIZ / 'sql'

# México ITRF2008 / UTM zona 14N: Hidalgo (99.9° a 97.9° O) cabe completo en la zona 14 (102° a 96° O).
# Todo lo que se mide (áreas, distancias, pendientes) se hace en metros sobre este sistema.
SRID = 6369


def leer_env(ruta: Path = RAIZ / '.env') -> dict[str, str]:
    """Lee el .env (CLAVE=valor; # comenta)."""
    if not ruta.exists():
        sys.exit(f'Falta {ruta}: copia .env.example como .env y llénalo.')
    cfg: dict[str, str] = {}
    for linea in ruta.read_text(encoding='utf-8').splitlines():
        linea = linea.strip()
        if not linea or linea.startswith('#') or '=' not in linea:
            continue
        clave, valor = linea.split('=', 1)
        cfg[clave.strip()] = valor.strip().strip('"').strip("'")
    return cfg


CFG = leer_env()
SERVICIO = CFG.get('PG_SERVICE', 'relieveqgis')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def conectar():
    """Conexión con autocommit: cada archivo SQL corre dentro de su propia transacción (correr_sql)."""
    import psycopg
    con = psycopg.connect(host=CFG['DB_HOST'], port=CFG.get('DB_PORT', '5432'), dbname=CFG['DB_DATABASE'],
                          user=CFG['DB_USERNAME'], password=CFG['DB_PASSWORD'], autocommit=True)
    con.add_notice_handler(_aviso)
    return con


def _aviso(d) -> None:
    """Muestra los RAISE NOTICE de los SQL, sin los «no existe, omitiendo» de DROP ... IF EXISTS."""
    msg = d.message_primary or ''
    if 'omitiendo' in msg or 'skipping' in msg:
        return
    print(f'    {msg}', flush=True)


def correr_sql(con, ruta: Path) -> None:
    """Corre un archivo SQL completo en una sola transacción: si algo falla, no queda nada a medias."""
    t0 = time.time()
    with con.transaction():
        con.execute(ruta.read_text(encoding='utf-8'))
    log(f'{ruta.relative_to(RAIZ).as_posix()} listo ({time.time() - t0:.1f} s)')


def consulta(con, sql: str, params=None) -> list[tuple]:
    return con.execute(sql, params).fetchall()


def descargar(url: str, destino: Path, minimo: int = 1000) -> Path:
    """Baja un archivo si no está ya (o si quedó vacío). Escribe a .part y renombra al terminar."""
    if destino.exists() and destino.stat().st_size >= minimo:
        log(f'ya está {destino.relative_to(RAIZ).as_posix()}')
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + '.part')
    log(f'bajando {url}')
    req = urllib.request.Request(url, headers={'User-Agent': 'relieve-qgis/0.1'})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, 'wb') as f:
        shutil.copyfileobj(r, f)
    if tmp.stat().st_size < minimo:
        raise RuntimeError(f'{url} devolvió solo {tmp.stat().st_size} bytes')
    tmp.replace(destino)
    log(f'  {destino.stat().st_size / 1e6:.1f} MB')
    return destino


def pg_gdal() -> str:
    """Cadena de conexión de GDAL a la base (con la contraseña del .env; no se imprime)."""
    return (f"PG:host={CFG['DB_HOST']} port={CFG.get('DB_PORT', '5432')} dbname='{CFG['DB_DATABASE']}' "
            f"user={CFG['DB_USERNAME']} password={CFG['DB_PASSWORD']}")


def cargar_vector(origen: Path, esquema: str, tabla: str, *, srs_origen: str | None = None,
                  caja: tuple[float, float, float, float] | None = None, tipo: str = 'PROMOTE_TO_MULTI') -> None:
    """Carga un archivo vectorial a PostGIS reproyectado a EPSG:6369, con geometrías válidas e índice espacial.

    srs_origen: para archivos cuyo sistema no se lee bien (el GeoJSON de INEGI declara EPSG:6365 dentro de cada
    geometría, donde GDAL no lo busca). caja: (oeste, sur, este, norte) en el sistema de origen.
    """
    from osgeo import gdal
    gdal.UseExceptions()
    t0 = time.time()
    opciones = gdal.VectorTranslateOptions(
        options=['-makevalid', '-lco', f'SCHEMA={esquema}', '-lco', 'GEOMETRY_NAME=geom', '-lco', 'FID=gid',
                 '-lco', 'SPATIAL_INDEX=GIST', '-lco', 'LAUNDER=YES', '-lco', 'PRECISION=NO'],
        format='PostgreSQL', accessMode='overwrite', layerName=tabla, srcSRS=srs_origen, dstSRS=f'EPSG:{SRID}',
        reproject=True, geometryType=tipo, spatFilter=caja)
    ds = gdal.VectorTranslate(pg_gdal(), str(origen), options=opciones)
    if ds is None:
        raise RuntimeError(f'No se pudo cargar {origen}')
    n = ds.GetLayerByName(f'{esquema}.{tabla}').GetFeatureCount()
    ds = None
    log(f'{esquema}.{tabla}: {n} elementos de {Path(origen).name} ({time.time() - t0:.1f} s)')


def escribir_servicio() -> Path:
    """Escribe (o actualiza) la sección del servicio en %APPDATA%\\postgresql\\.pg_service.conf.

    Con ella QGIS abre las capas con service='relieveqgis' y el proyecto .qgz no guarda la contraseña.
    Respeta las demás secciones que ya hubiera en el archivo.
    """
    ruta = Path(os.environ['APPDATA']) / 'postgresql' / '.pg_service.conf'
    bloque = [f'[{SERVICIO}]', f"host={CFG['DB_HOST']}", f"port={CFG.get('DB_PORT', '5432')}",
              f"dbname={CFG['DB_DATABASE']}", f"user={CFG['DB_USERNAME']}", f"password={CFG['DB_PASSWORD']}"]
    otras: list[str] = []
    if ruta.exists():
        dentro = False
        for linea in ruta.read_text(encoding='utf-8').splitlines():
            s = linea.strip()
            if s.startswith('[') and s.endswith(']'):
                dentro = s[1:-1] == SERVICIO
            if not dentro:
                otras.append(linea)
    while otras and not otras[-1].strip():
        otras.pop()
    texto = '\n'.join(otras + ([''] if otras else []) + bloque) + '\n'
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding='utf-8')
    log(f'servicio [{SERVICIO}] en {ruta}')
    return ruta
