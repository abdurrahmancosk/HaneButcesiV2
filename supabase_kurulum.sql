-- =====================================================================
-- HANE BÜTÇESİ v2  –  Supabase kurulum betiği
-- Supabase Dashboard > SQL Editor > New query  içine yapıştırıp RUN edin.
-- Kullanıcı oluşturmaya gerek yok: şifreler ilk açılışta uygulamadan belirlenir.
-- Betik tekrar çalıştırılabilir (idempotent). Eski "islemler" tablonuza dokunmaz.
-- =====================================================================

-- ---------- 1) Profiller (Abdurrahman = yönetici, Hatice = üye) ----------
create table if not exists public.hb_profiller (
  id            uuid primary key references auth.users(id) on delete cascade,
  kullanici_adi text unique not null,
  ad            text not null,
  rol           text not null default 'uye' check (rol in ('yonetici','uye')),
  olusturma     timestamptz not null default now()
);

create or replace function public.hb_yonetici_mi()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.hb_profiller where id = auth.uid() and rol = 'yonetici');
$$;

-- Yeni auth kullanıcısı oluşturulunca profili otomatik aç
create or replace function public.hb_yeni_kullanici()
returns trigger language plpgsql security definer set search_path = public as $$
declare k text := lower(split_part(new.email, '@', 1));
begin
  if new.email ilike '%@hane.app' then
    insert into public.hb_profiller (id, kullanici_adi, ad, rol)
    values (new.id, k, initcap(k), case when k = 'abdurrahman' then 'yonetici' else 'uye' end)
    on conflict (id) do nothing;
  end if;
  return new;
end $$;

drop trigger if exists hb_yeni_kullanici_tetik on auth.users;
create trigger hb_yeni_kullanici_tetik after insert on auth.users
  for each row execute function public.hb_yeni_kullanici();

-- Kullanıcılar bu betikten ÖNCE oluşturulduysa profillerini şimdi aç
insert into public.hb_profiller (id, kullanici_adi, ad, rol)
select u.id, lower(split_part(u.email,'@',1)), initcap(split_part(u.email,'@',1)),
       case when lower(split_part(u.email,'@',1)) = 'abdurrahman' then 'yonetici' else 'uye' end
from auth.users u
where u.email ilike '%@hane.app'
on conflict (id) do nothing;

-- ---------- 2) İşlemler (gelir / gider / aktarım) ----------
create table if not exists public.hb_islemler (
  id           bigint generated always as identity primary key,
  tur          text not null check (tur in ('Gelir','Gider','Aktarım')),
  tarih        timestamptz not null default now(),
  firma        text,
  urun         text,
  kategori     text,
  miktar       text,
  birim_fiyat  numeric(14,2),
  tutar        numeric(14,2) not null check (tutar >= 0),
  aciklama     text,
  kasa_sahibi  uuid not null references public.hb_profiller(id),   -- paranın çıktığı/girdiği kasa
  hedef_kasa   uuid references public.hb_profiller(id),            -- sadece Aktarım için alıcı kasa
  ekleyen      uuid not null default auth.uid() references public.hb_profiller(id),
  ekleyen_ad   text,
  fis_grup     uuid,                                               -- aynı fişten gelen satırlar
  fis_gorsel   text,                                               -- storage yolu
  eski_id      bigint unique,
  gizli        boolean not null default false,                    -- true: Hatice göremez                                     -- eski uygulamadan aktarılan kaydın no'su
  olusturma    timestamptz not null default now(),
  guncelleme   timestamptz not null default now(),
  constraint hb_aktarim_hedef check ((tur = 'Aktarım') = (hedef_kasa is not null))
);
create index if not exists hb_islemler_tarih_idx on public.hb_islemler (tarih desc);
create index if not exists hb_islemler_kasa_idx  on public.hb_islemler (kasa_sahibi);
create index if not exists hb_islemler_hedef_idx on public.hb_islemler (hedef_kasa);
create index if not exists hb_islemler_fis_idx   on public.hb_islemler (fis_grup);

-- Ekleyen adını sunucu doldursun (taklit edilemesin), güncelleme zamanını tut
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
drop trigger if exists hb_islem_oncesi_tetik on public.hb_islemler;
create trigger hb_islem_oncesi_tetik before insert or update on public.hb_islemler
  for each row execute function public.hb_islem_oncesi();

-- ---------- 3) Ayarlar ve öğrenilen ürün→kategori eşlemeleri ----------
create table if not exists public.hb_ayarlar (
  anahtar text primary key,
  deger   text
);
create table if not exists public.hb_kategori_eslemeleri (
  urun_anahtar text primary key,
  kategori     text not null,
  guncelleme   timestamptz not null default now()
);

