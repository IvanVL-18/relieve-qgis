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
    ('Calles y manzanas (piloto)', [
        ('terreno.calles', 'Calles por pendiente máxima en 20 m', True, '"zona" = \'piloto\''),
        ('base.mg_servicios_a', 'Parques, escuelas y espacios públicos (INEGI 2025)', True, ''),
        ('base.mg_manzanas', 'Manzanas (INEGI 2025)', True, ''),
        ('base.inegi50_carreteras', 'Carreteras (INEGI 1:50 000)', False, ''),
        ('base.inegi50_caminos', 'Caminos y brechas (INEGI 1:50 000)', False, ''),
        ('base.osm_lineas_piloto', 'OpenStreetMap: vías y cauces', False, ''),
    ]),
    ('Agua del relieve fino (piloto)', [
        ('terreno.cuerpos_agua', 'Cuerpos de agua (planos a su nivel en 3D)', True, '"zona" = \'piloto\''),
        ('terreno.cauces', 'Cauces calculados del relieve (5 m)', True, '"zona" = \'piloto\''),
        ('base.inegi50_corrientes', 'Corrientes (INEGI 1:50 000)', False, ''),
        ('terreno.subcuencas', 'Subcuencas de 2 km² o más', False, '"zona" = \'piloto\''),
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
        ('qgis.rios', None, False, ''),
        ('qgis.ordenamientos_agua', None, False, ''),
        ('qgis.acuiferos', None, False, ''),
    ]),
    ('Vías', [
        ('qgis.red_vial', None, False, ''),
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
    ('Relieve', [
        ('terreno.zonas', 'Zonas de trabajo', True, '"zona" <> \'estado\''),
        ('terreno.hojas', 'Hojas de INEGI (control de calidad)', False, ''),
        ('terreno.cobertura', 'Qué tan fino es el relieve', False, ''),
        ('archivo:sombreado_piloto_1p5m', 'Sombreado, piloto (1.5 m)', True, ''),
        ('archivo:sombreado_hidalgo_15m', 'Sombreado, Hidalgo (15 m)', True, ''),
        ('archivo:pendiente_piloto_1p5m', 'Pendiente, piloto (1.5 m)', False, ''),
        ('archivo:pendiente_hidalgo_15m', 'Pendiente, Hidalgo (15 m)', False, ''),
        ('archivo:relieve_piloto_1p5m', 'Altitud, piloto (1.5 m)', False, ''),
        ('archivo:cem4_15m', 'Altitud, Hidalgo (CEM 4.0, 15 m)', False, ''),
        ('archivo:ajuste_cem_piloto_15m', 'Ajuste del CEM hacia las hojas, piloto (m)', False, ''),
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
    elif capa == 'terreno.calles':
        from qgis.core import QgsRuleBasedRenderer
        raiz = QgsRuleBasedRenderer.Rule(None)
        for etiqueta, expr, color in (
                ('por revisar: puente, paso a desnivel o escalón en el relieve',
                 'coalesce("puente", false) OR coalesce("perfil_irregular", false)', '#9e9e9e'),
                ('menos de 5 %', '"pend_max_pct" < 5', '#1a9641'),
                ('5 a 10 %', '"pend_max_pct" >= 5 AND "pend_max_pct" < 10', '#a6d96a'),
                ('10 a 15 %', '"pend_max_pct" >= 10 AND "pend_max_pct" < 15', '#fdae61'),
                ('15 a 25 %', '"pend_max_pct" >= 15 AND "pend_max_pct" < 25', '#d7191c'),
                ('25 % o más', '"pend_max_pct" >= 25', '#7b3294')):
            if not etiqueta.startswith('por revisar'):
                expr = f'NOT coalesce("puente", false) AND NOT coalesce("perfil_irregular", false) AND {expr}'
            s = QgsLineSymbol.createSimple({'color': color, 'width': '0.55', 'capstyle': 'round'})
            raiz.appendChild(QgsRuleBasedRenderer.Rule(s, 0, 0, expr, etiqueta))
        lyr.setRenderer(QgsRuleBasedRenderer(raiz))
        lyr.setScaleBasedVisibility(True)
        lyr.setMinimumScale(150_000)
    elif capa == 'base.mg_manzanas':
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple(
            {'color': '242,232,213,150', 'outline_color': '#b9a88a', 'outline_width': '0.12'}))
        lyr.setScaleBasedVisibility(True)
        lyr.setMinimumScale(40_000)
    elif capa == 'base.mg_servicios_a':
        from qgis.core import QgsRuleBasedRenderer
        raiz = QgsRuleBasedRenderer.Rule(None)
        for etiqueta, expr, color in (
                ('parques y jardines', 'lower("geografico") LIKE \'%parque%\' OR lower("geografico") LIKE \'%jard%\'', '127,178,90,200'),
                ('deportivos', 'lower("geografico") LIKE \'%deport%\' OR lower("geografico") LIKE \'%cancha%\'', '166,206,120,200'),
                ('otros espacios (escuelas, panteones, mercados…)', 'ELSE', '205,196,184,180')):
            s = QgsFillSymbol.createSimple({'color': color, 'outline_color': '#8c8c8c', 'outline_width': '0.1'})
            raiz.appendChild(QgsRuleBasedRenderer.Rule(s, 0, 0, '' if expr == 'ELSE' else expr, etiqueta,
                                                       '', expr == 'ELSE'))
        lyr.setRenderer(QgsRuleBasedRenderer(raiz))
        lyr.setScaleBasedVisibility(True)
        lyr.setMinimumScale(40_000)
    elif capa == 'base.inegi50_carreteras':
        lyr.renderer().setSymbol(QgsLineSymbol.createSimple({'color': '#c0392b', 'width': '0.5'}))
    elif capa == 'base.inegi50_caminos':
        lyr.renderer().setSymbol(QgsLineSymbol.createSimple({'color': '#8d6e63', 'width': '0.3', 'line_style': 'dash'}))
    elif capa == 'base.osm_lineas_piloto':
        lyr.renderer().setSymbol(QgsLineSymbol.createSimple({'color': '#607d8b', 'width': '0.2'}))
    elif capa == 'terreno.cauces':
        from qgis.core import QgsRuleBasedRenderer
        raiz = QgsRuleBasedRenderer.Rule(None)
        for etiqueta, expr, ancho, estilo in (
                ('río principal (100 km² o más)', '"clase" = \'río principal\'', '1.1', 'solid'),
                ('río (10 a 100 km²)', '"clase" = \'río\'', '0.75', 'solid'),
                ('arroyo (1 a 10 km²)', '"clase" = \'arroyo\'', '0.45', 'solid'),
                ('escurrimiento (0.1 a 1 km²)', '"clase" = \'escurrimiento\'', '0.2', 'solid')):
            for urbano in (False, True):
                s = QgsLineSymbol.createSimple({'color': '#6baed6' if urbano else '#1f78b4', 'width': ancho,
                                                'line_style': 'dot' if urbano else estilo, 'capstyle': 'round'})
                raiz.appendChild(QgsRuleBasedRenderer.Rule(
                    s, 0, 0, f'{expr} AND {"" if urbano else "NOT "}coalesce("urbano", false)',
                    etiqueta + (' en zona urbana (puede ir entubado)' if urbano else '')))
        lyr.setRenderer(QgsRuleBasedRenderer(raiz))
    elif capa == 'base.inegi50_corrientes':
        from qgis.core import QgsRuleBasedRenderer
        raiz = QgsRuleBasedRenderer.Rule(None)
        for etiqueta, expr, estilo in (('perenne', 'lower("condicion") LIKE \'perenne%\'', 'solid'),
                                       ('intermitente', 'ELSE', 'dash')):
            s = QgsLineSymbol.createSimple({'color': '#08306b', 'width': '0.35', 'line_style': estilo})
            raiz.appendChild(QgsRuleBasedRenderer.Rule(s, 0, 0, '' if expr == 'ELSE' else expr, etiqueta, '',
                                                       expr == 'ELSE'))
        lyr.setRenderer(QgsRuleBasedRenderer(raiz))
    elif capa == 'terreno.cuerpos_agua':
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple(
            {'color': '76,134,168,220', 'outline_color': '#2c5d7c', 'outline_width': '0.25'}))
        agua_3d(lyr)
    elif capa == 'terreno.subcuencas':
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple(
            {'style': 'no', 'outline_color': '#6a3d9a', 'outline_width': '0.4', 'outline_style': 'dash'}))
    elif capa == 'terreno.zonas':
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple(
            {'style': 'no', 'outline_color': '#d7191c', 'outline_width': '0.6', 'outline_style': 'dash'}))
    elif capa == 'terreno.cobertura':
        colores = {'1.5 m': '#1a9850', '5 m': '#fee08b', '15 m (solo CEM)': '#d73027'}
        cats = [QgsRendererCategory(r, QgsFillSymbol.createSimple(
                    {'color': f'{QColor(c).red()},{QColor(c).green()},{QColor(c).blue()},110', 'outline_style': 'no'}), r)
                for r, c in colores.items()]
        lyr.setRenderer(QgsCategorizedSymbolRenderer('resolucion', cats))
    elif capa == 'terreno.hojas':
        from qgis.core import QgsRuleBasedRenderer
        sym = QgsFillSymbol.createSimple({'style': 'no', 'outline_color': '#2b83ba', 'outline_width': '0.3'})
        raiz = QgsRuleBasedRenderer.Rule(None)
        for etiqueta, expr, color in (('ok', '"revision" = \'ok\'', '#1a9850'),
                                      ('revisar', '"revision" LIKE \'revisar%\'', '#d73027'),
                                      ('sin revisar', '"revision" IS NULL', '#2b83ba')):
            s = sym.clone()
            s.symbolLayer(0).setStrokeColor(QColor(color))
            raiz.appendChild(QgsRuleBasedRenderer.Rule(s, 0, 0, expr, etiqueta))
        lyr.setRenderer(QgsRuleBasedRenderer(raiz))
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


