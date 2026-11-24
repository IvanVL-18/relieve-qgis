-- Fase 0 · 2: tablas definitivas de base a partir de las cargas de GDAL (*_carga, que se borran al final).
-- Las áreas en km² son elipsoidales (sobre geography): exactas, sin la deformación de la proyección UTM (< 0.1 %).

-- ── Límites de INEGI: Marco Geoestadístico, diciembre de 2025 (servicio wscatgeo) ──────────────────────────────────

drop table if exists base.municipios;
create table base.municipios (
  cvegeo    text primary key,
  cve_mun   smallint not null unique,
  nombre    text not null,
  cve_cab   text,
  area_km2  double precision not null,
  geom      geometry(MultiPolygon, 6369) not null
);
insert into base.municipios
select cvegeo, cve_mun::smallint, nomgeo, cve_cab,
       ST_Area(ST_Transform(geom, 4326)::geography) / 1e6,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
from base.municipios_carga;
create index on base.municipios using gist (geom);
comment on table base.municipios is 'Municipios de Hidalgo, INEGI Marco Geoestadístico de diciembre de 2025 (servicio wscatgeo, publicado en EPSG:6365), en EPSG:6369. area_km2 elipsoidal. Vértice cada ≈ 50 m en promedio; la copia que usaba el proyecto web (GitHub, MG 2022) difiere 9 m como máximo';

drop table if exists base.entidades;
create table base.entidades (
  cvegeo    text primary key,
  nombre    text not null,
  abrev     text,
  area_km2  double precision not null,
  geom      geometry(MultiPolygon, 6369) not null
);
insert into base.entidades
select cvegeo, nomgeo, nom_abrev,
       ST_Area(ST_Transform(geom, 4326)::geography) / 1e6,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
from base.entidades_carga;
create index on base.entidades using gist (geom);
comment on table base.entidades is 'Las 32 entidades, INEGI Marco Geoestadístico de diciembre de 2025, en EPSG:6369 (lejos de Hidalgo la proyección UTM 14N deforma: úsese solo como referencia). area_km2 elipsoidal';

drop table if exists base.estado;
create table base.estado as
select cvegeo, nombre, area_km2, geom from base.entidades where cvegeo = '13';
alter table base.estado add primary key (cvegeo);
create index on base.estado using gist (geom);
comment on table base.estado is 'Límite del estado de Hidalgo (INEGI Marco Geoestadístico de diciembre de 2025), en EPSG:6369';

drop table if exists base.municipios_edomex;
create table base.municipios_edomex (
  cvegeo    text primary key,
  cve_mun   smallint not null,
  nombre    text not null,
  area_km2  double precision not null,
  geom      geometry(MultiPolygon, 6369) not null
);
insert into base.municipios_edomex
select cvegeo, cve_mun::smallint, nomgeo,
       ST_Area(ST_Transform(geom, 4326)::geography) / 1e6,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
from base.municipios_edomex_carga;
create index on base.municipios_edomex using gist (geom);
comment on table base.municipios_edomex is 'Municipios del Estado de México (INEGI Marco Geoestadístico de diciembre de 2025): destinos de relieve.movilidad_flujos';

-- ── CONAGUA: acuíferos y ordenamientos de aguas subterráneas (los que caen en la caja de Hidalgo) ──────────────────

drop table if exists base.acuiferos;
create table base.acuiferos as
select clv_acui as clave, min(nom_acui) as nombre, min(clv_edo) as cve_ent, min(nom_edo) as estado,
       min(nom_region) as region, count(*)::int as poligonos,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(geom)), 3))::geometry(MultiPolygon, 6369) as geom
from base.acuiferos_carga
group by clv_acui;
alter table base.acuiferos add primary key (clave);
create index on base.acuiferos using gist (geom);
comment on table base.acuiferos is 'Polígonos de los acuíferos de CONAGUA (disponibilidad media anual, DOF 9-nov-2023, shapefile de la Gerencia de Aguas Subterráneas, CC BY 4.0) que tocan la caja de Hidalgo, completos (sin recortar), en EPSG:6369. Sus cifras están en relieve.acuiferos';

drop table if exists base.ordenamientos;
create table base.ordenamientos (
  id          serial primary key,
  tipo        text not null,          -- veda | suspension
  nombre      text,                   -- NOM_CORTO
  oficial     text,                   -- NOM_OFI
  fecha_dof   text,
  acuifero    text,                   -- CLV_ACUI
  acuifero_nombre text,
  clasificacion text,                 -- CLASIF_LEY (solo vedas)
  descripcion text,                   -- DES_CLASIF
  decreto     text,
  liga        text,
  geom        geometry(MultiPolygon, 6369) not null
);
insert into base.ordenamientos (tipo, nombre, oficial, fecha_dof, acuifero, acuifero_nombre, clasificacion, descripcion, decreto, liga, geom)
select 'veda', nom_corto, nom_ofi, fecha_dof, nullif(trim(clv_acui), ''), nom_acui, clasif_ley, des_clasif, decreto, link_dof,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
from base.vedas_carga
union all
select 'suspension', nom_corto, nom_ofi, fecha_dof, nullif(trim(clv_acui), ''), nom_acui, null, des_clasif, decreto, link_dof,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
from base.suspensiones_carga;
create index on base.ordenamientos using gist (geom);
comment on table base.ordenamientos is 'Vedas (decretos de 1954 a 1978) y suspensiones del libre alumbramiento (acuerdos del DOF del 5-abr-2013) de CONAGUA, corte del 25-nov-2021 (CC BY 4.0), que tocan la caja de Hidalgo, tal como se publican, en EPSG:6369. El proyecto web detectó vértices con un posible corrimiento de datum respecto a los acuíferos y los corrigió; aquí NO están corregidos. Los reglamentos, reservas y zonas reglamentadas no tocan Hidalgo';

-- ── Limpieza de las cargas ───────────────────────────────────────────────────────────────────────────────────────
drop table base.municipios_carga, base.entidades_carga, base.municipios_edomex_carga,
           base.acuiferos_carga, base.vedas_carga, base.suspensiones_carga;
