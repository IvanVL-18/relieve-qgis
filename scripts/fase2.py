"""Fase 2: agua y calles.

  correr scripts\\fase2.py mg          Marco Geoestadístico 2025 de INEGI, Hidalgo: calles (ejes de vialidad), manzanas…
  correr scripts\\fase2.py topo50      cartas 1:50 000 de INEGI: corrientes, cuerpos de agua, caminos y carreteras
  correr scripts\\fase2.py osm         OpenStreetMap de la zona: vías y agua con sus etiquetas
  correr scripts\\fase2.py drenaje     red de drenaje y subcuencas calculadas del relieve fino (GRASS)
  correr scripts\\fase2.py agua        cauces, cuerpos de agua con su nivel y control contra INEGI
  correr scripts\\fase2.py calles      calles de la zona con su pendiente medida en el relieve de 1.5 m

Opción --zona=piloto (por omisión). Los pasos se pueden repetir: lo bajado no se vuelve a bajar.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from comun import DATOS, FUENTES, RAIZ, SQL, SRID, cargar_vector, conectar, consulta, correr_sql, log
import inegi

# Marco Geoestadístico 2025 (INEGI): un zip nacional de 2.7 GB con un zip por estado; se baja solo el de Hidalgo.
MG_UPC = '794551163061'
MG_URL = f'{inegi.SITIO}/contenidos/productos/prod_serv/contenidos/espanol/bvinegi/productos/geografia/marcogeo/{MG_UPC}_s.zip'
MG_MIEMBRO = '13_hidalgo.zip'


def zona_arg() -> str:
    return next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--zona=')), 'piloto')


def paso_mg() -> Path:
    carpeta = FUENTES / 'inegi' / 'mg_2025'
    destino = carpeta / MG_MIEMBRO
    if not destino.exists():
        inicio, comprimido, tamano, crc, metodo = inegi.miembro_zip(MG_URL, MG_MIEMBRO)
        if metodo not in (0, 8):
            raise IOError(f'método de compresión {metodo} inesperado')
        crudo = carpeta / (MG_MIEMBRO + ('.deflate' if metodo == 8 else '.part0'))
        inegi.descargar_rangos(MG_URL, crudo, inicio, comprimido, hilos=8, trozo=8 * inegi.MB)
        if metodo == 8:
            inegi.inflar(crudo, destino, tamano, crc)
            crudo.unlink()
        else:
            crudo.replace(destino)
    # Capas del Marco Geoestadístico que se usan (todo el estado; los cálculos finos se hacen por zona)
    import zipfile
    from comun import codificacion_dbf
    con = conectar()
    for capa, tabla in (('13e', 'mg_ejes_carga'), ('13m', 'mg_manzanas_carga'), ('13l', 'mg_localidades_carga'),
                        ('13sia', 'mg_servicios_a_carga'), ('13sil', 'mg_servicios_l_carga'),
                        ('13sip', 'mg_servicios_p_carga')):
        tipo = {'13e': 'MULTILINESTRING', '13sil': 'MULTILINESTRING', '13sip': 'POINT'}.get(capa, 'MULTIPOLYGON')
        with zipfile.ZipFile(destino) as z:
            cod = codificacion_dbf(z.read(f'conjunto_de_datos/{capa}.dbf'))
        cargar_vector(f'/vsizip/{destino.as_posix()}/conjunto_de_datos/{capa}.shp', 'base', tabla, tipo=tipo,
                      codificacion=cod)
        log(f'  ({capa}: texto en {cod})')
    correr_sql(con, SQL / 'fase2' / '01_mg.sql')
    return destino


# ── Cartas topográficas 1:50 000 de INEGI (caché del proyecto web) ──────────────────────────────────────────────────

CAPAS50 = {   # tabla de carga: (nombres de la capa según la edición de la carta, geometría)
    'corrientes': (['corriente_ag_l', 'corriente_ag50_l'], 'MULTILINESTRING'),
    'corrientes_area': (['corriente_ag_a', 'corriente_ag50_a'], 'MULTIPOLYGON'),
    'cuerpos_agua': (['cuerpo_agua_a', 'cuerpo_agua50_a'], 'MULTIPOLYGON'),
    'canales': (['canal_l', 'canal50_l'], 'MULTILINESTRING'),
    'presas': (['presa_l', 'presa50_l'], 'MULTILINESTRING'),
    'bordos': (['bordo_l', 'bordo50_l'], 'MULTILINESTRING'),
    'caminos': (['camino_l', 'camino50_l'], 'MULTILINESTRING'),
    'carreteras': (['carretera_l', 'carretera50_l'], 'MULTILINESTRING'),
}


def paso_topo50() -> None:
    import zipfile
    from osgeo import gdal
    from comun import CFG, pg_gdal
    gdal.UseExceptions()
    carpeta = Path(CFG['WEB_DATA']) / 'cache' / 'inegi' / 'topo50'
    zips = sorted(carpeta.glob('*.zip'))
    con = conectar()
    for t in CAPAS50:
        con.execute(f'drop table if exists base.carga50_{t}')
    n = 0
    for z in zips:
        hoja, edicion = z.stem.split('_')
        with zipfile.ZipFile(z) as zz:
            shps = {Path(x).stem: x for x in zz.namelist() if x.lower().endswith('.shp')}
        for t, (nombres, tipo) in CAPAS50.items():
            capa = next((c for c in nombres if c in shps), None)
            if capa is None:
                continue
            # Cada edición nombra distinto sus campos: se cargan todos y se unifican en SQL
            opciones = gdal.VectorTranslateOptions(
                options=['-makevalid', '-lco', 'GEOMETRY_NAME=geom', '-lco', 'FID=gid', '-lco', 'LAUNDER=YES',
                         '-lco', 'SPATIAL_INDEX=NONE', '-lco', 'PRECISION=NO'],
                format='PostgreSQL', accessMode='append', addFields=True, layerName=f'base.carga50_{t}',
                dstSRS=f'EPSG:{SRID}', reproject=True, geometryType=tipo,
                SQLStatement=f"SELECT *, '{hoja}' AS hoja50, '{edicion}' AS edicion50 FROM \"{capa}\"", SQLDialect='OGRSQL')
            gdal.VectorTranslate(pg_gdal(), f'/vsizip/{z.as_posix()}/{shps[capa]}', options=opciones)
            n += 1
    log(f'{len(zips)} cartas 1:50 000, {n} capas cargadas')
    correr_sql(con, SQL / 'fase2' / '02_topo50.sql')
    for t, filas in consulta(con, """select 'corrientes', count(*) from base.inegi50_corrientes union all
                                     select 'cuerpos de agua', count(*) from base.inegi50_cuerpos_agua union all
                                     select 'caminos', count(*) from base.inegi50_caminos union all
                                     select 'carreteras', count(*) from base.inegi50_carreteras"""):
        log(f'  {t}: {filas:,}')


# ── OpenStreetMap de la zona (Overpass) ─────────────────────────────────────────────────────────────────────────────

OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
            'https://overpass.private.coffee/api/interpreter']   # el principal y dos espejos públicos


def overpass(q: str) -> bytes:
    """Consulta Overpass con reintentos: si un servidor está saturado (429, 502, 504) prueba el siguiente."""
    import urllib.parse
    import urllib.request
    datos = urllib.parse.urlencode({'data': q}).encode()
    ultimo = None
    for intento in range(3):
        for url in OVERPASS:
            try:
                req = urllib.request.Request(url, data=datos, headers={'User-Agent': 'relieve-qgis/0.1'})
                with urllib.request.urlopen(req, timeout=900) as r:
                    cuerpo = r.read()
                if b'<remark> runtime error' in cuerpo[-2000:]:
                    raise IOError('Overpass cortó la consulta (runtime error)')
                log(f'  {url.split("/")[2]}: {len(cuerpo) / 1e6:.1f} MB')
                return cuerpo
            except Exception as e:
                ultimo = e
                log(f'  {url.split("/")[2]}: {e}')
        time.sleep(30 * (intento + 1))
    raise RuntimeError(f'Overpass no respondió: {ultimo}')


def caja_wgs84(con, zona: str, margen: float = 2000) -> tuple[float, float, float, float]:
    """(sur, oeste, norte, este) de la zona con margen, en grados."""
    return consulta(con, """select ST_YMin(b), ST_XMin(b), ST_YMax(b), ST_XMax(b) from (
        select ST_Transform(ST_Expand(ST_Envelope(geom), %s), 4326) b from terreno.zonas where zona = %s) x""",
                    (margen, zona))[0]


def osmconf() -> Path:
    """Configuración del lector OSM de GDAL: las etiquetas útiles como columnas y todas las demás en JSON."""
    import re
    from comun import CFG  # noqa: F401
    base = Path(r'C:\Program Files\QGIS 3.44.15\apps\gdal\share\gdal\osmconf.ini')
    texto = base.read_text(encoding='utf-8')
    texto = texto.replace('#tags_format=json', 'tags_format=json')
    texto = texto.replace('closed_ways_are_polygons=aeroway,', 'closed_ways_are_polygons=water,reservoir,aeroway,')
    extra = {'[lines]': 'name,highway,waterway,railway,surface,lanes,oneway,maxspeed,bridge,tunnel,layer,ref,'
                        'intermittent,tracktype,service,width,smoothness,sidewalk,lit',
             '[multipolygons]': 'name,type,natural,water,landuse,leisure,amenity,waterway,intermittent,'
                                'reservoir_type,building,place'}
    for seccion, attrs in extra.items():
        i = texto.index(seccion)
        j = texto.index('attributes=', i)
        k = texto.index('\n', j)
        texto = texto[:j] + 'attributes=' + attrs + texto[k:]
    destino = DATOS / 'fuentes' / 'osm' / 'osmconf.ini'
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding='utf-8')
    return destino


def paso_osm() -> None:
    import urllib.parse
    import urllib.request
    from osgeo import gdal
    from comun import pg_gdal
    gdal.UseExceptions()
    zona = zona_arg()
    con = conectar()
    s, w, n, e = caja_wgs84(con, zona)
    archivo = DATOS / 'fuentes' / 'osm' / f'{zona}.osm'
    if not archivo.exists():
        caja = f'{s:.5f},{w:.5f},{n:.5f},{e:.5f}'
        q = (f'[out:xml][timeout:600];('
             f'way["highway"]({caja});way["waterway"]({caja});way["natural"="water"]({caja});'
             f'relation["natural"="water"]({caja});way["landuse"="reservoir"]({caja});way["water"]({caja});'
             f'way["leisure"~"park|garden|pitch|playground"]({caja});'
             f');(._;>;);out body;')
        log(f'Overpass: vías y agua de la zona {zona} ({caja})')
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(overpass(q))
    gdal.SetConfigOption('OSM_CONFIG_FILE', str(osmconf()))
    for capa, tabla, tipo in (('lines', f'osm_lineas_{zona}', 'MULTILINESTRING'),
                              ('multipolygons', f'osm_poligonos_{zona}', 'MULTIPOLYGON')):
        opciones = gdal.VectorTranslateOptions(
            options=['-makevalid', '-lco', 'GEOMETRY_NAME=geom', '-lco', 'FID=gid', '-lco', 'LAUNDER=YES',
                     '-lco', 'SPATIAL_INDEX=GIST'],
            format='PostgreSQL', accessMode='overwrite', layerName=f'base.{tabla}', layers=[capa],
            dstSRS=f'EPSG:{SRID}', reproject=True, geometryType=tipo)
        ds = gdal.VectorTranslate(pg_gdal(), str(archivo), options=opciones)
        ds = None
    filas = consulta(con, f"""select coalesce(highway, 'agua: ' || waterway) t, count(*) from base.osm_lineas_{zona}
                              group by 1 order by 2 desc limit 12""")
    log('  OSM: ' + ', '.join(f'{t} {c}' for t, c in filas))
    from psycopg import sql
    fecha = time.strftime('%Y-%m-%d', time.localtime(archivo.stat().st_mtime))
    for tabla, texto in ((f'osm_lineas_{zona}', f'OpenStreetMap (ODbL, © colaboradores de OpenStreetMap), vías y '
                                                f'cauces de la zona {zona} (Overpass, {fecha}); other_tags en JSON'),
                         (f'osm_poligonos_{zona}', f'OpenStreetMap (ODbL), cuerpos de agua, parques y jardines de la '
                                                   f'zona {zona} (Overpass, {fecha}); other_tags en JSON')):
        con.execute(sql.SQL('comment on table {} is {}').format(sql.Identifier('base', tabla), sql.Literal(texto)))


# ── Red de drenaje calculada del relieve fino (GRASS) ───────────────────────────────────────────────────────────────

TERRENO = DATOS / 'terreno'
HIDRO = DATOS / 'terreno' / 'hidro'
CELDA_HIDRO = 5.0          # m: el relieve de 1.5 m se promedia a 5 m (49 Mpx en el piloto; a 1.5 m no cabe en memoria)
CAUCE_KM2 = 0.1            # área drenada desde la que empieza un cauce
SUBCUENCA_KM2 = 2.0        # tamaño mínimo de subcuenca
CLASES = [(100, 'río principal'), (10, 'río'), (1, 'arroyo'), (0, 'escurrimiento')]   # por km² drenados
QGIS_PROCESS = Path(r'C:\Program Files\QGIS 3.44.15\bin\qgis_process-qgis-ltr.bat')


def qgis_process(algoritmo: str, entradas: dict) -> dict:
    """Corre un algoritmo de Processing (p. ej. de GRASS) con qgis_process; las entradas van en JSON por stdin."""
    import json
    import os
    import subprocess
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}
    t0 = time.time()
    r = subprocess.run([str(QGIS_PROCESS), '--json', 'run', algoritmo, '-'], input=json.dumps({'inputs': entradas}),
                       capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(f'{algoritmo}: {r.stderr[-1500:] or r.stdout[-1500:]}')
    salida = json.loads(r.stdout[r.stdout.index('{'):])
    log(f'  {algoritmo} ({time.time() - t0:.0f} s)')
    return salida.get('results', {})


def leer(ruta: Path):
    from osgeo import gdal
    ds = gdal.Open(str(ruta))
    a = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    ds = None
    return a, gt


def paso_drenaje() -> None:
    import numpy as np
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    zona = zona_arg()
    con = conectar()
    correr_sql(con, SQL / 'fase2' / '03_hidro.sql')
    HIDRO.mkdir(parents=True, exist_ok=True)
    fino = TERRENO / f'relieve_{zona}_1p5m.tif'
    dem5 = HIDRO / f'relieve_{zona}_5m.tif'
    if not dem5.exists():
        gdal.Warp(str(dem5), str(fino), xRes=CELDA_HIDRO, yRes=CELDA_HIDRO, targetAlignedPixels=True,
                  resampleAlg='average', srcNodata=-9999, dstNodata=-9999,
                  creationOptions=['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=3'])
    celda_m2 = CELDA_HIDRO ** 2
    acc, cuencas = HIDRO / f'acumulacion_{zona}.tif', HIDRO / f'subcuencas_{zona}.tif'
    if not acc.exists():
        # r.watershed busca el camino de menor costo y atraviesa las depresiones sin rellenarlas; con flujo múltiple
        # (convergencia 5). Valores negativos = puede entrar agua de fuera del recuadro (cuenca incompleta).
        qgis_process('grass:r.watershed', {
            'elevation': str(dem5), 'threshold': int(SUBCUENCA_KM2 * 1e6 / celda_m2), 'convergence': 5, '-b': True,
            'accumulation': str(acc), 'basin': str(cuencas), 'GRASS_REGION_CELLSIZE_PARAMETER': CELDA_HIDRO})
    vec = HIDRO / f'cauces_{zona}.gpkg'
    if not vec.exists():
        umbral = int(CAUCE_KM2 * 1e6 / celda_m2)
        qgis_process('grass:r.stream.extract', {
            'elevation': str(dem5), 'threshold': umbral, 'd8cut': umbral, 'stream_length': 20, 'memory': 4000,
            'stream_vector': str(vec), 'GRASS_OUTPUT_TYPE_PARAMETER': 2, 'GRASS_REGION_CELLSIZE_PARAMETER': CELDA_HIDRO})

    # atributos de cada tramo: área drenada en su extremo de aguas abajo, cuenca incompleta, alturas y pendiente
    a, gt = leer(acc)
    z, _ = leer(dem5)
    h, w = a.shape

    def valor(arr, x, y):
        c, f = int((x - gt[0]) / gt[1]), int((gt[3] - y) / -gt[5])
        return arr[min(max(f, 0), h - 1), min(max(c, 0), w - 1)]

    ds = ogr.Open(str(vec))
    capa = ds.GetLayer(0)
    filas = []
    for f in capa:
        g = f.GetGeometryRef()
        partes = [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())] if g.GetGeometryCount() else [g]
        pts = [p for parte in partes for p in parte.GetPoints()]
        if len(pts) < 2:
            continue
        a0, a1 = valor(a, *pts[0][:2]), valor(a, *pts[-1][:2])
        abajo, arriba = (pts[-1], pts[0]) if abs(a1) >= abs(a0) else (pts[0], pts[-1])
        aa = a1 if abs(a1) >= abs(a0) else a0
        km2 = abs(float(aa)) * celda_m2 / 1e6
        z_arriba, z_abajo = float(valor(z, *arriba[:2])), float(valor(z, *abajo[:2]))
        largo = g.Length()
        clase = next(c for lim, c in CLASES if km2 >= lim)
        tipo = f.GetField('stream_type') if f.GetFieldIndex('stream_type') >= 0 else None
        red = f.GetField('network') if f.GetFieldIndex('network') >= 0 else None
        filas.append((zona, tipo, red, round(km2, 4), bool(aa < 0), clase, round(z_arriba, 2), round(z_abajo, 2),
                      round(largo, 1), round(100 * (z_arriba - z_abajo) / largo, 2) if largo > 0 else None,
                      g.ExportToWkb()))
    ds = None
    with con.transaction():
        con.execute('delete from terreno.cauces where zona = %s', (zona,))
        with con.cursor() as cur:
            cur.executemany("""insert into terreno.cauces (zona, tipo, red, area_km2, cuenca_incompleta, clase, z_arriba,
                                 z_abajo, largo_m, pendiente_pct, geom)
                               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                       ST_Multi(ST_SetSRID(ST_GeomFromWKB(%s), 6369)))""", filas)
        con.execute("""update terreno.cauces c set urbano = exists (
                         select 1 from base.mg_localidades l where l.ambito = 'Urbana' and ST_Intersects(l.geom, c.geom))
                       where zona = %s""", (zona,))
    con.execute('analyze terreno.cauces')   # sin estadísticas, el planeador recorre la tabla en cada búsqueda
    log(f'cauces {zona}: {len(filas):,} tramos')

    # subcuencas: del ráster de cuencas a polígonos; las que tocan la orilla del recuadro quedan como incompletas
    tmp = HIDRO / f'subcuencas_{zona}.gpkg'
    if tmp.exists():
        tmp.unlink()
    src = gdal.Open(str(cuencas))
    drv = ogr.GetDriverByName('GPKG').CreateDataSource(str(tmp))
    lyr = drv.CreateLayer('subcuencas', srs=src.GetSpatialRef(), geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('cuenca', ogr.OFTInteger))
    gdal.Polygonize(src.GetRasterBand(1), src.GetRasterBand(1).GetMaskBand(), lyr, 0)
    drv = None
    src = None
    cargar_vector(tmp, 'terreno', f'subcuencas_carga_{zona}')
    with con.transaction():
        con.execute('delete from terreno.subcuencas where zona = %s', (zona,))
        con.execute(f"""
            insert into terreno.subcuencas (zona, cuenca, area_km2, incompleta, geom)
            select %s, s.cuenca, ST_Area(ST_Transform(ST_Union(s.geom), 4326)::geography) / 1e6,
                   ST_Intersects(ST_Union(s.geom), ST_Boundary((select ST_Envelope(ST_Collect(geom))
                                                                 from terreno.subcuencas_carga_{zona}))),
                   ST_Multi(ST_Union(s.geom))
            from terreno.subcuencas_carga_{zona} s
            where s.cuenca > 0
            group by s.cuenca""", (zona,))
        con.execute(f'drop table terreno.subcuencas_carga_{zona}')
    r = consulta(con, """select count(*), count(*) filter (where not incompleta), round(sum(area_km2)::numeric)
                         from terreno.subcuencas where zona = %s""", (zona,))[0]
    log(f'subcuencas {zona}: {r[0]} ({r[1]} completas), {r[2]} km²')
    for clase, n, km, inc, urb in consulta(con, """
            select clase, count(*), round(sum(largo_m)::numeric / 1000, 1),
                   count(*) filter (where cuenca_incompleta), count(*) filter (where urbano)
            from terreno.cauces where zona = %s group by clase order by min(area_km2) desc""", (zona,)):
        log(f'  {clase}: {n:,} tramos, {km} km ({inc} con cuenca incompleta, {urb} en zona urbana)')


# ── Perfiles sobre el relieve de 1.5 m ──────────────────────────────────────────────────────────────────────────────

class Relieve:
    """Lee alturas del relieve fino por ventanas (no cabe entero en memoria) con interpolación bilineal."""

    def __init__(self, ruta: Path):
        from osgeo import gdal
        self.ds = gdal.Open(str(ruta))
        self.b = self.ds.GetRasterBand(1)
        self.gt = self.ds.GetGeoTransform()
        self.w, self.h = self.ds.RasterXSize, self.ds.RasterYSize

    def alturas(self, xs, ys):
        import numpy as np
        cx = (np.asarray(xs) - self.gt[0]) / self.gt[1] - 0.5
        cy = (self.gt[3] - np.asarray(ys)) / -self.gt[5] - 0.5
        x0, y0 = max(int(np.floor(cx.min())), 0), max(int(np.floor(cy.min())), 0)
        x1, y1 = min(int(np.floor(cx.max())) + 2, self.w), min(int(np.floor(cy.max())) + 2, self.h)
        if x1 <= x0 or y1 <= y0:
            return np.full(len(cx), np.nan)
        v = self.b.ReadAsArray(x0, y0, x1 - x0, y1 - y0).astype(np.float64)
        v[v <= -1000] = np.nan
        fx, fy = np.clip(cx - x0, 0, x1 - x0 - 1), np.clip(cy - y0, 0, y1 - y0 - 1)
        i0, j0 = np.floor(fy).astype(int), np.floor(fx).astype(int)
        i1, j1 = np.minimum(i0 + 1, v.shape[0] - 1), np.minimum(j0 + 1, v.shape[1] - 1)
        dy, dx = fy - i0, fx - j0
        return (v[i0, j0] * (1 - dx) * (1 - dy) + v[i0, j1] * dx * (1 - dy)
                + v[i1, j0] * (1 - dx) * dy + v[i1, j1] * dx * dy)


def muestrear(linea, paso: float):
    """Puntos cada `paso` metros sobre una línea de shapely (incluye los dos extremos)."""
    import numpy as np
    import shapely
    d = np.append(np.arange(0, linea.length, paso), linea.length)
    p = shapely.line_interpolate_point(linea, d)
    return d, shapely.get_x(p), shapely.get_y(p)


def paso_agua() -> None:
    import numpy as np
    import shapely
    zona = zona_arg()
    con = conectar()
    correr_sql(con, SQL / 'fase2' / '04_agua_calles.sql')
    with con.transaction():
        con.execute('delete from terreno.cuerpos_agua where zona = %s', (zona,))
        con.execute(f"""
            insert into terreno.cuerpos_agua (zona, fuente, nombre, tipo, condicion, area_ha, geom)
            select z.zona, 'INEGI 1:50 000', c.nombre, c.tipo, c.condicion,
                   ST_Area(ST_Transform(c.geom, 4326)::geography) / 1e4, c.geom
            from base.inegi50_cuerpos_agua c join terreno.zonas z on z.zona = %s and ST_Intersects(c.geom, z.geom)
            union all
            select z.zona, 'OpenStreetMap', o.name, coalesce(o.water, o.reservoir_type, o."natural", o.landuse),
                   case when o.intermittent = 'yes' then 'Intermitente' end,
                   ST_Area(ST_Transform(o.geom, 4326)::geography) / 1e4, ST_Multi(o.geom)
            from base.osm_poligonos_{zona} o join terreno.zonas z on z.zona = %s and ST_Intersects(o.geom, z.geom)
            where o."natural" = 'water' or o.landuse = 'reservoir' or o.water is not null""", (zona, zona))
    # nivel del agua: la altura en la orilla (cada 3 m sobre el anillo exterior)
    rel = Relieve(TERRENO / f'relieve_{zona}_1p5m.tif')
    filas = []
    for id_, wkb in consulta(con, 'select id, ST_AsBinary(ST_ExteriorRing((ST_Dump(geom)).geom)) from terreno.cuerpos_agua '
                                  'where zona = %s', (zona,)):
        anillo = shapely.from_wkb(bytes(wkb))
        _, xs, ys = muestrear(anillo, 3.0)
        z = rel.alturas(xs, ys)
        z = z[np.isfinite(z)]
        if z.size:
            filas.append((float(np.median(z)), float(np.percentile(z, 90) - np.percentile(z, 10)), id_))
    with con.transaction(), con.cursor() as cur:
        cur.executemany('update terreno.cuerpos_agua set nivel_m = %s, nivel_rango_m = %s where id = %s', filas)
    r = consulta(con, """select fuente, count(*), round(sum(area_ha)::numeric, 1), count(nivel_m)
                         from terreno.cuerpos_agua where zona = %s group by 1""", (zona,))
    for fuente, n, ha, con_nivel in r:
        log(f'cuerpos de agua {zona} ({fuente}): {n}, {ha} ha, {con_nivel} con nivel')

    # control: qué tanto caen los ríos de INEGI y de OSM sobre los cauces calculados
    con.execute('analyze terreno.cauces')
    with con.transaction():
        con.execute('delete from terreno.control_cauces where zona = %s', (zona,))
        con.execute(f"""
            with z as (select geom from terreno.zonas where zona = %(z)s),
            ref as (
              select 'INEGI 1:50 000' as referencia, lower(coalesce(c.condicion, 'sin dato')) as grupo,
                     ST_Intersection(c.geom, z.geom) as g
              from base.inegi50_corrientes c, z where ST_Intersects(c.geom, z.geom)
              union all
              select 'OpenStreetMap', coalesce(o.waterway, 'cauce'), ST_Intersection(o.geom, z.geom)
              from base.osm_lineas_{zona} o, z where o.waterway is not null and ST_Intersects(o.geom, z.geom)),
            pts as (
              select r.referencia, r.grupo, (ST_DumpPoints(ST_Segmentize(r.g, 10))).geom as p from ref r
              where not ST_IsEmpty(r.g)),
            d as (
              select p.referencia, p.grupo,
                     (select ST_Distance(p.p, k.geom) from terreno.cauces k where k.zona = %(z)s
                      order by k.geom <-> p.p limit 1) as dist
              from pts p)
            insert into terreno.control_cauces
            select %(z)s, referencia, coalesce(grupo, 'todos'), count(*), count(*) * 10 / 1000.0,
                   percentile_cont(0.5) within group (order by dist),
                   100.0 * avg((dist <= 20)::int), 100.0 * avg((dist <= 50)::int)
            from d group by referencia, rollup(grupo)""", {'z': zona})
    from fase0 import tabla
    tabla([tuple(r) for r in consulta(con, """select referencia, grupo, km, round(mediana_m::numeric, 1),
                                               round(pct_20m::numeric), round(pct_50m::numeric)
                                              from terreno.control_cauces where zona = %s order by 1, 3 desc""", (zona,))],
          ('referencia', 'grupo', 'km', 'distancia mediana m', '% a ≤ 20 m', '% a ≤ 50 m'))


def paso_calles() -> None:
    import numpy as np
    import shapely
    zona = zona_arg()
    con = conectar()
    correr_sql(con, SQL / 'fase2' / '04_agua_calles.sql')
    VENTANA_M, PASO_M = 20.0, 1.5
    rel = Relieve(TERRENO / f'relieve_{zona}_1p5m.tif')
    ejes = consulta(con, """select e.cvegeo, e.nomvial, e.tipovial, e.sentido, e.ambito, ST_AsBinary(e.geom)
                            from base.mg_ejes e join terreno.zonas z on z.zona = %s and ST_Intersects(e.geom, z.geom)""",
                    (zona,))
    log(f'calles de {zona}: {len(ejes):,} segmentos del Marco Geoestadístico')
    filas, t0 = [], time.time()

    def pend_max_en(d, z, ventana_m):
        """La mayor pendiente (%) en `ventana_m` metros seguidos; en todo el tramo si es más corto."""
        k = int(round(ventana_m / PASO_M))
        if len(z) > k:
            return float(np.max(np.abs(z[k:] - z[:-k]) / (d[k:] - d[:-k])) * 100)
        return abs(float(z[-1] - z[0])) / max(float(d[-1]), 1e-6) * 100

    for cvegeo, nombre, tipo, sentido, ambito, wkb in ejes:
        g = shapely.from_wkb(bytes(wkb))
        linea = shapely.line_merge(g) if g.geom_type == 'MultiLineString' else g
        if linea.geom_type != 'LineString' or linea.length < 1:
            continue
        d, xs, ys = muestrear(linea, PASO_M)
        z = rel.alturas(xs, ys)
        if not np.isfinite(z).all():
            continue
        dz = np.diff(z)
        largo = float(linea.length)
        p20, p60 = pend_max_en(d, z, VENTANA_M), pend_max_en(d, z, 60.0)
        # Una calle empinada de verdad lo es también en 60 m; un escalón corto (puente que el relieve no tiene,
        # paso a desnivel, muro o error del relieve) da mucha pendiente en 20 m y poca en 60 m.
        irregular = largo >= 60 and p20 > 2 * p60 + 10
        filas.append((zona, cvegeo, nombre, tipo, sentido, ambito, round(largo, 1), round(float(z[0]), 2),
                      round(float(z[-1]), 2), round(abs(float(z[-1] - z[0])), 2),
                      round(abs(float(z[-1] - z[0])) / largo * 100, 2), round(p20, 2), round(p60, 2), irregular,
                      round(float(dz[dz > 0].sum()), 2), round(float(-dz[dz < 0].sum()), 2), bytes(wkb)))
    log(f'  perfiles medidos: {len(filas):,} ({time.time() - t0:.0f} s)')
    with con.transaction():
        con.execute('delete from terreno.calles where zona = %s', (zona,))
        with con.cursor() as cur:
            cur.executemany("""insert into terreno.calles (zona, fuente, cvegeo, nombre, tipo, sentido, ambito, largo_m,
                                 z_ini, z_fin, desnivel_m, pend_media_pct, pend_max_pct, pend_max_60m_pct,
                                 perfil_irregular, subida_m, bajada_m, geom)
                               values (%s, 'INEGI Marco Geoestadístico 2025', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                       %s, %s, %s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromWKB(%s), 6369)))""", filas)
        con.execute('analyze terreno.calles')
        # tipo y superficie de OSM: el tramo de vía que más se le encima a ≤ 10 m; puente si OSM marca uno encima
        con.execute(f"""
            update terreno.calles c set osm_tipo = o.highway, osm_superficie = o.surface
            from (
              select distinct on (c2.id) c2.id, o2.highway, o2.surface
              from terreno.calles c2
              join base.osm_lineas_{zona} o2 on o2.highway is not null and ST_DWithin(o2.geom, c2.geom, 10)
              where c2.zona = %(z)s
              order by c2.id, ST_Length(ST_Intersection(o2.geom, ST_Buffer(c2.geom, 10))) desc) o
            where c.id = o.id""", {'z': zona})
        # puente o paso a desnivel: una vía de OSM con bridge o con nivel (layer) distinto de 0 a ≤ 15 m, que
        # acompañe a la calle al menos 10 m (en los distribuidores, el eje de INEGI y los de OSM no coinciden)
        con.execute(f"""
            update terreno.calles c set puente = exists (
              select 1 from base.osm_lineas_{zona} o
              where o.highway is not null
                and ((o.bridge is not null and o.bridge <> 'no') or coalesce(o.layer, '0') not in ('0', ''))
                and ST_DWithin(o.geom, c.geom, 15)
                and ST_Length(ST_Intersection(o.geom, ST_Buffer(c.geom, 15))) > 10)
            where c.zona = %(z)s""", {'z': zona})
    from fase0 import tabla
    tabla([tuple(r) for r in consulta(con, """
        select case when pend_max_pct < 5 then 'a. menos de 5 %%' when pend_max_pct < 10 then 'b. 5 a 10 %%'
                    when pend_max_pct < 15 then 'c. 10 a 15 %%' when pend_max_pct < 25 then 'd. 15 a 25 %%'
                    else 'e. 25 %% o más' end as pendiente_max,
               count(*), round(sum(largo_m)::numeric / 1000, 1) as km
        from terreno.calles where zona = %s and not coalesce(puente, false) and not perfil_irregular
        group by 1 order by 1""", (zona,))],
          ('pendiente máxima (20 m)', 'segmentos', 'km'))
    r = consulta(con, """select count(*) filter (where puente), count(*) filter (where perfil_irregular and not puente),
                                count(osm_superficie), count(*)
                         from terreno.calles where zona = %s""", (zona,))[0]
    log(f'  {r[0]} junto a puentes o pasos a desnivel y {r[1]} con perfil irregular (pendiente por revisar); '
        f'{r[2]:,} de {r[3]:,} con superficie de OSM')


PASOS = {'mg': paso_mg, 'topo50': paso_topo50, 'osm': paso_osm, 'drenaje': paso_drenaje, 'agua': paso_agua,
         'calles': paso_calles}


def main() -> int:
    pasos = [a for a in sys.argv[1:] if not a.startswith('--')] or list(PASOS)
    for p in pasos:
        if p not in PASOS:
            sys.exit(f'paso desconocido: {p} (hay: {", ".join(PASOS)})')
    t0 = time.time()
    for p in pasos:
        log(f'── paso {p}')
        PASOS[p]()
    log(f'fase 2 ({", ".join(pasos)}) terminada en {(time.time() - t0) / 60:.1f} min')
    return 0


if __name__ == '__main__':
    sys.exit(main())
