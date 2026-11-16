-- MÜKERRER KAYIT & KASA FARKI KONTROLÜ
-- Supabase > SQL Editor > New query > yapıştır > Run.  HİÇBİR VERİYİ DEĞİŞTİRMEZ (yalnızca okur).
-- Sonuç tablosunun tamamının ekran görüntüsünü gönderin (veya CSV indirip gönderin).
with
kasa as (
  select p.id, p.ad,
         coalesce(sum(case
           when i.tur = 'Gelir'   and i.kasa_sahibi = p.id then  i.tutar
           when i.tur = 'Gider'   and i.kasa_sahibi = p.id then -i.tutar
           when i.tur = 'Aktarım' and i.kasa_sahibi = p.id then -i.tutar
           when i.tur = 'Aktarım' and i.hedef_kasa  = p.id then  i.tutar
           else 0 end), 0) bakiye
  from public.hb_profiller p
  left join public.hb_islemler i on (i.kasa_sahibi = p.id or i.hedef_kasa = p.id)
  group by p.id, p.ad
),
k as (
  select i.*, p.ad kasa_ad,
         translate(lower(trim(coalesce(i.firma,'') || ' ' || coalesce(i.urun,''))), 'ışğüöçâî', 'isguocai') metin,
         (i.tarih at time zone 'Europe/Istanbul') yerel
  from public.hb_islemler i join public.hb_profiller p on p.id = i.kasa_sahibi
),
-- Aynı kasa, aynı tür, aynı tutar, 3 gün içinde iki kayıt (aynı fişin farklı ürün satırları hariç)
cift as (
  select a.id a_id, b.id b_id, a.kasa_ad, a.tur, a.tutar,
         to_char(a.yerel,'DD.MM.YY HH24:MI') || ' «' || coalesce(nullif(a.metin,''), a.kategori, '') || '» ' || coalesce(a.aciklama,'') a_txt,
         to_char(b.yerel,'DD.MM.YY HH24:MI') || ' «' || coalesce(nullif(b.metin,''), b.kategori, '') || '» ' || coalesce(b.aciklama,'') b_txt,
         case when a.metin = b.metin and date_trunc('minute', a.yerel) = date_trunc('minute', b.yerel) then 'KESİN'
              when a.metin = b.metin then 'ÇOK OLASI'
              else 'olası' end derece
  from k a join k b
    on a.id < b.id and a.kasa_sahibi = b.kasa_sahibi and a.tur = b.tur and a.tutar = b.tutar
   and abs(extract(epoch from (a.tarih - b.tarih))) <= 3*86400
   and coalesce(a.hedef_kasa::text,'') = coalesce(b.hedef_kasa::text,'')
   and not (a.fis_grup is not null and a.fis_grup = b.fis_grup and a.metin <> b.metin)
  where a.tutar > 0
    and ((a.metin = b.metin and a.yerel::date = b.yerel::date)
         or (a.tutar >= 100 and abs(extract(epoch from (a.tarih - b.tarih))) <= 86400
             and split_part(a.metin,' ',1) = split_part(b.metin,' ',1)))
),
-- Aynı fiş iki kez okutulmuş mu: farklı fiş grubu, aynı gün, aynı toplam
fis as (
  select fis_grup, kasa_ad, min(yerel) zaman, min(firma) firma, sum(tutar) toplam, count(*) satir
  from k where fis_grup is not null group by fis_grup, kasa_ad
),
fis_cift as (
  select a.kasa_ad, a.toplam, a.satir,
         to_char(a.zaman,'DD.MM.YY HH24:MI') || ' ' || coalesce(a.firma,'') || '  ↔  ' || to_char(b.zaman,'DD.MM.YY HH24:MI') || ' ' || coalesce(b.firma,'') txt
  from fis a join fis b on a.fis_grup::text < b.fis_grup::text and a.kasa_ad = b.kasa_ad
   and a.toplam = b.toplam and abs(extract(epoch from (a.zaman - b.zaman))) <= 3*86400
),
-- Bir fatura için birden fazla ödeme kaydı
fatura_cift as (
  select f.id, coalesce(f.kurum, f.tur) ad, f.donem, f.tutar, count(i.id) adet
  from public.hb_faturalar f
  join public.hb_islemler i on i.aciklama = 'Fatura ödemesi' and i.tutar = f.tutar
       and i.kasa_sahibi = f.kasa_sahibi
       and lower(coalesce(i.firma,'') || ' ' || coalesce(i.urun,'')) like '%' || lower(coalesce(f.kurum, f.tur)) || '%'
       and abs((i.tarih at time zone 'Europe/Istanbul')::date - coalesce(f.son_odeme, f.fatura_tarihi, (i.tarih at time zone 'Europe/Istanbul')::date)) <= 40
  where f.odendi
  group by f.id, f.kurum, f.tur, f.donem, f.tutar having count(i.id) > 1
),
-- Son 15 günün kasa hareketleri (farkı bulmak için)
son as (
  select kasa_ad, tur, tutar, to_char(yerel,'DD.MM.YY HH24:MI') || ' | ' || coalesce(nullif(metin,''), kategori, '') || ' | ' || coalesce(aciklama,'') || ' | #' || id txt
  from k where tarih >= now() - interval '15 days'
)
select 1 sira, 'KASA' bolum, ad || ' kasası' detay, round(bakiye, 2) tutar from kasa
union all select 2, 'TOPLAM KASA', 'Uygulamanın gösterdiği', round(sum(bakiye), 2) from kasa
union all select 3, 'FARK', 'Elinizdeki 31.020 − uygulama (eksik gösterilen)', round(31020 - sum(bakiye), 2) from kasa
union all
select 4, 'MÜKERRER ' || derece, kasa_ad || ' | ' || tur || ' | #' || a_id || ' ' || a_txt || '  ↔  #' || b_id || ' ' || b_txt, tutar from cift
union all
select 5, 'AYNI FİŞ 2 KEZ?', kasa_ad || ' | ' || satir || ' satır | ' || txt, toplam from fis_cift
union all
select 6, 'FATURA 2 KEZ ÖDENMİŞ?', ad || ' ' || coalesce(donem,'') || ' | ' || adet || ' ödeme kaydı (fatura #' || id || ')', tutar from fatura_cift
union all
select 7, 'SON 15 GÜN ' || tur, kasa_ad || ' | ' || txt, tutar from son
order by 1, 2, 3;
