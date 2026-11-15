-- =====================================================================
-- Hane Bütçesi v2.7 – kredi kartı taksitleri + hane sohbeti (para isteği, kayda yorum)
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- =====================================================================

-- ---------- 1) Taksitler ----------
create table if not exists public.hb_taksitler (
  id             bigint generated always as identity primary key,
  ad             text not null,                        -- ne alındı: "Buzdolabı"
  kart           text,                                 -- hangi kart: "Bonus", "World"...
  aylik_tutar    numeric(14,2) not null check (aylik_tutar > 0),
  toplam_taksit  int not null check (toplam_taksit between 1 and 60),
  odenen         int not null default 0,               -- kaç taksit ödendi
  odeme_gunu     int not null check (odeme_gunu between 1 and 31),
  ilk_odeme      date not null,                        -- sıradaki ödemelerin hesaplandığı ilk ödeme tarihi
  kategori       text not null default 'Diğer',
  kasa_sahibi    uuid not null references public.hb_profiller(id),
  aktif          boolean not null default true,
  son_odeme_islem bigint references public.hb_islemler(id) on delete set null,
  ekleyen        uuid not null default auth.uid() references public.hb_profiller(id),
  ekleyen_ad     text,
  olusturma      timestamptz not null default now()
);
drop trigger if exists hb_taksitler_ekleyen on public.hb_taksitler;
create trigger hb_taksitler_ekleyen before insert or update on public.hb_taksitler
  for each row execute function public.hb_ekleyen_doldur();
alter table public.hb_taksitler enable row level security;
drop policy if exists hb_taksitler_tum on public.hb_taksitler;
create policy hb_taksitler_tum on public.hb_taksitler for all to authenticated
  using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())
  with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid());

-- Sıradaki taksit tarihi: ilk ödemenin üzerine ödenen ay sayısı (ay sonu taşmalarını kırpar)
create or replace function public.hb_taksit_vade(t public.hb_taksitler)
returns date language sql immutable as $$
  select (date_trunc('month', t.ilk_odeme) + make_interval(months => t.odenen))::date
         + least(t.odeme_gunu,
                 extract(day from (date_trunc('month', t.ilk_odeme) + make_interval(months => t.odenen + 1) - interval '1 day'))::int) - 1;
$$;

-- Hatırlatma: vadeden bir gün önce ve vade günü (kart bazında tek bildirim)
create or replace function public.hb_taksit_hatirlat()
returns int language plpgsql security definer set search_path = public as $$
declare
  bugun date := (now() at time zone 'Europe/Istanbul')::date;
  g record; p record; adet int := 0;
begin
  for g in
    select coalesce(nullif(t.kart, ''), 'Kart') as kart, t.kasa_sahibi, public.hb_taksit_vade(t) as vade,
           sum(t.aylik_tutar) as toplam, count(*) as n, string_agg(t.ad, ', ' order by t.ad) as adlar
      from public.hb_taksitler t
     where t.aktif and t.odenen < t.toplam_taksit and public.hb_taksit_vade(t) in (bugun, bugun + 1)
     group by 1, 2, 3
  loop
    for p in select id from public.hb_profiller where id = g.kasa_sahibi or rol = 'yonetici' loop
      insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
      values (p.id, '💳 ' || g.kart || ' taksit ödemesi ' || case when g.vade = bugun then 'BUGÜN' else 'YARIN' end,
              public.hb_tl(g.toplam) || ' • ' || g.adlar, 'hatirlatma',
              'hat-taksit:' || g.kart || ':' || g.kasa_sahibi || ':' || g.vade || ':' || bugun || ':' || p.id)
      on conflict (anahtar) do nothing;
      adet := adet + 1;
    end loop;
  end loop;
  return adet;
end $$;
grant execute on function public.hb_taksit_hatirlat() to authenticated;

