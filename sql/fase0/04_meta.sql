-- Fase 0 · 4: catálogo de capas.
-- Regla del proyecto: ningún cálculo es más preciso que su dato más grueso. Cada capa dice de dónde viene, de cuándo
-- es y el tamaño más chico que distingue (detalle_m); un análisis reporta el mayor detalle_m de lo que usa.

create table if not exists meta.capas (
  capa        text primary key,          -- esquema.tabla
  titulo      text,
  tema        text,
  fuentes     text,                      -- claves de relieve.fuentes, separadas por coma, o la fuente escrita
  fecha_datos text,                      -- fecha o periodo de los datos (no de la descarga)
  escala      text,                      -- escala o resolución de origen, como la publica la fuente
  detalle_m   real,                      -- tamaño más chico que la capa distingue, en m (aprox.); null si no aplica
  notas       text,
  geometria   text,                      -- automático
  srid        int,                       -- automático
  filas       bigint,                    -- automático
  actualizado timestamptz                -- automático
);
comment on table meta.capas is 'Catálogo de capas: fuente, fecha, escala y detalle_m (tamaño más chico que la capa distingue, aprox., en m). Regla: un cálculo no es más preciso que el mayor detalle_m de lo que usa. geometria, srid, filas y actualizado los llena meta.actualizar_capas()';

