"""Renderiza una vista 3D del proyecto de QGIS a PNG sin abrir QGIS, para revisar el relieve.

  correr scripts\\vista_3d.py NOMBRE X Y DISTANCIA [INCLINACION] [RUMBO] [EXAGERACION] [--terreno=ARCHIVO]
      X, Y: punto que se mira (EPSG:6369); DISTANCIA de la cámara en m; INCLINACION en grados (0 = cenital,
      por omisión 60); RUMBO en grados (por omisión 0); EXAGERACION vertical (por omisión 1);
      --terreno=cem4_15m usa otro relieve de datos/terreno (por omisión, el del proyecto)
  → datos/vistas/NOMBRE.png

PyQGIS no expone el motor 3D fuera de pantalla, así que se usa un mapa 3D de composición de impresión (el mismo
motor). El terreno es el del proyecto (Propiedades del proyecto → Elevación) y la textura, las capas visibles.
"""
from __future__ import annotations

import os
import sys

from comun import DATOS, RAIZ, log

from qgis.core import (QgsApplication, QgsLayoutExporter, QgsLayoutSize, QgsPrintLayout, QgsProject, QgsRectangle,
                       QgsUnitTypes, QgsVector3D)
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtGui import QColor

PROYECTO = RAIZ / 'qgis' / 'RelieveHidalgo.qgz'


def main() -> int:
    otro_terreno = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--terreno=')), None)
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 4:
        print(__doc__)
        return 1
    nombre = args[0]
    x, y, dist = map(float, args[1:4])
    inclinacion = float(args[4]) if len(args) > 4 else 60
    rumbo = float(args[5]) if len(args) > 5 else 0
    exageracion = float(args[6]) if len(args) > 6 else 1
    qgs = QgsApplication([], True)    # con interfaz gráfica: el motor 3D necesita OpenGL
    qgs.initQgis()
    try:
        import qgis._3d as q3
        from qgis._3d import Qgs3DMapSettings, QgsCameraPose, QgsDemTerrainSettings, QgsLayoutItem3DMap
        # Sin esto, al leer el proyecto las capas pierden su representación 3D (edificios extruidos, árboles, agua):
        # la aplicación de QGIS la registra al arrancar, un script suelto no.
        if hasattr(q3, 'Qgs3D'):
            q3.Qgs3D.initialize()
        proj = QgsProject.instance()
        if not proj.read(str(PROYECTO)):
            raise RuntimeError(f'No se pudo abrir {PROYECTO}')
        prov = proj.elevationProperties().terrainProvider()
        dem = prov.layer() if prov is not None and hasattr(prov, 'layer') else None
        if otro_terreno:
            dem = next((l for l in proj.mapLayers().values() if otro_terreno in l.source()), None)
            if dem is None:
                raise RuntimeError(f'No hay una capa de {otro_terreno} en el proyecto')
            from qgis.core import QgsRasterDemTerrainProvider
            prov = QgsRasterDemTerrainProvider()
            prov.setLayer(dem)
        if dem is None:
            raise RuntimeError('El proyecto no tiene terreno: corre la fase 1 y proyecto_qgis.py --forzar')
        altura = prov.heightAt(x, y)
        altura = 0.0 if altura != altura else altura   # NaN fuera del relieve

        s = Qgs3DMapSettings()
        s.setCrs(proj.crs())
        s.setTransformContext(proj.transformContext())
        s.setPathResolver(proj.pathResolver())
        s.setMapThemeCollection(proj.mapThemeCollection())
        s.setOrigin(QgsVector3D(x, y, 0))
        lado = max(dist * 3, 3000)
        s.setExtent(QgsRectangle(x - lado, y - lado, x + lado, y + lado))
        s.setLayers([n.layer() for n in proj.layerTreeRoot().findLayers() if n.isVisible()])
        t = QgsDemTerrainSettings()
        t.setLayer(dem)
        t.setResolution(32)
        t.setSkirtHeight(60)   # «faldas» de las teselas: tapan las rendijas entre niveles de detalle en laderas fuertes
        t.setVerticalScale(exageracion)
        t.setMapTileResolution(1024)
        t.setMaximumScreenError(2)
        t.setMaximumGroundError(1)
        s.setTerrainSettings(t)
        s.setBackgroundColor(QColor('#c9dcef'))
        s.setOutputDpi(96)
        try:   # luz de sol desde el sureste, para que se distingan techos y fachadas
            sol = q3.QgsDirectionalLightSettings()
            sol.setDirection(QgsVector3D(-0.5, 0.6, -0.7))
            sol.setIntensity(1.0)
            s.setLightSources([sol])
        except Exception as e:
            log(f'(sin luz direccional: {e})')

        layout = QgsPrintLayout(proj)
        layout.initializeDefaults()
        layout.pageCollection().page(0).setPageSize(QgsLayoutSize(320, 200, QgsUnitTypes.LayoutMillimeters))
        item = QgsLayoutItem3DMap(layout)
        layout.addLayoutItem(item)
        item.attemptSetSceneRect(QRectF(0, 0, 320, 200))
        item.setMapSettings(s)
        pose = QgsCameraPose()
        pose.setCenterPoint(QgsVector3D(0, 0, altura * exageracion))   # mundo 3D relativo al origen, z hacia arriba
        pose.setDistanceFromCenterPoint(dist)
        pose.setPitchAngle(inclinacion)
        pose.setHeadingAngle(rumbo)
        item.setCameraPose(pose)

        destino = DATOS / 'vistas' / f'{nombre}.png'
        destino.parent.mkdir(parents=True, exist_ok=True)
        ajustes = QgsLayoutExporter.ImageExportSettings()
        ajustes.dpi = 127   # 320 mm → ≈ 1600 px
        r = QgsLayoutExporter(layout).exportToImage(str(destino), ajustes)
        if r != QgsLayoutExporter.Success:
            raise RuntimeError(f'exportación 3D: código {r}')
        log(f'{destino} (terreno {dem.name()}, altura del punto {altura:.0f} m, exageración {exageracion})')
        # al desmontar la escena 3D, QGIS puede cerrar con un código de error aunque la imagen ya esté guardada
        sys.stdout.flush()
        os._exit(0)
    finally:
        qgs.exitQgis()


if __name__ == '__main__':
    sys.exit(main())