-- ---------- 4) Satır düzeyi güvenlik (RLS) ----------
alter table public.hb_profiller           enable row level security;
alter table public.hb_islemler            enable row level security;
alter table public.hb_ayarlar             enable row level security;
alter table public.hb_kategori_eslemeleri enable row level security;

drop policy if exists hb_profil_oku on public.hb_profiller;
create policy hb_profil_oku on public.hb_profiller for select to authenticated using (true);

-- Abdurrahman her şeyi görür; Hatice yalnızca kendi kasasını ve kendisine gelen aktarımları
drop policy if exists hb_islem_oku on public.hb_islemler;
create policy hb_islem_oku on public.hb_islemler for select to authenticated
  using (public.hb_yonetici_mi() or ((kasa_sahibi = auth.uid() or hedef_kasa = auth.uid()) and not gizli));

drop policy if exists hb_islem_ekle on public.hb_islemler;
create policy hb_islem_ekle on public.hb_islemler for insert to authenticated
  with check (public.hb_yonetici_mi() or (kasa_sahibi = auth.uid() and not gizli));

drop policy if exists hb_islem_guncelle on public.hb_islemler;
create policy hb_islem_guncelle on public.hb_islemler for update to authenticated
  using (public.hb_yonetici_mi() or (ekleyen = auth.uid() and not gizli))
  with check (public.hb_yonetici_mi() or (kasa_sahibi = auth.uid() and not gizli));

drop policy if exists hb_islem_sil on public.hb_islemler;
create policy hb_islem_sil on public.hb_islemler for delete to authenticated
  using (public.hb_yonetici_mi() or (ekleyen = auth.uid() and not gizli));

drop policy if exists hb_ayar_oku on public.hb_ayarlar;
create policy hb_ayar_oku on public.hb_ayarlar for select to authenticated using (true);
drop policy if exists hb_ayar_yaz on public.hb_ayarlar;
create policy hb_ayar_yaz on public.hb_ayarlar for all to authenticated
  using (public.hb_yonetici_mi()) with check (public.hb_yonetici_mi());

drop policy if exists hb_esleme_oku on public.hb_kategori_eslemeleri;
create policy hb_esleme_oku on public.hb_kategori_eslemeleri for select to authenticated using (true);
drop policy if exists hb_esleme_ekle on public.hb_kategori_eslemeleri;
create policy hb_esleme_ekle on public.hb_kategori_eslemeleri for insert to authenticated with check (true);
drop policy if exists hb_esleme_guncelle on public.hb_kategori_eslemeleri;
create policy hb_esleme_guncelle on public.hb_kategori_eslemeleri for update to authenticated using (true) with check (true);

-- ---------- 5) Kasa bakiyeleri (tüm zamanlar) ----------
-- Gizli kayıtlar dahil hesaplanır; Hatice yalnızca kendi kasasının toplamını alır.
create or replace function public.hb_bakiyeler()
returns table (kisi uuid, ad text, bakiye numeric)
language sql stable security definer set search_path = public as $$
  select p.id, p.ad,
         coalesce(sum(case
           when i.tur = 'Gelir'   and i.kasa_sahibi = p.id then  i.tutar
           when i.tur = 'Gider'   and i.kasa_sahibi = p.id then -i.tutar
           when i.tur = 'Aktarım' and i.kasa_sahibi = p.id then -i.tutar
           when i.tur = 'Aktarım' and i.hedef_kasa  = p.id then  i.tutar
           else 0 end), 0) as bakiye
  from public.hb_profiller p
  left join public.hb_islemler i on (i.kasa_sahibi = p.id or i.hedef_kasa = p.id)
  where public.hb_yonetici_mi() or p.id = auth.uid()
  group by p.id, p.ad
  order by p.ad;
$$;
grant execute on function public.hb_bakiyeler() to authenticated;

-- ---------- 6) Anlık senkronizasyon (Realtime) ----------
do $$ begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'hb_islemler') then
    alter publication supabase_realtime add table public.hb_islemler;
  end if;
end $$;

-- ---------- 7) Fiş görselleri için özel depolama alanı ----------
insert into storage.buckets (id, name, public)
values ('hb-fisler', 'hb-fisler', false)
on conflict (id) do nothing;

drop policy if exists hb_fis_yukle on storage.objects;
create policy hb_fis_yukle on storage.objects for insert to authenticated
  with check (bucket_id = 'hb-fisler' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists hb_fis_oku on storage.objects;
create policy hb_fis_oku on storage.objects for select to authenticated
  using (bucket_id = 'hb-fisler' and ((storage.foldername(name))[1] = auth.uid()::text or public.hb_yonetici_mi()));

drop policy if exists hb_fis_sil on storage.objects;
create policy hb_fis_sil on storage.objects for delete to authenticated
  using (bucket_id = 'hb-fisler' and ((storage.foldername(name))[1] = auth.uid()::text or public.hb_yonetici_mi()));

-- ---------- 9) Uygulama içinden ilk şifre belirleme ----------
-- Abdurrahman ve Hatice hesabı yoksa, uygulamanın giriş ekranından şifre belirlenerek oluşturulur.
-- Hesap bir kez oluştuktan sonra bu fonksiyon o kullanıcı için bir daha çalışmaz.
create extension if not exists pgcrypto with schema extensions;