insert into meta.capas (capa, titulo, tema, fuentes, fecha_datos, escala, detalle_m, notas) values
  -- base
  ('base.estado', 'Límite de Hidalgo', 'límites', 'INEGI Marco Geoestadístico', 'dic. 2025', null, null, 'Vértice cada ≈ 50 m en promedio'),
  ('base.municipios', 'Municipios (INEGI)', 'límites', 'INEGI Marco Geoestadístico', 'dic. 2025', null, null, 'Vértice cada ≈ 50 m en promedio; difiere ≤ 9 m de la copia de 2022 que usaba el web'),
  ('base.entidades', 'Entidades de México', 'límites', 'INEGI Marco Geoestadístico', 'dic. 2025', null, null, 'Solo referencia: lejos de Hidalgo la UTM 14N deforma'),
  ('base.municipios_edomex', 'Municipios del Estado de México', 'límites', 'INEGI Marco Geoestadístico', 'dic. 2025', null, null, 'Destinos de la movilidad'),
  ('base.acuiferos', 'Acuíferos de CONAGUA (completos)', 'agua', 'acuiferos', 'DOF 9-nov-2023', null, null, 'Sin recortar'),
  ('base.ordenamientos', 'Vedas y suspensiones (CONAGUA, sin corregir)', 'agua', 'ordenamientos_agua', 'corte 25-nov-2021', null, null, 'El web detectó un posible corrimiento de datum en algunos vértices; aquí sin corregir'),
  -- límites y población
  ('qgis.municipios', 'Municipios con indicadores', 'límites', 'iter,imm,relieve,usv,edificios,cenapred,solar,atlas_solar,sgm', '2020 (población); 2018 (uso de suelo)', 'indicadores por municipio', null, 'Relieve medido a 30 m (Terrain Tiles z12, ≈ 36 m reales); laderas, potencial y solar a 90 m'),
  ('qgis.regiones_geoculturales', 'Regiones geoculturales', 'límites', 'Secretaría de Cultura de Hidalgo', '2019', 'por municipio', null, 'Contorno = municipios de INEGI dic. 2025'),
  ('qgis.localidades', 'Localidades (ITER 2020)', 'población', 'iter,iml', '2020', 'punto por localidad', null, 'El punto es la coordenada de la localidad en el ITER, no su mancha urbana'),
  ('qgis.lugares', 'Lugares fuera del ITER', 'población', 'catalogo,denue', '2020–2026', 'punto aproximado', null, 'Asentamientos del DENUE ubicados en la mediana de sus negocios'),
  ('qgis.servicios', 'Salud y escuelas', 'población', 'clues,denue', 'ago. 2026 (CLUES)', 'punto', null, null),
  ('qgis.movilidad_flujos', 'Traslados al trabajo y la escuela', 'población', 'muestra', '2020', 'por municipio', null, 'Líneas entre puntos interiores de los polígonos: no son caminos; con registros < 20 la cifra es imprecisa'),
  -- vías
  ('qgis.red_vial', 'Red vial (grafo para rutas)', 'vías', 'vias', 'oct. 2026', 'tramo entre cruces', null, 'Tramos rectos entre nodos: forma_aproximada marca los que pierden sus curvas; sin calles residenciales. Para rutas, no para dibujar'),
  ('qgis.red_vial_nodos', 'Nodos de la red vial', 'vías', 'vias', 'oct. 2026', 'punto', null, null),
  -- agua
  ('qgis.rios', 'Ríos calculados (90 m)', 'agua', 'relieve,agua', '2016 (relieve)', 'rejilla de 90 m', 90, 'Drenaje calculado del relieve a 90 m guiado por OSM: con un relieve más fino no cae en el fondo de los valles; se recalcula en la fase 2'),
  ('qgis.manantiales', 'Manantiales (cartas 1:50 000)', 'agua', 'topo50', '2013–2023', '1:50 000', 25, 'detalle_m = 0.5 mm de la carta; un manantial del mapa puede estar seco o captado'),
  ('qgis.aguas_termales', 'Aguas termales', 'agua', 'cerros,estudios_disponibilidad', '2024 (estudios)', 'punto', null, 'aproximada = punto de la localidad que nombra la fuente'),
  ('qgis.agua_bordos', 'Sitios para bordos', 'agua', 'relieve,chirps,estudios_disponibilidad', '1981–2025 (lluvia)', 'vaso a 30 m sobre flujo de 90 m', 90, 'Orientativo: falta revisar suelo, roca, tenencia y vertedor'),
  ('qgis.agua_localidades', 'Agua en las localidades', 'agua', 'iter,repda,piezometria,calidad_agua,topo50', '2020–2025', 'punto de la localidad', null, 'Profundidad del agua por kriging con su intervalo de 90 %; orienta, no sustituye un estudio geohidrológico'),
  ('qgis.agua_prioridad', 'Prioridad de atención de agua', 'agua', 'iter,iml,repda,chirps', '2020–2025', 'punto de la localidad', null, 'Orienta y se verifica en campo'),
  ('qgis.acuiferos', 'Acuíferos (parte de Hidalgo)', 'agua', 'acuiferos,calidad_agua,estudios_disponibilidad', 'DOF 9-nov-2023', null, null, 'Recorte simple al límite estatal: quedan franjas angostas de acuíferos vecinos'),
  ('qgis.ordenamientos_agua', 'Vedas y suspensiones (parte de Hidalgo)', 'agua', 'ordenamientos_agua', 'corte 25-nov-2021', null, null, 'Polígonos sin la corrección de datum del web'),
  ('qgis.calidad_agua_sitios', 'Calidad del agua subterránea (RENAMECA)', 'agua', 'calidad_agua', '2012–2025', 'punto', null, null),
  ('qgis.piezometria_pozos', 'Pozos de la red piezométrica', 'agua', 'piezometria', '1996–2025', 'punto', null, 'ubicacion: parte de la capa venía en NAD27 leída como WGS 84 (≈ 200 m); ver el campo'),
  ('qgis.piezometria_propuesta', 'Dónde falta medir el nivel del agua', 'agua', 'piezometria,repda,topo50', '2021–2025', 'punto', null, null),
  ('qgis.repda_subterraneos', 'Pozos concesionados (REPDA)', 'agua', 'repda', 'ene. 2021', 'punto', null, 'Sin titulares; se omiten los registros sin coordenadas confiables'),
  ('qgis.repda_superficiales', 'Tomas superficiales (REPDA)', 'agua', 'repda', 'ene. 2021', 'punto', null, 'Sin titulares; se omiten los registros sin coordenadas confiables'),
  ('qgis.repda_descargas', 'Descargas de aguas residuales (REPDA)', 'agua', 'repda', 'ene. 2021', 'punto', null, 'Sin titulares; se omiten los registros sin coordenadas confiables'),
  ('qgis.recarga_focos', 'Urbanización en zonas de recarga', 'agua', 'usv,usv6,edificios,sgm', '2014–2018', '1:250 000 (50 ha)', 707, 'detalle_m = lado de 50 ha, el polígono mínimo de las series'),
  -- suelo
  ('qgis.uso_suelo', 'Uso de suelo y vegetación (Series VI y VII)', 'suelo', 'usv,usv6', '2014 (VI) y 2018 (VII)', '1:250 000 (polígono mínimo 50 ha)', 707, 'detalle_m = lado de 50 ha: no sirve para decidir sobre un predio; 37 polígonos reparados con ST_MakeValid'),
  -- riesgos y geología
  ('qgis.deslizamientos', 'Deslizamientos registrados', 'riesgos', 'cenapred,deslizamientos', '2008–2009 (atlas) y catálogo NASA', 'punto', null, 'Los de la NASA tienen precisión de kilómetros (campo precision)'),
  ('qgis.volcanes', 'Volcanes', 'geología', 'volcanes_cenapred,gvp,topo50', 'atlas CENAPRED; GVP 5.3', 'punto', null, 'altitud y alto_m del relieve de INEGI a 30 m'),
  -- culturas y turismo
  ('qgis.culturas_sitios', 'Culturas antiguas: sitios', 'culturas', 'culturas', 'nov. 2026 (textos)', 'punto', null, 'aproximada = punto en el pueblo que nombra la fuente (sitios no abiertos al público)'),
  ('qgis.culturas_rutas', 'Rutas prehispánicas probables', 'culturas', 'culturas,relieve', null, 'camino de menor tiempo sobre relieve de 90 m', 90, 'Una ruta probable (regla de Tobler), no un camino hallado'),
  ('qgis.culturas_provincias', 'Provincias hacia 1500', 'culturas', 'culturas', 'hacia 1500', 'por municipio actual', null, 'Contorno = municipios de hoy, no el de la provincia'),
  ('qgis.geoparque_sitios', 'Geoparque y Pueblos Mágicos', 'culturas', 'Canet et al. 2017 (Terra Digitalis); Pueblos Mágicos', '2017 (geositios)', 'punto', null, 'Fotos de Wikimedia Commons con su autor y licencia')
on conflict (capa) do update set
  titulo = excluded.titulo, tema = excluded.tema, fuentes = excluded.fuentes, fecha_datos = excluded.fecha_datos,
  escala = excluded.escala, detalle_m = excluded.detalle_m, notas = excluded.notas;

-- Llena lo automático y agrega (sin metadatos) cualquier capa de base o qgis que falte en la lista.
create or replace function meta.actualizar_capas() returns void language plpgsql as $$
declare
  r record;
  n bigint;
begin
  insert into meta.capas (capa)
  select f_table_schema || '.' || f_table_name from geometry_columns
  where f_table_schema in ('base', 'qgis')
  on conflict (capa) do nothing;
  delete from meta.capas c
  where not exists (select 1 from geometry_columns g where g.f_table_schema || '.' || g.f_table_name = c.capa);
  for r in
    select c.capa, g.type, g.srid from meta.capas c
    join geometry_columns g on g.f_table_schema || '.' || g.f_table_name = c.capa
  loop
    execute format('select count(*) from %s', r.capa) into n;
    update meta.capas set geometria = r.type, srid = r.srid, filas = n, actualizado = now() where capa = r.capa;
  end loop;
end $$;

select meta.actualizar_capas();
