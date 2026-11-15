-- =====================================================================
-- HANE BÜTÇESİ v2 – ESKİ UYGULAMADAKİ VERİLERİ AKTARMA
-- Ön koşul: supabase_kurulum.sql çalıştırılmış ve uygulamada HEM Abdurrahman
-- HEM Hatice için şifre belirlenmiş olmalı (kasalar bu hesaplara bağlanır).
-- Supabase > SQL Editor > New query > yapıştır > Run.
-- Tekrar çalıştırmak güvenlidir: daha önce aktarılan kayıtlar atlanır.
-- Eski "islemler" tablosu DEĞİŞTİRİLMEZ, sadece okunur.
-- =====================================================================

-- Aktarılan kaydın eski numarası (tekrar aktarmayı önler)
alter table public.hb_islemler add column if not exists eski_id bigint unique;

-- SQL Editor'den (oturumsuz) eklemede "ekleyen" bilgisinin korunmasına izin ver
create or replace function public.hb_islem_oncesi()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if auth.uid() is not null then
      new.ekleyen := auth.uid();
    end if;
    new.ekleyen_ad := (select ad from public.hb_profiller where id = new.ekleyen);
  else
    new.ekleyen := old.ekleyen;
    new.ekleyen_ad := old.ekleyen_ad;
  end if;
  new.guncelleme := now();
  return new;
end $$;

-- "1.234,50" / "10,00" / "1.0" / 25 -> sayı
create or replace function pg_temp.sayi(x text) returns numeric language sql immutable as $$
  select case
    when x is null or btrim(x) = '' then null
    when x ~ ',' then nullif(regexp_replace(replace(replace(x, '.', ''), ',', '.'), '[^0-9.\-]', '', 'g'), '')::numeric
    else nullif(regexp_replace(x, '[^0-9.\-]', '', 'g'), '')::numeric
  end;
$$;

do $$
declare
  a uuid := (select id from public.hb_profiller where kullanici_adi = 'abdurrahman');
  h uuid := (select id from public.hb_profiller where kullanici_adi = 'hatice');
  adet int;
begin
  if a is null or h is null then
    raise exception 'Önce uygulamada Abdurrahman ve Hatice için şifre belirleyin (iki hesap da gerekli).';
  end if;

  with eski as (
    select e.*,
           case when lower(coalesce(e.kullanici::text,'')) ~ '(hatice|aile üyesi|aile uyesi)' then h else a end as kisi,
           lower(coalesce(e.kaynak::text,'')) as kaynak_k
    from public.islemler e
  )
  insert into public.hb_islemler
    (eski_id, tur, tarih, firma, urun, kategori, miktar, birim_fiyat, tutar, aciklama,
     kasa_sahibi, hedef_kasa, ekleyen, olusturma)
  select
    e.id,
    case e.tur::text when 'Gelir' then 'Gelir' when 'Para Aktarımı' then 'Aktarım' else 'Gider' end,
    (to_timestamp(e.tarih::text || ' ' || coalesce(nullif(e.saat::text, ''), '12:00'), 'DD.MM.YYYY HH24:MI')::timestamp
       at time zone 'Europe/Istanbul'),
    case when e.tur::text = 'Gelir' then nullif(e.kaynak::text, '') when e.tur::text = 'Para Aktarımı' then null
         else nullif(e.firma::text, '') end,
    case when e.tur::text = 'Para Aktarımı' then null else nullif(e.urun::text, '') end,
    case when e.tur::text = 'Gelir' then coalesce(nullif(e.gelir_turu::text, ''), 'Diğer Gelir')
         when e.tur::text = 'Para Aktarımı' then 'Transfer / Birikim'
         else coalesce(nullif(e.kategori::text, ''), 'Diğer') end,
    case when e.tur::text = 'Gider' then nullif(e.miktar::text, '') end,
    case when e.tur::text = 'Gider' then pg_temp.sayi(e.birim_fiyat::text) end,
    abs(pg_temp.sayi(e.tutar::text)),
    nullif(e.aciklama::text, ''),
    e.kisi,
    case when e.tur::text = 'Para Aktarımı' then
      case when e.kaynak_k ~ '(hatice|aile üyesi|aile uyesi)' then h
           when e.kaynak_k ~ 'abdurrahman' then a
           when e.kisi = a then h else a end
    end,
    e.kisi,
    coalesce(e.created_at, now())
  from eski e
  where pg_temp.sayi(e.tutar::text) is not null
    and pg_temp.sayi(e.tutar::text) <> 0
    and e.tarih::text ~ '^\d{2}\.\d{2}\.\d{4}$'
    -- kendi kasasına aktarım olamaz
    and not (e.tur::text = 'Para Aktarımı' and
             (case when e.kaynak_k ~ '(hatice|aile üyesi|aile uyesi)' then h
                   when e.kaynak_k ~ 'abdurrahman' then a
                   when e.kisi = a then h else a end) = e.kisi)
  on conflict (eski_id) do nothing;

  get diagnostics adet = row_count;
  raise notice 'Aktarılan yeni kayıt: %', adet;

  -- Eski gelir türlerini yeni listeye ekle
  update public.hb_ayarlar s
  set deger = (
    select jsonb_agg(t order by ilk)::text
    from (
      select t, min(sira) as ilk from (
        select value as t, ordinality as sira
        from jsonb_array_elements_text(coalesce(s.deger, '[]')::jsonb) with ordinality
        union all
        select distinct kategori, 1000 from public.hb_islemler where tur = 'Gelir'
      ) x group by t
    ) y
  )
  where s.anahtar = 'gelir_turleri';
end $$;

-- Sonuç özeti
select tur, count(*) as adet, sum(tutar) as toplam from public.hb_islemler where eski_id is not null group by tur;
select p.ad as kasa,
       sum(case when i.tur='Gelir' and i.kasa_sahibi=p.id then i.tutar
                when i.tur in ('Gider','Aktarım') and i.kasa_sahibi=p.id then -i.tutar
                when i.tur='Aktarım' and i.hedef_kasa=p.id then i.tutar else 0 end) as bakiye
from public.hb_profiller p join public.hb_islemler i on i.kasa_sahibi=p.id or i.hedef_kasa=p.id
group by p.ad;
