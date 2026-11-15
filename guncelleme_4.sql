-- =====================================================================
-- HANE BÜTÇESİ v2 – GÜNCELLEME 4: Bildirimler
-- * Biri kayıt/fiş/fatura/alışveriş listesi eklediğinde diğerine bildirim
-- * Her gün 09:00'da fatura ve düzenli ödeme hatırlatmaları
-- * Uygulama kapalıyken telefona anlık bildirim (OneSignal, isteğe bağlı)
-- * Her bildirim bir kez üretilir; okunan/temizlenen bildirim tekrar gelmez
-- Supabase > SQL Editor > New query > tamamını yapıştır > Run. Tekrar çalıştırmak güvenlidir.
-- =====================================================================

do $$ begin
  create extension if not exists pg_net;
exception when others then raise notice 'pg_net kurulamadı: %', sqlerrm;
end $$;

create or replace function public.hb_tl(x numeric) returns text language sql immutable as $$
  select translate(to_char(x, 'FM999,999,999,990.00'), ',.', '.,') || ' ₺';
$$;

-- ---------- Bildirim kutusu ----------
create table if not exists public.hb_bildirimler (
  id         bigint generated always as identity primary key,
  alici      uuid not null references public.hb_profiller(id) on delete cascade,
  baslik     text not null,
  metin      text,
  tur        text not null default 'bilgi',      -- islem, fis, alisveris, fatura, hatirlatma
  anahtar    text unique,                        -- aynı bildirimin ikinci kez üretilmesini engeller
  okundu     boolean not null default false,
  olusturma  timestamptz not null default now()
);
create index if not exists hb_bildirim_alici_idx on public.hb_bildirimler (alici, okundu, olusturma desc);
alter table public.hb_bildirimler enable row level security;
drop policy if exists hb_bildirim_kendi on public.hb_bildirimler;
create policy hb_bildirim_kendi on public.hb_bildirimler for all to authenticated
  using (alici = auth.uid()) with check (alici = auth.uid());

-- ---------- Gizli ayarlar (istemciler OKUYAMAZ: politika yok) ----------
create table if not exists public.hb_gizli (anahtar text primary key, deger text);
alter table public.hb_gizli enable row level security;

create or replace function public.hb_push_ayarla(p_app_id text, p_api_key text)
returns text language plpgsql security definer set search_path = public as $$
begin
  if not public.hb_yonetici_mi() then raise exception 'Yetkisiz'; end if;
  insert into public.hb_gizli values ('onesignal_app_id', nullif(trim(p_app_id), ''))
    on conflict (anahtar) do update set deger = excluded.deger;
  if coalesce(trim(p_api_key), '') <> '' then
    insert into public.hb_gizli values ('onesignal_api_key', trim(p_api_key))
      on conflict (anahtar) do update set deger = excluded.deger;
  end if;
  insert into public.hb_ayarlar values ('onesignal_app_id', nullif(trim(p_app_id), ''))
    on conflict (anahtar) do update set deger = excluded.deger;
  return 'ok';
end $$;
grant execute on function public.hb_push_ayarla(text, text) to authenticated;

create or replace function public.hb_push_durumu()
returns boolean language sql stable security definer set search_path = public as $$
  select public.hb_yonetici_mi() and exists (select 1 from public.hb_gizli where anahtar = 'onesignal_api_key' and deger is not null)
     and exists (select 1 from public.hb_gizli where anahtar = 'onesignal_app_id' and deger is not null);
$$;
grant execute on function public.hb_push_durumu() to authenticated;

-- ---------- Bildirim eklenince telefona gönder (OneSignal ayarlıysa) ----------
create or replace function public.hb_bildirim_push()
returns trigger language plpgsql security definer set search_path = public, extensions as $$
declare
  app text := (select deger from public.hb_gizli where anahtar = 'onesignal_app_id');
  anahtar_ text := (select deger from public.hb_gizli where anahtar = 'onesignal_api_key');
