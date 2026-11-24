-- Fase 1 · 1: esquema terreno. Los rásters viven en datos/terreno como GeoTIFF optimizados (COG); aquí van su índice,
-- las zonas de trabajo y la cobertura de cada resolución, para verlas y consultarlas en QGIS y en SQL.

create schema if not exists terreno;
comment on schema terreno is 'Relieve: zonas de trabajo, índice de hojas de los modelos de INEGI (1.5 y 5 m) con su control de calidad, cobertura por resolución y rásters registrados fuera de la base (out-db). Lo escribe scripts/fase1.py';

create table if not exists terreno.zonas (
  zona        text primary key,
  descripcion text,
  municipios  text[],
  area_km2    double precision,
  geom        geometry(MultiPolygon, 6369) not null
);
comment on table terreno.zonas is 'Zonas de trabajo del relieve fino: piloto = Pachuca de Soto, Mineral de la Reforma, Mineral del Monte y Mineral del Chico (municipios de INEGI dic. 2025 con 500 m de margen)';

create table if not exists terreno.hojas (
  clave          text primary key,                  -- hoja 1:10 000 de INEGI (p. ej. F14D81E1)
  resolucion_m   real not null,                     -- 1.5 o 5: la más fina que tiene terreno y superficie
  edicion        int not null,
  formato        text,                              -- TIF o BIL
  upc_terreno    text, url_terreno text,
  upc_superficie text, url_superficie text,
  mb             real,                              -- descarga de las dos (zips)
  en_hidalgo     boolean,
  zonas          text[] not null default '{}',
  archivo_terreno    text,                          -- ruta relativa a la raíz del proyecto, si ya se bajó
  archivo_superficie text,
  sin_dato_pct   real,                              -- % de píxeles sin dato dentro de la hoja (terreno)
  sesgo_m        real,                              -- mediana de (hoja − CEM 4.0) en celdas de 15 m
  nmad_m         real,                              -- dispersión robusta de esa diferencia (1.4826 × MAD)
  p95_abs_m      real,                              -- percentil 95 de |hoja − CEM|
  costura_m      real,                              -- mediana de |diferencia| con las hojas vecinas donde se enciman
  revision       text,                              -- ok | revisar (y por qué)
  geom           geometry(Polygon, 6369) not null   -- recuadro de la hoja
);
create index if not exists hojas_geom on terreno.hojas using gist (geom);
comment on table terreno.hojas is 'Hojas 1:10 000 de los modelos digitales de elevación de INEGI que tocan Hidalgo (catálogo de INEGI): la resolución más fina con terreno y superficie, la edición más reciente. Las de 1.5 m (ediciones 2025–2026) y 5 m (2015–2026) salen de fotogrametría de imágenes de satélite en estéreo (no LiDAR): bajo bosque denso el terreno es una estimación. Control de calidad contra el CEM 4.0 de 15 m: sesgo_m, nmad_m, p95_abs_m y costura_m';

create table if not exists terreno.cobertura (
  resolucion   text primary key,                    -- 1.5 m | 5 m | 15 m (solo CEM)
  area_km2     double precision,
  pct_estado   double precision,
  geom         geometry(MultiPolygon, 6369)
);
comment on table terreno.cobertura is 'Qué tan fino es el relieve disponible en cada parte de Hidalgo (catálogo de INEGI): 1.5 m, 5 m o solo el CEM 4.0 de 15 m. Es la capa de «qué tan fino es el dato aquí» de la regla de confiabilidad';
