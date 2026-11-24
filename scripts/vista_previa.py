"""Renderiza el proyecto de QGIS a PNG sin abrir QGIS, para revisar capas y estilos.

  correr scripts\\vista_previa.py                       vista de todo el estado → datos/vistas/estado.png
  correr scripts\\vista_previa.py pachuca 520000 2218000 18000
        nombre, centro x, centro y y ancho en metros (EPSG:6369) → datos/vistas/pachuca.png
"""
from __future__ import annotations

import sys

from comun import DATOS, RAIZ, log

from qgis.core import QgsApplication, QgsMapRendererParallelJob, QgsMapSettings, QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

PROYECTO = RAIZ / 'qgis' / 'RelieveHidalgo.qgz'


def main() -> int:
    nombre = sys.argv[1] if len(sys.argv) > 1 else 'estado'
    qgs = QgsApplication([], False)
    qgs.initQgis()
    try:
        proj = QgsProject.instance()
        if not proj.read(str(PROYECTO)):
            raise RuntimeError(f'No se pudo abrir {PROYECTO}')
        if len(sys.argv) >= 5:
            x, y, ancho = map(float, sys.argv[2:5])
            alto = ancho * 0.75
            extension = QgsRectangle(x - ancho / 2, y - alto / 2, x + ancho / 2, y + alto / 2)
        else:
            extension = proj.viewSettings().defaultViewExtent()
        visibles = [n.layer() for n in proj.layerTreeRoot().findLayers() if n.isVisible()]
        ms = QgsMapSettings()
        ms.setLayers(visibles)
        ms.setDestinationCrs(proj.crs())
        ms.setEllipsoid(proj.ellipsoid())
        ms.setExtent(extension)
        ms.setOutputSize(QSize(1600, 1200))
        ms.setBackgroundColor(QColor('#f4f1ea'))
        job = QgsMapRendererParallelJob(ms)
        job.start()
        job.waitForFinished()
        destino = DATOS / 'vistas' / f'{nombre}.png'
        destino.parent.mkdir(parents=True, exist_ok=True)
        job.renderedImage().save(str(destino))
        errores = job.errors()
        for e in errores:
            log(f'error en {e.layerID}: {e.message}')
        log(f'{destino} ({len(visibles)} capas visibles, escala 1:{ms.scale():,.0f})')
        return 1 if errores else 0
    finally:
        qgs.exitQgis()


if __name__ == '__main__':
    sys.exit(main())
