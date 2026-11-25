-- Fase 2 · 5: agua y calles en el catálogo de capas.

insert into meta.capas (capa, titulo, tema, fuentes, fecha_datos, escala, detalle_m, notas) values
  ('base.mg_ejes', 'Calles (ejes de vialidad, INEGI 2025)', 'calles', 'INEGI Marco Geoestadístico 2025 (UPC 794551163061)', '2025', 'cartografía de localidades', null,
   'Todo Hidalgo: nombre, tipo y sentido de cada segmento entre cruces'),
  ('base.mg_manzanas', 'Manzanas (INEGI 2025)', 'calles', 'INEGI Marco Geoestadístico 2025', '2025', 'cartografía de localidades', null, null),
  ('base.mg_localidades', 'Localidades amanzanadas (INEGI 2025)', 'límites', 'INEGI Marco Geoestadístico 2025', '2025', null, null, 'Polígono de cada localidad urbana o rural amanzanada'),
  ('base.mg_servicios_a', 'Parques, escuelas y espacios públicos (INEGI 2025)', 'calles', 'INEGI Marco Geoestadístico 2025', '2025', null, null, 'Servicios con información adicional (áreas)'),
  ('base.mg_servicios_l', 'Servicios en línea (INEGI 2025)', 'calles', 'INEGI Marco Geoestadístico 2025', '2025', null, null, 'Corrientes, vías férreas, bordos dentro de las localidades'),
  ('base.mg_servicios_p', 'Servicios en punto (INEGI 2025)', 'calles', 'INEGI Marco Geoestadístico 2025', '2025', null, null, 'Templos, escuelas, centros de salud…'),
  ('base.inegi50_corrientes', 'Corrientes (INEGI 1:50 000)', 'agua', 'topo50', '2013–2023 (según la carta)', '1:50 000', 25, 'Condición perenne o intermitente según la carta; no siempre caen en el fondo del valle del relieve de 1.5 m'),
  ('base.inegi50_cuerpos_agua', 'Cuerpos de agua (INEGI 1:50 000)', 'agua', 'topo50', '2013–2023', '1:50 000', 25, 'Vasos de presas y bordos, pozas, lagunas y corrientes de área'),
  ('base.inegi50_obras_agua', 'Canales, presas y bordos (INEGI 1:50 000)', 'agua', 'topo50', '2013–2023', '1:50 000', 25, null),
  ('base.inegi50_caminos', 'Caminos y brechas (INEGI 1:50 000)', 'vías', 'topo50', '2013–2023', '1:50 000', 25, null),
  ('base.inegi50_carreteras', 'Carreteras (INEGI 1:50 000)', 'vías', 'topo50', '2013–2023', '1:50 000', 25, 'Número, administración, condición y pavimento'),
  ('base.osm_lineas_piloto', 'OpenStreetMap: vías y cauces (piloto)', 'calles', 'OpenStreetMap (ODbL)', 'nov. 2026', null, null, 'Todas las etiquetas en other_tags (JSON)'),
  ('base.osm_poligonos_piloto', 'OpenStreetMap: agua y parques (piloto)', 'agua', 'OpenStreetMap (ODbL)', 'nov. 2026', null, null, null),
  ('terreno.cauces', 'Cauces calculados del relieve (5 m)', 'agua', 'Relieve del piloto (1.5 m promediado a 5 m); GRASS r.watershed y r.stream.extract', '2016–2024 (relieve)', 'rejilla de 5 m', 5,
   'Desde 0.1 km² drenados. Bajo bosque el relieve es una interpolación y el trazo es menos fiable; en la ciudad el agua puede ir entubada o por las calles (urbano); cuenca_incompleta = le entra agua de fuera del recuadro (el área es un mínimo)'),
  ('terreno.subcuencas', 'Subcuencas de 2 km² o más', 'agua', 'Relieve del piloto a 5 m; GRASS r.watershed', '2016–2024', 'rejilla de 5 m', 5, 'incompleta = toca la orilla del recuadro'),
  ('terreno.cuerpos_agua', 'Cuerpos de agua con su nivel', 'agua', 'topo50, OpenStreetMap; nivel del relieve de 1.5 m', '2013–2026', '1:50 000 (INEGI) u OSM', 25, 'nivel_m = mediana de la altura en la orilla; nivel_rango_m grande = orilla dispareja o polígono corrido'),
  ('terreno.calles', 'Calles por pendiente (piloto)', 'calles', 'INEGI Marco Geoestadístico 2025; relieve de 1.5 m; OpenStreetMap (tipo y superficie)', '2025 (calles), 2016–2024 (relieve)', 'perfil cada 1.5 m', 1.5,
   'Pendiente máxima en 20 m seguidos: el ruido del relieve (decímetros) da ≈ ±2 %. No vale junto a puentes y pasos a desnivel (puente; el relieve no los tiene) ni en perfiles con un escalón corto (perfil_irregular)')
on conflict (capa) do update set
  titulo = excluded.titulo, tema = excluded.tema, fuentes = excluded.fuentes, fecha_datos = excluded.fecha_datos,
  escala = excluded.escala, detalle_m = excluded.detalle_m, notas = excluded.notas;

select meta.actualizar_capas();
