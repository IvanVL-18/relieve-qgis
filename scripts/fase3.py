"""Fase 3: edificios con su altura medida y árboles uno por uno.

  correr scripts\\fase3.py altura      altura sobre el suelo (superficie − terreno de INEGI, 1.5 m) de la zona
  correr scripts\\fase3.py edificios   contornos de Microsoft con su altura medida y control contra OpenStreetMap
  correr scripts\\fase3.py arboles     cimas y copas de los árboles, dosel y control contra el modelo de Meta

Opción --zona=piloto (por omisión). Los pasos se pueden repetir.
"""
from __future__ import annotations

import gzip
import io
import json
import sys
import time
from pathlib import Path

import numpy as np

from comun import CFG, DATOS, FUENTES, RAIZ, SQL, SRID, cargar_vector, conectar, consulta, correr_sql, log

TERRENO = DATOS / 'terreno'
NODATA = -9999.0
ALTO_M = 2.0           # más que esto sobre el suelo = algo construido o vegetación
BLOQUE = 512           # filas por bloque


def zona_arg() -> str:
    return next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--zona=')), 'piloto')


def gdal_():
    from osgeo import gdal
    gdal.UseExceptions()
    gdal.SetConfigOption('GDAL_NUM_THREADS', 'ALL_CPUS')
    gdal.SetCacheMax(1024 * 1024 * 1024)
    return gdal


def crear(ruta: Path, plantilla, tipo=None, nodata=NODATA):
    """GeoTIFF con la rejilla de otro (plantilla = dataset de GDAL)."""
    gdal = gdal_()
    tipo = gdal.GDT_Float32 if tipo is None else tipo
    ds = gdal.GetDriverByName('GTiff').Create(str(ruta), plantilla.RasterXSize, plantilla.RasterYSize, 1, tipo,
                                              ['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=YES', 'NUM_THREADS=ALL_CPUS'])
    ds.SetGeoTransform(plantilla.GetGeoTransform())
    ds.SetSpatialRef(plantilla.GetSpatialRef())
    if nodata is not None:
        ds.GetRasterBand(1).SetNoDataValue(nodata)
    return ds


def cog(origen: Path, destino: Path, error_max: float | None = None) -> None:
    gdal = gdal_()
    comp = (['COMPRESS=DEFLATE', 'PREDICTOR=YES'] if error_max is None
            else ['COMPRESS=LERC_ZSTD', f'MAX_Z_ERROR={error_max}'])
    gdal.Translate(str(destino), str(origen), format='COG', outputSRS=f'EPSG:{SRID}',
                   creationOptions=comp + ['BLOCKSIZE=512', 'OVERVIEW_RESAMPLING=AVERAGE', 'NUM_THREADS=ALL_CPUS',
                                           'BIGTIFF=IF_SAFER'])


# ── Altura sobre el suelo ───────────────────────────────────────────────────────────────────────────────────────────

def paso_altura() -> Path:
    gdal = gdal_()
    zona = zona_arg()
    destino = TERRENO / f'altura_suelo_{zona}_1p5m.tif'
    if destino.exists():
        log(f'ya está {destino.relative_to(RAIZ).as_posix()}')
        return destino
    ds_s = gdal.Open(str(TERRENO / f'superficie_{zona}_1p5m.tif'))
    ds_t = gdal.Open(str(TERRENO / f'relieve_{zona}_1p5m.tif'))
    if ds_s.GetGeoTransform() != ds_t.GetGeoTransform():
        raise RuntimeError('la superficie y el terreno no tienen la misma rejilla')
    bs, bt = ds_s.GetRasterBand(1), ds_t.GetRasterBand(1)
    tmp = TERRENO / 'tmp' / f'altura_suelo_{zona}.tif'
    tmp.parent.mkdir(parents=True, exist_ok=True)
    out = crear(tmp, ds_s)
    ob = out.GetRasterBand(1)
    w, h = ds_s.RasterXSize, ds_s.RasterYSize
    neg = total = 0
    for y in range(0, h, BLOQUE):
        n = min(BLOQUE, h - y)
        s, t = bs.ReadAsArray(0, y, w, n), bt.ReadAsArray(0, y, w, n)
        ok = (s > -1000) & (t > -1000)
        a = np.where(ok, s - t, NODATA).astype(np.float32)
        neg += int(np.count_nonzero(ok & (a < -1)))
        total += int(np.count_nonzero(ok))
        ob.WriteArray(a, 0, y)
    out = None
    cog(tmp, destino, error_max=0.05)
    tmp.unlink()
    log(f'{destino.relative_to(RAIZ).as_posix()}: {total / 1e6:,.0f} Mpx con dato; {100 * neg / max(total, 1):.2f} % '
        f'con la superficie más de 1 m por debajo del terreno (ruido o terreno interpolado)')
    return destino


