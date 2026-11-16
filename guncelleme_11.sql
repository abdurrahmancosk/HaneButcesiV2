-- =====================================================================
-- Hane Bütçesi v2.12 – Hatice hanenin tüm harcamalarını ve faturalarını görür
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
--
-- Hatice (üye) artık görür:   kendi kasasındaki her şey + kendisine gelen aktarımlar
--                              + HERKESİN gizli işaretlenmemiş giderleri
--                              + tüm faturalar (ödenen / ödenecek, kart ekstreleri dahil)
--                              + bu kayıtların fiş / fatura görselleri
-- Hatice görmez:               başka kasaların gelirleri ve aktarımları, kasa bakiyeleri (toplam kasa),
--                              “Hatice'den gizle” işaretli kayıtlar
-- Değiştirme yetkisi değişmez: Hatice yalnızca kendi eklediği kayıtları ve kendi kasasının faturalarını
--                              düzenler / siler; başkasının faturasını yalnızca görür.
-- =====================================================================

-- 1) Harcamalar
drop policy if exists hb_islem_oku on public.hb_islemler;
create policy hb_islem_oku on public.hb_islemler for select to authenticated
  using (public.hb_yonetici_mi()
         or (not gizli and (kasa_sahibi = auth.uid() or hedef_kasa = auth.uid() or tur = 'Gider')));

-- 2) Faturalar: herkes okur, yalnızca kendi kasasınınkini ekler / değiştirir / siler (yönetici hepsini)
drop policy if exists hb_faturalar_tum on public.hb_faturalar;
drop policy if exists hb_faturalar_oku on public.hb_faturalar;
drop policy if exists hb_faturalar_ekle on public.hb_faturalar;
drop policy if exists hb_faturalar_guncelle on public.hb_faturalar;
drop policy if exists hb_faturalar_sil on public.hb_faturalar;
create policy hb_faturalar_oku on public.hb_faturalar for select to authenticated using (true);
create policy hb_faturalar_ekle on public.hb_faturalar for insert to authenticated
  with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid());
create policy hb_faturalar_guncelle on public.hb_faturalar for update to authenticated
  using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid())
  with check (public.hb_yonetici_mi() or kasa_sahibi = auth.uid());
create policy hb_faturalar_sil on public.hb_faturalar for delete to authenticated
  using (public.hb_yonetici_mi() or kasa_sahibi = auth.uid());

-- 3) Fiş / fatura görselleri: görebildiği kaydın görseli açılır (alt sorgular kullanıcının kendi
--    yetkisiyle çalışır; gizli kaydın görseli yine açılmaz)
create index if not exists hb_islemler_gorsel_idx on public.hb_islemler (fis_gorsel) where fis_gorsel is not null;
drop policy if exists hb_fis_oku on storage.objects;
create policy hb_fis_oku on storage.objects for select to authenticated
  using (bucket_id = 'hb-fisler' and (
         (storage.foldername(name))[1] = auth.uid()::text
         or public.hb_yonetici_mi()
         or exists (select 1 from public.hb_islemler i where i.fis_gorsel = objects.name)
         or exists (select 1 from public.hb_faturalar f where f.gorsel = objects.name)));

-- 4) İSTEĞE BAĞLI: Hatice önceden sizin kasanızı hiç görmediği için eski harcamalarınızı gizlememiş olabilirsiniz.
--    Bugüne kadarki KENDİ harcamalarınızın hepsini Hatice'den gizlemek isterseniz (yeni harcamalar yine görünür),
--    alttaki satırın başındaki iki tireyi (--) silip yalnızca o satırı çalıştırın:
-- update public.hb_islemler set gizli = true where tur = 'Gider' and tarih < now() and kasa_sahibi in (select id from public.hb_profiller where rol = 'yonetici');

select 'Güncelleme 11 tamam' as sonuc;