create or replace function public.hb_kurulum_durumu()
returns table (kullanici_adi text, hazir boolean)
language sql stable security definer set search_path = public, auth as $$
  select k, exists (select 1 from auth.users u where lower(u.email) = k || '@hane.app')
  from unnest(array['abdurrahman','hatice']) as k;
$$;

create or replace function public.hb_ilk_sifre(p_kullanici text, p_sifre text)
returns text
language plpgsql security definer set search_path = public, auth, extensions as $$
declare
  k text := lower(trim(p_kullanici));
  e text;
  yeni uuid := gen_random_uuid();
begin
  if k not in ('abdurrahman','hatice') then
    raise exception 'Geçersiz kullanıcı';
  end if;
  if length(coalesce(p_sifre,'')) < 6 then
    raise exception 'Şifre en az 6 karakter olmalı';
  end if;
  e := k || '@hane.app';
  if exists (select 1 from auth.users where lower(email) = e) then
    raise exception 'Bu kullanıcının şifresi zaten belirlenmiş';
  end if;

  insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
                          raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
                          confirmation_token, email_change, email_change_token_new, recovery_token)
  values ('00000000-0000-0000-0000-000000000000', yeni, 'authenticated', 'authenticated', e,
          crypt(p_sifre, gen_salt('bf')), now(),
          '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now(), '', '', '', '');

  insert into auth.identities (id, user_id, provider_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
  values (gen_random_uuid(), yeni, yeni::text,
          jsonb_build_object('sub', yeni::text, 'email', e, 'email_verified', true),
          'email', now(), now(), now());

  return e;  -- profil, auth.users tetikleyicisiyle otomatik açılır
end $$;

revoke all on function public.hb_ilk_sifre(text, text) from public;
grant execute on function public.hb_ilk_sifre(text, text) to anon, authenticated;
grant execute on function public.hb_kurulum_durumu() to anon, authenticated;

-- ---------- 8) Başlangıç verileri (mevcut uygulamanızdan aktarıldı) ----------
insert into public.hb_ayarlar (anahtar, deger) values
  ('kategoriler', '["Market & Temel Gıda", "Abur Cubur & Atıştırmalık", "Kira & Aidat & Faturalar", "Ev", "Temizlik & Hijyen & Kişisel Bakım", "Giyim, Ayakkabı & Aksesuar", "Sağlık, İlaç & Medikal", "Eğitim, Okul & Kırtasiye", "Ulaşım & Toplu Taşıma", "Dışarıda Yemek & Kafe & Restoran", "Eğlence, Kültür & Etkinlik", "Elektronik & Teknoloji", "Ev Eşyası & Mobilya & Beyaz Eşya", "Tadilat, Tamirat & Yapı Market", "Evcil Hayvan (Pamuk)", "Sigara/Tütün", "Tatil & Seyahat & Konaklama", "Hediye, Bağış & Yardımlaşma", "Kredi Kartı, Kredi Ödemesi & Borç", "Vergi, Harç & Resmi İşlemler", "Transfer / Birikim", "Yatırım & Altın & Döviz", "Poşet", "Oyuncak", "Sağlık", "Dışarıda Yemek / Eğlence", "Yardım", "Diğer"]'),
  ('gelir_turleri', '["Maaş", "Ek Gelir", "Kira Geliri", "Prim / İkramiye", "Borç Tahsilatı", "Hediye", "Açılış Bakiyesi", "Diğer Gelir"]')
on conflict (anahtar) do nothing;

insert into public.hb_kategori_eslemeleri (urun_anahtar, kategori) values
  ('tema plastik poset', 'Poşet'),
  ('alişveriş poşeti bim', 'Poşet'),
  ('alisveris poseti bim', 'Poşet'),
  ('alişveriş poşeti', 'Poşet'),
  ('tk market poset', 'Poşet'),
  ('alisveris poseti', 'Poşet'),
  ('buyuk çay', 'Eğitim, Okul & Kırtasiye'),
  ('kasarli tost', 'Eğitim, Okul & Kırtasiye'),
  ('okul harcligi (2 çocuk)', 'Eğitim, Okul & Kırtasiye'),
  ('29 ekim bayrak', 'Eğitim, Okul & Kırtasiye'),
  ('çay', 'Eğitim, Okul & Kırtasiye'),
  ('ayran', 'Eğitim, Okul & Kırtasiye'),
  ('okul kitaplari (oglum)', 'Eğitim, Okul & Kırtasiye'),
  ('kofte', 'Eğitim, Okul & Kırtasiye'),
  ('simit', 'Eğitim, Okul & Kırtasiye'),
  ('4-6 yas kurs aidati (15 eyl-15 kas)', 'Eğitim, Okul & Kırtasiye'),
  ('2. sinif kitap seti', 'Eğitim, Okul & Kırtasiye'),
  ('2. sinif deneme seti', 'Eğitim, Okul & Kırtasiye'),
  ('gondol tasty beslenme kabi', 'Eğitim, Okul & Kırtasiye'),
  ('çinar 72904 a4 sp 60yp', 'Eğitim, Okul & Kırtasiye'),
  ('tost', 'Eğitim, Okul & Kırtasiye'),
  ('kahve + su', 'Eğitim, Okul & Kırtasiye'),
  ('resimli türkçe sözlük', 'Eğitim, Okul & Kırtasiye'),
  ('ottonya lisansli çitçi', 'Eğitim, Okul & Kırtasiye'),
  ('legan beslenme çantasi', 'Eğitim, Okul & Kırtasiye'),
  ('gözde okul peçetesi', 'Eğitim, Okul & Kırtasiye'),
  ('fixpoint a4 renkli fot', 'Eğitim, Okul & Kırtasiye'),
  ('fatih f12 12 renk sulu', 'Eğitim, Okul & Kırtasiye'),
  ('pansiyon çay parasi', 'Eğitim, Okul & Kırtasiye'),
  ('deneme sinavi ücreti (kizim)', 'Eğitim, Okul & Kırtasiye'),
  ('m9 plus anycast hdmi goruntu aktarici', 'Eğitim, Okul & Kırtasiye'),
  ('kirmizi tahta kalemi', 'Eğitim, Okul & Kırtasiye'),
  ('soru bankasi (2. sinif)', 'Eğitim, Okul & Kırtasiye'),
  ('çinar 33000 spralli re', 'Eğitim, Okul & Kırtasiye'),
  ('südor para bandi(11x10)', 'Eğitim, Okul & Kırtasiye'),
  ('fatih 20 gr glue stick', 'Eğitim, Okul & Kırtasiye'),
  ('gezer patik panduf 336', 'Eğitim, Okul & Kırtasiye'),
  ('fatih 12 renk üçgen ju', 'Eğitim, Okul & Kırtasiye'),
  ('okul kiyafeti', 'Eğitim, Okul & Kırtasiye'),
  ('abc imla yazim klavuzu', 'Eğitim, Okul & Kırtasiye'),
  ('kutuphane katki payi (kizim)', 'Eğitim, Okul & Kırtasiye'),
  ('emir hattaba kitap', 'Eğitim, Okul & Kırtasiye'),
  ('motorin', 'Ulaşım & Toplu Taşıma'),
  ('bingo sivi det (3 litre)', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('peçete 200 lü', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('hij.ped normal 20 li', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('molped pure-soft uzun 18li', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('agarta marka dis macunu', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('sivi sabun 750ml işil', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('günlük ped 20 li', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('bebek şampuani 900ml', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('soda plus 500 g miss', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('pipet ve islak mendil', 'Temizlik & Hijyen & Kişisel Bakım'),
  ('tübitak borcu ödemesi', 'Kredi Kartı, Kredi Ödemesi & Borç'),
  ('kredi karti borcu', 'Kredi Kartı, Kredi Ödemesi & Borç'),
  ('lastik (3 cm eninde - 10 metre)', 'Giyim, Ayakkabı & Aksesuar'),
  ('lastik (20 cm)', 'Giyim, Ayakkabı & Aksesuar'),
  ('ucan kalem (terzi malzemesi)', 'Giyim, Ayakkabı & Aksesuar'),
  ('geoder cetvel (terzi malzemesi)', 'Giyim, Ayakkabı & Aksesuar'),
  ('basortu (kizim)', 'Giyim, Ayakkabı & Aksesuar'),
  ('takke (ogluma)', 'Giyim, Ayakkabı & Aksesuar'),
  ('yelek dugmesi', 'Giyim, Ayakkabı & Aksesuar'),
  ('çocuk giyim takimi', 'Giyim, Ayakkabı & Aksesuar'),
  ('kulaklik (soguktan korunma)', 'Giyim, Ayakkabı & Aksesuar'),
  ('tac', 'Giyim, Ayakkabı & Aksesuar'),
  ('seher yildizi alt çamasir (6 numara)', 'Giyim, Ayakkabı & Aksesuar'),
  ('termal tayt', 'Giyim, Ayakkabı & Aksesuar'),
  ('saris''e ayakkabi', 'Giyim, Ayakkabı & Aksesuar'),
  ('anneme mes ve lastik', 'Giyim, Ayakkabı & Aksesuar'),
  ('3''lu kiz çocuk kulotlu çorap', 'Giyim, Ayakkabı & Aksesuar'),
  ('3''lu çocuk çorap', 'Giyim, Ayakkabı & Aksesuar'),
  ('çocuk kulotlu çorap', 'Giyim, Ayakkabı & Aksesuar'),
  ('buyuk ucan kalem (terzi malzemesi)', 'Giyim, Ayakkabı & Aksesuar'),
  ('erkek çocuk tayt', 'Giyim, Ayakkabı & Aksesuar'),
  ('külot kadin 3''lü', 'Giyim, Ayakkabı & Aksesuar'),
  ('askili atlet kadin', 'Giyim, Ayakkabı & Aksesuar'),
  ('beyaz alpaka kumas', 'Giyim, Ayakkabı & Aksesuar'),
  ('kiz çocuk tayt', 'Giyim, Ayakkabı & Aksesuar'),
  ('çift tarafli tela (yarim metre)', 'Giyim, Ayakkabı & Aksesuar'),
  ('krt çinar resim defteri', 'Eğitim, Okul & Kırtasiye')
on conflict (urun_anahtar) do nothing;


-- ====================== (Güncelleme 3 içeriği) ======================


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


-- ====================== (Güncelleme 4 içeriği) ======================


do $$ begin
  create extension if not exists pg_net;
exception when others then raise notice 'pg_net kurulamadı: %', sqlerrm;
end $$;

create or replace function public.hb_tl(x numeric) returns text language sql immutable as $$
  select translate(to_char(x, 'FM999,999,999,990.00'), ',.', '.,') || ' ₺';
$$;

-- ---------- Bildirim kutusu ----------
create table if not exists public.hb_bildirimler (
  id         bigint generated always as identity primary key,
  alici      uuid not null references public.hb_profiller(id) on delete cascade,
  baslik     text not null,
  metin      text,
  tur        text not null default 'bilgi',      -- islem, fis, alisveris, fatura, hatirlatma
  anahtar    text unique,                        -- aynı bildirimin ikinci kez üretilmesini engeller
  okundu     boolean not null default false,
  olusturma  timestamptz not null default now()
);
create index if not exists hb_bildirim_alici_idx on public.hb_bildirimler (alici, okundu, olusturma desc);
alter table public.hb_bildirimler enable row level security;
drop policy if exists hb_bildirim_kendi on public.hb_bildirimler;
create policy hb_bildirim_kendi on public.hb_bildirimler for all to authenticated
  using (alici = auth.uid()) with check (alici = auth.uid());

-- ---------- Gizli ayarlar (istemciler OKUYAMAZ: politika yok) ----------
create table if not exists public.hb_gizli (anahtar text primary key, deger text);
alter table public.hb_gizli enable row level security;

create or replace function public.hb_push_ayarla(p_app_id text, p_api_key text)
returns text language plpgsql security definer set search_path = public as $$
begin
  if not public.hb_yonetici_mi() then raise exception 'Yetkisiz'; end if;
  insert into public.hb_gizli values ('onesignal_app_id', nullif(trim(p_app_id), ''))
    on conflict (anahtar) do update set deger = excluded.deger;
  if coalesce(trim(p_api_key), '') <> '' then
    insert into public.hb_gizli values ('onesignal_api_key', trim(p_api_key))
      on conflict (anahtar) do update set deger = excluded.deger;
  end if;
  insert into public.hb_ayarlar values ('onesignal_app_id', nullif(trim(p_app_id), ''))
    on conflict (anahtar) do update set deger = excluded.deger;
  return 'ok';
end $$;
grant execute on function public.hb_push_ayarla(text, text) to authenticated;

create or replace function public.hb_push_durumu()
returns boolean language sql stable security definer set search_path = public as $$
  select public.hb_yonetici_mi() and exists (select 1 from public.hb_gizli where anahtar = 'onesignal_api_key' and deger is not null)
     and exists (select 1 from public.hb_gizli where anahtar = 'onesignal_app_id' and deger is not null);
$$;
grant execute on function public.hb_push_durumu() to authenticated;

-- ---------- Bildirim eklenince telefona gönder (OneSignal ayarlıysa) ----------
create or replace function public.hb_bildirim_push()
returns trigger language plpgsql security definer set search_path = public, extensions as $$
declare
  app text := (select deger from public.hb_gizli where anahtar = 'onesignal_app_id');
  anahtar_ text := (select deger from public.hb_gizli where anahtar = 'onesignal_api_key');
begin
  if app is null or anahtar_ is null then return new; end if;
  begin
    perform net.http_post(
      url := 'https://api.onesignal.com/notifications?c=push',
      headers := jsonb_build_object('Content-Type', 'application/json', 'Authorization', 'Key ' || anahtar_),
      body := jsonb_build_object(
        'app_id', app,
        'target_channel', 'push',
        'include_aliases', jsonb_build_object('external_id', jsonb_build_array(new.alici::text)),
        'headings', jsonb_build_object('en', new.baslik, 'tr', new.baslik),
        'contents', jsonb_build_object('en', coalesce(new.metin, new.baslik), 'tr', coalesce(new.metin, new.baslik)),
        'android_group', 'hane-butcesi',
        'data', jsonb_build_object('bildirim_id', new.id, 'tur', new.tur)));
  exception when others then
    raise warning 'Push gönderilemedi: %', sqlerrm;   -- bildirim yine de uygulama içinde görünür
  end;
  return new;
end $$;
drop trigger if exists hb_bildirim_push_tetik on public.hb_bildirimler;
create trigger hb_bildirim_push_tetik after insert on public.hb_bildirimler
  for each row execute function public.hb_bildirim_push();

-- Yardımcı: bir kaydı görebilecek diğer kullanıcılara bildirim yaz
create or replace function public.hb_bildir(p_kaynak uuid, p_sahip uuid, p_hedef uuid, p_gizli boolean,
                                            p_baslik text, p_metin text, p_tur text, p_anahtar text)
returns void language plpgsql security definer set search_path = public as $$
declare p record;
begin
  for p in select id, rol from public.hb_profiller where id <> coalesce(p_kaynak, '00000000-0000-0000-0000-000000000000') loop
    if p.rol = 'yonetici' or ((p_sahip = p.id or p_hedef = p.id) and not coalesce(p_gizli, false)) then
      insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
      values (p.id, p_baslik, p_metin, p_tur, case when p_anahtar is null then null else p_anahtar || ':' || p.id end)
      on conflict (anahtar) do nothing;
    end if;
  end loop;
end $$;

-- ---------- İşlem eklenince ----------
create or replace function public.hb_islem_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
declare kim text := coalesce(new.ekleyen_ad, 'Biri');
begin
  if new.eski_id is not null then return new; end if;            -- eski veri aktarımında bildirim yok
  if new.fis_grup is not null then
    perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, new.hedef_kasa, new.gizli,
      '🧾 ' || kim || ' fiş ekledi', coalesce(new.firma, 'Market') || ' alışverişi kaydedildi', 'fis', 'fis:' || new.fis_grup);
  elsif new.tur = 'Aktarım' then
    perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, new.hedef_kasa, new.gizli,
      '💸 Para aktarımı', kim || ': ' || public.hb_tl(new.tutar), 'islem', 'islem:' || new.id);
  else
    perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, new.hedef_kasa, new.gizli,
      case when new.tur = 'Gelir' then '💰 ' else '🛍️ ' end || kim || ' ' || lower(new.tur) || ' ekledi',
      coalesce(new.urun, new.kategori, '') || coalesce(' • ' || new.firma, '') || ' • ' ||
        public.hb_tl(new.tutar), 'islem', 'islem:' || new.id);
  end if;
  return new;
end $$;
drop trigger if exists hb_islem_bildirim_tetik on public.hb_islemler;
create trigger hb_islem_bildirim_tetik after insert on public.hb_islemler
  for each row execute function public.hb_islem_bildirim();

-- ---------- Alışveriş listesine ürün eklenince ----------
create or replace function public.hb_alisveris_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
  select p.id, '🛒 ' || coalesce(new.ekleyen_ad, 'Biri') || ' listeye ekledi',
         new.urun || coalesce(' (' || new.miktar || ')', ''), 'alisveris', 'liste:' || new.id || ':' || p.id
  from public.hb_profiller p where p.id <> new.ekleyen
  on conflict (anahtar) do nothing;
  return new;
end $$;
drop trigger if exists hb_alisveris_bildirim_tetik on public.hb_alisveris;
create trigger hb_alisveris_bildirim_tetik after insert on public.hb_alisveris
  for each row execute function public.hb_alisveris_bildirim();

-- ---------- Fatura yüklenince ----------
create or replace function public.hb_fatura_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, null, false,
    '🧾 ' || coalesce(new.ekleyen_ad, 'Biri') || ' ' || new.tur || ' faturası yükledi',
    public.hb_tl(new.tutar) || coalesce(' • son ödeme ' || to_char(new.son_odeme, 'DD.MM.YYYY'), ''),
    'fatura', 'fatura-yeni:' || new.id);
  return new;
end $$;
drop trigger if exists hb_fatura_bildirim_tetik on public.hb_faturalar;
create trigger hb_fatura_bildirim_tetik after insert on public.hb_faturalar
  for each row execute function public.hb_fatura_bildirim();

-- ---------- Günlük hatırlatmalar (son ödemeden 1 gün önce ve gününde) ----------
create or replace function public.hb_hatirlatmalari_uret()
returns int language plpgsql security definer set search_path = public as $$
declare
  bugun date := (now() at time zone 'Europe/Istanbul')::date;
  f record; d record; p record; adet int := 0; gun int;
begin
  for f in select * from public.hb_faturalar where not odendi and son_odeme in (bugun, bugun + 1) loop
    for p in select id from public.hb_profiller where id = f.kasa_sahibi or rol = 'yonetici' loop
      insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
      values (p.id, '⏰ ' || f.tur || ' faturası: son ödeme ' || case when f.son_odeme = bugun then 'BUGÜN' else 'YARIN' end,
              coalesce(f.kurum || ' • ', '') || public.hb_tl(f.tutar), 'hatirlatma',
              'hat-fatura:' || f.id || ':' || bugun || ':' || p.id)
      on conflict (anahtar) do nothing;
      adet := adet + 1;
    end loop;
  end loop;
  for d in select * from public.hb_duzenli where aktif
           and coalesce(son_odenen, '') <> to_char(bugun, 'YYYY-MM') loop
    gun := least(d.gun, extract(day from (date_trunc('month', bugun) + interval '1 month - 1 day'))::int);
    if gun in (extract(day from bugun)::int, extract(day from bugun + 1)::int) then
      for p in select id from public.hb_profiller where id = d.kasa_sahibi or rol = 'yonetici' loop
        insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
        values (p.id, '⏰ ' || d.ad || ' ödemesi ' || case when gun = extract(day from bugun)::int then 'bugün' else 'yarın' end,
                public.hb_tl(d.tutar), 'hatirlatma', 'hat-duzenli:' || d.id || ':' || bugun || ':' || p.id)
        on conflict (anahtar) do nothing;
        adet := adet + 1;
      end loop;
    end if;
  end loop;
  return adet;
end $$;
grant execute on function public.hb_hatirlatmalari_uret() to authenticated;

-- Her gün 09:00 (Türkiye) = 06:00 UTC. pg_cron yoksa uygulama açılışında da çağrılır.
do $$
begin
  create extension if not exists pg_cron;
  perform cron.unschedule(jobid) from cron.job where jobname = 'hb-hatirlatma';
  perform cron.schedule('hb-hatirlatma', '0 6 * * *', 'select public.hb_hatirlatmalari_uret()');
exception when others then
  raise notice 'pg_cron kullanılamadı (%); hatırlatmalar uygulama açılınca üretilecek.', sqlerrm;
end $$;

-- ---------- Anlık senkron ----------
do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime'
                 and schemaname = 'public' and tablename = 'hb_bildirimler') then
    alter publication supabase_realtime add table public.hb_bildirimler;
  end if;
end $$;

select 'Güncelleme 4 tamam' as sonuc;


-- ===================================================== Güncelleme 5 (v2.4)
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


-- ===================================================== Güncelleme 6 (v2.5)
-- =====================================================================
-- Hane Bütçesi v2.5 – marketlerin aktüel katalogları + Erzurum kuyumcu fiyatı
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- =====================================================================

-- ---------- 1) Aktüel (haftalık indirim) ürünleri – iki telefon ortak kullanır ----------
create table if not exists public.hb_aktuel (
  id         bigint generated always as identity primary key,
  market     text not null,
  urun       text not null,
  fiyat      numeric(12,2) not null check (fiyat > 0),
  bas        date not null,
  bit        date not null,
  olusturma  timestamptz not null default now()
);
create unique index if not exists hb_aktuel_tekil on public.hb_aktuel (market, urun, bas);
create index if not exists hb_aktuel_bit on public.hb_aktuel (bit);
alter table public.hb_aktuel enable row level security;
drop policy if exists hb_aktuel_tum on public.hb_aktuel;
create policy hb_aktuel_tum on public.hb_aktuel for all to authenticated using (true) with check (true);

-- ---------- 2) Alışveriş listesindeki ürün aktüelde ise ikinize bildirim ----------
create or replace function public.hb_aktuel_duyur(p_baslik text, p_metin text, p_anahtar text)
returns int language plpgsql security definer set search_path = public as $$
declare n int := 0; p record;
begin
  for p in select id from public.hb_profiller loop
    insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
    values (p.id, p_baslik, p_metin, 'aktuel', 'aktuel:' || p_anahtar || ':' || p.id)
    on conflict (anahtar) do nothing;
    if found then n := n + 1; end if;
  end loop;
  return n;
end $$;
grant execute on function public.hb_aktuel_duyur(text, text, text) to authenticated;

-- ---------- 3) Süresi geçen aktüelleri temizle ----------
create or replace function public.hb_aktuel_temizle()
returns int language sql security definer set search_path = public as $$
  with s as (delete from public.hb_aktuel where bit < public.hb_bugun() - 3 returning 1) select count(*)::int from s;
$$;
grant execute on function public.hb_aktuel_temizle() to authenticated;

do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'hb_aktuel') then
    alter publication supabase_realtime add table public.hb_aktuel;
  end if;
end $$;

select 'Güncelleme 6 tamam' as sonuc;


-- ===================================================== Güncelleme 7 (v2.7)
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

-- ---------- Faturaya harcama kategorisi ----------
alter table public.hb_faturalar add column if not exists kategori text;


-- ===================================================== Güncelleme 8 (v2.8)
-- =====================================================================
-- Hane Bütçesi v2.8 – e-postadan otomatik fatura takibi + abonelikler
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- =====================================================================

-- Aynı e-postadaki fatura iki kez eklenmesin (telefon ve bilgisayar aynı anda tarasa bile)
alter table public.hb_faturalar add column if not exists mail_id text;
alter table public.hb_faturalar add column if not exists kategori text;
create unique index if not exists hb_faturalar_mail_id on public.hb_faturalar (mail_id);

-- Abonelikler: su, doğalgaz, elektrik, internet, telefon… (abone no ile fatura eşleştirme, "fatura gelmedi" uyarısı)
create table if not exists public.hb_abonelikler (
  id            bigint generated always as identity primary key,
  tur           text not null,
  kurum         text,
  abone_no      text,
  beklenen_gun  int check (beklenen_gun between 1 and 31),   -- faturanın genelde geldiği gün
  kasa_sahibi   uuid not null references public.hb_profiller(id),
  aktif         boolean not null default true,
  not_          text,
  ekleyen       uuid not null default auth.uid() references public.hb_profiller(id),
  ekleyen_ad    text,
  olusturma     timestamptz not null default now()
);
drop trigger if exists hb_abonelikler_ekleyen on public.hb_abonelikler;
create trigger hb_abonelikler_ekleyen before insert or update on public.hb_abonelikler
  for each row execute function public.hb_ekleyen_doldur();
alter table public.hb_abonelikler enable row level security;
drop policy if exists hb_abonelikler_tum on public.hb_abonelikler;
create policy hb_abonelikler_tum on public.hb_abonelikler for all to authenticated
  using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())
  with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid());

