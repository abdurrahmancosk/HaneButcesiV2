-- =====================================================================
-- HANE BÜTÇESİ v2 – GÜNCELLEME 2
-- 1) "Hatice'den gizle" özelliği   2) Kasa farkının (3.004,26 TL) düzeltilmesi
-- Supabase > SQL Editor > New query > tamamını yapıştır > Run. Tekrar çalıştırmak güvenlidir.
-- =====================================================================

-- ---------- A) Gizli kayıt alanı ----------
alter table public.hb_islemler add column if not exists gizli boolean not null default false;
alter table public.hb_islemler add column if not exists eski_id bigint unique;

-- Hatice gizli kayıtları göremez; sadece Abdurrahman gizli kayıt oluşturabilir/değiştirebilir
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

-- Bakiye gizli kayıtlar dahil doğru hesaplansın (Hatice yine sadece kendi kasasının TOPLAMINI görür)
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

-- ---------- B) Oturumsuz (SQL Editor) eklemede ekleyen bilgisini koru ----------
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

-- ---------- C) Buluttan yanlışlıkla silinmiş 24 gerçek alışverişi geri yükle (toplam 3.004,26 TL) ----------
-- Eski uygulama 'mükerrer temizleme' sırasında bu kayıtları buluttan silmiş, ama telefondaki kopyaları
-- saymaya devam etmişti. Eski uygulamadaki 84.787,47 TL ile yeni uygulama arasındaki farkın tamamı budur.
insert into public.hb_islemler (eski_id, tur, tarih, firma, urun, kategori, miktar, birim_fiyat, tutar, aciklama, kasa_sahibi, ekleyen, olusturma)
select v.eski_id, 'Gider',
       (to_date(v.tarih, 'DD.MM.YYYY') + v.saat::time) at time zone 'Europe/Istanbul',
       v.firma, v.urun, v.kategori, v.miktar, v.birim_fiyat, v.tutar, v.aciklama,
       (select id from public.hb_profiller where kullanici_adi = 'abdurrahman'),
       (select id from public.hb_profiller where kullanici_adi = 'abdurrahman'),
       v.olusturma::timestamptz
