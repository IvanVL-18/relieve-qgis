"""Fase 1: el relieve.

  correr scripts\\fase1.py cem        CEM 4.0 de INEGI (15 m, 2025) para Hidalgo y alrededores
  correr scripts\\fase1.py hojas      modelos de 1.5 y 5 m de INEGI (terreno y superficie) de la zona (piloto)

Los pasos se pueden repetir: lo que ya está bajado o hecho no se rehace.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from comun import DATOS, FUENTES, RAIZ, SRID, conectar, consulta, log
import inegi

TERRENO = DATOS / 'terreno'

# Continuo de Elevaciones Mexicano 4.0 (INEGI, 2025, 15 m): un solo zip nacional de 9.6 GB con un GeoTIFF de 7.6 GB
# comprimido dentro (deflate). Como no se puede leer un pedazo de un miembro comprimido, se baja solo ese miembro
# (6.97 GB) por rangos y se descomprime aquí, comprobando su CRC32 contra el zip.
CEM_UPC = '794551151600'
CEM_URL = (f'{inegi.SITIO}/contenidos/productos/prod_serv/contenidos/espanol/bvinegi/productos/geografia/relieve/'
           f'{CEM_UPC}_t.zip')
CEM_TIF = 'conjunto_de_datos/continuonacional_15m.tif'
CEM_CHICOS = ['conjunto_de_datos/continuonacional_15m.tfw', 'conjunto_de_datos/continuonacional_15m.tif.aux.xml',
              'conjunto_de_datos/continuonacional_15m.tif.xml', 'metadato/contiuonacional_15m.txt',
              'metadato/metadatos_contiuonacional_15m.txt']
MARGEN_M = 25_000   # alrededor del estado: montañas vecinas para el horizonte del 3D


def gdal_():
    from osgeo import gdal
    gdal.UseExceptions()
    gdal.SetConfigOption('GDAL_NUM_THREADS', 'ALL_CPUS')
    gdal.SetCacheMax(1024 * 1024 * 1024)
    return gdal


def caja_estado(margen: float) -> tuple[float, float, float, float]:
    con = conectar()
    return consulta(con, """select ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b)
                            from (select ST_Expand(ST_Envelope(geom), %s) as b from base.estado) x""", (margen,))[0]


def paso_cem() -> Path:
    gdal = gdal_()
    carpeta = FUENTES / 'inegi' / 'cem4'
    tif = carpeta / Path(CEM_TIF).name
    destino = TERRENO / 'cem4_15m.tif'
    if destino.exists():
        log(f'ya está {destino.relative_to(RAIZ).as_posix()}')
        return destino
    if not tif.exists():
        inicio, comprimido, tamano, crc, metodo = inegi.miembro_zip(CEM_URL, CEM_TIF)
        if metodo != 8:
            raise IOError(f'método de compresión {metodo} inesperado')
        crudo = carpeta / (tif.name + '.deflate')
        inegi.descargar_rangos(CEM_URL, crudo, inicio, comprimido, hilos=10)
        inegi.inflar(crudo, tif, tamano, crc)
        crudo.unlink()
    for nombre in CEM_CHICOS:
        f = carpeta / Path(nombre).name
        if not f.exists():
            f.write_bytes(inegi.leer_miembro_chico(CEM_URL, nombre))
    info = gdal.Info(str(tif), format='json')
    log(f"CEM nacional: {info['size'][0]} × {info['size'][1]} px, {info['bands'][0]['type']}, "
        f"{info['coordinateSystem']['wkt'].splitlines()[0][:80]}")
    xmin, ymin, xmax, ymax = caja_estado(MARGEN_M)
    TERRENO.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tmp = destino.with_name(destino.stem + '_tmp.tif')
    # Bilineal: no inventa crestas ni valles (la cúbica puede rebasar en los cantiles).
    gdal.Warp(str(tmp), str(tif), dstSRS=f'EPSG:{SRID}', outputBounds=(xmin, ymin, xmax, ymax), xRes=15, yRes=15,
              targetAlignedPixels=True, resampleAlg='bilinear', outputType=gdal.GDT_Float32, dstNodata=-9999,
              multithread=True, warpMemoryLimit=1024, creationOptions=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
    cog(tmp, destino)
    tmp.unlink()
    log(f'{destino.relative_to(RAIZ).as_posix()}: EPSG:{SRID} a 15 m ({time.time() - t0:.0f} s)')
    return destino


def cog(origen: Path, destino: Path, resampleo: str = 'AVERAGE', error_max: float | None = None) -> None:
    """GeoTIFF optimizado (COG) en EPSG:6369: teselas, vistas reducidas para QGIS y compresión sin pérdida (DEFLATE con
    predictor), o LERC con un error máximo garantizado (error_max, en las unidades del dato) para lo que casi no se
    comprime sin pérdida, como la pendiente. El sistema se asigna (no se reproyecta): las hojas de INEGI lo traen con
    un nombre propio ("MEXICO_ITRF_2008_UTM_Zone_14N") que equivale a EPSG:6369."""
    gdal = gdal_()
    compresion = (['COMPRESS=DEFLATE', 'PREDICTOR=YES', 'LEVEL=6'] if error_max is None
                  else ['COMPRESS=LERC_ZSTD', f'MAX_Z_ERROR={error_max}'])
    gdal.Translate(str(destino), str(origen), format='COG', outputSRS=f'EPSG:{SRID}',
                   creationOptions=compresion + ['BLOCKSIZE=512', f'OVERVIEW_RESAMPLING={resampleo}',
                                                 'NUM_THREADS=ALL_CPUS', 'BIGTIFF=IF_SAFER'])


# ── Hojas 1:10 000 de INEGI (1.5 y 5 m) ─────────────────────────────────────────────────────────────────────────────

ZONAS = {
    'piloto': (['13048', '13051', '13039', '13038'],
               'Pachuca de Soto, Mineral de la Reforma, Mineral del Monte y Mineral del Chico'),
    'estado': (None, 'Todo Hidalgo'),
}
MARGEN_ZONA_M = 500
HOJAS = FUENTES / 'inegi' / 'mde'

# Cuadrantes de la nomenclatura de cartas de INEGI: esquina noroeste (lat, lon) de cada bloque de 2° × 3°.
CUADRANTES = {'F14A': (24, -102), 'F14B': (24, -99), 'F14C': (22, -102), 'F14D': (22, -99),
              'E14A': (20, -102), 'E14B': (20, -99), 'E14C': (18, -102), 'E14D': (18, -99)}


def caja_hoja(clave: str) -> tuple[float, float, float, float]:
    """(oeste, sur, este, norte) en grados de una hoja 1:10 000 (p. ej. F14D81E1): carta 1:50 000 de 15' × 20',
    seis 1:20 000 (A–F, 2 × 3) y cuatro 1:10 000 (1–4, 2 × 2)."""
    import re
    m = re.fullmatch(r'([EF]14[A-D])([1-8])([1-9])([A-F])([1-4])', clave.upper())
    if not m:
        raise ValueError(clave)
    top, oeste = CUADRANTES[m[1]]
    dy, dx = 0.25, 1 / 3
    n, w = top - (int(m[2]) - 1) * dy, oeste + (int(m[3]) - 1) * dx
    i = 'ABCDEF'.index(m[4]); dy, dx = dy / 2, dx / 3
    n -= (i // 3) * dy; w += (i % 3) * dx
    i = int(m[5]) - 1; dy, dx = dy / 2, dx / 2
    n -= (i // 2) * dy; w += (i % 2) * dx
    return w, n - dy, w + dx, n


def catalogo_mde() -> list[dict]:
    """Por hoja: la resolución más fina que tiene terreno y superficie, y de ella la edición más reciente."""
    import re
    regs = inegi.catalogo('modelo digital de elevación', '13')
    por_clave: dict[str, dict] = {}
    for r in regs:
        m15 = re.search(r'tipo (terreno|superficie) con resoluci[oó]n de 1\.5 metros', r['titulo'], re.I)
        m5 = re.search(r'tipo (terreno|superficie) con 5 ?m de resoluci[oó]n', r['titulo'], re.I)
        m = m15 or m5
        if not m or not re.fullmatch(r'[EF]14[A-D]\d\d[A-F][1-4]', r['clave']):
            continue
        fmt = 'TIF' if 'TIF' in r['formatos'] else 'BIL' if 'BIL' in r['formatos'] else None
        if not fmt:
            continue
        clave = (1.5 if m15 else 5.0, r['edicion'])
        por_clave.setdefault(r['clave'], {}).setdefault(clave, {})[m[1].lower()] = {
            'upc': r['upc'], 'url': r['formatos'][fmt]['url'], 'mb': r['formatos'][fmt]['mb'] or 0, 'formato': fmt,
            'ascii': (r['formatos'].get('ASCII') or {}).get('url')}
    hojas = []
    for clave, ops in sorted(por_clave.items()):
        completas = [k for k, d in ops.items() if 'terreno' in d and 'superficie' in d]
        if not completas:
            continue
        res, ed = min(completas, key=lambda k: (k[0], -k[1]))
        d = ops[(res, ed)]
        hojas.append({'clave': clave, 'resolucion_m': res, 'edicion': ed, 'formato': d['terreno']['formato'],
                      'terreno': d['terreno'], 'superficie': d['superficie'],
                      'mb': d['terreno']['mb'] + d['superficie']['mb'], 'caja': caja_hoja(clave)})
    log(f'catálogo de INEGI: {len(regs)} registros, {len(hojas)} hojas con terreno y superficie '
        f'({sum(h["resolucion_m"] == 1.5 for h in hojas)} de 1.5 m)')
    return hojas


def registrar_hojas(con, hojas: list[dict]) -> None:
    """Índice de hojas y cobertura por resolución en PostGIS (la cuadrícula de INEGI es ITRF2008 geográfico, 6365)."""
    with con.transaction():
        for h in hojas:
            w, s, e, n = h['caja']
            con.execute("""
                insert into terreno.hojas (clave, resolucion_m, edicion, formato, upc_terreno, url_terreno, upc_superficie,
                                           url_superficie, mb, geom)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                        ST_Transform(ST_Segmentize(ST_MakeEnvelope(%s, %s, %s, %s, 6365), 0.001), 6369))
                on conflict (clave) do update set
                  resolucion_m = excluded.resolucion_m, edicion = excluded.edicion, formato = excluded.formato,
                  upc_terreno = excluded.upc_terreno, url_terreno = excluded.url_terreno,
                  upc_superficie = excluded.upc_superficie, url_superficie = excluded.url_superficie,
                  mb = excluded.mb, geom = excluded.geom""",
                        (h['clave'], h['resolucion_m'], h['edicion'], h['formato'], h['terreno']['upc'], h['terreno']['url'],
                         h['superficie']['upc'], h['superficie']['url'], h['mb'], w, s, e, n))
        con.execute("""
            update terreno.hojas h set en_hidalgo = ST_Intersects(h.geom, e.geom) from base.estado e;
            delete from terreno.hojas where not en_hidalgo;
            update terreno.hojas h set zonas = coalesce((select array_agg(z.zona order by z.zona) from terreno.zonas z
                                                         where ST_Intersects(z.geom, h.geom)), '{}');
            truncate terreno.cobertura;
            with e as (select geom from base.estado),
                 f15 as (select ST_Union(geom) g from terreno.hojas where resolucion_m = 1.5),
                 f5 as (select ST_Union(geom) g from terreno.hojas),
                 partes as (
                   select '1.5 m' r, ST_Intersection(e.geom, f15.g) g from e, f15
                   union all select '5 m', ST_Difference(ST_Intersection(e.geom, f5.g), f15.g) from e, f5, f15
                   union all select '15 m (solo CEM)', ST_Difference(e.geom, f5.g) from e, f5)
            insert into terreno.cobertura
            select r, ST_Area(ST_Transform(g, 4326)::geography) / 1e6,
                   100 * ST_Area(ST_Transform(g, 4326)::geography) / ST_Area(ST_Transform((select geom from e), 4326)::geography),
                   ST_Multi(ST_CollectionExtract(ST_MakeValid(g), 3))
            from partes;""")
    for r, km2, pct in consulta(con, 'select resolucion, area_km2, pct_estado from terreno.cobertura order by 1'):
        log(f'  cobertura {r}: {km2:,.0f} km² ({pct:.1f} % de Hidalgo)')


def definir_zona(con, zona: str) -> None:
    municipios, descripcion = ZONAS[zona]
    filtro = 'true' if municipios is None else 'cvegeo = any(%s)'
    params = () if municipios is None else (municipios,)
    with con.transaction():
        con.execute(f"""
            insert into terreno.zonas (zona, descripcion, municipios, area_km2, geom)
            select %s, %s, array_agg(cvegeo order by cvegeo), null,
                   ST_Multi(ST_Buffer(ST_Union(geom), {MARGEN_ZONA_M}))
            from base.municipios where {filtro}
            on conflict (zona) do update set descripcion = excluded.descripcion, municipios = excluded.municipios,
                                             geom = excluded.geom""", (zona, descripcion, *params))
        con.execute("update terreno.zonas set area_km2 = ST_Area(ST_Transform(geom, 4326)::geography) / 1e6 where zona = %s",
                    (zona,))


def extraer_raster(zip_: Path, destino: Path, url_ascii: str | None) -> None:
    """Saca el modelo de un zip de INEGI a GeoTIFF en EPSG:6369 (los BIL no traen sistema: son UTM 14N ITRF2008)."""
    import shutil
    import zipfile
    gdal = gdal_()
    tmp = destino.parent / (destino.stem + '_x')
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_) as z:
            z.extractall(tmp)
        rasters = [p for p in tmp.rglob('*') if p.suffix.lower() in ('.tif', '.bil')]
        meta = [p for p in tmp.rglob('*.txt') if 'metadato' in p.as_posix().lower()]
        if meta:
            shutil.copy2(meta[0], destino.with_suffix('.metadatos.txt'))
        if not rasters and url_ascii:
            # algunas hojas de 5 m traen otra cosa en el zip «BIL»: el modelo viene también como lista de puntos
            za = descargar_simple(url_ascii, tmp / 'ascii.zip')
            with zipfile.ZipFile(za) as z:
                z.extractall(tmp / 'ascii')
            rasters = [p for p in (tmp / 'ascii').rglob('*') if p.suffix.lower() in ('.xyz', '.txt', '.asc', '.csv')
                       and 'metadato' not in p.as_posix().lower()]
        if not rasters:
            raise IOError(f'{zip_.name} no trae un modelo que se pueda leer')
        origen = rasters[0]
        ds = gdal.Open(str(origen))
        srs = ds.GetSpatialRef()
        ds = None
        gdal.Translate(str(destino), str(origen), format='GTiff', outputType=gdal.GDT_Float32,
                       outputSRS=None if srs else f'EPSG:{SRID}',
                       creationOptions=['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=3', 'BIGTIFF=IF_SAFER'])
        normalizar_nodata(destino)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


MINIMO_VALIDO = -1000.0   # m: nada en Hidalgo está por debajo; menos que esto (o no finito) es «sin dato»


def normalizar_nodata(ruta: Path) -> bool:
    """Deja el «sin dato» de una hoja en NODATA (-9999). INEGI no lo marca igual en todas: las de 1.5 m usan
    -3.4028235e38 y algunas de 5 m declaran -3.4028231e38, que en flotante de 32 bits no es el mismo número y, al
    interpolar, se cuela como altura. Devuelve True si cambió el archivo."""
    import numpy as np
    gdal = gdal_()
    ds = gdal.Open(str(ruta))
    b = ds.GetRasterBand(1)
    if b.GetNoDataValue() == NODATA:
        return False
    a = b.ReadAsArray()
    gt, srs = ds.GetGeoTransform(), ds.GetSpatialRef()
    ds = None
    a = np.where(np.isfinite(a) & (a > MINIMO_VALIDO), a, NODATA).astype(np.float32)
    tmp = ruta.with_name(ruta.stem + '_n.tif')
    out = gdal.GetDriverByName('GTiff').Create(str(tmp), a.shape[1], a.shape[0], 1, gdal.GDT_Float32,
                                               ['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=3'])
    out.SetGeoTransform(gt)
    out.SetSpatialRef(srs)
    out.GetRasterBand(1).SetNoDataValue(NODATA)
    out.GetRasterBand(1).WriteArray(a)
    out = None
    aux = ruta.with_name(ruta.name + '.aux.xml')
    if aux.exists():
        aux.unlink()
    tmp.replace(ruta)
    return True


def paso_normalizar() -> None:
    con = conectar()
    n = 0
    for (archivo,) in consulta(con, """select archivo_terreno from terreno.hojas where archivo_terreno is not null
                                       union all
                                       select archivo_superficie from terreno.hojas where archivo_superficie is not null"""):
        n += normalizar_nodata(RAIZ / archivo)
    log(f'«sin dato» normalizado a {NODATA:g} en {n} archivos')


def descargar_simple(url: str, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(inegi._pedir(url, tiempo=600))
    return destino


def paso_hojas() -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from comun import SQL, correr_sql
    zona = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--zona=')), 'piloto')
    if zona not in ZONAS:
        sys.exit(f'zona desconocida: {zona} (hay: {", ".join(ZONAS)})')
    con = conectar()
    correr_sql(con, SQL / 'fase1' / '01_terreno.sql')
    definir_zona(con, zona)
    if zona != 'estado':
        definir_zona(con, 'estado')
    cat = catalogo_mde()
    registrar_hojas(con, cat)
    hojas = consulta(con, """select clave, resolucion_m, formato, url_terreno, url_superficie, mb from terreno.hojas
                             where %s = any(zonas) order by clave""", (zona,))
    # urls ASCII de respaldo para las hojas de 5 m cuyo zip BIL no trae el modelo
    ascii_ = {(h['clave'], t): h[t]['ascii'] for h in cat for t in ('terreno', 'superficie')}
    log(f'zona {zona}: {len(hojas)} hojas, {sum(h[5] for h in hojas) / 1024:.2f} GB de zips')
    trabajos = []
    for clave, res, formato, u_t, u_s, _ in hojas:
        carpeta = HOJAS / ('1.5m' if res == 1.5 else '5m')
        for tipo, url in (('terreno', u_t), ('superficie', u_s)):
            trabajos.append((clave, tipo, url, carpeta / f'{clave}_{tipo}.tif', ascii_.get((clave, tipo))))

    def uno(t):
        clave, tipo, url, destino, u_ascii = t
        if destino.exists():
            return clave, tipo, destino, False
        zip_ = destino.parent / 'zips' / f'{clave}_{tipo}.zip'
        descargar_simple(url, zip_)
        extraer_raster(zip_, destino, u_ascii)
        zip_.unlink()
        return clave, tipo, destino, True

    t0, nuevos = time.time(), 0
    with ThreadPoolExecutor(6) as ex:
        futuros = [ex.submit(uno, t) for t in trabajos]
        for k, fu in enumerate(as_completed(futuros), 1):
            clave, tipo, destino, nuevo = fu.result()
            nuevos += nuevo
            con.execute(f'update terreno.hojas set archivo_{tipo} = %s where clave = %s',
                        (destino.relative_to(RAIZ).as_posix(), clave))
            if k % 6 == 0 or k == len(futuros):
                log(f'  {k}/{len(futuros)} archivos ({nuevos} nuevos, {(time.time() - t0) / 60:.1f} min)')


# ── Mosaico, fusión con el CEM y productos derivados ────────────────────────────────────────────────────────────────

FINO = 1.5          # m: rejilla del relieve fino (la de las hojas de 1.5 m; las de 5 m se interpolan a ella)
TRANSICION_M = 150  # m: ancho de la transición entre el dato fino y el CEM donde se acaba la hoja
NODATA = -9999.0


def zona_arg() -> str:
    zona = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--zona=')), 'piloto')
    if zona not in ZONAS:
        sys.exit(f'zona desconocida: {zona} (hay: {", ".join(ZONAS)})')
    return zona


def archivos_zona(con, zona: str, tipo: str) -> list[Path]:
    """Hojas bajadas de la zona: primero las de 5 m y luego las de 1.5 m por edición (en el VRT manda la última)."""
    filas = consulta(con, f"""select archivo_{tipo} from terreno.hojas
                              where %s = any(zonas) and archivo_{tipo} is not null
                              order by resolucion_m desc, edicion, clave""", (zona,))
    return [RAIZ / f[0] for f in filas]


def vrt_fino(con, zona: str, tipo: str) -> Path:
    gdal = gdal_()
    archivos = archivos_zona(con, zona, tipo)
    if not archivos:
        sys.exit(f'no hay hojas bajadas de {zona}: corre antes el paso hojas')
    vrt = TERRENO / f'{tipo}_{zona}_hojas.vrt'
    ds = gdal.Open(str(archivos[-1]))   # el dataset debe vivir mientras se usa su banda
    nd = ds.GetRasterBand(1).GetNoDataValue()
    ds = None
    gdal.BuildVRT(str(vrt), [str(a) for a in archivos], xRes=FINO, yRes=FINO, resampleAlg='bilinear',
                  srcNodata=nd, VRTNodata=NODATA)
    return vrt


def rejilla_zona(con, zona: str, vrt: Path, margen: float = 1500) -> tuple[float, float, float, float]:
    """Caja de la zona con margen, ajustada a la rejilla de las hojas (sin remuestrear el dato fino) y a múltiplos de 10
    píxeles (celdas de 15 m enteras para el peso de la transición)."""
    gdal = gdal_()
    gt = gdal.Open(str(vrt)).GetGeoTransform()
    x0, y0 = gt[0], gt[3]
    xmin, ymin, xmax, ymax = consulta(con, """select ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b)
        from (select ST_Expand(ST_Envelope(geom), %s) b from terreno.zonas where zona = %s) x""", (margen, zona))[0]
    paso = FINO * 10
    ax = lambda v, f: x0 + f((v - x0) / paso) * paso
    ay = lambda v, f: y0 + f((v - y0) / paso) * paso
    import math
    return ax(xmin, math.floor), ay(ymin, math.floor), ax(xmax, math.ceil), ay(ymax, math.ceil)


ANCHO_COSTURA_M = 60                 # rampa del peso de cada hoja desde su propia orilla
PRIORIDAD = {1.5: 1.0, 5.0: 0.25}    # donde se enciman, la de 1.5 m pesa 4 veces más que la de 5 m
BLOQUE = 500                         # filas por bloque (múltiplo de 10)


def _crear(ruta: Path, w: int, h: int, gt: tuple, nodata: float | None = NODATA):
    gdal = gdal_()
    from osgeo import osr
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(SRID)
    ds = gdal.GetDriverByName('GTiff').Create(str(ruta), w, h, 1, gdal.GDT_Float32,
                                              ['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=3', 'BIGTIFF=YES',
                                               'NUM_THREADS=ALL_CPUS'])
    ds.SetGeoTransform(gt)
    ds.SetSpatialRef(srs)
    if nodata is not None:
        ds.GetRasterBand(1).SetNoDataValue(nodata)
    return ds


def _peso_hoja(archivo: Path, resolucion: float) -> Path:
    """Peso de una hoja en su propia rejilla: 0 en la orilla de su dato y 1 a ANCHO_COSTURA_M hacia dentro, por su
    prioridad. Así, donde dos hojas se enciman se mezclan en vez de que la última tape a la otra con un escalón."""
    import numpy as np
    from scipy import ndimage
    gdal = gdal_()
    destino = TERRENO / 'tmp' / f'peso_{archivo.stem}.tif'
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    ds = gdal.Open(str(archivo))
    nd = ds.GetRasterBand(1).GetNoDataValue()
    a = ds.GetRasterBand(1).ReadAsArray()
    valido = np.pad(np.isfinite(a) & (a > MINIMO_VALIDO), 1)       # el borde del arreglo también es orilla
    dist = ndimage.distance_transform_edt(valido)[1:-1, 1:-1] * ds.GetGeoTransform()[1]
    peso = (np.clip(dist / ANCHO_COSTURA_M, 0, 1) * PRIORIDAD[resolucion]).astype(np.float32)
    out = _crear(destino, peso.shape[1], peso.shape[0], ds.GetGeoTransform(), None)
    out.GetRasterBand(1).WriteArray(peso)
    out = None
    return destino


def mezclar_hojas(con, zona: str, tipo: str, caja: tuple, destino: Path) -> Path:
    """Mosaico de las hojas de la zona en la rejilla fina (caja), con las costuras mezcladas por peso."""
    import math
    import numpy as np
    gdal = gdal_()
    if destino.exists():
        return destino
    xmin, ymin, xmax, ymax = caja
    w, h = round((xmax - xmin) / FINO), round((ymax - ymin) / FINO)
    filas = consulta(con, f"""select archivo_{tipo}, resolucion_m from terreno.hojas
                              where %s = any(zonas) and archivo_{tipo} is not null order by clave""", (zona,))
    fuentes = []
    for archivo, res in filas:
        ruta = RAIZ / archivo
        ds = gdal.Open(str(ruta))
        gt, nd = ds.GetGeoTransform(), ds.GetRasterBand(1).GetNoDataValue()
        sx0, sy1 = gt[0], gt[3]
        sx1, sy0 = sx0 + gt[1] * ds.RasterXSize, sy1 + gt[5] * ds.RasterYSize
        ds = None
        bx0 = max(xmin, xmin + math.floor((sx0 - xmin) / FINO) * FINO)
        bx1 = min(xmax, xmin + math.ceil((sx1 - xmin) / FINO) * FINO)
        by1 = min(ymax, ymax - math.floor((ymax - sy1) / FINO) * FINO)
        by0 = max(ymin, ymax - math.ceil((ymax - sy0) / FINO) * FINO)
        if bx1 <= bx0 or by1 <= by0:
            continue
        alineada = abs((sx0 - xmin) / FINO - round((sx0 - xmin) / FINO)) < 1e-6 and gt[1] == FINO \
            and abs((ymax - sy1) / FINO - round((ymax - sy1) / FINO)) < 1e-6
        alg = 'near' if alineada else 'bilinear'
        opc = dict(format='VRT', outputBounds=(bx0, by0, bx1, by1), xRes=FINO, yRes=FINO, resampleAlg=alg)
        v = gdal.Warp('', str(ruta), srcNodata=nd, dstNodata=NODATA, **opc)
        p = gdal.Warp('', str(_peso_hoja(ruta, res)), **opc)
        fuentes.append({'v': v, 'p': p, 'c0': round((bx0 - xmin) / FINO), 'r0': round((ymax - by1) / FINO),
                        'w': v.RasterXSize, 'h': v.RasterYSize})
    out = _crear(destino, w, h, (xmin, FINO, 0, ymax, 0, -FINO))
    ob = out.GetRasterBand(1)
    for y in range(0, h, BLOQUE):
        n = min(BLOQUE, h - y)
        num = np.zeros((n, w), np.float64)
        den = np.zeros((n, w), np.float64)
        for s in fuentes:
            ry0, ry1 = max(y, s['r0']), min(y + n, s['r0'] + s['h'])
            if ry0 >= ry1:
                continue
            vals = s['v'].GetRasterBand(1).ReadAsArray(0, ry0 - s['r0'], s['w'], ry1 - ry0)
            pes = s['p'].GetRasterBand(1).ReadAsArray(0, ry0 - s['r0'], s['w'], ry1 - ry0)
            ok = np.isfinite(vals) & (vals > MINIMO_VALIDO)
            pes = np.where(ok, pes, 0)
            sl = (slice(ry0 - y, ry1 - y), slice(s['c0'], s['c0'] + s['w']))
            num[sl] += pes * np.where(ok, vals, 0)
            den[sl] += pes
        ob.WriteArray(np.where(den > 0, num / np.maximum(den, 1e-12), NODATA).astype(np.float32), 0, y)
    ob.FlushCache()
    out = None
    log(f'  mosaico de {tipo} ({len(fuentes)} hojas, costuras mezcladas en {ANCHO_COSTURA_M} m)')
    return destino


def _suavizar_extender(d, m, sigmas=(20, 60, 180)):
    """Promedio local de d (donde m) que se extiende hacia afuera: primero a 300 m, luego a 900 m y a 2.7 km
    (sigmas en celdas de 15 m); lo que quede, con la mediana."""
    import numpy as np
    from scipy import ndimage
    corr = np.full(d.shape, np.nan, np.float32)
    dm = np.where(m, d, 0).astype(np.float64)
    mm = m.astype(np.float64)
    for s in sigmas:
        num = ndimage.gaussian_filter(dm, s, truncate=3)
        den = ndimage.gaussian_filter(mm, s, truncate=3)
        llenar = np.isnan(corr) & (den > 0.02)
        corr[llenar] = (num[llenar] / den[llenar]).astype(np.float32)
    corr[np.isnan(corr)] = float(np.median(d[m])) if m.any() else 0.0
    return corr


def fusionar(con, zona: str) -> Path:
    """Relieve de la zona a 1.5 m: hojas de INEGI (costuras mezcladas) donde las hay y CEM 4.0 donde no.

    El CEM queda por encima del terreno de las hojas (≈ 4 m en terreno abierto y más bajo bosque y ciudad: sale de
    radar y se comporta en parte como superficie). Antes de usarlo se le suma un ajuste local: la diferencia
    hoja − CEM suavizada y extendida hacia donde no hay hoja (se guarda como ajuste_cem_<zona>_15m.tif). Luego, una
    transición lineal de TRANSICION_M metros hacia dentro de la hoja, para que no quede escalón."""
    import numpy as np
    from scipy import ndimage
    gdal = gdal_()
    destino = TERRENO / f'relieve_{zona}_1p5m.tif'
    if destino.exists():
        log(f'ya está {destino.relative_to(RAIZ).as_posix()}')
        return destino
    cem = TERRENO / 'cem4_15m.tif'
    if not cem.exists():
        sys.exit('falta el CEM: corre antes el paso cem')
    caja = rejilla_zona(con, zona, vrt_fino(con, zona, 'terreno'))
    xmin, ymin, xmax, ymax = caja
    w, h = round((xmax - xmin) / FINO), round((ymax - ymin) / FINO)
    log(f'relieve {zona}: {w:,} × {h:,} px a {FINO} m ({w * h / 1e6:,.0f} Mpx)')
    mezcla = mezclar_hojas(con, zona, 'terreno', caja, TERRENO / 'tmp' / f'terreno_{zona}_mezcla.tif')
    ds_f = gdal.Open(str(mezcla))
    bf = ds_f.GetRasterBand(1)
    base = gdal.Warp('', str(cem), format='VRT', outputBounds=caja, xRes=FINO, yRes=FINO,
                     resampleAlg='cubic', srcNodata=NODATA, dstNodata=NODATA)
    bb = base.GetRasterBand(1)

    # 1) celdas de 15 m completamente cubiertas por las hojas y su altura media
    lleno = np.zeros((h // 10, w // 10), dtype=bool)
    fino15 = np.zeros((h // 10, w // 10), dtype=np.float32)
    for y in range(0, h, BLOQUE):
        n = min(BLOQUE, h - y)
        f = bf.ReadAsArray(0, y, w, n).reshape(n // 10, 10, w // 10, 10)
        lleno[y // 10:(y + n) // 10] = (f != NODATA).all(axis=(1, 3))
        fino15[y // 10:(y + n) // 10] = f.mean(axis=(1, 3))
    # 2) peso del dato fino: 0 en la orilla de lo cubierto, 1 a TRANSICION_M hacia dentro
    dist = ndimage.distance_transform_edt(lleno) * (FINO * 10)
    peso15 = np.clip((dist - FINO * 10) / TRANSICION_M, 0, 1).astype(np.float32)
    # 3) ajuste local del CEM hacia el terreno de las hojas
    cem15 = gdal.Warp('', str(cem), format='MEM', outputBounds=caja, xRes=FINO * 10, yRes=FINO * 10,
                      resampleAlg='bilinear', srcNodata=NODATA, dstNodata=NODATA).ReadAsArray()
    m = lleno & (cem15 != NODATA)
    ajuste15 = _suavizar_extender(fino15 - cem15, m)
    fuera = ~lleno & (cem15 != NODATA)
    log(f'  dato fino en {100 * lleno.mean():.1f} % de la caja; ajuste del CEM donde no hay hoja: mediana '
        f'{float(np.median(ajuste15[fuera])) if fuera.any() else 0:+.2f} m '
        f'(de {float(ajuste15[fuera].min()) if fuera.any() else 0:+.1f} a {float(ajuste15[fuera].max()) if fuera.any() else 0:+.1f}); '
        f'transición de {TRANSICION_M} m')
    ruta_ajuste = TERRENO / f'ajuste_cem_{zona}_15m.tif'
    a = _crear(TERRENO / 'tmp' / f'ajuste_cem_{zona}.tif', w // 10, h // 10, (xmin, FINO * 10, 0, ymax, 0, -FINO * 10))
    a.GetRasterBand(1).WriteArray(np.where(cem15 != NODATA, ajuste15, NODATA).astype(np.float32))
    a = None
    cog(TERRENO / 'tmp' / f'ajuste_cem_{zona}.tif', ruta_ajuste)

    # 4) mezcla final por bloques
    tmp = TERRENO / 'tmp' / f'relieve_{zona}.tif'
    out = _crear(tmp, w, h, (xmin, FINO, 0, ymax, 0, -FINO))
    ob = out.GetRasterBand(1)
    cols = (np.arange(w) + 0.5) / 10 - 0.5
    for y in range(0, h, BLOQUE):
        n = min(BLOQUE, h - y)
        f = bf.ReadAsArray(0, y, w, n)
        b = bb.ReadAsArray(0, y, w, n)
        filas = (np.arange(y, y + n) + 0.5) / 10 - 0.5
        rr, cc = np.meshgrid(filas, cols, indexing='ij')
        p = ndimage.map_coordinates(peso15, [rr, cc], order=1, mode='nearest').astype(np.float32)
        aj = ndimage.map_coordinates(ajuste15, [rr, cc], order=1, mode='nearest').astype(np.float32)
        p[f == NODATA] = 0
        # sin CEM queda el dato fino (o nada); con CEM, la mezcla (p = 0 donde no hay dato fino: queda el CEM ajustado)
        r = np.where(b == NODATA, f, p * f + (1 - p) * (b + aj))
        ob.WriteArray(r.astype(np.float32), 0, y)
    ob.FlushCache()
    out = None
    ds_f = None
    cog(tmp, destino)
    tmp.unlink()
    log(f'{destino.relative_to(RAIZ).as_posix()} listo')
    return destino


def derivados(dem: Path, nombre: str) -> None:
    """Sombreado multidireccional y pendiente (grados) del relieve, como COG."""
    gdal = gdal_()
    # pendiente con LERC y error máximo de 0.01°: en flotantes casi no se comprime sin pérdida (1.2 GB a 15 m)
    for proc, sufijo, opciones, error in (('hillshade', 'sombreado', {'multiDirectional': True}, None),
                                          ('slope', 'pendiente', {'slopeFormat': 'degree'}, 0.01)):
        destino = TERRENO / f'{sufijo}_{nombre}.tif'
        if destino.exists():
            continue
        tmp = destino.with_name(destino.stem + '_tmp.tif')
        t0 = time.time()
        gdal.DEMProcessing(str(tmp), str(dem), proc, computeEdges=True, **opciones,
                           creationOptions=['TILED=YES', 'COMPRESS=ZSTD', 'BIGTIFF=YES', 'NUM_THREADS=ALL_CPUS'])
        cog(tmp, destino, error_max=error)
        tmp.unlink()
        log(f'{destino.relative_to(RAIZ).as_posix()} ({time.time() - t0:.0f} s)')


def paso_relieve() -> None:
    zona = zona_arg()
    con = conectar()
    cem = paso_cem()
    derivados(cem, 'hidalgo_15m')
    dem = fusionar(con, zona)
    derivados(dem, f'{zona}_1p5m')
    # la superficie (edificios y árboles) se deja lista en mosaico para la fase 3
    sup = TERRENO / f'superficie_{zona}_1p5m.tif'
    if not sup.exists():
        caja = rejilla_zona(con, zona, vrt_fino(con, zona, 'terreno'))
        tmp = mezclar_hojas(con, zona, 'superficie', caja, TERRENO / 'tmp' / f'superficie_{zona}_mezcla.tif')
        cog(tmp, sup)
        log(f'{sup.relative_to(RAIZ).as_posix()} listo')
    # los temporales (pesos de las hojas y mosaicos intermedios) se pueden borrar
    import shutil
    shutil.rmtree(TERRENO / 'tmp', ignore_errors=True)


# ── Control de calidad de las hojas ─────────────────────────────────────────────────────────────────────────────────

# Criterios para marcar una hoja como «revisar». El CEM 4.0 no sirve de referencia absoluta: sale del radar de ALOS
# y se comporta en parte como modelo de superficie (queda arriba del terreno, más bajo bosque y ciudad). Por eso se
# compara en terreno abierto (superficie − terreno < 1 m) y lo que se busca es una hoja distinta de sus vecinas.
# (El NMAD contra el CEM no es criterio: en terreno quebrado crece por comparar 15 m con 1.5 m, no por la hoja.)
UMBRAL = {'desfase_m': 1.5,          # su sesgo en terreno abierto se aparta de la mediana de la zona
          'costura_abierto_m': 0.5,  # diferencia con una hoja vecina donde se enciman, en terreno abierto
          'sin_dato_pct': 5.0}
ABIERTO_M = 1.0   # superficie − terreno por debajo de esto = suelo descubierto (sin árboles ni techos)


def _mem(arr, gt, srs, nodata=None):
    """Dataset en memoria para pasar un arreglo de numpy a gdal.Warp."""
    gdal = gdal_()
    ds = gdal.GetDriverByName('MEM').Create('', arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    ds.SetSpatialRef(srs)
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    return ds


def _estadisticas(d):
    import numpy as np
    if d.size == 0:
        return None, None, None
    med = float(np.median(d))
    return med, float(1.4826 * np.median(np.abs(d - med))), float(np.percentile(np.abs(d), 95))


def paso_calidad() -> None:
    import math
    import numpy as np
    gdal = gdal_()
    zona = zona_arg()
    con = conectar()
    correr_sql_fase1(con)
    cem = TERRENO / 'cem4_15m.tif'
    hojas = consulta(con, """select clave, archivo_terreno, archivo_superficie from terreno.hojas
                             where %s = any(zonas) and archivo_terreno is not null order by clave""", (zona,))
    ds_cem = gdal.Open(str(cem))
    gt_cem = ds_cem.GetGeoTransform()
    ds_cem = None
    resultados = {}
    for clave, archivo, archivo_sup in hojas:
        ds = gdal.Open(str(RAIZ / archivo))
        nd = ds.GetRasterBand(1).GetNoDataValue()
        t = ds.GetRasterBand(1).ReadAsArray()
        gt, srs = ds.GetGeoTransform(), ds.GetSpatialRef()
        dss = gdal.Open(str(RAIZ / archivo_sup))
        nds = dss.GetRasterBand(1).GetNoDataValue()
        s = dss.GetRasterBand(1).ReadAsArray()
        dss = None
        valido = np.isfinite(t) & (t > MINIMO_VALIDO)
        abierto = valido & np.isfinite(s) & (s > MINIMO_VALIDO) & ((s - t) < ABIERTO_M)
        sin_dato = 100 * float(1 - valido.mean())
        pct_abierto = 100 * float(abierto.sum() / max(1, valido.sum()))
        x0, y1 = gt[0], gt[3]
        x1, y0 = x0 + gt[1] * ds.RasterXSize, y1 + gt[5] * ds.RasterYSize
        # caja alineada a la rejilla del CEM, hacia dentro de la hoja
        ax = lambda v, f: gt_cem[0] + f((v - gt_cem[0]) / 15) * 15
        ay = lambda v, f: gt_cem[3] + f((v - gt_cem[3]) / 15) * 15
        caja = (ax(x0, math.ceil), ay(y0, math.ceil), ax(x1, math.floor), ay(y1, math.floor))
        opc = dict(format='MEM', outputBounds=caja, xRes=15, yRes=15)
        h15 = gdal.Warp('', ds, resampleAlg='average', srcNodata=nd, dstNodata=NODATA, **opc).ReadAsArray()
        a15 = gdal.Warp('', _mem(abierto.astype(np.float32), gt, srs), resampleAlg='average', **opc).ReadAsArray()
        c15 = gdal.Warp('', str(cem), resampleAlg='near', dstNodata=NODATA, **opc).ReadAsArray()
        ds = None
        ok = (h15 != NODATA) & (c15 != NODATA)
        d_todo = (h15 - c15)[ok]
        d_abierto = (h15 - c15)[ok & (a15 >= 0.9)]
        sesgo, nmad, p95 = _estadisticas(d_todo)
        sesgo_a, nmad_a, _ = _estadisticas(d_abierto)
        resultados[clave] = {
            'sin_dato_pct': sin_dato, 'pct_abierto': pct_abierto, 'sesgo_m': sesgo, 'nmad_m': nmad, 'p95_abs_m': p95,
            'sesgo_abierto_m': sesgo_a, 'nmad_abierto_m': nmad_a, 'celdas_abiertas': int(d_abierto.size),
            'costura_m': None, 'costura_abierto_m': None, 'gt': gt, 'forma': (t.shape[1], t.shape[0]),
            'archivo': archivo, 'archivo_sup': archivo_sup, 'nd': nd, 'nds': nds}
    # desfase de cada hoja respecto a la mediana de la zona (en terreno abierto)
    sesgos = [r['sesgo_abierto_m'] for r in resultados.values() if r['sesgo_abierto_m'] is not None]
    med_zona = float(np.median(sesgos)) if sesgos else 0.0
    for r in resultados.values():
        r['desfase_m'] = None if r['sesgo_abierto_m'] is None else abs(r['sesgo_abierto_m'] - med_zona)

    # costuras: donde dos hojas vecinas se enciman, mediana de |diferencia| (en todo y solo en terreno abierto de las
    # dos). La ventana se ajusta a la rejilla de la primera; si la segunda está corrida (algunas ediciones empiezan
    # medio píxel después), se interpola a esa rejilla.
    claves = list(resultados)
    for i, ca in enumerate(claves):
        for cb in claves[i + 1:]:
            ra, rb = resultados[ca], resultados[cb]
            ga, gb = ra['gt'], rb['gt']
            ix0, ix1 = max(ga[0], gb[0]), min(ga[0] + ga[1] * ra['forma'][0], gb[0] + gb[1] * rb['forma'][0])
            iy1, iy0 = min(ga[3], gb[3]), max(ga[3] + ga[5] * ra['forma'][1], gb[3] + gb[5] * rb['forma'][1])
            px = ga[1]
            ix0 = ga[0] + math.ceil((ix0 - ga[0]) / px) * px
            ix1 = ga[0] + math.floor((ix1 - ga[0]) / px) * px
            iy1 = ga[3] - math.ceil((ga[3] - iy1) / px) * px
            iy0 = ga[3] - math.floor((ga[3] - iy0) / px) * px
            if ix1 - ix0 < 10 * px or iy1 - iy0 < 10 * px:
                continue
            caja = (ix0, iy0, ix1, iy1)

            def leer(archivo, nd, alg):
                return gdal.Warp('', str(RAIZ / archivo), format='MEM', outputBounds=caja, xRes=px, yRes=px,
                                 resampleAlg=alg, srcNodata=nd, dstNodata=NODATA).ReadAsArray()

            ta, sa = leer(ra['archivo'], ra['nd'], 'near'), leer(ra['archivo_sup'], ra['nds'], 'near')
            tb, sb = leer(rb['archivo'], rb['nd'], 'bilinear'), leer(rb['archivo_sup'], rb['nds'], 'bilinear')
            ok = (ta != NODATA) & (tb != NODATA)
            if ok.sum() < 100:
                continue
            abierto = ok & (sa != NODATA) & (sb != NODATA) & ((sa - ta) < ABIERTO_M) & ((sb - tb) < ABIERTO_M)
            c = float(np.median(np.abs(ta[ok] - tb[ok])))
            ca_ = float(np.median(np.abs(ta[abierto] - tb[abierto]))) if abierto.sum() >= 100 else None
            for k in (ca, cb):
                resultados[k]['costura_m'] = max(c, resultados[k]['costura_m'] or 0)
                if ca_ is not None:
                    resultados[k]['costura_abierto_m'] = max(ca_, resultados[k]['costura_abierto_m'] or 0)

    filas = []
    f = lambda v, fmt: '' if v is None else format(v, fmt)
    with con.transaction():
        for clave, r in resultados.items():
            motivos = [k for k, u in UMBRAL.items() if r[k] is not None and r[k] > u]
            revision = 'ok' if not motivos else 'revisar: ' + ', '.join(motivos)
            con.execute("""update terreno.hojas set sin_dato_pct = %s, sesgo_m = %s, nmad_m = %s, p95_abs_m = %s,
                             costura_m = %s, pct_abierto = %s, sesgo_abierto_m = %s, nmad_abierto_m = %s,
                             desfase_m = %s, costura_abierto_m = %s, revision = %s
                           where clave = %s""",
                        (r['sin_dato_pct'], r['sesgo_m'], r['nmad_m'], r['p95_abs_m'], r['costura_m'], r['pct_abierto'],
                         r['sesgo_abierto_m'], r['nmad_abierto_m'], r['desfase_m'], r['costura_abierto_m'], revision,
                         clave))
            filas.append((clave, f(r['pct_abierto'], '.0f'), f(r['sesgo_m'], '+.2f'), f(r['sesgo_abierto_m'], '+.2f'),
                          f(r['nmad_abierto_m'], '.2f'), f(r['desfase_m'], '.2f'), f(r['costura_m'], '.2f'),
                          f(r['costura_abierto_m'], '.2f'), revision))
    from fase0 import tabla
    tabla(filas, ('hoja', 'abierto %', 'hoja−CEM', 'en abierto', 'NMAD ab.', 'desfase', 'costura', 'cost. ab.',
                  'revisión'))
    d = consulta(con, """select count(*), count(*) filter (where revision = 'ok'),
                                percentile_cont(0.5) within group (order by sesgo_m),
                                percentile_cont(0.5) within group (order by sesgo_abierto_m),
                                percentile_cont(0.5) within group (order by nmad_abierto_m)
                         from terreno.hojas where %s = any(zonas) and revision is not null""", (zona,))[0]
    log(f'calidad {zona}: {d[1]} de {d[0]} hojas ok · hoja − CEM: {d[2]:+.2f} m en todo, {d[3]:+.2f} m en terreno '
        f'abierto (NMAD {d[4]:.2f} m): el CEM queda por encima del terreno, más bajo bosque y ciudad')


def correr_sql_fase1(con) -> None:
    from comun import SQL, correr_sql
    correr_sql(con, SQL / 'fase1' / '01_terreno.sql')


# ── PostGIS: rásters fuera de la base y altitud por SQL ─────────────────────────────────────────────────────────────

PG_BIN = Path(r'C:\Program Files\PostgreSQL\17\bin')


def registrar_raster(archivo: Path, tabla: str) -> None:
    """Registra un GeoTIFF en PostGIS fuera de la base (raster2pgsql -R): la tabla guarda teselas que apuntan al
    archivo, y el servidor lo lee al consultar. Si el servidor no puede leer el archivo, lo dice la prueba de después."""
    import os
    import subprocess
    from comun import CFG
    # raster2pgsql usa el GDAL de PostGIS: sin las rutas de GDAL y PROJ que fija el lanzador de QGIS
    env = {k: v for k, v in os.environ.items() if k not in ('GDAL_DRIVER_PATH', 'GDAL_DATA', 'PROJ_DATA', 'PROJ_LIB')}
    env.update({'PGPASSWORD': CFG['DB_PASSWORD'], 'GDAL_DATA': str(PG_BIN.parent / 'gdal-data'),
                'PROJ_LIB': str(PG_BIN.parent / 'share' / 'contrib' / 'postgis-3.6' / 'proj')})
    r2p = subprocess.Popen([str(PG_BIN / 'raster2pgsql.exe'), '-s', str(SRID), '-t', '512x512', '-R', '-I', '-C', '-M',
                            '-d', '-Y', str(archivo.resolve()), tabla], stdout=subprocess.PIPE, env=env)
    psql = subprocess.run([str(PG_BIN / 'psql.exe'), '-q', '-h', CFG['DB_HOST'], '-p', CFG.get('DB_PORT', '5432'),
                           '-U', CFG['DB_USERNAME'], '-d', CFG['DB_DATABASE'], '-v', 'ON_ERROR_STOP=1'],
                          stdin=r2p.stdout, env=env, capture_output=True, text=True)
    r2p.wait()
    if r2p.returncode or psql.returncode:
        raise RuntimeError(f'raster2pgsql/psql: {psql.stderr[-800:]}')
    log(f'{tabla} ← {archivo.relative_to(RAIZ).as_posix()} (fuera de la base)')


def paso_registrar() -> None:
    from comun import SQL, correr_sql
    import subprocess
    zona = zona_arg()
    con = conectar()
    # El servicio de PostgreSQL corre como NetworkService (SID S-1-5-20) y no puede leer la carpeta del usuario: se le
    # da solo lectura sobre datos\terreno (lo heredan los archivos nuevos). Se quita con: icacls datos\terreno /remove *S-1-5-20
    subprocess.run(['icacls', str(TERRENO), '/grant', '*S-1-5-20:(OI)(CI)RX', '/Q'], check=True, capture_output=True)
    log('lectura de datos/terreno para el servicio de PostgreSQL (NetworkService)')
    registrar_raster(TERRENO / 'cem4_15m.tif', 'terreno.r_cem4_15m')
    fino = TERRENO / f'relieve_{zona}_1p5m.tif'
    if fino.exists():
        registrar_raster(fino, f'terreno.r_relieve_{zona}_1p5m')
    # Prueba: el servidor de PostgreSQL debe poder leer los archivos (corre con otra cuenta de Windows)
    try:
        v = consulta(con, """select ST_Value(rast, p) from terreno.r_cem4_15m,
                             (select ST_PointOnSurface(geom) p from base.municipios where cvegeo = '13048') x
                             where ST_Intersects(rast, p)""")
        log(f'  prueba de lectura: altitud del CEM en Pachuca = {v[0][0]:.1f} m')
    except Exception as e:
        raise RuntimeError(f'PostgreSQL no puede leer los rásters fuera de la base: {e}') from e
    zonas_finas = [z for z in ZONAS if (TERRENO / f'relieve_{z}_1p5m.tif').exists()]
    ramas = '\n'.join(f"""    select ST_Value(r.rast, p) from terreno.r_relieve_{z}_1p5m r where ST_Intersects(r.rast, p)
    union all""" for z in zonas_finas)
    with con.transaction():
        con.execute(f"""
