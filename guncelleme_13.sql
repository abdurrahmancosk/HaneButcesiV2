-- =====================================================================
-- Hane Bütçesi v2.12.2 – Hatice toplam kasayı ve günlük harcama sınırını da görür
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- guncelleme_11 / guncelleme_12'yi çalıştırdıysanız da çalıştırmadıysanız da yalnızca bu dosya yeterlidir
-- (ikisinin içeriği de burada).
--
-- Hatice (üye) GÖRMEZ:  başka kasaların gelirleri ve “Hatice'den gizle” işaretli kayıtlar
-- Hatice GÖRÜR:          toplam kasa ve her kasanın bakiyesi, harcamalar, aktarımlar, faturalar, kart ekstreleri,
--                        düzenli ödemeler, taksitler, birikim hedefleri, borç/alacaklar, altın & döviz, abonelikler
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

-- 5) Kasa bakiyeleri: hanedeki herkes tüm kasaların bakiyesini (toplam kasa) görür
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
  where public.hb_yonetici_mi() or exists (select 1 from public.hb_profiller x where x.id = auth.uid())
  group by p.id, p.ad
  order by p.ad;
$$;
grant execute on function public.hb_bakiyeler() to authenticated;

-- 6) Günlük harcama sınırı iki telefonda aynı çıksın: Hatice'nin göremediği (gizli) bugünkü harcamaların
--    yalnızca toplamı (kayıtların kendisi değil). Fatura / kart ödemeleri sayılmaz (uygulamadaki kuralın aynısı).
create or replace function public.hb_gizli_bugun()
returns numeric
language sql stable security definer set search_path = public as $$
  select coalesce(sum(i.tutar), 0)
  from public.hb_islemler i
  where i.gizli and i.tur = 'Gider'
    and (i.tarih at time zone 'Europe/Istanbul')::date = (now() at time zone 'Europe/Istanbul')::date
    and coalesce(i.kategori, '') not in ('Kira & Aidat & Faturalar', 'Kredi Kartı, Kredi Ödemesi & Borç')
    and coalesce(i.aciklama, '') not in ('Fatura ödemesi', 'Kredi kartı taksidi')
    and exists (select 1 from public.hb_profiller x where x.id = auth.uid());
$$;
grant execute on function public.hb_gizli_bugun() to authenticated;

-- 7) İSTEĞE BAĞLI: Hatice önceden sizin kasanızı hiç görmediği için eski harcamalarınızı gizlememiş olabilirsiniz.
--    Bugüne kadarki KENDİ harcamalarınızın hepsini Hatice'den gizlemek isterseniz (yeni harcamalar yine görünür),
--    alttaki satırın başındaki iki tireyi (--) silip yalnızca o satırı çalıştırın:
-- update public.hb_islemler set gizli = true where tur = 'Gider' and tarih < now() and kasa_sahibi in (select id from public.hb_profiller where rol = 'yonetici');

select 'Güncelleme 13 tamam' as sonuc;