# ── Edificios ───────────────────────────────────────────────────────────────────────────────────────────────────────

QUADKEYS = {'piloto': ['023310031', '023310033']}   # cuadros z9 de Bing que cubren la zona


def caja_wgs84(con, zona: str, margen: float = 1500) -> tuple[float, float, float, float]:
    return consulta(con, """select ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) from (
        select ST_Transform(ST_Expand(ST_Envelope(geom), %s), 4326) b from terreno.zonas where zona = %s) x""",
                    (margen, zona))[0]


def cargar_contornos(con, zona: str) -> None:
    """Contornos de Microsoft (GeoJSON por renglón, un archivo por cuadro z9) que caen en la caja de la zona."""
    w, s, e, n = caja_wgs84(con, zona)
    carpeta = Path(CFG['WEB_DATA']) / 'cache' / 'edificios'
    salida = FUENTES / 'edificios' / f'ms_{zona}.geojsonl'
    salida.parent.mkdir(parents=True, exist_ok=True)
    if not salida.exists():
        k = 0
        with open(salida, 'w', encoding='utf-8') as fo:
            for qk in QUADKEYS[zona]:
                archivo = next(carpeta.glob(f'{qk}-*.csv.gz'))
                with gzip.open(archivo, 'rt', encoding='utf-8') as fi:
                    for linea in fi:
                        i = linea.find('[[[')
                        if i < 0:
                            continue
                        j = linea.find(']', i)
                        lon, lat = map(float, linea[i + 3:j].split(','))
                        if w <= lon <= e and s <= lat <= n:
                            fo.write(linea)
                            k += 1
        log(f'contornos de Microsoft en la caja de {zona}: {k:,}')
    cargar_vector(salida, 'base', f'ms_edificios_{zona}', srs_origen='EPSG:4326')
    con.execute(f"comment on table base.ms_edificios_{zona} is 'Contornos de edificios de Microsoft Global ML Building "
                f"Footprints (versión 2026-02-03, ODbL), detectados en imágenes de satélite; height = -1 si no la traen'")


def niveles_osm(con, zona: str) -> None:
    """Edificios de OpenStreetMap con número de niveles (building:levels), para cotejar los pisos medidos."""
    from fase2 import overpass
    archivo = FUENTES / 'osm' / f'{zona}_niveles.json'
    if not archivo.exists():
        s, w, n, e = consulta(con, """select ST_YMin(b), ST_XMin(b), ST_YMax(b), ST_XMax(b) from (
            select ST_Transform(ST_Envelope(geom), 4326) b from terreno.zonas where zona = %s) x""", (zona,))[0]
        caja = f'{s:.5f},{w:.5f},{n:.5f},{e:.5f}'
        archivo.write_bytes(overpass(f'[out:json][timeout:300];way["building"]["building:levels"]({caja});out center tags;'))
    datos = json.loads(archivo.read_text(encoding='utf-8'))
    filas = []
    for el in datos.get('elements', []):
        c, t = el.get('center'), el.get('tags', {})
        try:
            niveles = int(float(str(t.get('building:levels', '')).split(';')[0]))
        except ValueError:
            continue
        if c and 0 < niveles < 60:
            filas.append((el['id'], niveles, c['lon'], c['lat']))
    with con.transaction():
        con.execute('drop table if exists base.osm_niveles_' + zona)
        con.execute(f'create table base.osm_niveles_{zona} (osm_id bigint, niveles smallint, geom geometry(Point, 6369))')
        with con.cursor() as cur:
            cur.executemany(f"""insert into base.osm_niveles_{zona} values
                                (%s, %s, ST_Transform(ST_SetSRID(ST_Point(%s, %s), 4326), 6369))""", filas)
        con.execute(f'create index on base.osm_niveles_{zona} using gist (geom)')
    log(f'edificios de OSM con niveles en {zona}: {len(filas):,}')


