-- Fase 1 · 2: el relieve en el catálogo de capas (rásters como «archivo:ruta» y las tablas de terreno).

insert into meta.capas (capa, titulo, tema, fuentes, fecha_datos, escala, detalle_m, notas) values
  ('archivo:datos/terreno/cem4_15m.tif', 'Altitud, Hidalgo (CEM 4.0, 15 m)', 'relieve',
   'INEGI, Continuo de Elevaciones Mexicano 4.0 (UPC 794551151600)', 'edición 2025 (datos a 2024)', '15 m', 15,
   'Altitud en metros enteros sobre el Geoide Gravimétrico Mexicano 2010. INEGI lo armó con su modelo de 12.5 m (radar ALOS PALSAR) y sus datos de 5 m (LiDAR o fotogrametría), quitando valores atípicos. OJO: en el piloto queda ≈ 3.8 m por encima del terreno de las hojas de 1.5 m en terreno abierto y de 6 a 10 m bajo bosque (el radar ve en parte copas y techos): úsese como relieve de referencia, no para alturas absolutas finas. Reproyectado (bilineal) a EPSG:6369; el estado más 25 km alrededor'),
  ('archivo:datos/terreno/relieve_piloto_1p5m.tif', 'Altitud, piloto (1.5 m)', 'relieve',
   'INEGI, modelos digitales de elevación tipo terreno de 1.5 m (hojas 1:10 000, ediciones 2025–2026); CEM 4.0 donde no hay hoja',
   '2016–2024 (imágenes de las hojas)', '1.5 m (15 m donde solo hay CEM; ver terreno.cobertura)', 1.5,
   'Fotogrametría de imágenes de satélite en estéreo: bajo bosque denso el terreno es una estimación y se ve en triángulos (INEGI lo interpoló de pocos puntos del suelo), así que ahí el detalle real es menor que 1.5 m. Alturas ortométricas sobre el Geoide Gravimétrico Mexicano 2010; los metadatos de INEGI dejan vacía la sección de exactitud (ver terreno.hojas para el control propio). Hojas vecinas difieren ≈ 1 m donde se enciman: se mezclan con pesos que crecen 60 m desde la orilla de cada una (la de 1.5 m pesa 4 veces más que la de 5 m). Donde no hay hoja: CEM 4.0 (interpolación cúbica) más un ajuste local hacia el terreno de las hojas (ajuste_cem_piloto_15m.tif), con transición lineal de 150 m; ahí el detalle real es de 15 m'),
  ('archivo:datos/terreno/ajuste_cem_piloto_15m.tif', 'Ajuste del CEM, piloto (15 m)', 'relieve',
   'Hojas de 1.5 m de INEGI y CEM 4.0', '2016–2024', '15 m', 15,
   'Lo que se le suma al CEM para empatarlo con el terreno de las hojas: (hoja − CEM) suavizada a 300 m y extendida a 900 m y 2.7 km hacia donde no hay hoja. Negativo = el CEM estaba arriba'),
  ('archivo:datos/terreno/superficie_piloto_1p5m.tif', 'Superficie, piloto (1.5 m)', 'relieve',
   'INEGI, modelos digitales de elevación tipo superficie de 1.5 m (hojas 1:10 000, ediciones 2025–2026)',
   '2016–2024 (imágenes de las hojas)', '1.5 m', 1.5,
   'Incluye edificios y árboles: superficie − terreno = altura sobre el suelo (fase 3). Solo donde hay hoja; costuras mezcladas igual que el terreno'),
  ('archivo:datos/terreno/sombreado_hidalgo_15m.tif', 'Sombreado, Hidalgo (15 m)', 'relieve', 'CEM 4.0', 'edición 2025', '15 m', 15,
   'Sombreado multidireccional (gdaldem)'),
  ('archivo:datos/terreno/pendiente_hidalgo_15m.tif', 'Pendiente, Hidalgo (15 m)', 'relieve', 'CEM 4.0', 'edición 2025', '15 m', 15,
   'Grados. A 15 m la pendiente de laderas cortas sale más suave que la real'),
  ('archivo:datos/terreno/sombreado_piloto_1p5m.tif', 'Sombreado, piloto (1.5 m)', 'relieve', 'Altitud del piloto (1.5 m)',
   '2016–2024', '1.5 m', 1.5, 'Sombreado multidireccional (gdaldem)'),
  ('archivo:datos/terreno/pendiente_piloto_1p5m.tif', 'Pendiente, piloto (1.5 m)', 'relieve', 'Altitud del piloto (1.5 m)',
   '2016–2024', '1.5 m', 1.5, 'Grados. Donde solo hay CEM el detalle real es de 15 m'),
  ('terreno.zonas', 'Zonas de trabajo', 'relieve', 'INEGI Marco Geoestadístico', 'dic. 2025', null, null,
   'Municipios con 500 m de margen'),
  ('terreno.hojas', 'Hojas de INEGI (control de calidad)', 'relieve', 'Catálogo de productos de INEGI', '2015–2026', '1:10 000', null,
   'Recuadro de cada hoja con su resolución, edición y control de calidad: diferencia con el CEM en todo y en terreno abierto (superficie − terreno < 1 m), desfase respecto a las demás hojas de la zona y costuras con sus vecinas. revisar = desfase > 1.5 m, costura en terreno abierto > 0.5 m o más de 5 % sin dato'),
  ('terreno.cobertura', 'Qué tan fino es el relieve', 'relieve', 'Catálogo de productos de INEGI', '2015–2026', null, null,
   '1.5 m, 5 m o solo CEM de 15 m en cada parte del estado')
on conflict (capa) do update set
  titulo = excluded.titulo, tema = excluded.tema, fuentes = excluded.fuentes, fecha_datos = excluded.fecha_datos,
  escala = excluded.escala, detalle_m = excluded.detalle_m, notas = excluded.notas;

select meta.actualizar_capas();