TERRENO = RAIZ / 'datos' / 'terreno'

# Tintas hipsométricas: de las tierras bajas de la Huasteca (verde) a las cumbres (blanco), en fracciones del rango.
HIPSOMETRIA = [(0.00, '#3e7b4f'), (0.15, '#7da55b'), (0.32, '#c8c27c'), (0.50, '#c49a63'), (0.68, '#9a7353'),
               (0.85, '#d9cfc4'), (1.00, '#ffffff')]


def agua_3d(lyr) -> None:
    """En las vistas 3D, cada cuerpo de agua como superficie plana a su nivel (nivel_m + 0.3 m), no pegada al relieve."""
    try:
        import qgis._3d as q3
        import qgis.core as qc
        from qgis.core import Qgis, QgsProperty
        # según la versión, cada clase vive en qgis._3d o en qgis.core
        clase = lambda n: getattr(q3, n, None) or getattr(qc, n)
        QgsAbstract3DSymbol, QgsPhongMaterialSettings = clase('QgsAbstract3DSymbol'), clase('QgsPhongMaterialSettings')
        QgsPolygon3DSymbol, QgsVectorLayer3DRenderer = clase('QgsPolygon3DSymbol'), clase('QgsVectorLayer3DRenderer')
        sim = QgsPolygon3DSymbol()
        sim.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
        mat = QgsPhongMaterialSettings()
        mat.setDiffuse(QColor('#3f7fa6'))
        mat.setAmbient(QColor('#1d4f6e'))
        mat.setSpecular(QColor('#ffffff'))
        mat.setShininess(80)
        sim.setMaterialSettings(mat)
        prop = getattr(QgsAbstract3DSymbol, 'Property', None)
        clave = prop.Height if prop is not None and hasattr(prop, 'Height') else QgsAbstract3DSymbol.PropertyHeight
        sim.dataDefinedProperties().setProperty(clave, QgsProperty.fromExpression('coalesce("nivel_m", 0) + 0.3'))
        lyr.setRenderer3D(QgsVectorLayer3DRenderer(sim))
    except Exception as e:   # sin 3D en esta instalación: queda solo pintada sobre el relieve
        log(f'  (sin agua plana en 3D: {e})')


