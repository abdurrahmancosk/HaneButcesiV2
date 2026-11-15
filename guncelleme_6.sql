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
