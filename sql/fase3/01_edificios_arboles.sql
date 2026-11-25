-- Fase 3 · 1: edificios con su altura medida y árboles uno por uno (por zona).

create table if not exists terreno.edificios (
  id            bigint not null,             -- el gid de base.ms_edificios_<zona>
  zona          text not null,
  area_m2       real,
  pixeles       int,                         -- píxeles de 1.5 m dentro del contorno
  frac_alto     real,                        -- parte del contorno con más de 2 m sobre el suelo
  altura_m      real,                        -- mediana de la altura de los píxeles de más de 2 m (el techo)
  altura_p90_m  real,                        -- percentil 90 (tinacos, pretiles, segundo nivel)
  pisos         smallint,                    -- altura / 3 m, al menos 1
  z_suelo       real,                        -- altura del terreno en su base (mediana)
  confianza     text,                        -- alta | media | sin medida (ver comentario)
  osm_niveles   smallint,                    -- building:levels de OpenStreetMap, si un edificio de OSM lo cubre
  geom          geometry(MultiPolygon, 6369) not null,
  primary key (zona, id)
);
create index if not exists edificios_geom on terreno.edificios using gist (geom);
create index if not exists edificios_zona on terreno.edificios (zona);
comment on table terreno.edificios is 'Edificios de la zona: contornos de Microsoft Global ML Building Footprints (ODbL) con la altura MEDIDA en el modelo de superficie menos el de terreno de INEGI (1.5 m, fotogrametría de satélite): mediana de los píxeles de más de 2 m dentro del contorno. confianza alta = 20 píxeles o más y 70 % del contorno alto; media = 40 % o más; sin medida = el modelo no ve el edificio (de un piso bajo, nuevo, demolido o contorno corrido). pisos = altura / 3 m';

create table if not exists terreno.arboles (
  id            bigserial primary key,
  zona          text not null,
  altura_m      real,                        -- altura de la copa sobre el suelo (máximo local del modelo de dosel)
  copa_diam_m   real,                        -- diámetro equivalente de la copa (2·√(área/π))
  copa_area_m2  real,
  z_suelo       real,
  geom          geometry(Point, 6369) not null
);
alter table terreno.arboles add column if not exists desv_copa_m real;   -- desviación de la altura dentro de la copa
alter table terreno.arboles add column if not exists tipo text;          -- árbol | posible construcción | pico dudoso
create index if not exists arboles_geom on terreno.arboles using gist (geom);
create index if not exists arboles_zona on terreno.arboles (zona);
comment on table terreno.arboles is 'Árboles uno por uno detectados en la altura sobre el suelo (superficie − terreno de INEGI, 1.5 m) fuera de los edificios: cima = máximo local con ventana que crece con la altura (3 a 9 píxeles), de 3 m o más; copa = cuenca (watershed) alrededor de la cima dentro de lo que pasa de 2 m. tipo: posible construcción = dentro de una localidad amanzanada (± 30 m), «copa» de 20 m² o más que varía menos de 0.6 m (un techo plano sin contorno de Microsoft; fuera de las localidades una copa plana es dosel de bosque suavizado); pico dudoso = 30 m o más con copa de menos de 15 m² (torre, poste, orilla de barranco). Bajo bosque denso el terreno es una interpolación: vemos ≈ la mitad del dosel que el modelo de Meta, así que conteo y alturas ahí son un mínimo (terreno.control_dosel)';

create table if not exists terreno.control_dosel (
  zona          text not null,
  ventana       text not null,
  km2           real,
  cubierta_ours_pct  real,                   -- % con dosel de 3 m o más en nuestro modelo
  cubierta_meta_pct  real,                   -- % en el de Meta y WRI
  coincidencia_iou   real,                   -- intersección / unión de las dos cubiertas
  dif_mediana_m      real,                   -- mediana de (nuestra altura − Meta) donde las dos pasan de 5 m
  correlacion        real,                   -- de las alturas donde las dos pasan de 5 m
  primary key (zona, ventana)
);
comment on table terreno.control_dosel is 'Comparación del dosel (altura de la vegetación) medido con los modelos de INEGI contra el de Meta y World Resources Institute (High Resolution Canopy Height Maps, Tolan et al. 2024, 1 m, CC BY 4.0; estimado con aprendizaje automático sobre imágenes de 2009–2020) en ventanas de muestra';
