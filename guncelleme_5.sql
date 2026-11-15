-- =====================================================================
-- HANE BÜTÇESİ v2 – GÜNCELLEME 5
-- Altın/döviz varlıkları, kişi (harçlık) bütçesi bildirimleri, okul harçlığı otomatiği,
-- haftalık özet bildirimi. Tekrar çalıştırmak güvenlidir.
-- =====================================================================

-- ---------- Yardımcılar ----------
create or replace function public.hb_bugun() returns date language sql stable as $$
  select (now() at time zone 'Europe/Istanbul')::date;
$$;
create or replace function public.hb_donem_bas(d date) returns date language sql immutable as $$
  select case when extract(day from d) >= 15 then date_trunc('month', d)::date + 14
              else (date_trunc('month', d) - interval '1 month')::date + 14 end;
$$;

-- ---------- 1) Altın / döviz varlıkları ----------
create table if not exists public.hb_varliklar (
  id             bigint generated always as identity primary key,
  tur            text not null,                 -- gram, ceyrek, yarim, tam, cumhuriyet, ata, bilezik22, USD, EUR, GBP
  miktar         numeric(14,3) not null check (miktar > 0),
  birim_maliyet  numeric(14,2),                 -- alındığı birim fiyat (TL); bilinmiyorsa boş
  tarih          date not null default public.hb_bugun(),
  aciklama       text,
  durum          text not null default 'elde' check (durum in ('elde','satildi')),
  satis_fiyati   numeric(14,2),
  satis_tarihi   date,
  islem_id       bigint references public.hb_islemler(id) on delete set null,
  kasa_sahibi    uuid not null references public.hb_profiller(id),
  olusturma      timestamptz not null default now()
);
alter table public.hb_varliklar enable row level security;
drop policy if exists hb_varliklar_tum on public.hb_varliklar;
create policy hb_varliklar_tum on public.hb_varliklar for all to authenticated
  using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())
  with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid());

-- ---------- 2) Kişi (harçlık) bütçesi: %80 ve %100'de bildirim ----------
-- Limit hb_butceler tablosunda 'kisi:<kullanıcı id>' anahtarıyla tutulur.
create or replace function public.hb_kisi_butce_kontrol()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  lim numeric; harcanan numeric; bas date; oran numeric; esik int; kisi_ad text; p record;
begin
  if new.tur <> 'Gider' or new.eski_id is not null then return new; end if;
  select limit_tutar into lim from public.hb_butceler where kategori = 'kisi:' || new.kasa_sahibi;
  if lim is null then return new; end if;
  bas := public.hb_donem_bas((new.tarih at time zone 'Europe/Istanbul')::date);
  select coalesce(sum(tutar), 0) into harcanan from public.hb_islemler
   where kasa_sahibi = new.kasa_sahibi and tur = 'Gider'
     and (tarih at time zone 'Europe/Istanbul')::date between bas and (bas + interval '1 month - 1 day')::date;
  oran := harcanan / lim;
  esik := case when oran >= 1 then 100 when oran >= 0.8 then 80 else 0 end;
  if esik = 0 then return new; end if;
  select pr.ad into kisi_ad from public.hb_profiller pr where pr.id = new.kasa_sahibi;
  for p in select id from public.hb_profiller where id = new.kasa_sahibi or rol = 'yonetici' loop
    insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
    values (p.id,
            case when esik = 100 then '🚨 ' || kisi_ad || ' bütçesi aşıldı' else '⚠️ ' || kisi_ad || ' bütçesinin %80''i doldu' end,
            public.hb_tl(harcanan) || ' / ' || public.hb_tl(lim), 'hatirlatma',
            'kisibutce:' || new.kasa_sahibi || ':' || bas || ':' || esik || ':' || p.id)
    on conflict (anahtar) do nothing;
  end loop;
  return new;