begin
  if app is null or anahtar_ is null then return new; end if;
  begin
    perform net.http_post(
      url := 'https://api.onesignal.com/notifications?c=push',
      headers := jsonb_build_object('Content-Type', 'application/json', 'Authorization', 'Key ' || anahtar_),
      body := jsonb_build_object(
        'app_id', app,
        'target_channel', 'push',
        'include_aliases', jsonb_build_object('external_id', jsonb_build_array(new.alici::text)),
        'headings', jsonb_build_object('en', new.baslik, 'tr', new.baslik),
        'contents', jsonb_build_object('en', coalesce(new.metin, new.baslik), 'tr', coalesce(new.metin, new.baslik)),
        'android_group', 'hane-butcesi',
        'data', jsonb_build_object('bildirim_id', new.id, 'tur', new.tur)));
  exception when others then
    raise warning 'Push gönderilemedi: %', sqlerrm;   -- bildirim yine de uygulama içinde görünür
  end;
  return new;
end $$;
drop trigger if exists hb_bildirim_push_tetik on public.hb_bildirimler;
create trigger hb_bildirim_push_tetik after insert on public.hb_bildirimler
  for each row execute function public.hb_bildirim_push();

-- Yardımcı: bir kaydı görebilecek diğer kullanıcılara bildirim yaz
create or replace function public.hb_bildir(p_kaynak uuid, p_sahip uuid, p_hedef uuid, p_gizli boolean,
                                            p_baslik text, p_metin text, p_tur text, p_anahtar text)
returns void language plpgsql security definer set search_path = public as $$
declare p record;
begin
  for p in select id, rol from public.hb_profiller where id <> coalesce(p_kaynak, '00000000-0000-0000-0000-000000000000') loop
    if p.rol = 'yonetici' or ((p_sahip = p.id or p_hedef = p.id) and not coalesce(p_gizli, false)) then
      insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
      values (p.id, p_baslik, p_metin, p_tur, case when p_anahtar is null then null else p_anahtar || ':' || p.id end)
      on conflict (anahtar) do nothing;
    end if;
  end loop;
end $$;

-- ---------- İşlem eklenince ----------
create or replace function public.hb_islem_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
declare kim text := coalesce(new.ekleyen_ad, 'Biri');
begin
  if new.eski_id is not null then return new; end if;            -- eski veri aktarımında bildirim yok
  if new.fis_grup is not null then
    perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, new.hedef_kasa, new.gizli,
      '🧾 ' || kim || ' fiş ekledi', coalesce(new.firma, 'Market') || ' alışverişi kaydedildi', 'fis', 'fis:' || new.fis_grup);
  elsif new.tur = 'Aktarım' then
    perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, new.hedef_kasa, new.gizli,
      '💸 Para aktarımı', kim || ': ' || public.hb_tl(new.tutar), 'islem', 'islem:' || new.id);
  else
    perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, new.hedef_kasa, new.gizli,
      case when new.tur = 'Gelir' then '💰 ' else '🛍️ ' end || kim || ' ' || lower(new.tur) || ' ekledi',
      coalesce(new.urun, new.kategori, '') || coalesce(' • ' || new.firma, '') || ' • ' ||
        public.hb_tl(new.tutar), 'islem', 'islem:' || new.id);
  end if;
  return new;
end $$;
drop trigger if exists hb_islem_bildirim_tetik on public.hb_islemler;
create trigger hb_islem_bildirim_tetik after insert on public.hb_islemler
  for each row execute function public.hb_islem_bildirim();

-- ---------- Alışveriş listesine ürün eklenince ----------
create or replace function public.hb_alisveris_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
  select p.id, '🛒 ' || coalesce(new.ekleyen_ad, 'Biri') || ' listeye ekledi',
         new.urun || coalesce(' (' || new.miktar || ')', ''), 'alisveris', 'liste:' || new.id || ':' || p.id
  from public.hb_profiller p where p.id <> new.ekleyen
  on conflict (anahtar) do nothing;
  return new;
