"""Acceso a INEGI: catálogo de productos (API interna_v2), zips remotos leídos por rangos y descargas en paralelo.

INEGI entrega ≈ 1.4 MB/s por conexión y acepta peticiones por rangos; con 8 conexiones llega a ≈ 3.7 MB/s.
"""
from __future__ import annotations

import io
import json
import threading
import time
import urllib.request
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from comun import RAIZ, log

UA = {'User-Agent': 'relieve-qgis/0.1'}
API = 'https://www.inegi.org.mx/app/api/productos/interna_v2'
SITIO = 'https://www.inegi.org.mx'
MB = 1024 * 1024


def _pedir(url: str, rango: tuple[int, int] | None = None, intentos: int = 6, datos: bytes | None = None,
           tipo: str | None = None, tiempo: int = 180) -> bytes:
    """GET (o POST con datos) con reintentos y espera creciente."""
    for k in range(1, intentos + 1):
        try:
            h = dict(UA)
            if rango:
                h['Range'] = f'bytes={rango[0]}-{rango[1]}'
            if tipo:
                h['Content-Type'] = tipo
            req = urllib.request.Request(url, headers=h, data=datos)
            with urllib.request.urlopen(req, timeout=tiempo) as r:
                cuerpo = r.read()
            if rango and len(cuerpo) != rango[1] - rango[0] + 1:
                raise IOError(f'rango incompleto: {len(cuerpo)} de {rango[1] - rango[0] + 1} bytes')
            return cuerpo
        except Exception as e:
            if k == intentos:
                raise
            espera = 5 * k
            log(f'  reintento {k} en {espera} s ({e})')
            time.sleep(espera)
    raise RuntimeError('inalcanzable')


