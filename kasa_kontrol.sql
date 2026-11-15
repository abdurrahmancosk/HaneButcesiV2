-- KASA FARKI KONTROLÜ: Supabase > SQL Editor > New query > yapıştır > Run
-- Sonuç tablosunun tamamının ekran görüntüsünü gönderin. Hiçbir veriyi değiştirmez.
with
eski as (
  select e.id, e.tur::text tur, e.tarih::text tarih, e.saat::text saat, coalesce(e.firma::text,'') firma,
         coalesce(e.urun::text,'') urun, e.kullanici::text kullanici,
         nullif(regexp_replace(replace(case when e.tutar::text ~ ',' then replace(e.tutar::text,'.','') else e.tutar::text end, ',', '.'), '[^0-9.\-]', '', 'g'), '')::numeric tutar
  from public.islemler e
),
eski_kasa as (
  select sum(case when tur='Gelir' then tutar when tur='Gider' then -tutar else 0 end) v, count(*) n from eski
),
yeni_kasa as (
  select sum(case when tur='Gelir' then tutar when tur='Gider' then -tutar else 0 end) v, count(*) n from public.hb_islemler
),
ciftler as (
  select tarih, saat, lower(firma) f, lower(urun) u, tutar, tur, count(*) adet, min(id) ilk_id
  from eski group by 1,2,3,4,5,6 having count(*) > 1
)
select 1 sira, 'ESKİ tablo kasası' bolum, (select n from eski_kasa)::text || ' kayıt' detay, (select v from eski_kasa) tutar
union all
select 2, 'YENİ tablo kasası', (select n from yeni_kasa)::text || ' kayıt', (select v from yeni_kasa)
union all
select 3, 'AKTARILMAMIŞ eski kayıt', e.id || ' | ' || e.tur || ' | ' || e.tarih || ' ' || coalesce(e.saat,'') || ' | ' || e.firma || ' ' || e.urun || ' | ' || coalesce(e.kullanici,''), e.tutar
from eski e where not exists (select 1 from public.hb_islemler h where h.eski_id = e.id)
union all
select 4, 'Yeni uygulamada eklenen', h.tur || ' | ' || to_char(h.tarih at time zone 'Europe/Istanbul','DD.MM.YYYY HH24:MI') || ' | ' || coalesce(h.urun, h.kategori, '') || ' | ' || coalesce(h.ekleyen_ad,''), h.tutar
from public.hb_islemler h where h.eski_id is null
union all
select 5, 'Eski tabloda MÜKERRER', c.adet || ' adet | ' || c.tur || ' | ' || c.tarih || ' ' || c.saat || ' | ' || c.f || ' ' || c.u, c.tutar
from ciftler c
order by 1, 2, 3;