end $$;
drop trigger if exists hb_alisveris_bildirim_tetik on public.hb_alisveris;
create trigger hb_alisveris_bildirim_tetik after insert on public.hb_alisveris
  for each row execute function public.hb_alisveris_bildirim();

-- ---------- Fatura yüklenince ----------
create or replace function public.hb_fatura_bildirim()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  perform public.hb_bildir(new.ekleyen, new.kasa_sahibi, null, false,
    '🧾 ' || coalesce(new.ekleyen_ad, 'Biri') || ' ' || new.tur || ' faturası yükledi',
    public.hb_tl(new.tutar) || coalesce(' • son ödeme ' || to_char(new.son_odeme, 'DD.MM.YYYY'), ''),
    'fatura', 'fatura-yeni:' || new.id);
  return new;
end $$;
drop trigger if exists hb_fatura_bildirim_tetik on public.hb_faturalar;
create trigger hb_fatura_bildirim_tetik after insert on public.hb_faturalar
  for each row execute function public.hb_fatura_bildirim();

-- ---------- Günlük hatırlatmalar (son ödemeden 1 gün önce ve gününde) ----------
create or replace function public.hb_hatirlatmalari_uret()
returns int language plpgsql security definer set search_path = public as $$
declare
  bugun date := (now() at time zone 'Europe/Istanbul')::date;
  f record; d record; p record; adet int := 0; gun int;
begin
  for f in select * from public.hb_faturalar where not odendi and son_odeme in (bugun, bugun + 1) loop
    for p in select id from public.hb_profiller where id = f.kasa_sahibi or rol = 'yonetici' loop
      insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
      values (p.id, '⏰ ' || f.tur || ' faturası: son ödeme ' || case when f.son_odeme = bugun then 'BUGÜN' else 'YARIN' end,
              coalesce(f.kurum || ' • ', '') || public.hb_tl(f.tutar), 'hatirlatma',
              'hat-fatura:' || f.id || ':' || bugun || ':' || p.id)
      on conflict (anahtar) do nothing;
      adet := adet + 1;
    end loop;
  end loop;
  for d in select * from public.hb_duzenli where aktif
           and coalesce(son_odenen, '') <> to_char(bugun, 'YYYY-MM') loop
    gun := least(d.gun, extract(day from (date_trunc('month', bugun) + interval '1 month - 1 day'))::int);
    if gun in (extract(day from bugun)::int, extract(day from bugun + 1)::int) then
      for p in select id from public.hb_profiller where id = d.kasa_sahibi or rol = 'yonetici' loop
        insert into public.hb_bildirimler (alici, baslik, metin, tur, anahtar)
        values (p.id, '⏰ ' || d.ad || ' ödemesi ' || case when gun = extract(day from bugun)::int then 'bugün' else 'yarın' end,
                public.hb_tl(d.tutar), 'hatirlatma', 'hat-duzenli:' || d.id || ':' || bugun || ':' || p.id)
        on conflict (anahtar) do nothing;
        adet := adet + 1;
      end loop;
    end if;
  end loop;
  return adet;
end $$;
grant execute on function public.hb_hatirlatmalari_uret() to authenticated;

-- Her gün 09:00 (Türkiye) = 06:00 UTC. pg_cron yoksa uygulama açılışında da çağrılır.
do $$
begin
  create extension if not exists pg_cron;
  perform cron.unschedule(jobid) from cron.job where jobname = 'hb-hatirlatma';
  perform cron.schedule('hb-hatirlatma', '0 6 * * *', 'select public.hb_hatirlatmalari_uret()');
exception when others then
  raise notice 'pg_cron kullanılamadı (%); hatırlatmalar uygulama açılınca üretilecek.', sqlerrm;
end $$;

-- ---------- Anlık senkron ----------
do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime'
                 and schemaname = 'public' and tablename = 'hb_bildirimler') then
    alter publication supabase_realtime add table public.hb_bildirimler;
  end if;
end $$;

select 'Güncelleme 4 tamam' as sonuc;
