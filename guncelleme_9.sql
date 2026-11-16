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
