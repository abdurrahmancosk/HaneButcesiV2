-- =====================================================================
-- HANE BÜTÇESİ v2 – GÜNCELLEME 3
-- Bütçe limitleri, birikim hedefleri, faturalar + hatırlatıcılar, düzenli ödemeler,
-- ortak alışveriş listesi, borç/alacak.
-- Supabase > SQL Editor > New query > tamamını yapıştır > Run. Tekrar çalıştırmak güvenlidir.
-- =====================================================================

-- Ortak: ekleyen + ekleyen adı sunucu tarafından doldurulur
create or replace function public.hb_ekleyen_doldur()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if auth.uid() is not null then new.ekleyen := auth.uid(); end if;
    new.ekleyen_ad := (select ad from public.hb_profiller where id = new.ekleyen);
  else
    new.ekleyen := old.ekleyen;
    new.ekleyen_ad := old.ekleyen_ad;
  end if;
  return new;
end $$;

-- ---------- 1) Kategori bütçe limitleri (dönem başına) ----------
create table if not exists public.hb_butceler (
  kategori    text primary key,
  limit_tutar numeric(14,2) not null check (limit_tutar > 0),
  guncelleme  timestamptz not null default now()
);
alter table public.hb_butceler enable row level security;
drop policy if exists hb_butce_oku on public.hb_butceler;
create policy hb_butce_oku on public.hb_butceler for select to authenticated using (true);
drop policy if exists hb_butce_yaz on public.hb_butceler;
create policy hb_butce_yaz on public.hb_butceler for all to authenticated
  using (public.hb_yonetici_mi()) with check (public.hb_yonetici_mi());

-- ---------- 2) Birikim hedefleri ----------
create table if not exists public.hb_hedefler (
  id           bigint generated always as identity primary key,
  ad           text not null,
  hedef_tutar  numeric(14,2) not null check (hedef_tutar > 0),
  hedef_tarih  date,
  simge        text,
  kasa_sahibi  uuid not null references public.hb_profiller(id),
  kapandi      boolean not null default false,
  olusturma    timestamptz not null default now()
);
alter table public.hb_islemler add column if not exists hedef_id bigint references public.hb_hedefler(id) on delete set null;

-- ---------- 3) Faturalar ----------
create table if not exists public.hb_faturalar (
  id            bigint generated always as identity primary key,
  tur           text not null,                 -- Elektrik, Su, Doğalgaz, İnternet, Telefon, Aidat, Kira, Diğer
  kurum         text,
  abone_no      text,
  donem         text,                          -- örn. "Ekim 2026"
  fatura_tarihi date,
  son_odeme     date,
  tuketim       numeric(14,3),
  birim         text,                          -- kWh, m³, GB ...
  birim_fiyat   numeric(14,4),
  tutar         numeric(14,2) not null check (tutar >= 0),
  gorsel        text,
  analiz        text,                          -- önceki faturayla karşılaştırma notu
  odendi        boolean not null default false,
  odeme_islem_id bigint references public.hb_islemler(id) on delete set null,
  kasa_sahibi   uuid not null references public.hb_profiller(id),
  ekleyen       uuid not null default auth.uid() references public.hb_profiller(id),
  ekleyen_ad    text,
  olusturma     timestamptz not null default now()
);
drop trigger if exists hb_fatura_ekleyen on public.hb_faturalar;
create trigger hb_fatura_ekleyen before insert or update on public.hb_faturalar
  for each row execute function public.hb_ekleyen_doldur();

-- ---------- 4) Düzenli ödemeler (kira, aidat... tutarı güncellenebilir) ----------
create table if not exists public.hb_duzenli (
  id            bigint generated always as identity primary key,
  ad            text not null,
  kategori      text not null default 'Kira & Aidat & Faturalar',
  tutar         numeric(14,2) not null check (tutar > 0),
  gun           int not null check (gun between 1 and 31),   -- ayın kaçında ödenir
  kasa_sahibi   uuid not null references public.hb_profiller(id),
  aktif         boolean not null default true,
  son_odenen    text,                                        -- 'YYYY-MM' (son ödendiği ay)
  olusturma     timestamptz not null default now()
);