def capa_raster(nombre_archivo: str, nombre: str):
    """Capa de un GeoTIFF de datos/terreno con su estilo, o None si todavía no existe."""
    from osgeo import gdal
    from qgis.core import (QgsColorRampShader, QgsRasterLayer, QgsRasterShader, QgsSingleBandPseudoColorRenderer)
    from qgis.PyQt.QtGui import QPainter
    ruta = TERRENO / f'{nombre_archivo}.tif'
    if not ruta.exists():
        return None
    lyr = QgsRasterLayer(str(ruta), nombre)
    if not lyr.isValid():
        raise RuntimeError(f'No se pudo abrir {ruta}')

    def rampa(vmin, vmax, paradas):
        sh = QgsColorRampShader(vmin, vmax)
        sh.setColorRampType(QgsColorRampShader.Interpolated)
        sh.setColorRampItemList([QgsColorRampShader.ColorRampItem(vmin + f * (vmax - vmin), QColor(c), f'{vmin + f * (vmax - vmin):,.0f}')
                                 for f, c in paradas])
        rs = QgsRasterShader()
        rs.setRasterShaderFunction(sh)
        r = QgsSingleBandPseudoColorRenderer(lyr.dataProvider(), 1, rs)
        r.setClassificationMin(vmin)
        r.setClassificationMax(vmax)
        lyr.setRenderer(r)

    if nombre_archivo.startswith('sombreado'):
        lyr.setBlendMode(QPainter.CompositionMode_Multiply)
        lyr.setOpacity(0.75)
        # para que no se sumen los dos sombreados: el fino al acercarse más de 1:50 000, el del estado al alejarse
        lyr.setScaleBasedVisibility(True)
        if '1p5m' in nombre_archivo:
            lyr.setMinimumScale(50_000)
        else:
            lyr.setMaximumScale(50_000)
    elif nombre_archivo.startswith('pendiente'):
        rampa(0, 45, [(0, '#ffffcc'), (0.33, '#fd8d3c'), (0.66, '#e31a1c'), (1, '#4a1486')])
    elif nombre_archivo.startswith('ajuste'):
        rampa(-12, 4, [(0, '#2166ac'), (0.5, '#92c5de'), (0.75, '#f7f7f7'), (1, '#b2182b')])
    else:   # altitud
        ds = gdal.Open(str(ruta))   # el dataset debe vivir mientras se usa su banda
        vmin, vmax = ds.GetRasterBand(1).ComputeRasterMinMax(True)
        ds = None
        rampa(vmin, vmax, HIPSOMETRIA)
        try:   # que el perfil de elevación y el 3D la reconozcan como superficie de terreno
            from qgis.core import Qgis
            ep = lyr.elevationProperties()
            ep.setEnabled(True)
            ep.setMode(Qgis.RasterElevationMode.RepresentsElevationSurface)
        except Exception:
            pass
    return lyr