def tamano_remoto(url: str) -> int:
    req = urllib.request.Request(url, headers={**UA, 'Range': 'bytes=0-0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers['Content-Range'].split('/')[1])


class ZipRemoto(io.RawIOBase):
    """Archivo remoto de solo lectura con peticiones por rangos: zipfile lee su directorio sin bajar el zip."""

    def __init__(self, url: str):
        self.url, self.pos, self.size = url, 0, tamano_remoto(url)

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b''
        fin = min(self.size, self.pos + n) - 1
        datos = _pedir(self.url, (self.pos, fin))
        self.pos += len(datos)
        return datos

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def miembro_zip(url: str, nombre: str) -> tuple[int, int, int, int, int]:
    """(inicio de los datos, tamaño comprimido, tamaño, crc32, método) de un archivo dentro de un zip remoto."""
    f = ZipRemoto(url)
    info = zipfile.ZipFile(f).getinfo(nombre)
    f.seek(info.header_offset)
    cab = f.read(30)
    if cab[:4] != b'PK\x03\x04':
        raise IOError('encabezado local del zip inesperado')
    largo_nombre = int.from_bytes(cab[26:28], 'little')
    largo_extra = int.from_bytes(cab[28:30], 'little')
    inicio = info.header_offset + 30 + largo_nombre + largo_extra
    return inicio, info.compress_size, info.file_size, info.CRC, info.compress_type


def leer_miembro_chico(url: str, nombre: str) -> bytes:
    return zipfile.ZipFile(ZipRemoto(url)).read(nombre)


def descargar_rangos(url: str, destino: Path, inicio: int = 0, largo: int | None = None,
                     hilos: int = 8, trozo: int = 32 * MB) -> Path:
    """Baja [inicio, inicio + largo) de url a destino con varias conexiones. Se puede interrumpir y retomar:
    destino.partes.json lleva la cuenta de los trozos completos."""
    if largo is None:
        largo = tamano_remoto(url) - inicio
    if destino.exists() and destino.stat().st_size == largo and not destino.with_name(destino.name + '.partes.json').exists():
        log(f'ya está {destino.relative_to(RAIZ).as_posix()}')
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + '.part')
    control = destino.with_name(destino.name + '.partes.json')
    hechos: set[int] = set(json.loads(control.read_text())) if control.exists() and parcial.exists() else set()
    if not parcial.exists():
        with open(parcial, 'wb') as f:
            f.truncate(largo)
    trozos = [(i, i * trozo, min(largo, (i + 1) * trozo) - 1) for i in range((largo + trozo - 1) // trozo)]
    pendientes = [t for t in trozos if t[0] not in hechos]
    candado = threading.Lock()
    t0, bajado = time.time(), 0
    log(f'{destino.name}: {largo / 1e9:.2f} GB en {len(trozos)} trozos ({len(pendientes)} pendientes, {hilos} conexiones)')

    def uno(t):
        i, a, b = t
        datos = _pedir(url, (inicio + a, inicio + b))
        with candado:
            with open(parcial, 'r+b') as f:
                f.seek(a)
                f.write(datos)
            hechos.add(i)
            control.write_text(json.dumps(sorted(hechos)))
        return len(datos)

    with ThreadPoolExecutor(hilos) as ex:
        futuros = [ex.submit(uno, t) for t in pendientes]
        for k, fu in enumerate(as_completed(futuros), 1):
            bajado += fu.result()
            if k % 10 == 0 or k == len(futuros):
                v = bajado / MB / max(1e-6, time.time() - t0)
                resta = (sum(b - a + 1 for i, a, b in trozos if i not in hechos)) / MB / max(v, 1e-6)
                log(f'  {len(hechos)}/{len(trozos)} trozos · {v:.1f} MB/s · faltan ≈ {resta / 60:.0f} min')
    control.unlink()
    parcial.replace(destino)
    return destino


def inflar(origen: Path, destino: Path, tamano: int, crc: int) -> Path:
    """Descomprime un miembro deflate (crudo, sin encabezado) y comprueba su tamaño y CRC32 contra el zip."""
    if destino.exists() and destino.stat().st_size == tamano:
        log(f'ya está {destino.relative_to(RAIZ).as_posix()}')
        return destino
    d = zlib.decompressobj(-15)
    c, n, t0 = 0, 0, time.time()
    tmp = destino.with_name(destino.name + '.part')
    with open(origen, 'rb') as fi, open(tmp, 'wb') as fo:
        while True:
            bloque = fi.read(16 * MB)
            if not bloque:
                break
            salida = d.decompress(bloque)
            fo.write(salida)
            c = zlib.crc32(salida, c)
            n += len(salida)
        resto = d.flush()
        fo.write(resto)
        c = zlib.crc32(resto, c)
        n += len(resto)
    if n != tamano or c != crc:
        raise IOError(f'{destino.name}: {n} bytes y CRC {c:08x}; el zip dice {tamano} y {crc:08x}')
    tmp.replace(destino)
    log(f'{destino.name}: {n / 1e9:.2f} GB, CRC32 {c:08x} correcto ({time.time() - t0:.0f} s)')
    return destino


def catalogo(busqueda: str, entidad: str = '13', paginas: int = 80) -> list[dict]:
    """Productos del catálogo de INEGI que devuelve una búsqueda por palabras (con su ficha mínima y sus formatos)."""
    cuerpo = {'enti': entidad, 'muni': '', 'loca': '', 'titg': '', 'esca': '', 'form': '', 'edic': '', 'seri': '',
              'prog': '', 'clave': '', 'rango': '', 'tipoB': 2, 'adv': False, 'wordag': '', 'mkeys': '', 'mageo': '',
              'formIncl': '', 'formExcl': '', 'orden': 4, 'desc': True, 'tema': '', 'busc': busqueda, 'tam': 100}
    todos = []
    for pag in range(paginas):
        r = json.loads(_pedir(f'{API}/componente/mapas/lista/resultados/', datos=json.dumps({**cuerpo, 'pag': pag}).encode(),
                              tipo='application/json'))
        lista = json.loads(r['list']) if isinstance(r.get('list'), str) else r.get('list') or {}
        mapas = lista.get('mapas') or []
        for m in mapas:
            todos.append({'upc': m.get('key'), 'titulo': m.get('titulo') or '', 'clave': (m.get('clave_carta') or '').upper(),
                          'edicion': int(m.get('edicion') or 0),
                          'formatos': {f['extension']: {'mb': f.get('peso'), 'url': SITIO + f['url']['valor']}
                                       for f in m.get('formatos') or [] if f.get('url', {}).get('valor')}})
        if len(mapas) < cuerpo['tam']:
            break
    return todos