do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'hb_abonelikler') then
    alter publication supabase_realtime add table public.hb_abonelikler;
  end if;
end $$;

select 'Güncelleme 8 tamam' as sonuc;


-- ===================================================== Güncelleme 9 (v2.9)
-- =====================================================================
-- Hane Bütçesi v2.9 – kurum sayfasından otomatik borç sorgusu (ESKİ su)
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- =====================================================================
alter table public.hb_abonelikler add column if not exists baglanti   text;         -- 'eski' = ESKİ borç sorgu sayfası
alter table public.hb_abonelikler add column if not exists musteri_no text;
alter table public.hb_abonelikler add column if not exists son_sorgu  timestamptz;
alter table public.hb_abonelikler add column if not exists son_borc   numeric(14,2);
alter table public.hb_abonelikler add column if not exists son_bilgi  text;
select 'Güncelleme 9 tamam' as sonuc;


-- ===================================================== Güncelleme 10 (v2.11)
-- =====================================================================
-- Hane Bütçesi v2.11 – kredi kartı ekstresi: gelecek ay tahminleri için bildirim gönderme
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- Çalıştırmasanız da uygulama çalışır; yalnızca Hatice ekstre yüklediğinde her tahmini ay için
-- ayrı "fatura yükledi" bildirimi gider.
-- =====================================================================
create or replace function public.hb_fatura_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if coalesce(new.mail_id, '') like 'ekstre:%:tahmin' then
    return new;  -- ekstredeki kalan taksitlerden üretilen gelecek ay tahmini: bildirim yok
  end if;
  perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, null, false,
    case when new.tur = 'Kredi kartı'
         then '💳 ' || coalesce(new.ekleyen_ad, 'Biri') || ' kart ekstresi yükledi'
         else '🧾 ' || coalesce(new.ekleyen_ad, 'Biri') || ' ' || new.tur || ' faturası yükledi' end,
    public.hb_tl(new.tutar) || coalesce(' • son ödeme ' || to_char(new.son_odeme, 'DD.MM.YYYY'), ''),
    'fatura', 'fatura-yeni:' || new.id);
  return new;
end $$;
select 'Güncelleme 10 tamam' as sonuc;
