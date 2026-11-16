-- Hane Bütçesi 2.16: alışveriş listesinde "nereden, ne zaman, ne kadar alındı" bilgisi
-- Supabase > SQL Editor > New query > yapıştır > Run (bir kez). Mevcut veriyi değiştirmez.
alter table public.hb_alisveris add column if not exists islem_id    bigint references public.hb_islemler(id) on delete set null;
alter table public.hb_alisveris add column if not exists alis_yeri   text;
alter table public.hb_alisveris add column if not exists alis_tutar  numeric(14,2);
alter table public.hb_alisveris add column if not exists alis_miktar text;
alter table public.hb_alisveris add column if not exists alan_ad     text;
select 'Güncelleme 14 tamam' as sonuc;