create or replace function terreno.altitud(p geometry) returns double precision
language sql stable parallel safe as $f$
  -- Altitud del mejor relieve disponible en un punto (EPSG:6369): el fino de una zona si lo hay, si no el CEM 4.0.
  select v from (
{ramas}
    select ST_Value(r.rast, p) from terreno.r_cem4_15m r where ST_Intersects(r.rast, p)
  ) x(v) where v is not null limit 1
$f$;
comment on function terreno.altitud(geometry) is 'Altitud (m sobre el nivel medio del mar) del mejor relieve disponible en un punto EPSG:6369: el de 1.5 m de una zona si lo hay, si no el CEM 4.0 de 15 m';""")
    correr_sql(con, SQL / 'fase0' / '04_meta.sql')
    correr_sql(con, SQL / 'fase1' / '02_meta_relieve.sql')

    # Cotejo independiente: la altitud que da el ITER 2020 a cada localidad contra el relieve en su punto
    r = consulta(con, """
        with d as (select l.altitud - terreno.altitud(l.geom) as dif, l.pob from qgis.localidades l)
        select count(*), percentile_cont(0.5) within group (order by dif),
               percentile_cont(0.5) within group (order by abs(dif)),
               percentile_cont(0.9) within group (order by abs(dif)),
               count(*) filter (where abs(dif) > 50)
        from d where dif is not null""")[0]
    log(f'  ITER 2020 contra el relieve en {r[0]:,} localidades: diferencia mediana {r[1]:+.1f} m, '
        f'|dif| mediana {r[2]:.1f} m, p90 {r[3]:.1f} m, {r[4]} a más de 50 m')
    if zonas_finas:
        z = zonas_finas[0]
        r = consulta(con, f"""
            with d as (select l.nombre, l.altitud, terreno.altitud(l.geom) fino,
                              (select ST_Value(rast, l.geom) from terreno.r_cem4_15m where ST_Intersects(rast, l.geom)) cem
                       from qgis.localidades l, terreno.zonas zz
                       where zz.zona = %s and ST_Intersects(l.geom, zz.geom))
            select count(*), percentile_cont(0.5) within group (order by fino - cem),
                   percentile_cont(0.5) within group (order by abs(fino - cem)),
                   percentile_cont(0.5) within group (order by abs(altitud - fino))
            from d where fino is not null and cem is not null""", (z,))[0]
        log(f'  {z}: {r[0]} localidades · relieve fino − CEM: mediana {r[1]:+.2f} m, |dif| mediana {r[2]:.2f} m · '
            f'|ITER − fino| mediana {r[3]:.1f} m')


PASOS = {'cem': paso_cem, 'hojas': paso_hojas, 'normalizar': paso_normalizar, 'relieve': paso_relieve,
         'calidad': paso_calidad, 'registrar': paso_registrar}


def main() -> int:
    pasos = [a for a in sys.argv[1:] if not a.startswith('--')] or list(PASOS)
    for p in pasos:
        if p not in PASOS:
            sys.exit(f'paso desconocido: {p} (hay: {", ".join(PASOS)})')
    t0 = time.time()
    for p in pasos:
        log(f'── paso {p}')
        PASOS[p]()
    log(f'fase 1 ({", ".join(pasos)}) terminada en {(time.time() - t0) / 60:.1f} min')
    return 0


if __name__ == '__main__':
    sys.exit(main())
