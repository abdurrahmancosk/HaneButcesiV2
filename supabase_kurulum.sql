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
