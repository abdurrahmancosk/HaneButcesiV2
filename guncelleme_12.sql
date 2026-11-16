-- =====================================================================
-- Hane Bütçesi v2.12.1 – Hatice gelirler ve gizlenen kayıtlar dışında her şeyi görür
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- guncelleme_11.sql'i çalıştırdıysanız da çalıştırmadıysanız da yalnızca bu dosya yeterlidir.
--
-- Hatice (üye) GÖRMEZ:  başka kasaların gelirleri, “Hatice'den gizle” işaretli kayıtlar,
--                        kasa bakiyeleri / toplam kasa (yalnızca kendi kasasının bakiyesi)
-- Hatice GÖRÜR:          harcamalar, aktarımlar, faturalar, kart ekstreleri, düzenli ödemeler, taksitler,
--                        birikim hedefleri, borç/alacaklar, altın & döviz, abonelikler, fiş/fatura görselleri
-- Değiştirme yetkisi:    yalnızca kendi eklediği kayıtlar ve kendi kasasına ait olanlar (yönetici hepsini)
-- =====================================================================

-- 1) İşlemler: gelirler (kendi kasası hariç) ve gizli kayıtlar dışında hepsi
drop policy if exists hb_islem_oku on public.hb_islemler;
create policy hb_islem_oku on public.hb_islemler for select to authenticated
  using (public.hb_yonetici_mi()
         or (not gizli and (tur <> 'Gelir' or kasa_sahibi = auth.uid())));

-- 2) Kasa sahibine bağlı tablolar: herkes okur, yalnızca kendi kasasınınkini ekler / değiştirir / siler
do $$
declare t text;
begin
  foreach t in array array['hb_faturalar','hb_duzenli','hb_taksitler','hb_hedefler','hb_borclar',
                           'hb_varliklar','hb_abonelikler'] loop
    execute format('drop policy if exists %I on public.%I', t || '_tum', t);
    execute format('drop policy if exists %I on public.%I', t || '_oku', t);
    execute format('drop policy if exists %I on public.%I', t || '_ekle', t);
    execute format('drop policy if exists %I on public.%I', t || '_guncelle', t);
    execute format('drop policy if exists %I on public.%I', t || '_sil', t);
    execute format('create policy %I on public.%I for select to authenticated using (true)', t || '_oku', t);
    execute format('create policy %I on public.%I for insert to authenticated
                    with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())', t || '_ekle', t);
    execute format('create policy %I on public.%I for update to authenticated
                    using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())
                    with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())', t || '_guncelle', t);
    execute format('create policy %I on public.%I for delete to authenticated
                    using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())', t || '_sil', t);
  end loop;
end $$;

-- 3) Hedeflerde biriken: herkesin hedefi görünür; üyede gizli kayıtlar toplama katılmaz
create or replace function public.hb_hedef_durumlari()
returns table (hedef_id bigint, biriken numeric)
language sql stable security definer set search_path = public as $$
  select h.id,
         coalesce(sum(case when i.tur = 'Gider' then i.tutar when i.tur = 'Gelir' then -i.tutar else 0 end), 0)
  from public.hb_hedefler h
  left join public.hb_islemler i on i.hedef_id = h.id and (not i.gizli or public.hb_yonetici_mi())
  group by h.id;
$$;
grant execute on function public.hb_hedef_durumlari() to authenticated;

-- 4) Fiş / fatura görselleri: görebildiği kaydın görseli açılır (gizli kaydınki açılmaz)
create index if not exists hb_islemler_gorsel_idx on public.hb_islemler (fis_gorsel) where fis_gorsel is not null;
drop policy if exists hb_fis_oku on storage.objects;
create policy hb_fis_oku on storage.objects for select to authenticated
  using (bucket_id = 'hb-fisler' and (
         (storage.foldername(name))[1] = auth.uid()::text
         or public.hb_yonetici_mi()
         or exists (select 1 from public.hb_islemler i where i.fis_gorsel = objects.name)
         or exists (select 1 from public.hb_faturalar f where f.gorsel = objects.name)));

-- 5) İSTEĞE BAĞLI: Hatice önceden sizin kasanızı hiç görmediği için eski harcamalarınızı gizlememiş olabilirsiniz.
--    Bugüne kadarki KENDİ harcamalarınızın hepsini Hatice'den gizlemek isterseniz (yeni harcamalar yine görünür),
--    alttaki satırın başındaki iki tireyi (--) silip yalnızca o satırı çalıştırın:
-- update public.hb_islemler set gizli = true where tur = 'Gider' and tarih < now() and kasa_sahibi in (select id from public.hb_profiller where rol = 'yonetici');

select 'Güncelleme 12 tamam' as sonuc;
