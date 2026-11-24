"""Fase 0: PostGIS, esquemas base / qgis / meta y todas las capas con geometría en EPSG:6369.

  correr scripts\\fase0.py

Se puede correr las veces que haga falta (también después de recargar el esquema relieve desde el proyecto web):
rehace base, qgis y meta sin tocar relieve. Las descargas se guardan en datos/fuentes y no se repiten.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from comun import CFG, FUENTES, SQL, cargar_vector, conectar, consulta, correr_sql, descargar, escribir_servicio, log

WSCATGEO = 'https://gaia.inegi.org.mx/wscatgeo/v2/geo'
# Caja de Hidalgo con margen (oeste, sur, este, norte; grados WGS84) para no cargar todo el país.
CAJA_HIDALGO = (-100.2, 19.4, -97.7, 21.6)


def cargar_base(web: Path) -> None:
    mg = FUENTES / 'inegi' / 'mg_2025_12'
    descargar(f'{WSCATGEO}/mgem/13', mg / 'mgem_13.json')
    descargar(f'{WSCATGEO}/mgee/', mg / 'mgee.json')
    descargar(f'{WSCATGEO}/mgem/15', mg / 'mgem_15.json')
    # El GeoJSON de INEGI declara EPSG:6365 (ITRF2008 geográfico) dentro de cada geometría, donde GDAL no lo lee.
    cargar_vector(mg / 'mgem_13.json', 'base', 'municipios_carga', srs_origen='EPSG:6365')
    cargar_vector(mg / 'mgee.json', 'base', 'entidades_carga', srs_origen='EPSG:6365')
    cargar_vector(mg / 'mgem_15.json', 'base', 'municipios_edomex_carga', srs_origen='EPSG:6365')

    conagua = web / 'CONAGUA'
    cargar_vector(conagua / 'disponibilidad_agua_subterranea' / 'disponibilidad_de_agua_subterranea_09-11-2023.shp',
                  'base', 'acuiferos_carga', caja=CAJA_HIDALGO)
    cargar_vector(conagua / 'ordenamientos_asub_vedas' / 'ordenamientos_asub_vedas_25nov2021.shp',
                  'base', 'vedas_carga', caja=CAJA_HIDALGO)
    cargar_vector(conagua / 'ordenamientos_asub_suspension_libre_alumbramiento'
                  / 'ordenamientos_asub_suspension_de_libre_alumbramiento_25nov2021.shp',
                  'base', 'suspensiones_carga', caja=CAJA_HIDALGO)


def tabla(filas: list[tuple], titulos: tuple[str, ...]) -> None:
    filas = [tuple('' if v is None else str(v) for v in f) for f in filas]
    anchos = [max(len(t), *(len(f[i]) for f in filas)) if filas else len(t) for i, t in enumerate(titulos)]
    print('    ' + ' | '.join(t.ljust(a) for t, a in zip(titulos, anchos)))
    print('    ' + '-+-'.join('-' * a for a in anchos))
    for f in filas:
        print('    ' + ' | '.join(v.ljust(a) for v, a in zip(f, anchos)))


def validar(con) -> int:
    """Revisiones de la fase 0. Devuelve cuántos problemas encontró (los avisos informativos no cuentan)."""
    problemas = 0
    capas = [r[0] for r in consulta(con, "select capa from meta.capas order by capa")]

    log(f'validación 1: geometrías inválidas, vacías o nulas y sistema de coordenadas ({len(capas)} capas)')
    filas = []
    for capa in capas:
        inval, vacias, nulas = consulta(con, f"""
            select count(*) filter (where geom is not null and not ST_IsValid(geom)),
                   count(*) filter (where geom is not null and ST_IsEmpty(geom)),
                   count(*) filter (where geom is null)
            from {capa}""")[0]
        srid = consulta(con, 'select srid from meta.capas where capa = %s', (capa,))[0][0]
        if inval or vacias or srid != 6369:
            problemas += 1
        if inval or vacias or nulas or srid != 6369:
            filas.append((capa, inval, vacias, nulas, srid))
    tabla(filas, ('capa', 'inválidas', 'vacías', 'sin geometría', 'srid')) if filas else print('    todo bien')

    log('validación 2: filas de relieve que no llegaron a qgis')
    filas = []
    for capa, en_qgis in consulta(con, "select capa, filas from meta.capas where capa like 'qgis.%' order by 1"):
        t = capa.split('.', 1)[1]
        if t in ('municipios', 'regiones_geoculturales', 'culturas_provincias'):   # se arman por municipio
            continue
        if not consulta(con, 'select to_regclass(%s) is not null', (f'relieve.{t}',))[0][0]:
            continue
        en_relieve = consulta(con, f'select count(*) from relieve.{t}')[0][0]
        if en_relieve != en_qgis:
            filas.append((capa, en_relieve, en_qgis, en_relieve - en_qgis))
            if not capa.startswith('qgis.repda_'):     # en repda_* son los registros sin coordenadas confiables
                problemas += 1
    tabla(filas, ('capa', 'en relieve', 'en qgis', 'faltan')) if filas else print('    ninguna: todas completas')

    log('validación 3: límites de INEGI (estado contra la unión de sus municipios)')
    a_est, a_mun, dif_m = consulta(con, """
        select e.area_km2, (select sum(area_km2) from base.municipios),
               ST_HausdorffDistance(ST_Boundary(e.geom), ST_Boundary((select ST_Union(geom) from base.municipios)))
        from base.estado e""")[0]
    print(f'    estado {a_est:,.1f} km² · suma de municipios {a_mun:,.1f} km² · diferencia máxima del contorno {dif_m:.1f} m')
    if abs(a_est - a_mun) > 1 or dif_m > 50:
        problemas += 1

    log('validación 4: puntos fuera de Hidalgo (a más de 1 km del límite)')
    filas = []
    con.execute('create temp table if not exists estado_partes as '
                'select ST_Subdivide(ST_Buffer(geom, 1000), 256) as g from base.estado')
    con.execute('create index if not exists estado_partes_g on estado_partes using gist (g)')
    for capa, n in consulta(con, "select capa, filas from meta.capas where capa like 'qgis.%' and geometria = 'POINT' order by 1"):
        fuera = consulta(con, f"""select count(*) from {capa} t
                                  where t.geom is not null
                                    and not exists (select 1 from estado_partes e where ST_Intersects(t.geom, e.g))""")[0][0]
        if fuera:
            filas.append((capa, n, fuera))
    tabla(filas, ('capa', 'puntos', 'fuera')) if filas else print('    ninguno')
    print('    (informativo: la red vial, los sitios de calidad del agua y los volcanes incluyen vecinos a propósito)')

    log('validación 5: uniones por clave')
    filas = consulta(con, """
        select 'acuíferos de relieve sin polígono de CONAGUA', count(*) from relieve.acuiferos r
          where not exists (select 1 from base.acuiferos a where a.clave = trim(r.clave))
        union all
        select 'acuíferos con recorte vacío en Hidalgo', count(*) from qgis.acuiferos where geom is null or ST_IsEmpty(geom)
        union all
        select 'ordenamientos sin polígono', count(*) from qgis.ordenamientos_agua where geom is null
        union all
        select 'municipios sin indicadores del web', count(*) from qgis.municipios where pob is null
        union all
        select 'flujos de movilidad sin destino dibujable', count(*) from qgis.movilidad_flujos where geom is null
        union all
        select 'tramos viales con forma aproximada', count(*) from qgis.red_vial where forma_aproximada""")
    tabla(filas, ('revisión', 'casos'))
    for nombre, n in filas:
        if n and nombre.startswith(('acuíferos de relieve', 'ordenamientos', 'municipios')):
            problemas += 1

    log('validación 6: áreas de ordenamientos en Hidalgo contra las del proyecto web')
    filas = consulta(con, """
        select tipo, nombre, hgo_km2 as web_km2,
               round((ST_Area(ST_Transform(geom, 4326)::geography) / 1e6)::numeric, 1) as aqui_km2
        from qgis.ordenamientos_agua
        where geom is not null
          and abs(ST_Area(ST_Transform(geom, 4326)::geography) / 1e6 - hgo_km2) > greatest(1, 0.02 * hgo_km2)
        order by abs(ST_Area(ST_Transform(geom, 4326)::geography) / 1e6 - hgo_km2) desc""")
    tabla(filas, ('tipo', 'nombre', 'web km²', 'aquí km²')) if filas else print('    coinciden (±2 %)')
    print('    (informativo: las diferencias vienen de franjas angostas en la orilla, donde los límites de CONAGUA y de\n'
          '     INEGI no casan; el web las pasa al acuífero de Hidalgo de al lado y aquí se recortan tal cual)')
    return problemas


def main() -> int:
    t0 = time.time()
    web = Path(CFG['WEB_DATA'])
    if not (web / 'CONAGUA').exists():
        sys.exit(f'No encuentro {web / "CONAGUA"}: revisa WEB_DATA en .env')
    con = conectar()
    version = consulta(con, 'select version()')[0][0].split(',')[0]
    log(f"base {CFG['DB_DATABASE']} en {CFG['DB_HOST']}: {version}")

    correr_sql(con, SQL / 'fase0' / '01_extensiones_esquemas.sql')
    log('PostGIS ' + consulta(con, 'select postgis_lib_version()')[0][0]
        + ' · pgRouting ' + consulta(con, 'select pgr_version()')[0][0])
    cargar_base(web)
    for nombre in ('02_base.sql', '03_qgis.sql', '04_meta.sql'):
        correr_sql(con, SQL / 'fase0' / nombre)

    problemas = validar(con)
    escribir_servicio()
    resumen = consulta(con, """
        select split_part(capa, '.', 1), count(*), sum(filas) from meta.capas group by 1 order by 1""")
    for esquema, n, filas in resumen:
        log(f'{esquema}: {n} capas, {filas:,} elementos')
    log(f'fase 0 terminada en {time.time() - t0:.0f} s · {problemas} problema(s)')
    return 1 if problemas else 0


if __name__ == '__main__':
    sys.exit(main())
