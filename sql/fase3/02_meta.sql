-- Fase 3 · 2: edificios y árboles en el catálogo de capas.

insert into meta.capas (capa, titulo, tema, fuentes, fecha_datos, escala, detalle_m, notas) values
  ('base.ms_edificios_piloto', 'Contornos de edificios de Microsoft (piloto)', 'edificios',
   'Microsoft Global ML Building Footprints (versión 2026-02-03, ODbL)', 'imágenes de 2014–2024 (según la zona)', 'contorno detectado en imagen', null,
   'Detectados con aprendizaje automático: pueden faltar edificios nuevos, sobrar demolidos o estar corridos 1–3 m'),
  ('terreno.edificios', 'Edificios por pisos (altura medida)', 'edificios',
   'Contornos de Microsoft; altura = superficie − terreno de INEGI (1.5 m, ediciones 2025–2026)', '2016–2024 (imágenes de INEGI)', '1.5 m', 1.5,
   'altura_m = mediana de los píxeles de más de 2 m dentro del contorno (el techo); pisos = altura / 3 m; confianza alta / media / sin medida. En 3D se extruyen a esa altura (3 m si no la tienen)'),
  ('terreno.arboles', 'Árboles (copa a escala)', 'vegetación', 'Superficie − terreno de INEGI (1.5 m), fuera de los edificios', '2016–2024', '1.5 m', 1.5,
   'Cima = máximo local de 3 m o más con ventana de 3 a 9 píxeles según la altura; copa por cuencas (watershed). tipo separa los árboles de techos planos sin contorno (posible construcción) y picos del modelo. Bajo bosque denso vemos ≈ la mitad del dosel que Meta: conteo y alturas ahí son un mínimo; en ciudad y campo vemos más que Meta (árboles chicos que Meta no ve, o techos que se colaron). Arbustos de menos de 3 m no cuentan'),
  ('archivo:datos/terreno/altura_suelo_piloto_1p5m.tif', 'Altura sobre el suelo, piloto (1.5 m)', 'edificios',
   'Superficie − terreno de INEGI (1.5 m)', '2016–2024', '1.5 m', 1.5, 'Edificios, árboles, bardas, puentes…; LERC con error ≤ 5 cm; sin dato fuera de las hojas de 1.5 m'),
  ('archivo:datos/terreno/dosel_piloto_1p5m.tif', 'Altura de la vegetación, piloto (1.5 m)', 'vegetación',
   'Altura sobre el suelo de 2 m o más, fuera de los edificios (con 3 m de margen)', '2016–2024', '1.5 m', 1.5,
   'Comparada con el dosel de Meta y WRI en terreno.control_dosel')
on conflict (capa) do update set
  titulo = excluded.titulo, tema = excluded.tema, fuentes = excluded.fuentes, fecha_datos = excluded.fecha_datos,
  escala = excluded.escala, detalle_m = excluded.detalle_m, notas = excluded.notas;

select meta.actualizar_capas();