def marcadores(proj, con, crs, caja_estado) -> None:
    """Marcadores espaciales del proyecto (panel Marcadores espaciales, o Ver → Mostrar marcadores): un clic y el
    mapa va ahí. Las cabeceras se centran en su localidad del ITER con 4 km de lado."""
    from qgis.core import QgsBookmark
    bm = proj.bookmarkManager()
    bm.clear()

    def poner(nombre, x0, y0, x1, y1):
        b = QgsBookmark()
        b.setName(nombre)
        b.setGroup('Relieve de Hidalgo')
        b.setExtent(QgsReferencedRectangle(QgsRectangle(x0, y0, x1, y1), crs))
        bm.addBookmark(b)

    poner('1. Todo Hidalgo', *caja_estado)
    z = consulta(con, """select ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b)
                         from (select ST_Envelope(geom) b from terreno.zonas where zona = 'piloto') x""")
    if z:
        poner('2. Zona piloto (relieve de 1.5 m)', *z[0])
    for i, (nombre, x, y) in enumerate(consulta(con, """
            select nombre, ST_X(geom), ST_Y(geom) from qgis.localidades
            where cvegeo in ('130480001', '130390001', '130380001', '130510001')
            order by array_position(array['130480001', '130390001', '130380001', '130510001'], cvegeo::text)"""), 3):
        poner(f'{i}. {nombre}', x - 2000, y - 2000, x + 2000, y + 2000)


