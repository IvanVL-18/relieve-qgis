"""Arma el proyecto de QGIS (qgis/RelieveHidalgo.qgz) con las capas de la base, agrupadas y con estilos básicos.

  correr scripts\\proyecto_qgis.py            crea el proyecto (no pisa uno que ya exista)
  correr scripts\\proyecto_qgis.py --forzar   lo rehace (guarda el anterior como .qgz.bak)

Las capas se conectan con el servicio de PostgreSQL (service='relieveqgis', lo escribe la fase 0), así que el .qgz
no guarda la contraseña. La ficha de cada capa (Propiedades → Metadatos) trae su fuente, fecha y detalle de meta.capas.
"""
from __future__ import annotations

import shutil
import sys

from comun import RAIZ, SERVICIO, SRID, conectar, consulta, log

from qgis.core import (Qgis, QgsApplication, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem, QgsDataSourceUri,
                       QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject, QgsProperty,
                       QgsRectangle, QgsReferencedRectangle, QgsRendererCategory, QgsSymbolLayer, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor, QFont

DESTINO = RAIZ / 'qgis' / 'RelieveHidalgo.qgz'

# (grupo, [(capa, nombre en QGIS o None = el título de meta.capas, visible, filtro)]) de arriba hacia abajo.
CAPAS = [
    ('Límites', [
        ('base.estado', 'Hidalgo', True, ''),
        ('qgis.municipios', 'Municipios', True, ''),
        ('qgis.regiones_geoculturales', None, False, ''),
        ('base.municipios_edomex', None, False, ''),
        ('base.entidades', None, False, ''),
    ]),
    ('Población y servicios', [
        ('qgis.localidades', None, True, ''),
        ('qgis.servicios', None, False, ''),
        ('qgis.lugares', None, False, ''),
        ('qgis.movilidad_flujos', None, False, ''),
    ]),
    ('Agua', [
        ('qgis.manantiales', None, True, ''),
        ('qgis.aguas_termales', None, False, ''),
        ('qgis.agua_prioridad', None, False, ''),
        ('qgis.agua_localidades', None, False, ''),
        ('qgis.agua_bordos', None, False, ''),
        ('qgis.piezometria_pozos', None, False, ''),
        ('qgis.piezometria_propuesta', None, False, ''),
        ('qgis.calidad_agua_sitios', None, False, ''),
        ('qgis.repda_subterraneos', None, False, ''),
        ('qgis.repda_superficiales', None, False, ''),
        ('qgis.repda_descargas', None, False, ''),
        ('qgis.recarga_focos', None, False, ''),
        ('qgis.rios', None, True, ''),
        ('qgis.ordenamientos_agua', None, False, ''),
        ('qgis.acuiferos', None, False, ''),
    ]),
    ('Vías', [
        ('qgis.red_vial', None, True, ''),
        ('qgis.red_vial_nodos', None, False, ''),
    ]),
    ('Riesgos y geología', [
        ('qgis.deslizamientos', None, False, ''),
        ('qgis.volcanes', None, False, ''),
    ]),
    ('Culturas y turismo', [
        ('qgis.culturas_sitios', None, False, ''),
        ('qgis.geoparque_sitios', None, False, ''),
        ('qgis.culturas_rutas', None, False, ''),
        ('qgis.culturas_provincias', None, False, ''),
    ]),
    ('Uso de suelo (1:250 000)', [
        ('qgis.uso_suelo', 'Uso de suelo, Serie VII (2018)', True, '"serie" = 7'),
        ('qgis.uso_suelo', 'Uso de suelo, Serie VI (2014)', False, '"serie" = 6'),
    ]),
]

COLORES_PUNTO = {
    'qgis.manantiales': '#1f78b4', 'qgis.aguas_termales': '#e31a1c', 'qgis.agua_prioridad': '#ff7f00',
    'qgis.agua_localidades': '#a6cee3', 'qgis.agua_bordos': '#33a02c', 'qgis.piezometria_pozos': '#6a3d9a',
    'qgis.piezometria_propuesta': '#cab2d6', 'qgis.calidad_agua_sitios': '#b15928', 'qgis.repda_subterraneos': '#0b4f6c',
    'qgis.repda_superficiales': '#01baef', 'qgis.repda_descargas': '#8c510a', 'qgis.recarga_focos': '#d95f02',
    'qgis.servicios': '#e7298a', 'qgis.lugares': '#999999', 'qgis.deslizamientos': '#a50f15', 'qgis.volcanes': '#7f2704',
    'qgis.culturas_sitios': '#984ea3', 'qgis.geoparque_sitios': '#4daf4a', 'qgis.red_vial_nodos': '#666666',
}

VIAS = [  # clase de OSM, etiqueta, color, ancho en mm
    ('motorway', 'Autopista', '#c0392b', 0.9), ('trunk', 'Troncal', '#d35400', 0.75),
    ('primary', 'Primaria', '#e67e22', 0.6), ('secondary', 'Secundaria', '#f1c40f', 0.45),
    ('tertiary', 'Terciaria', '#bdbdbd', 0.3), ('unclassified', 'Sin clasificar', '#cfcfcf', 0.2),
    ('track', 'Brecha', '#a1887f', 0.15),
]


def propiedad(nombre: str):
    """QgsSymbolLayer.Property.X (QGIS ≥ 3.30) o QgsSymbolLayer.PropertyX (anteriores)."""
    enum = getattr(QgsSymbolLayer, 'Property', None)
    return getattr(enum, nombre) if enum is not None and hasattr(enum, nombre) else getattr(QgsSymbolLayer, f'Property{nombre}')


def capa_pg(capa: str, nombre: str, clave: str, geometria: str, filtro: str) -> QgsVectorLayer:
    esquema, tabla = capa.split('.')
    uri = QgsDataSourceUri()
    uri.setConnection(SERVICIO, '', '', '')
    uri.setDataSource(esquema, tabla, 'geom', filtro, clave)
    uri.setSrid(str(SRID))
    lyr = QgsVectorLayer(uri.uri(False), nombre, 'postgres')
    if not lyr.isValid():
        raise RuntimeError(f'No se pudo abrir {capa} con el servicio {SERVICIO}: {lyr.error().summary()}')
    return lyr


def estilo(lyr: QgsVectorLayer, capa: str, grupos_suelo: list[tuple]) -> None:
    if capa == 'base.estado':
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple(
            {'style': 'no', 'outline_color': '#1b1b1b', 'outline_width': '0.8'}))
    elif capa == 'qgis.municipios':
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple(
            {'style': 'no', 'outline_color': '#555555', 'outline_width': '0.25', 'outline_style': 'dash'}))
        pal = QgsPalLayerSettings()
        pal.fieldName = 'nombre'
        fmt = QgsTextFormat()
        fmt.setFont(QFont('Segoe UI'))
        fmt.setSize(7)
        fmt.setColor(QColor('#333333'))
        pal.setFormat(fmt)
        pal.scaleVisibility = True
        pal.minimumScale = 1_500_000      # se ven al acercarse más que 1:1 500 000
        pal.maximumScale = 0
        lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        lyr.setLabelsEnabled(True)
    elif capa in ('qgis.regiones_geoculturales', 'qgis.culturas_provincias', 'qgis.acuiferos',
                  'qgis.ordenamientos_agua', 'base.entidades', 'base.municipios_edomex'):
        colores = {'qgis.regiones_geoculturales': '#8e44ad', 'qgis.culturas_provincias': '#984ea3',
                   'qgis.acuiferos': '#1f78b4', 'qgis.ordenamientos_agua': '#e31a1c'}
        q = QColor(colores.get(capa, '#888888'))
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple(
            {'color': f'{q.red()},{q.green()},{q.blue()},35', 'outline_color': q.name(), 'outline_width': '0.4'}))
    elif capa == 'qgis.uso_suelo':
        cats = []
        for gid, nombre, color in grupos_suelo:
            sym = QgsFillSymbol.createSimple({'color': color, 'outline_style': 'no'})
            cats.append(QgsRendererCategory(gid, sym, nombre))
        lyr.setRenderer(QgsCategorizedSymbolRenderer('grupo', cats))
        lyr.setOpacity(0.85)
    elif capa == 'qgis.rios':
        sym = QgsLineSymbol.createSimple({'color': '#2b7bb9', 'width': '0.2', 'capstyle': 'round'})
        sym.symbolLayer(0).setDataDefinedProperty(propiedad('StrokeWidth'),
                                                  QgsProperty.fromExpression('0.08 + 0.12 * "orden"'))
        lyr.renderer().setSymbol(sym)
    elif capa == 'qgis.red_vial':
        cats = [QgsRendererCategory(clase, QgsLineSymbol.createSimple({'color': color, 'width': str(w)}), etiqueta)
                for clase, etiqueta, color, w in VIAS]
        lyr.setRenderer(QgsCategorizedSymbolRenderer('clase', cats))
    elif capa in ('qgis.culturas_rutas', 'qgis.movilidad_flujos'):
        c = '#984ea3' if capa == 'qgis.culturas_rutas' else '#e7298a'
        lyr.renderer().setSymbol(QgsLineSymbol.createSimple({'color': c, 'width': '0.5', 'line_style': 'dash'}))
    elif capa == 'qgis.localidades':
        sym = QgsMarkerSymbol.createSimple({'name': 'circle', 'color': '#333333', 'outline_color': '#ffffff',
                                            'outline_width': '0.15'})
        sym.setDataDefinedSize(QgsProperty.fromExpression('scale_exp("pob", 0, 200000, 0.7, 7, 0.5)'))
        lyr.renderer().setSymbol(sym)
    elif lyr.geometryType() == Qgis.GeometryType.Point:
        lyr.renderer().setSymbol(QgsMarkerSymbol.createSimple(
            {'name': 'circle', 'color': COLORES_PUNTO.get(capa, '#555555'), 'size': '1.6',
             'outline_color': '#ffffff', 'outline_width': '0.15'}))


