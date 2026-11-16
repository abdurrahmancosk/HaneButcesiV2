-- =====================================================================
-- Hane Bütçesi v2.11 – kredi kartı ekstresi: gelecek ay tahminleri için bildirim gönderme
-- Supabase > SQL Editor'da bir kez çalıştırın (tekrar çalıştırmak zararsızdır).
-- Çalıştırmasanız da uygulama çalışır; yalnızca Hatice ekstre yüklediğinde her tahmini ay için
-- ayrı "fatura yükledi" bildirimi gider.
-- =====================================================================
create or replace function public.hb_fatura_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if coalesce(new.mail_id, '') like 'ekstre:%:tahmin' then
    return new;  -- ekstredeki kalan taksitlerden üretilen gelecek ay tahmini: bildirim yok
  end if;
  perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, null, false,
    case when new.tur = 'Kredi kartı'
         then '💳 ' || coalesce(new.ekleyen_ad, 'Biri') || ' kart ekstresi yükledi'
         else '🧾 ' || coalesce(new.ekleyen_ad, 'Biri') || ' ' || new.tur || ' faturası yükledi' end,
    public.hb_tl(new.tutar) || coalesce(' • son ödeme ' || to_char(new.son_odeme, 'DD.MM.YYYY'), ''),
    'fatura', 'fatura-yeni:' || new.id);
  return new;
end $$;
select 'Güncelleme 10 tamam' as sonuc;
