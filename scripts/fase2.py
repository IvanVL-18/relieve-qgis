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


PASOS = {'mg': paso_mg, 'topo50': paso_topo50, 'osm': paso_osm}


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