def ficha(lyr: QgsVectorLayer, m: dict) -> None:
    md = lyr.metadata()
    partes = [m.get('notas') or '',
              f"Fuente: {m['fuentes']}" if m.get('fuentes') else '',
              f"Fecha de los datos: {m['fecha_datos']}" if m.get('fecha_datos') else '',
              f"Escala o resolución de origen: {m['escala']}" if m.get('escala') else '',
              f"Detalle (tamaño más chico que distingue): ≈ {m['detalle_m']:g} m" if m.get('detalle_m') else '',
              f"Tabla: {m['capa']} · {m['filas']:,} elementos · EPSG:{m['srid']}"]
    md.setTitle(m.get('titulo') or m['capa'])
    md.setAbstract('\n'.join(p for p in partes if p))
    lyr.setMetadata(md)


def main() -> int:
    forzar = '--forzar' in sys.argv
    if DESTINO.exists() and not forzar:
        log(f'ya existe {DESTINO.relative_to(RAIZ).as_posix()}: usa --forzar para rehacerlo')
        return 0

    con = conectar()
    cols = ('capa', 'titulo', 'fuentes', 'fecha_datos', 'escala', 'detalle_m', 'notas', 'geometria', 'srid', 'filas')
    meta = {r[0]: dict(zip(cols, r)) for r in consulta(con, f"select {', '.join(cols)} from meta.capas")}
    claves = dict(consulta(con, """
        select n.nspname || '.' || c.relname, string_agg(a.attname, ',' order by x.ord)
        from pg_index i
        join pg_class c on c.oid = i.indrelid
        join pg_namespace n on n.oid = c.relnamespace
        cross join lateral unnest(i.indkey) with ordinality as x(attnum, ord)
        join pg_attribute a on a.attrelid = i.indrelid and a.attnum = x.attnum
        where i.indisprimary and n.nspname in ('base', 'qgis')
        group by 1"""))
    grupos_suelo = consulta(con, 'select id, nombre, color from relieve.uso_suelo_grupos order by id')
    xmin, ymin, xmax, ymax = consulta(con, """
        select ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b)
        from (select ST_Expand(ST_Envelope(geom), 5000) as b from base.estado) x""")[0]

    qgs = QgsApplication([], False)
    qgs.initQgis()
    try:
        proj = QgsProject.instance()
        crs = QgsCoordinateReferenceSystem(f'EPSG:{SRID}')
        proj.setCrs(crs)
        proj.setTitle('Relieve de Hidalgo')
        proj.setEllipsoid('EPSG:7019')   # GRS80, el elipsoide de ITRF2008: medidas en el lienzo sobre el elipsoide
        raiz = proj.layerTreeRoot()
        n = 0
        for grupo, capas in CAPAS:
            nodo_grupo = raiz.addGroup(grupo)
            for capa, nombre, visible, filtro in capas:
                m = meta[capa]
                lyr = capa_pg(capa, nombre or m['titulo'] or capa, claves[capa], m['geometria'], filtro)
                estilo(lyr, capa, grupos_suelo)
                ficha(lyr, m)
                proj.addMapLayer(lyr, False)
                nodo = nodo_grupo.addLayer(lyr)
                nodo.setItemVisibilityChecked(visible)
                nodo.setExpanded(False)
                n += 1
            nodo_grupo.setExpanded(grupo in ('Límites', 'Agua'))
        proj.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(QgsRectangle(xmin, ymin, xmax, ymax), crs))
        DESTINO.parent.mkdir(parents=True, exist_ok=True)
        if DESTINO.exists():
            shutil.copy2(DESTINO, DESTINO.with_name(DESTINO.name + '.bak'))
        if not proj.write(str(DESTINO)):
            raise RuntimeError(f'No se pudo guardar {DESTINO}')
        log(f'{DESTINO.relative_to(RAIZ).as_posix()}: {n} capas en {len(CAPAS)} grupos, EPSG:{SRID}')
    finally:
        qgs.exitQgis()
    return 0


if __name__ == '__main__':
    sys.exit(main())
