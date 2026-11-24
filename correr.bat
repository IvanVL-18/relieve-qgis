@echo off
rem Corre un script con el Python de QGIS, que ya trae GDAL, PROJ, psycopg y PyQGIS configurados.
rem Uso:  correr scripts\fase0.py
rem Si QGIS vive en otra carpeta, define QGIS_DIR antes de llamarlo.
setlocal
if "%QGIS_DIR%"=="" set "QGIS_DIR=C:\Program Files\QGIS 3.44.15"
if not exist "%QGIS_DIR%\bin\python-qgis-ltr.bat" (
  echo No encuentro QGIS en "%QGIS_DIR%". Define QGIS_DIR con la carpeta de QGIS.
  exit /b 1
)
call "%QGIS_DIR%\bin\python-qgis-ltr.bat" %*