end $$;
drop trigger if exists hb_kisi_butce_tetik on public.hb_islemler;
create trigger hb_kisi_butce_tetik after insert on public.hb_islemler
  for each row execute function public.hb_kisi_butce_kontrol();

-- ---------- 3) Okul harçlığı otomatiği ----------
create table if not exists public.hb_tatiller (bas date not null, bit date not null, ad text, primary key (bas, bit));
alter table public.hb_tatiller enable row level security;
drop policy if exists hb_tatil_oku on public.hb_tatiller;
create policy hb_tatil_oku on public.hb_tatiller for select to authenticated using (true);
drop policy if exists hb_tatil_yaz on public.hb_tatiller;
create policy hb_tatil_yaz on public.hb_tatiller for all to authenticated
  using (public.hb_yonetici_mi()) with check (public.hb_yonetici_mi());
-- 2026-2027 MEB çalışma takvimi (eski uygulamadaki tarihler) + resmi tatiller
insert into public.hb_tatiller values
  ('2026-06-27','2026-09-06','Yaz tatili'),
  ('2026-10-29','2026-10-29','Cumhuriyet Bayramı'),
  ('2026-11-16','2026-11-20','1. ara tatil'),
  ('2027-01-01','2027-01-01','Yılbaşı'),
  ('2027-01-25','2027-02-05','Yarıyıl tatili'),
  ('2027-03-08','2027-03-12','2. ara tatil / Ramazan Bayramı'),
  ('2027-04-23','2027-04-23','23 Nisan'),
  ('2027-05-01','2027-05-01','1 Mayıs'),
  ('2027-05-17','2027-05-20','Kurban Bayramı'),
  ('2027-05-19','2027-05-19','19 Mayıs'),
  ('2027-06-26','2027-09-12','Yaz tatili')
on conflict do nothing;

create or replace function public.hb_okul_gunu(d date) returns boolean language sql stable as $$
  select extract(isodow from d) < 6
     and not exists (select 1 from public.hb_tatiller t where d between t.bas and t.bit);
$$;

-- Ayar: hb_ayarlar 'okul_harclik' = {"aktif":true,"cocuk":2,"tutar":10,"kasa":"<uuid>","saat":"08:30"}
create or replace function public.hb_harclik_tamamla()
returns int language plpgsql security definer set search_path = public as $$
declare
  a jsonb; gun date; adet int := 0; kasa uuid; toplam numeric; saat time;
begin
  select deger::jsonb into a from public.hb_ayarlar where anahtar = 'okul_harclik';
  if a is null or coalesce((a->>'aktif')::boolean, false) = false then return 0; end if;
  kasa := (a->>'kasa')::uuid;
  if kasa is null then select id into kasa from public.hb_profiller where rol = 'yonetici' limit 1; end if;
  toplam := coalesce((a->>'cocuk')::numeric, 1) * coalesce((a->>'tutar')::numeric, 0);
  saat := coalesce(nullif(a->>'saat', ''), '08:30')::time;
  if toplam <= 0 then return 0; end if;
  -- son 7 günü tamamla (telefon kapalı kaldıysa / zamanlayıcı yoksa)
  for gun in select generate_series(public.hb_bugun() - 6, public.hb_bugun(), interval '1 day')::date loop
    continue when not public.hb_okul_gunu(gun);
    continue when gun = public.hb_bugun() and (now() at time zone 'Europe/Istanbul')::time < saat;
    continue when gun < coalesce((a->>'baslangic')::date, gun);
    if not exists (select 1 from public.hb_islemler
                   where (aciklama = 'Otomatik okul harçlığı' or urun ilike 'okul har%')
                     and (tarih at time zone 'Europe/Istanbul')::date = gun) then
      insert into public.hb_islemler (tur, tarih, firma, urun, kategori, miktar, birim_fiyat, tutar, aciklama,
                                      kasa_sahibi, ekleyen)
      values ('Gider', (gun + saat) at time zone 'Europe/Istanbul', 'Nakit',
              'Okul Harçlığı (' || coalesce(a->>'cocuk', '1') || ' Çocuk)', 'Eğitim, Okul & Kırtasiye',
              coalesce(a->>'cocuk', '1') || ' çocuk', (a->>'tutar')::numeric, toplam, 'Otomatik okul harçlığı',
              kasa, kasa);
      adet := adet + 1;
    end if;
  end loop;
  return adet;