def paso_edificios() -> None:
    import pandas as pd
    gdal = gdal_()
    from comun import pg_gdal
    zona = zona_arg()
    con = conectar()
    correr_sql(con, SQL / 'fase3' / '01_edificios_arboles.sql')
    altura = paso_altura()
    cargar_contornos(con, zona)
    con.execute(f'analyze base.ms_edificios_{zona}')
    # 1) los contornos «pintados» sobre la rejilla de 1.5 m: cada píxel lleva el número de su edificio
    ds_a = gdal.Open(str(altura))
    gt, w, h = ds_a.GetGeoTransform(), ds_a.RasterXSize, ds_a.RasterYSize
    ids = TERRENO / 'tmp' / f'edificios_id_{zona}.tif'
    ids.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    gdal.Rasterize(str(ids), pg_gdal(), format='GTiff', outputType=gdal.GDT_UInt32, initValues=0, attribute='gid',
                   SQLStatement=f'select gid, geom from base.ms_edificios_{zona}',
                   outputBounds=(gt[0], gt[3] + gt[5] * h, gt[0] + gt[1] * w, gt[3]), xRes=gt[1], yRes=-gt[5],
                   outputSRS=f'EPSG:{SRID}',
                   creationOptions=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=YES', 'NUM_THREADS=ALL_CPUS'])
    log(f'  contornos en la rejilla de 1.5 m ({time.time() - t0:.0f} s)')
    # 2) alturas de los píxeles de cada edificio
    ds_i = gdal.Open(str(ids))
    ds_t = gdal.Open(str(TERRENO / f'relieve_{zona}_1p5m.tif'))
    bi, ba, bt = ds_i.GetRasterBand(1), ds_a.GetRasterBand(1), ds_t.GetRasterBand(1)
    partes = []
    for y in range(0, h, BLOQUE):
        n = min(BLOQUE, h - y)
        i = bi.ReadAsArray(0, y, w, n)
        m = i > 0
        if not m.any():
            continue
        a, t = ba.ReadAsArray(0, y, w, n)[m], bt.ReadAsArray(0, y, w, n)[m]
        partes.append(pd.DataFrame({'id': i[m], 'a': a, 't': t}))
    df = pd.concat(partes, ignore_index=True)
    df = df[(df.a > -1000) & (df.t > -1000)]
    df['alto'] = df.a >= ALTO_M
    g = df.groupby('id')
    res = pd.DataFrame({'pixeles': g.size(), 'frac_alto': g.alto.mean(), 'z_suelo': g.t.median()})
    alto = df[df.a >= ALTO_M].groupby('id').a
    res['altura_m'] = alto.median()
    res['altura_p90_m'] = alto.quantile(0.9)
    res['confianza'] = np.where((res.pixeles >= 20) & (res.frac_alto >= 0.7), 'alta',
                                np.where(res.frac_alto >= 0.4, 'media', 'sin medida'))
    res.loc[res.confianza == 'sin medida', ['altura_m', 'altura_p90_m']] = np.nan
    res['pisos'] = np.where(res.altura_m.notna(), np.maximum(1, np.round(res.altura_m / 3.0)), np.nan)
    log(f'  {len(df):,} píxeles en {len(res):,} edificios ({time.time() - t0:.0f} s)')
    # 3) a la base, con su contorno
    with con.transaction():
        con.execute('create temp table med (id bigint, pixeles int, frac_alto real, z_suelo real, altura_m real, '
                    'altura_p90_m real, confianza text, pisos smallint) on commit drop')
        with con.cursor().copy('copy med from stdin') as cp:
            for r in res.itertuples():
                cp.write_row((int(r.Index), int(r.pixeles), float(r.frac_alto),
                              None if np.isnan(r.z_suelo) else float(r.z_suelo),
                              None if np.isnan(r.altura_m) else round(float(r.altura_m), 2),
                              None if np.isnan(r.altura_p90_m) else round(float(r.altura_p90_m), 2),
                              r.confianza, None if np.isnan(r.pisos) else int(r.pisos)))
        con.execute('delete from terreno.edificios where zona = %s', (zona,))
        con.execute(f"""
            insert into terreno.edificios (id, zona, area_m2, pixeles, frac_alto, altura_m, altura_p90_m, pisos, z_suelo,
                                           confianza, geom)
            select e.gid, %s, ST_Area(e.geom), coalesce(m.pixeles, 0), m.frac_alto, m.altura_m, m.altura_p90_m, m.pisos,
                   m.z_suelo, coalesce(m.confianza, 'sin medida'), e.geom
            from base.ms_edificios_{zona} e
            join terreno.zonas z on z.zona = %s and ST_Intersects(e.geom, z.geom)
            left join med m on m.id = e.gid""", (zona, zona))
        con.execute('analyze terreno.edificios')
    # 4) control: pisos medidos contra building:levels de OpenStreetMap
    niveles_osm(con, zona)
    with con.transaction():
        con.execute(f"""update terreno.edificios e set osm_niveles = o.niveles from base.osm_niveles_{zona} o
                        where e.zona = %s and ST_Contains(e.geom, o.geom)""", (zona,))
    from fase0 import tabla
    tabla([tuple(r) for r in consulta(con, """
        select confianza, count(*), round(sum(area_m2)::numeric / 1e4, 1) as ha,
               round(percentile_cont(0.5) within group (order by altura_m)::numeric, 1) as altura_mediana,
               round(percentile_cont(0.95) within group (order by altura_m)::numeric, 1) as p95
        from terreno.edificios where zona = %s group by 1 order by 2 desc""", (zona,))],
          ('confianza', 'edificios', 'ha de techo', 'altura mediana m', 'p95 m'))
    r = consulta(con, """select count(*), count(*) filter (where pisos = osm_niveles),
                                count(*) filter (where abs(pisos - osm_niveles) <= 1)
                         from terreno.edificios where zona = %s and osm_niveles is not null and pisos is not null""",
                 (zona,))[0]
    if r[0]:
        log(f'  contra OSM ({r[0]} edificios con niveles): mismos pisos {100 * r[1] / r[0]:.0f} %, '
            f'±1 piso {100 * r[2] / r[0]:.0f} %')


# ── Árboles ─────────────────────────────────────────────────────────────────────────────────────────────────────────

ARBOL_MIN_M = 3.0      # cima mínima
TRASLAPE = 40          # filas de traslape entre bloques (60 m): copas y cimas en la orilla del bloque
# Una copa es irregular; un techo es plano: «copa» de 20 m² o más que varía menos de 0.6 m = posible construcción
# (edificios que no están en los contornos de Microsoft). Muy alto con copa diminuta = pico del modelo (torre,
# poste, orilla de barranco).
COPA_PLANA_M2, COPA_PLANA_DESV_M = 20.0, 0.6
PICO_M, PICO_COPA_M2 = 30.0, 15.0


def ventana_por_altura(s):
    """Lado (píxeles) de la ventana de búsqueda de cimas según la altura: los árboles altos tienen copas anchas."""
    return np.where(s < 8, 3, np.where(s < 15, 5, np.where(s < 25, 7, 9)))


def paso_arboles() -> None:
    from scipy import ndimage
    gdal = gdal_()
    zona = zona_arg()
    con = conectar()
    correr_sql(con, SQL / 'fase3' / '01_edificios_arboles.sql')
    altura = paso_altura()
    ids = TERRENO / 'tmp' / f'edificios_id_{zona}.tif'
    if not ids.exists():
        sys.exit('falta la rejilla de edificios: corre antes el paso edificios')
    ds_a, ds_i = gdal.Open(str(altura)), gdal.Open(str(ids))
    ds_t = gdal.Open(str(TERRENO / f'relieve_{zona}_1p5m.tif'))
    ba, bi, bt = ds_a.GetRasterBand(1), ds_i.GetRasterBand(1), ds_t.GetRasterBand(1)
    gt, w, h = ds_a.GetGeoTransform(), ds_a.RasterXSize, ds_a.RasterYSize
    tmp = TERRENO / 'tmp' / f'dosel_{zona}.tif'
    out = crear(tmp, ds_a)
    ob = out.GetRasterBand(1)
    cimas = []
    t0 = time.time()
    px2 = gt[1] * -gt[5]
    for y in range(0, h, BLOQUE * 2):
        n = min(BLOQUE * 2, h - y)
        y0, y1 = max(0, y - TRASLAPE), min(h, y + n + TRASLAPE)
        a = ba.ReadAsArray(0, y0, w, y1 - y0)
        edif = ndimage.binary_dilation(bi.ReadAsArray(0, y0, w, y1 - y0) > 0, iterations=2)   # 3 m alrededor
        veg = (a >= ALTO_M) & (a < 80) & ~edif
        chm = np.where(veg, a, 0).astype(np.float32)
        nucleo = slice(y - y0, y - y0 + n)
        ob.WriteArray(np.where(a > -1000, chm, NODATA)[nucleo], 0, y)
        if not veg.any():
            continue
        s = ndimage.gaussian_filter(chm, 1.0)
        ventana = ventana_por_altura(s)
        cima = np.zeros_like(veg)
        for lado in (3, 5, 7, 9):
            sel = ventana == lado
            if sel.any():
                cima |= sel & (s == ndimage.maximum_filter(s, size=lado))
        cima &= veg & (chm >= ARBOL_MIN_M)
        marcas, k = ndimage.label(cima, structure=np.ones((3, 3)))   # cimas planas de varios píxeles = una
        if k == 0:
            continue
        # copas: cuencas alrededor de cada cima dentro de la vegetación
        costo = np.clip((80 - s) * 200, 0, 65535).astype(np.uint16)
        semillas = marcas.astype(np.int32)
        semillas[~veg] = -1
        copas = ndimage.watershed_ift(costo, semillas)
        area = np.bincount(copas[veg & (copas > 0)].ravel(), minlength=k + 1) * px2
        idx = np.arange(1, k + 1)
        filas_c = ndimage.center_of_mass(cima, marcas, idx)
        alt = ndimage.maximum(chm, marcas, idx)
        copas_veg = np.where(veg, copas, 0)
        desv = ndimage.standard_deviation(chm, copas_veg, idx)   # qué tan pareja es la «copa»
        t = bt.ReadAsArray(0, y0, w, y1 - y0)
        for j, (fy, fx) in enumerate(filas_c):
            if not (y - y0 <= fy < y - y0 + n):     # solo las cimas del núcleo del bloque
                continue
            ar, h_, sd = float(area[j + 1]), float(alt[j]), float(desv[j])
            ix, iy = int(round(fx)), int(round(fy))
            tipo = ('posible construcción' if ar >= COPA_PLANA_M2 and sd < COPA_PLANA_DESV_M
                    else 'pico dudoso' if h_ >= PICO_M and ar < PICO_COPA_M2 else 'árbol')
            cimas.append((float(gt[0] + (fx + 0.5) * gt[1]), float(gt[3] + (y0 + fy + 0.5) * gt[5]),
                          round(h_, 2), round(2 * (ar / np.pi) ** 0.5, 2), round(ar, 1),
                          round(float(t[iy, ix]), 2), round(sd, 2), tipo))
        if (y // (BLOQUE * 2)) % 5 == 0:
            log(f'  fila {y:,} de {h:,}: {len(cimas):,} árboles ({time.time() - t0:.0f} s)')
    out = None
    cog(tmp, TERRENO / f'dosel_{zona}_1p5m.tif', error_max=0.05)
    tmp.unlink()
    with con.transaction():
        con.execute('delete from terreno.arboles where zona = %s', (zona,))
        with con.cursor().copy('copy terreno.arboles (zona, altura_m, copa_diam_m, copa_area_m2, z_suelo, desv_copa_m, '
                               'tipo, geom) from stdin') as cp:
            for x, yy, alt, diam, ar, z, sd, tipo in cimas:
                cp.write_row((zona, alt, diam, ar, z, sd, tipo, f'SRID=6369;POINT({x:.2f} {yy:.2f})'))
    con.execute('analyze terreno.arboles')
    # Un techo plano sin contorno solo tiene sentido donde hay construcciones: fuera de las localidades amanzanadas
    # (con 30 m de margen) una «copa plana» es dosel de bosque que la fotogrametría suaviza, y sigue siendo árbol.
    with con.transaction():
        con.execute("""update terreno.arboles a set tipo = 'árbol'
                       where a.zona = %s and a.tipo = 'posible construcción'
                         and not exists (select 1 from base.mg_localidades l where ST_DWithin(l.geom, a.geom, 30))""",
                    (zona,))
    log(f'cimas {zona}: {len(cimas):,} ({time.time() - t0:.0f} s)')
    from fase0 import tabla
    tabla([tuple(r) for r in consulta(con, """
        select tipo, case when altura_m < 5 then 'a. 3 a 5 m' when altura_m < 10 then 'b. 5 a 10 m'
                    when altura_m < 20 then 'c. 10 a 20 m' when altura_m < 30 then 'd. 20 a 30 m' else 'e. 30 m o más' end,
               count(*), round(percentile_cont(0.5) within group (order by copa_diam_m)::numeric, 1)
        from terreno.arboles where zona = %s group by 1, 2 order by 1, 2""", (zona,))],
          ('tipo', 'altura', 'cimas', 'copa mediana m'))
    control_dosel(con, zona)


# Ventanas de 1.5 km de lado para comparar con el dosel de Meta: bosque, ciudad y campo
VENTANAS = {'piloto': {'bosque de El Chico': (527500, 2236500), 'ciudad de Pachuca': (523500, 2221500),
                       'orilla agrícola (sur)': (521000, 2213500), 'ladera de Mineral del Monte': (535000, 2228000)}}
META_CHM = 'https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/{qk}.tif'


def control_dosel(con, zona: str) -> None:
    gdal = gdal_()
    # El GeoTIFF de Meta guarda renglones completos de 65 536 px: trozos grandes = menos peticiones
    gdal.SetConfigOption('CPL_VSIL_CURL_CHUNK_SIZE', str(4 * 1024 * 1024))
    gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
    gdal.SetConfigOption('GDAL_HTTP_USERAGENT', 'relieve-qgis/0.1')
    nuestro = TERRENO / f'dosel_{zona}_1p5m.tif'
    vrt = '/vsicurl/' + META_CHM.format(qk=QUADKEYS[zona][0])
    if len(QUADKEYS[zona]) > 1:   # los dos cuadros de Meta como un solo mosaico virtual
        vrt = gdal.BuildVRT('', ['/vsicurl/' + META_CHM.format(qk=q) for q in QUADKEYS[zona]])
    filas = []
    for nombre, (cx, cy) in VENTANAS[zona].items():
        caja = (cx - 750, cy - 750, cx + 750, cy + 750)
        opc = dict(format='MEM', outputBounds=caja, xRes=1.5, yRes=1.5, dstSRS=f'EPSG:{SRID}')
        t0 = time.time()
        ds_m = gdal.Warp('', vrt, resampleAlg='average', dstNodata=NODATA, **opc)
        meta = ds_m.ReadAsArray()
        ds_m = None
        ds_o = gdal.Warp('', str(nuestro), resampleAlg='near', **opc)
        ours = ds_o.ReadAsArray()
        ds_o = None
        ok = (meta != NODATA) & (ours != NODATA)
        a, b = ours[ok] >= 3, meta[ok] >= 3
        ambos = ok & (ours >= 5) & (meta >= 5)
        d = (ours - meta)[ambos]
        corr = float(np.corrcoef(ours[ambos], meta[ambos])[0, 1]) if ambos.sum() > 50 else None
        filas.append((zona, nombre, round(float(ok.sum() * 2.25 / 1e6), 2), round(100 * float(a.mean()), 1),
                      round(100 * float(b.mean()), 1), round(float((a & b).sum() / max((a | b).sum(), 1)), 2),
                      round(float(np.median(d)), 2) if d.size else None, round(corr, 2) if corr is not None else None))
        log(f'  dosel de Meta, {nombre} ({time.time() - t0:.0f} s)')
    with con.transaction(), con.cursor() as cur:
        cur.execute('delete from terreno.control_dosel where zona = %s', (zona,))
        cur.executemany('insert into terreno.control_dosel values (%s, %s, %s, %s, %s, %s, %s, %s)', filas)
    from fase0 import tabla
    tabla([f[1:] for f in filas], ('ventana', 'km²', 'dosel ≥ 3 m nuestro %', 'de Meta %', 'coincidencia (IoU)',
                                   'nuestro − Meta m', 'correlación'))


PASOS = {'altura': paso_altura, 'edificios': paso_edificios, 'arboles': paso_arboles}


def main() -> int:
    pasos = [a for a in sys.argv[1:] if not a.startswith('--')] or list(PASOS)
    for p in pasos:
        if p not in PASOS:
            sys.exit(f'paso desconocido: {p} (hay: {", ".join(PASOS)})')
    t0 = time.time()
    for p in pasos:
        log(f'── paso {p}')
        PASOS[p]()
    log(f'fase 3 ({", ".join(pasos)}) terminada en {(time.time() - t0) / 60:.1f} min')
    return 0


if __name__ == '__main__':
    sys.exit(main())
