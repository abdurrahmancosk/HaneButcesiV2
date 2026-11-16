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