def ficha(lyr, m: dict) -> None:
    md = lyr.metadata()
    partes = [m.get('notas') or '',
              f"Fuente: {m['fuentes']}" if m.get('fuentes') else '',
              f"Fecha de los datos: {m['fecha_datos']}" if m.get('fecha_datos') else '',
              f"Escala o resolución de origen: {m['escala']}" if m.get('escala') else '',
              f"Detalle (tamaño más chico que distingue): ≈ {m['detalle_m']:g} m" if m.get('detalle_m') else '',
              (f"Archivo: {m['capa'].split(':', 1)[1]} · EPSG:6369" if m['capa'].startswith('archivo:')
               else f"Tabla: {m['capa']} · {m['filas'] or 0:,} elementos · EPSG:{m['srid']}")]
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
        where i.indisprimary and n.nspname in ('base', 'qgis', 'terreno')
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
        n, terreno_3d = 0, None
        for grupo, capas in CAPAS:
            nodo_grupo = raiz.addGroup(grupo)
            for capa, nombre, visible, filtro in capas:
                if capa.startswith('archivo:'):
                    archivo = capa.split(':', 1)[1]
                    lyr = capa_raster(archivo, nombre)
                    if lyr is None:
                        log(f'  falta datos/terreno/{archivo}.tif: se omite (corre la fase 1)')
                        continue
                    m = meta.get(f'archivo:datos/terreno/{archivo}.tif')
                    if archivo == 'relieve_piloto_1p5m' or (archivo == 'cem4_15m' and terreno_3d is None):
                        terreno_3d = lyr
                else:
                    if capa not in meta:
                        log(f'  falta la tabla {capa}: se omite')
                        continue
                    m = meta[capa]
                    lyr = capa_pg(capa, nombre or m['titulo'] or capa, claves[capa], m['geometria'], filtro)
                    estilo(lyr, capa, grupos_suelo)
                if m:
                    ficha(lyr, m)
                proj.addMapLayer(lyr, False)
                nodo = nodo_grupo.addLayer(lyr)
                nodo.setItemVisibilityChecked(visible)
                nodo.setExpanded(False)
                n += 1
            nodo_grupo.setExpanded(grupo in ('Límites', 'Agua', 'Relieve'))
        if terreno_3d is not None:
            # Terreno del proyecto: lo usan el perfil de elevación y las vistas 3D nuevas
            from qgis.core import QgsRasterDemTerrainProvider
            prov = QgsRasterDemTerrainProvider()
            prov.setLayer(terreno_3d)
            proj.elevationProperties().setTerrainProvider(prov)
            log(f'  terreno 3D del proyecto: {terreno_3d.name()}')
        proj.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(QgsRectangle(xmin, ymin, xmax, ymax), crs))
        marcadores(proj, con, crs, (xmin, ymin, xmax, ymax))
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