end $$;
grant execute on function public.hb_harclik_tamamla() to authenticated;

-- ---------- 4) Haftalık özet bildirimi (pazar 20:00) ----------
create or replace function public.hb_haftalik_ozet()
returns int language plpgsql security definer set search_path = public as $$
declare
  bugun date := public.hb_bugun();
  bitis date; p record; bu numeric; once numeric; kat text; katt numeric; adet int := 0; degisim text;
begin
  -- haftanın son günü: bugün pazarsa bugün (20:00'den sonra), değilse geçen pazar (çarşambaya kadar telafi)
  if extract(isodow from bugun) = 7 and (now() at time zone 'Europe/Istanbul')::time >= '20:00' then bitis := bugun;
  elsif extract(isodow from bugun) between 1 and 3 then bitis := bugun - extract(isodow from bugun)::int;
  else return 0; end if;
  for p in select id, rol from public.hb_profiller loop
    select coalesce(sum(tutar), 0) into bu from public.hb_islemler i
     where tur = 'Gider' and (tarih at time zone 'Europe/Istanbul')::date between bitis - 6 and bitis
       and (p.rol = 'yonetici' or (i.kasa_sahibi = p.id and not i.gizli));
    select coalesce(sum(tutar), 0) into once from public.hb_islemler i
     where tur = 'Gider' and (tarih at time zone 'Europe/Istanbul')::date between bitis - 13 and bitis - 7
       and (p.rol = 'yonetici' or (i.kasa_sahibi = p.id and not i.gizli));
    select kategori, sum(tutar) into kat, katt from public.hb_islemler i
     where tur = 'Gider' and (tarih at time zone 'Europe/Istanbul')::date between bitis - 6 and bitis
       and (p.rol = 'yonetici' or (i.kasa_sahibi = p.id and not i.gizli))
     group by kategori order by 2 desc limit 1;
    degisim := case when once > 0 then ' • geçen haftadan %' || abs(round((bu - once) / once * 100)) ||
                    case when bu >= once then ' fazla' else ' az' end else '' end;
    insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
    values (p.id, '📊 Haftalık özet: ' || public.hb_tl(bu),
            coalesce('En çok: ' || kat || ' (' || public.hb_tl(katt) || ')', 'Bu hafta harcama yok') || degisim,
            'islem', 'haftalik:' || bitis || ':' || p.id)
    on conflict (anahtar) do nothing;
    adet := adet + 1;
  end loop;
  return adet;
end $$;
grant execute on function public.hb_haftalik_ozet() to authenticated;

-- ---------- Zamanlayıcılar (pg_cron varsa) ----------
do $$
begin
  create extension if not exists pg_cron;
  perform cron.unschedule(jobid) from cron.job where jobname in ('hb-harclik', 'hb-haftalik');
  perform cron.schedule('hb-harclik', '35 5 * * 1-5', 'select public.hb_harclik_tamamla()');   -- 08:35 TR
  perform cron.schedule('hb-haftalik', '5 17 * * 0', 'select public.hb_haftalik_ozet()');      -- pazar 20:05 TR
exception when others then
  raise notice 'pg_cron kullanılamadı (%); uygulama açılışında çalıştırılacak.', sqlerrm;
end $$;

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime'
                 and schemaname = 'public' and tablename = 'hb_varliklar') then
    alter publication supabase_realtime add table public.hb_varliklar;
  end if;
end $$;

select 'Güncelleme 5 tamam' as sonuc;
