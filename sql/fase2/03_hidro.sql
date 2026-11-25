-- Fase 2 · 3: agua calculada del relieve fino (por zona).

create table if not exists terreno.cauces (
  id                 serial primary key,
  zona               text not null,
  tipo               text,                 -- de r.stream.extract: start (nace), intermediate, outlet (sale)
  red                int,                  -- red de drenaje a la que pertenece
  area_km2           real,                 -- área drenada en su extremo de aguas abajo
  cuenca_incompleta  boolean,              -- puede entrarle agua de fuera del recuadro: el área es un mínimo
  clase              text,                 -- escurrimiento (< 1 km²), arroyo (1–10), río (10–100), río principal
  z_arriba           real, z_abajo real,   -- altura en sus extremos (m)
  largo_m            real,
  pendiente_pct      real,                 -- desnivel entre extremos / largo
  urbano             boolean,              -- cruza una localidad urbana: el cauce real puede estar entubado
  geom               geometry(MultiLineString, 6369) not null
);
create index if not exists cauces_geom on terreno.cauces using gist (geom);
create index if not exists cauces_zona on terreno.cauces (zona);
comment on table terreno.cauces is 'Red de drenaje calculada del relieve fino de la zona promediado a 5 m (GRASS r.watershed con flujo múltiple y r.stream.extract): cauces desde 0.1 km² drenados, con su área drenada, clase, alturas y pendiente. Bajo bosque el relieve de 1.5 m es una interpolación (el trazo es menos fiable) y en la ciudad el agua puede ir entubada o por las calles (urbano)';

create table if not exists terreno.subcuencas (
  zona        text not null,
  cuenca      int not null,
  area_km2    double precision,
  incompleta  boolean,        -- toca la orilla del recuadro: le falta la parte de afuera
  geom        geometry(MultiPolygon, 6369) not null,
  primary key (zona, cuenca)
);
create index if not exists subcuencas_geom on terreno.subcuencas using gist (geom);
comment on table terreno.subcuencas is 'Subcuencas de 2 km² o más calculadas del relieve fino de la zona a 5 m (GRASS r.watershed)';
