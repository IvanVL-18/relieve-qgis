-- Fase 2 · 4: cuerpos de agua con su nivel, control de los cauces calculados y calles con su pendiente (por zona).

create table if not exists terreno.cuerpos_agua (
  id          serial primary key,
  zona        text not null,
  fuente      text not null,               -- INEGI 1:50 000 | OpenStreetMap
  nombre      text,
  tipo        text,
  condicion   text,                        -- perenne | intermitente (INEGI) o intermitente (OSM)
  area_ha     double precision,
  nivel_m     real,                        -- mediana de la altura del relieve de 1.5 m en su orilla
  nivel_rango_m real,                      -- p90 − p10 de esa altura (si es grande, la orilla no es pareja)
  geom        geometry(MultiPolygon, 6369) not null
);
create index if not exists cuerpos_agua_geom on terreno.cuerpos_agua using gist (geom);
comment on table terreno.cuerpos_agua is 'Cuerpos de agua de la zona (vasos de presas y bordos, pozas, lagunas) de las cartas 1:50 000 de INEGI y de OpenStreetMap, con su nivel: la mediana de la altura del relieve de 1.5 m a lo largo de la orilla (para dibujarlos planos en 3D). Un vaso intermitente puede estar seco';

create table if not exists terreno.control_cauces (
  zona        text not null,
  referencia  text not null,               -- con qué se compara
  grupo       text not null,               -- perenne, intermitente, todos…
  puntos      int,                         -- puntos cada 10 m sobre la referencia
  km          real,
  mediana_m   real,                        -- distancia mediana al cauce calculado más cercano
  pct_20m     real,                        -- % de la referencia a ≤ 20 m de un cauce calculado
  pct_50m     real,
  primary key (zona, referencia, grupo)
);
comment on table terreno.control_cauces is 'Qué tanto coinciden los cauces calculados del relieve fino con los de las cartas 1:50 000 de INEGI y de OpenStreetMap: distancia de puntos cada 10 m sobre la referencia al cauce calculado más cercano';

create table if not exists terreno.calles (
  id             serial primary key,
  zona           text not null,
  fuente         text not null,            -- INEGI Marco Geoestadístico 2025
  cvegeo         text,                     -- clave del segmento en el Marco Geoestadístico
  nombre         text,
  tipo           text,                     -- tipo de vialidad (calle, avenida, privada…)
  sentido        text,
  ambito         text,                     -- urbana | rural
  largo_m        real,
  z_ini          real, z_fin real,
  desnivel_m     real,                     -- |z_fin − z_ini|
  pend_media_pct real,                     -- desnivel / largo
  pend_max_pct   real,                     -- la mayor en 20 m seguidos (o en todo el tramo si es más corto)
  subida_m       real, bajada_m real,      -- en el sentido en que está dibujada
  osm_tipo       text,                     -- highway de OpenStreetMap del tramo que más se le encima
  osm_superficie text,                     -- surface de OpenStreetMap (asfalto, empedrado…)
  puente         boolean,                  -- OSM marca un puente encima: el relieve no lo tiene y la pendiente es falsa
  geom           geometry(MultiLineString, 6369) not null
);
alter table terreno.calles add column if not exists pend_max_60m_pct real;   -- la mayor en 60 m seguidos
alter table terreno.calles add column if not exists perfil_irregular boolean; -- escalón corto: p20 > 2·p60 + 10
create index if not exists calles_geom on terreno.calles using gist (geom);
create index if not exists calles_zona on terreno.calles (zona);
comment on table terreno.calles is 'Calles de la zona (ejes de vialidad del Marco Geoestadístico 2025 de INEGI) con su perfil medido en el relieve de 1.5 m cada 1.5 m: pendiente media, pendiente máxima en 20 y en 60 m seguidos, subida y bajada. El relieve tiene ruido de decímetros (≈ ±2 % de pendiente en 20 m) y no tiene puentes: puente = hay una vía de OSM con bridge o layer ≠ 0 a ≤ 15 m (distribuidores, puentes); perfil_irregular = escalón corto (pendiente en 20 m > 2 × la de 60 m + 10): en los dos casos la pendiente máxima no vale. Tipo y superficie de OpenStreetMap del tramo que más se le encima';
