-- Fase 2 · 1: Marco Geoestadístico 2025 de INEGI (Hidalgo), de las cargas de GDAL a sus tablas.

do $$
declare
  t text;
begin
  foreach t in array array['mg_ejes', 'mg_manzanas', 'mg_localidades', 'mg_servicios_a', 'mg_servicios_l',
                           'mg_servicios_p'] loop
    execute format('drop table if exists base.%I', t);
    execute format('alter table base.%I rename to %I', t || '_carga', t);
  end loop;
end $$;

comment on table base.mg_ejes is 'Ejes de vialidad (calles y caminos de las localidades) de Hidalgo, INEGI Marco Geoestadístico 2025 (13e), en EPSG:6369: nombre (nomvial), tipo (tipovial), sentido; un renglón por segmento entre cruces (cvevial + cveseg)';
comment on table base.mg_manzanas is 'Manzanas de Hidalgo, INEGI Marco Geoestadístico 2025 (13m), en EPSG:6369';
comment on table base.mg_localidades is 'Polígonos de las localidades amanzanadas (urbanas y rurales) de Hidalgo, INEGI Marco Geoestadístico 2025 (13l), en EPSG:6369';
comment on table base.mg_servicios_a is 'Servicios con información adicional, áreas (parques, jardines, escuelas, panteones, mercados…), INEGI Marco Geoestadístico 2025 (13sia)';
comment on table base.mg_servicios_l is 'Servicios con información adicional, líneas (corrientes, vías férreas, bordos…), INEGI Marco Geoestadístico 2025 (13sil)';
comment on table base.mg_servicios_p is 'Servicios con información adicional, puntos (templos, escuelas, centros de salud…), INEGI Marco Geoestadístico 2025 (13sip)';