-- ---------- 5) Ortak alışveriş listesi ----------
create table if not exists public.hb_alisveris (
  id          bigint generated always as identity primary key,
  urun        text not null,
  miktar      text,
  ekleyen     uuid not null default auth.uid() references public.hb_profiller(id),
  ekleyen_ad  text,
  alindi      boolean not null default false,
  alinma      timestamptz,
  olusturma   timestamptz not null default now()
);
drop trigger if exists hb_alisveris_ekleyen on public.hb_alisveris;
create trigger hb_alisveris_ekleyen before insert or update on public.hb_alisveris
  for each row execute function public.hb_ekleyen_doldur();

-- ---------- 6) Borç / alacak ----------
create table if not exists public.hb_borclar (
  id           bigint generated always as identity primary key,
  kisi         text not null,
  yon          text not null check (yon in ('verdim','aldim')),   -- verdim = alacağım var, aldim = borcum var
  tutar        numeric(14,2) not null check (tutar > 0),
  aciklama     text,
  tarih        date not null default current_date,
  vade         date,
  kapandi      boolean not null default false,
  kapanis      timestamptz,
  kasa_sahibi  uuid not null references public.hb_profiller(id),
  olusturma    timestamptz not null default now()
);

-- ---------- RLS ----------
alter table public.hb_hedefler  enable row level security;
alter table public.hb_faturalar enable row level security;
alter table public.hb_duzenli   enable row level security;
alter table public.hb_alisveris enable row level security;
alter table public.hb_borclar   enable row level security;

do $$
declare t text;
begin
  -- Sahip bazlı tablolar: Abdurrahman hepsini, Hatice yalnızca kendi kasasına ait olanları görür/düzenler
  foreach t in array array['hb_hedefler','hb_faturalar','hb_duzenli','hb_borclar'] loop
    execute format('drop policy if exists %I on public.%I', t || '_tum', t);
    execute format('create policy %I on public.%I for all to authenticated
                    using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())
                    with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())', t || '_tum', t);
  end loop;
end $$;

-- Alışveriş listesi ortaktır: ikisi de görür ve düzenler
drop policy if exists hb_alisveris_tum on public.hb_alisveris;
create policy hb_alisveris_tum on public.hb_alisveris for all to authenticated using (true) with check (true);

-- ---------- Hedef durumları (birikmiş tutar) ----------
create or replace function public.hb_hedef_durumlari()
returns table (hedef_id bigint, biriken numeric)
language sql stable security definer set search_path = public as $$
  select h.id,
         coalesce(sum(case when i.tur = 'Gider' then i.tutar when i.tur = 'Gelir' then -i.tutar else 0 end), 0)
  from public.hb_hedefler h
  left join public.hb_islemler i on i.hedef_id = h.id
  where public.hb_yonetici_mi() or h.kasa_sahibi = auth.uid()
  group by h.id;
$$;
grant execute on function public.hb_hedef_durumlari() to authenticated;

-- ---------- Fiyat geçmişi (tüm zamanlar, sadece gerekli sütunlar) ----------
create or replace function public.hb_fiyat_gecmisi()
returns table (urun text, firma text, tarih timestamptz, miktar text, birim_fiyat numeric, tutar numeric)
language sql stable security invoker set search_path = public as $$
  select urun, firma, tarih, miktar, birim_fiyat, tutar
  from public.hb_islemler
  where tur = 'Gider' and urun is not null and tutar > 0
  order by tarih desc
  limit 20000;
$$;
grant execute on function public.hb_fiyat_gecmisi() to authenticated;

-- ---------- Anlık senkron ----------
do $$
declare t text;
begin
  foreach t in array array['hb_alisveris','hb_faturalar','hb_duzenli','hb_borclar','hb_hedefler'] loop
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end $$;

select 'Güncelleme 3 tamam' as sonuc;
