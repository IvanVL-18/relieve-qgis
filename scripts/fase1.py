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


def cog(origen: Path, destino: Path, resampleo: str = 'AVERAGE') -> None:
    """GeoTIFF optimizado (COG): teselas, DEFLATE con predictor de flotantes y vistas reducidas para QGIS."""
    gdal = gdal_()
    gdal.Translate(str(destino), str(origen), format='COG',
                   creationOptions=['COMPRESS=DEFLATE', 'PREDICTOR=YES', 'LEVEL=6', 'BLOCKSIZE=512',
                                    f'OVERVIEW_RESAMPLING={resampleo}', 'NUM_THREADS=ALL_CPUS', 'BIGTIFF=IF_SAFER'])


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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
    nd = gdal.Open(str(archivos[-1])).GetRasterBand(1).GetNoDataValue()
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


def fusionar(con, zona: str) -> Path:
    """Relieve de la zona a 1.5 m: hojas de INEGI donde las hay y CEM 4.0 (interpolación cúbica) donde no, con una
    transición lineal de TRANSICION_M metros hacia dentro de la hoja para que no quede un escalón."""
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
    vrt = vrt_fino(con, zona, 'terreno')
    xmin, ymin, xmax, ymax = rejilla_zona(con, zona, vrt)
    w, h = round((xmax - xmin) / FINO), round((ymax - ymin) / FINO)
    log(f'relieve {zona}: {w:,} × {h:,} px a {FINO} m ({w * h / 1e6:,.0f} Mpx)')
    fino = gdal.Translate('', str(vrt), format='VRT', projWin=(xmin, ymax, xmax, ymin), noData=NODATA)
    base = gdal.Warp('', str(cem), format='VRT', outputBounds=(xmin, ymin, xmax, ymax), xRes=FINO, yRes=FINO,
                     resampleAlg='cubic', srcNodata=NODATA, dstNodata=NODATA)
    bf, bb = fino.GetRasterBand(1), base.GetRasterBand(1)

    # 1) celdas de 15 m completamente cubiertas por el dato fino
    BLOQUE = 500    # filas por bloque (múltiplo de 10)
    lleno = np.zeros((h // 10, w // 10), dtype=bool)
    for y in range(0, h, BLOQUE):
        n = min(BLOQUE, h - y)
        v = bf.ReadAsArray(0, y, w, n) != NODATA
        lleno[y // 10:(y + n) // 10] = v.reshape(n // 10, 10, w // 10, 10).all(axis=(1, 3))
    # 2) peso del dato fino: 0 en la orilla de lo cubierto, 1 a TRANSICION_M hacia dentro
    dist = ndimage.distance_transform_edt(lleno) * (FINO * 10)
    peso15 = np.clip((dist - FINO * 10) / TRANSICION_M, 0, 1).astype(np.float32)
    log(f'  dato fino en {100 * lleno.mean():.1f} % de la caja; transición de {TRANSICION_M} m')

    tmp = destino.with_name(destino.stem + '_tmp.tif')
    drv = gdal.GetDriverByName('GTiff')
    out = drv.Create(str(tmp), w, h, 1, gdal.GDT_Float32,
                     ['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=3', 'BIGTIFF=YES', 'NUM_THREADS=ALL_CPUS'])
    out.SetGeoTransform((xmin, FINO, 0, ymax, 0, -FINO))
    out.SetSpatialRef(fino.GetSpatialRef())
    ob = out.GetRasterBand(1)
    ob.SetNoDataValue(NODATA)
    cols = (np.arange(w) + 0.5) / 10 - 0.5
    for y in range(0, h, BLOQUE):
        n = min(BLOQUE, h - y)
        f = bf.ReadAsArray(0, y, w, n)
        b = bb.ReadAsArray(0, y, w, n)
        filas = (np.arange(y, y + n) + 0.5) / 10 - 0.5
        rr, cc = np.meshgrid(filas, cols, indexing='ij')
        p = ndimage.map_coordinates(peso15, [rr, cc], order=1, mode='nearest').astype(np.float32)
        p[f == NODATA] = 0
        # sin CEM queda el dato fino (o nada); con CEM, la mezcla (p = 0 donde no hay dato fino: queda el CEM)
        r = np.where(b == NODATA, f, p * f + (1 - p) * b)
        ob.WriteArray(r.astype(np.float32), 0, y)
    ob.FlushCache()
    out = None
    cog(tmp, destino)
    tmp.unlink()
    log(f'{destino.relative_to(RAIZ).as_posix()} listo')
    return destino


def derivados(dem: Path, nombre: str) -> None:
    """Sombreado multidireccional y pendiente (grados) del relieve, como COG."""
    gdal = gdal_()
    for proc, sufijo, opciones in (('hillshade', 'sombreado', {'multiDirectional': True}),
                                   ('slope', 'pendiente', {'slopeFormat': 'degree'})):
        destino = TERRENO / f'{sufijo}_{nombre}.tif'
        if destino.exists():
            continue
        tmp = destino.with_name(destino.stem + '_tmp.tif')
        t0 = time.time()
        gdal.DEMProcessing(str(tmp), str(dem), proc, computeEdges=True, **opciones,
                           creationOptions=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER', 'NUM_THREADS=ALL_CPUS'])
        cog(tmp, destino)
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
        vrt = vrt_fino(con, zona, 'superficie')
        xmin, ymin, xmax, ymax = rejilla_zona(con, zona, vrt_fino(con, zona, 'terreno'))
        tmp = sup.with_name(sup.stem + '.vrt')
        gdal_().Translate(str(tmp), str(vrt), format='VRT', projWin=(xmin, ymax, xmax, ymin), noData=NODATA)
        cog(tmp, sup)
        tmp.unlink()
        log(f'{sup.relative_to(RAIZ).as_posix()} listo')


# ── Control de calidad de las hojas ─────────────────────────────────────────────────────────────────────────────────

# Umbrales para marcar una hoja como «revisar». El CEM 4.0 no es independiente (integra datos de 5 m de INEGI) ni
# más exacto (15 m): sirve para encontrar hojas desplazadas o con fallas gruesas, no para medir la exactitud fina.
UMBRAL = {'sesgo_m': 2.0, 'nmad_m': 4.0, 'p95_abs_m': 15.0, 'costura_m': 0.5, 'sin_dato_pct': 5.0}


def paso_calidad() -> None:
    import numpy as np
    gdal = gdal_()
    zona = zona_arg()
    con = conectar()
    cem = TERRENO / 'cem4_15m.tif'
    hojas = consulta(con, """select clave, archivo_terreno from terreno.hojas
                             where %s = any(zonas) and archivo_terreno is not null order by clave""", (zona,))
    gt_cem = gdal.Open(str(cem)).GetGeoTransform()
    resultados = {}
    for clave, archivo in hojas:
        ds = gdal.Open(str(RAIZ / archivo))
        b = ds.GetRasterBand(1)
        nd = b.GetNoDataValue()
        a = b.ReadAsArray()
        sin_dato = 100 * float(np.mean(a == nd)) if nd is not None else 0.0
        gt = ds.GetGeoTransform()
        x0, y1 = gt[0], gt[3]
        x1, y0 = x0 + gt[1] * ds.RasterXSize, y1 + gt[5] * ds.RasterYSize
        # caja alineada a la rejilla del CEM, hacia dentro de la hoja
        ax = lambda v, f: gt_cem[0] + f((v - gt_cem[0]) / 15) * 15
        ay = lambda v, f: gt_cem[3] + f((v - gt_cem[3]) / 15) * 15
        import math
        caja = (ax(x0, math.ceil), ay(y0, math.ceil), ax(x1, math.floor), ay(y1, math.floor))
        h15 = gdal.Warp('', ds, format='MEM', outputBounds=caja, xRes=15, yRes=15, resampleAlg='average',
                        srcNodata=nd, dstNodata=NODATA).ReadAsArray()
        c15 = gdal.Warp('', str(cem), format='MEM', outputBounds=caja, xRes=15, yRes=15, resampleAlg='near',
                        dstNodata=NODATA).ReadAsArray()
        ok = (h15 != NODATA) & (c15 != NODATA)
        d = (h15 - c15)[ok]
        med = float(np.median(d)) if d.size else None
        resultados[clave] = {
            'sin_dato_pct': sin_dato, 'sesgo_m': med,
            'nmad_m': float(1.4826 * np.median(np.abs(d - med))) if d.size else None,
            'p95_abs_m': float(np.percentile(np.abs(d), 95)) if d.size else None,
            'costura_m': None, 'gt': gt, 'forma': (ds.RasterXSize, ds.RasterYSize), 'archivo': archivo, 'nd': nd}
        ds = None

    # costuras: donde dos hojas vecinas se enciman, mediana de |diferencia|. La ventana se ajusta a la rejilla de la
    # primera; si la segunda está corrida (algunas ediciones empiezan medio píxel después), se interpola a esa rejilla.
    import math
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
            va = gdal.Warp('', str(RAIZ / ra['archivo']), format='MEM', outputBounds=caja, xRes=px, yRes=px,
                           resampleAlg='near', srcNodata=ra['nd'], dstNodata=NODATA).ReadAsArray()
            vb = gdal.Warp('', str(RAIZ / rb['archivo']), format='MEM', outputBounds=caja, xRes=px, yRes=px,
                           resampleAlg='bilinear', srcNodata=rb['nd'], dstNodata=NODATA).ReadAsArray()
            ok = (va != NODATA) & (vb != NODATA)
            if ok.sum() < 100:
                continue
            c = float(np.median(np.abs(va[ok] - vb[ok])))
            for k in (ca, cb):
                resultados[k]['costura_m'] = max(c, resultados[k]['costura_m'] or 0)

    filas = []
    with con.transaction():
        for clave, r in resultados.items():
            motivos = [k for k, u in UMBRAL.items()
                       if r[k] is not None and (abs(r[k]) if k == 'sesgo_m' else r[k]) > u]
            revision = 'ok' if not motivos else 'revisar: ' + ', '.join(motivos)
            con.execute("""update terreno.hojas set sin_dato_pct = %s, sesgo_m = %s, nmad_m = %s, p95_abs_m = %s,
                           costura_m = %s, revision = %s where clave = %s""",
                        (r['sin_dato_pct'], r['sesgo_m'], r['nmad_m'], r['p95_abs_m'], r['costura_m'], revision, clave))
            filas.append((clave, f"{r['sin_dato_pct']:.2f}", f"{r['sesgo_m']:+.2f}", f"{r['nmad_m']:.2f}",
                          f"{r['p95_abs_m']:.1f}", '' if r['costura_m'] is None else f"{r['costura_m']:.2f}", revision))
    from fase0 import tabla
    tabla(filas, ('hoja', 'sin dato %', 'sesgo m', 'NMAD m', 'p95 |d| m', 'costura m', 'revisión'))
    d = consulta(con, """select count(*), count(*) filter (where revision = 'ok'),
                                percentile_cont(0.5) within group (order by sesgo_m),
                                percentile_cont(0.5) within group (order by nmad_m)
                         from terreno.hojas where %s = any(zonas) and revision is not null""", (zona,))[0]
    log(f'calidad {zona}: {d[1]} de {d[0]} hojas ok · sesgo mediano {d[2]:+.2f} m · NMAD mediana {d[3]:.2f} m (contra CEM 4.0)')


# ── PostGIS: rásters fuera de la base y altitud por SQL ─────────────────────────────────────────────────────────────

PG_BIN = Path(r'C:\Program Files\PostgreSQL\17\bin')


def registrar_raster(archivo: Path, tabla: str) -> None:
    """Registra un GeoTIFF en PostGIS fuera de la base (raster2pgsql -R): la tabla guarda teselas que apuntan al
    archivo, y el servidor lo lee al consultar. Si el servidor no puede leer el archivo, lo dice la prueba de después."""
    import os
    import subprocess
    from comun import CFG
    env = {**os.environ, 'PGPASSWORD': CFG['DB_PASSWORD']}
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
  ) x where v is not null limit 1
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


PASOS = {'cem': paso_cem, 'hojas': paso_hojas, 'relieve': paso_relieve, 'calidad': paso_calidad,
         'registrar': paso_registrar}


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