do $$
begin
  create extension if not exists pg_cron;
  perform cron.unschedule(jobid) from cron.job where jobname = 'hb-taksit';
  perform cron.schedule('hb-taksit', '2 6 * * *', 'select public.hb_taksit_hatirlat()');
exception when others then
  raise notice 'pg_cron kullanılamadı (%); taksit hatırlatmaları uygulama açılınca üretilecek.', sqlerrm;
end $$;

-- ---------- 2) Hane sohbeti ----------
create table if not exists public.hb_mesajlar (
  id          bigint generated always as identity primary key,
  tur         text not null default 'mesaj' check (tur in ('mesaj','istek','yorum','sistem')),
  metin       text not null default '',
  tutar       numeric(14,2),                                   -- para isteğinde
  durum       text check (durum in ('bekliyor','gonderildi','reddedildi')),
  islem_id    bigint references public.hb_islemler(id) on delete set null,  -- yorum yapılan kayıt / yapılan aktarım
  ozet        text,                                            -- yorum yapılan kaydın kısa özeti
  gizli       boolean not null default false,                  -- gizli kayda yorum: yalnız yönetici görür
  okundu      boolean not null default false,
  ekleyen     uuid not null default auth.uid() references public.hb_profiller(id),
  ekleyen_ad  text,
  olusturma   timestamptz not null default now()
);
drop trigger if exists hb_mesajlar_ekleyen on public.hb_mesajlar;
create trigger hb_mesajlar_ekleyen before insert or update on public.hb_mesajlar
  for each row execute function public.hb_ekleyen_doldur();
alter table public.hb_mesajlar enable row level security;
drop policy if exists hb_mesajlar_oku on public.hb_mesajlar;
drop policy if exists hb_mesajlar_yaz on public.hb_mesajlar;
drop policy if exists hb_mesajlar_guncelle on public.hb_mesajlar;
drop policy if exists hb_mesajlar_sil on public.hb_mesajlar;
create policy hb_mesajlar_oku on public.hb_mesajlar for select to authenticated
  using (not gizli or public.hb_yonetici_mi());
create policy hb_mesajlar_yaz on public.hb_mesajlar for insert to authenticated
  with check (not gizli or public.hb_yonetici_mi());
create policy hb_mesajlar_guncelle on public.hb_mesajlar for update to authenticated
  using (not gizli or public.hb_yonetici_mi()) with check (not gizli or public.hb_yonetici_mi());
create policy hb_mesajlar_sil on public.hb_mesajlar for delete to authenticated
  using (ekleyen = auth.uid());

-- Yeni mesaj → diğer kişiye telefon bildirimi
create or replace function public.hb_mesaj_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
declare kim text := coalesce(new.ekleyen_ad, 'Eşiniz'); p record; baslik text; metin text;
begin
  if new.tur = 'sistem' then return new; end if;
  baslik := case new.tur when 'istek' then '💸 ' || kim || ' para istiyor: ' || public.hb_tl(new.tutar)
                         when 'yorum' then '💬 ' || kim || ' bir kayda yorum yazdı'
                         else '💬 ' || kim end;
  metin := case when new.tur = 'yorum' and new.ozet is not null then new.ozet || ': ' || new.metin else new.metin end;
  for p in select id, rol from public.hb_profiller where id <> new.ekleyen loop
    if not new.gizli or p.rol = 'yonetici' then
      insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
      values (p.id, baslik, left(coalesce(nullif(metin, ''), 'Yeni mesaj'), 200), 'mesaj', 'mesaj:' || new.id || ':' || p.id)
      on conflict (anahtar) do nothing;
    end if;
  end loop;
  return new;
end $$;
drop trigger if exists hb_mesaj_bildirim on public.hb_mesajlar;
create trigger hb_mesaj_bildirim after insert on public.hb_mesajlar
  for each row execute function public.hb_mesaj_bildirim();

do $$
declare t text;
begin
  foreach t in array array['hb_taksitler','hb_mesajlar'] loop
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end $$;

select 'Güncelleme 7 tamam' as sonuc;