from (values
  (7488, '07.11.2026', '11:25', 'BİM', 'ALIŞVERİŞ POŞETİ BİM', 'Poşet', '1 Adet', 1.0, 1.0, 'AI Toplu Fiş (BİM)', '2026-11-07T08:45:54.393771+00:00'),
  (8157, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'KRT ÇINAR RESİM DEFTERİ', 'Eğitim, Okul & Kırtasiye', '1 Adet', 39.5, 39.5, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:19.778757+00:00'),
  (8158, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'PALANDÖKEN TEREYAĞI', 'Market & Temel Gıda', '1 Adet', 595.0, 595.0, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:20.188004+00:00'),
  (8159, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ETİ GONG 66 GR SÜT MISIR', 'Abur Cubur & Atıştırmalık', '1 Adet', 32.5, 32.5, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:20.832329+00:00'),
  (8160, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ETİ MAXİMUS 50 GR', 'Abur Cubur & Atıştırmalık', '1 Adet', 22.5, 22.5, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:21.38296+00:00'),
  (8161, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ÜLKER ÇİKOLATA KARE', 'Abur Cubur & Atıştırmalık', '1 Adet', 49.5, 49.5, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:21.764273+00:00'),
  (8162, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ETİ BURÇAK YULAFLI 3''LÜ', 'Abur Cubur & Atıştırmalık', '1 Adet', 73.5, 73.5, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:22.131835+00:00'),
  (8163, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ETİ GONG 68 GR PEYNİRLİ', 'Abur Cubur & Atıştırmalık', '1 Adet', 32.5, 32.5, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:22.489564+00:00'),
  (8164, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ETİ TABLET 30 GR', 'Abur Cubur & Atıştırmalık', '1 Adet', 55.0, 55.0, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:22.844737+00:00'),
  (8165, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ÜLKER LAVİVA BATON ÇİKOLATA', 'Abur Cubur & Atıştırmalık', '1 Adet', 27.5, 27.5, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:23.210785+00:00'),
  (8166, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ETİ GOFRET KARAM GURME', 'Abur Cubur & Atıştırmalık', '1 Adet', 30.0, 30.0, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:23.721322+00:00'),
  (8167, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'DİMES MEYVE SUYU 200 ML', 'Abur Cubur & Atıştırmalık', '4 Adet', 16.95, 67.8, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:24.109408+00:00'),
  (8168, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'ETİ CANGA 45 GR', 'Abur Cubur & Atıştırmalık', '2 Adet', 25.0, 50.0, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:24.475711+00:00'),
  (8169, '07.11.2026', '21:04', 'DÜZGÜN MARKET', 'MEYSU MEYVE SUYU 200 ML', 'Abur Cubur & Atıştırmalık', '4 Adet', 12.95, 51.8, 'AI Toplu Fiş (DÜZGÜN MARKET)', '2026-11-11T14:13:24.839318+00:00'),
  (8170, '07.11.2026', '21:25', 'PALEN DOĞALGAZ', 'Doğalgaz Faturası', 'Kira & Aidat & Faturalar', '1 Adet', 921.0, 921.0, 'AI Toplu Fiş (PALEN DOĞALGAZ)', '2026-11-11T14:13:25.190816+00:00'),
  (8171, '04.11.2026', '18:58', 'A101', 'ROTHMANS BLUE', 'Sigara/Tütün', '4 Adet', 115.0, 460.0, 'AI Fiş (A101)', '2026-11-11T14:13:25.563509+00:00'),
  (8172, '04.11.2026', '16:14', 'BİM', 'Alışveriş Poşeti', 'Poşet', '1 Adet', 1.0, 1.0, 'AI Fiş (BİM)', '2026-11-11T14:13:26.090096+00:00'),
  (8173, '04.11.2026', '16:14', 'BİM', 'Yumurta 30''lu 53-62g', 'Market & Temel Gıda', '1 Adet', 169.0, 169.0, 'AI Fiş (BİM)', '2026-11-11T14:13:26.457535+00:00'),
  (8174, '04.11.2026', '18:58', 'A101', 'ETİ ÇANGA SÜT 45G', 'Abur Cubur & Atıştırmalık', '1 Adet', 24.5, 24.5, 'AI Fiş (A101)', '2026-11-11T14:13:26.807751+00:00'),
  (8175, '04.11.2026', '18:58', 'A101', 'BAR ÇİKOLATA BİSKÜVİ', 'Abur Cubur & Atıştırmalık', '2 Adet', 21.5, 43.0, 'AI Fiş (A101)', '2026-11-11T14:13:27.15414+00:00'),
  (8176, '04.11.2026', '18:58', 'A101', 'GOFRET 50G KARAM', 'Abur Cubur & Atıştırmalık', '1 Adet', 29.5, 29.5, 'AI Fiş (A101)', '2026-11-11T14:13:27.502862+00:00'),
  (8177, '04.11.2026', '18:58', 'A101', 'MUZ YERLİ', 'Market & Temel Gıda', '0.950 kg', 114.9, 109.16, 'AI Fiş (A101)', '2026-11-11T14:13:27.845288+00:00'),
  (8178, '04.11.2026', '18:58', 'A101', 'MISBON SÜT 375G', 'Abur Cubur & Atıştırmalık', '2 Adet', 37.5, 75.0, 'AI Fiş (A101)', '2026-11-11T14:13:28.19788+00:00'),
  (8179, '04.11.2026', '18:58', 'A101', 'MAXIMUS LOADING BAR', 'Abur Cubur & Atıştırmalık', '2 Adet', 22.0, 44.0, 'AI Fiş (A101)', '2026-11-11T14:13:28.814713+00:00')
) as v(eski_id, tarih, saat, firma, urun, kategori, miktar, birim_fiyat, tutar, aciklama, olusturma)
on conflict (eski_id) do nothing;

-- ---------- Sonuç ----------
select p.ad as kasa,
       sum(case when i.tur='Gelir' and i.kasa_sahibi=p.id then i.tutar
                when i.tur in ('Gider','Aktarım') and i.kasa_sahibi=p.id then -i.tutar
                when i.tur='Aktarım' and i.hedef_kasa=p.id then i.tutar else 0 end) as bakiye
from public.hb_profiller p join public.hb_islemler i on i.kasa_sahibi=p.id or i.hedef_kasa=p.id
group by rollup(p.ad)
order by p.ad nulls last;
