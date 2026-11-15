"""
Hane Bütçesi v2 – akıllı özellikler (arayüzden bağımsız)
- Gemini: fatura okuma, yazıyla hızlı ekleme, soru-cevap, dönem yorumu
- Fatura karşılaştırma (zam mı, kullanım mı?)
- Fiyat takibi, alışveriş listesi eşleştirme
- Excel / PDF dönem raporu
"""
from __future__ import annotations

import base64
import datetime as dt
import difflib
import io
import json
import os
import re

import hb_core as hb

# ----------------------------------------------------------------------------
# Gemini genel çağrı
# ----------------------------------------------------------------------------


def gemini(prompt: str, api_anahtari: str, gorsel: bytes | None = None, mime: str = "image/jpeg",
           json_mod: bool = True, sicaklik: float = 0.2):
    if not api_anahtari:
        raise hb.ApiHatasi(400, "Gemini API anahtarı ayarlanmamış (Menü > Ayarlar).")
    parcalar = [{"text": prompt}]
    if gorsel is not None:
        parcalar.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(gorsel).decode()}})
    ayar = {"temperature": sicaklik}
    if json_mod:
        ayar["responseMimeType"] = "application/json"
    govde = {"contents": [{"parts": parcalar}], "generationConfig": ayar}
    son = "bilinmeyen hata"
    for model in hb.gemini_modelleri(api_anahtari):
        try:
            j = hb._http("POST", f"{hb.GEMINI_TABAN}/models/{model}:generateContent", govde=govde,
                         basliklar={"x-goog-api-key": api_anahtari}, zaman_asimi=90)
            metin = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]).strip()
            if not json_mod:
                return metin
            metin = re.sub(r"^```(?:json)?|```$", "", metin).strip()
            return json.loads(metin)
        except hb.ApiHatasi as e:
            son = f"{model}: {e.mesaj}"
            if e.durum in (401, 403) or "API key not valid" in e.mesaj:
                raise hb.ApiHatasi(e.durum, "Gemini API anahtarı geçersiz.") from None
        except Exception as e:
            son = f"{model}: {e}"
    raise hb.ApiHatasi(500, f"Yapay zeka yanıt veremedi ({son})")


# ----------------------------------------------------------------------------
# Faturalar
# ----------------------------------------------------------------------------
FATURA_TURLERI = ["Elektrik", "Su", "Doğalgaz", "İnternet", "Telefon", "Aidat", "Kira", "Diğer"]
_AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _tarih_al(v) -> str | None:
    if not v:
        return None
    d = hb.tarih_coz(str(v), varsayilan=None) if str(v).strip() else None
    return d.date().isoformat() if d else None


def fatura_analiz_et(gorsel: bytes, mime: str, api_anahtari: str) -> dict:
    istem = f"""Bu bir Türk fatura belgesi (elektrik, su, doğalgaz, internet, telefon, aidat vb.). Bilgileri oku ve YALNIZCA JSON döndür:
{{"tur": "{'/'.join(FATURA_TURLERI)} değerlerinden biri",
 "kurum": "Fatura kesen kurum (örn: Aras Elektrik, ESKİ, Palen Doğalgaz, Türk Telekom)",
 "abone_no": "abone / tesisat / müşteri no (yoksa boş)",
 "donem": "Fatura dönemi, örn: Ekim 2026",
 "fatura_tarihi": "GG.AA.YYYY",
 "son_odeme": "GG.AA.YYYY (son ödeme tarihi)",
 "tuketim": 310.5, "birim": "kWh / m³ / GB / dk (tüketim birimi; yoksa boş)",
 "birim_fiyat": 2.85, "tutar": 977.00}}
Kurallar: tutar ödenecek toplam tutardır (KDV dahil). tuketim faturadaki dönem tüketimidir (endeks farkı).
birim_fiyat yoksa null bırak. Sayılar nokta ondalıklı sayı olsun."""
    j = gemini(istem, api_anahtari, gorsel, mime)
    tur = j.get("tur") if j.get("tur") in FATURA_TURLERI else "Diğer"
    tutar = hb.tutar_coz(j.get("tutar")) or 0
    tuketim = hb.tutar_coz(j.get("tuketim"))
    bf = hb.tutar_coz(j.get("birim_fiyat"))
    return {"tur": tur, "kurum": (j.get("kurum") or "").strip() or None, "abone_no": (j.get("abone_no") or "").strip() or None,
            "donem": (j.get("donem") or "").strip() or None, "fatura_tarihi": _tarih_al(j.get("fatura_tarihi")),
            "son_odeme": _tarih_al(j.get("son_odeme")), "tuketim": tuketim, "birim": (j.get("birim") or "").strip() or None,
            "birim_fiyat": bf, "tutar": abs(tutar)}


def _yuzde(yeni, eski):
    if not eski:
        return None
    return (float(yeni) - float(eski)) / float(eski) * 100


def fatura_karsilastir(yeni: dict, onceki: dict | None) -> str:
    """Yeni faturayı aynı türdeki bir önceki faturayla kıyaslar: zam mı, kullanım mı?"""
    if not onceki:
        return "İlk fatura kaydı – sonraki faturada kıyaslama yapılacak."
    t = _yuzde(yeni.get("tutar"), onceki.get("tutar"))
    parcalar = []
    if t is not None:
        yon = "arttı" if t > 0 else "azaldı"
        parcalar.append(f"Tutar {hb.tl(onceki.get('tutar'))} → {hb.tl(yeni.get('tutar'))} (%{abs(t):.0f} {yon}).")
    k1, k0 = yeni.get("tuketim"), onceki.get("tuketim")
    u = _yuzde(k1, k0) if k1 and k0 else None
    b1 = yeni.get("birim_fiyat") or ((float(yeni["tutar"]) / float(k1)) if k1 else None)
    b0 = onceki.get("birim_fiyat") or ((float(onceki["tutar"]) / float(k0)) if k0 else None)
    f = _yuzde(b1, b0) if b1 and b0 else None
    birim = yeni.get("birim") or onceki.get("birim") or ""
    if u is not None:
        parcalar.append(f"Kullanım {k0:g} → {k1:g} {birim} (%{abs(u):.0f} {'arttı' if u > 0 else 'azaldı'}).")
    if f is not None:
        parcalar.append(f"Birim fiyat %{abs(f):.0f} {'arttı' if f > 0 else 'azaldı'}.")
    if u is not None and f is not None and t is not None:
        if f > 3 and u <= 3:
            parcalar.append("👉 Artışın sebebi ZAM: kullanımınız artmamış.")
        elif u > 3 and f <= 3:
            parcalar.append("👉 Artışın sebebi KULLANIM: birim fiyat neredeyse aynı.")
        elif u > 3 and f > 3:
            parcalar.append("👉 Hem kullanım arttı hem zam geldi.")
        elif t < -3:
            parcalar.append("👍 Fatura düştü.")
        else:
            parcalar.append("Önemli bir değişiklik yok.")
    elif t is not None and abs(t) > 3:
        parcalar.append("Tüketim bilgisi olmadığı için zam/kullanım ayrımı yapılamadı.")
    return " ".join(parcalar)


def fatura_hatirlatmalari(faturalar: list[dict], bugun: dt.date | None = None) -> list[dict]:
    """Ödenmemiş faturalardan: gecikmiş, bugün son gün, yarın son gün."""
    bugun = bugun or hb.simdi().date()
    sonuc = []
    for f in faturalar:
        if f.get("odendi") or not f.get("son_odeme"):
            continue
        try:
            so = dt.date.fromisoformat(str(f["son_odeme"])[:10])
        except Exception:
            continue
        kalan = (so - bugun).days
        if kalan < 0:
            sonuc.append({"fatura": f, "seviye": "gecikti", "metin": f"{f.get('tur')} faturasının son ödeme tarihi {-kalan} gün geçti!"})
        elif kalan == 0:
            sonuc.append({"fatura": f, "seviye": "bugun", "metin": f"{f.get('tur')} faturasının SON ÖDEME GÜNÜ BUGÜN"})
        elif kalan == 1:
            sonuc.append({"fatura": f, "seviye": "yarin", "metin": f"{f.get('tur')} faturasının son ödeme günü YARIN"})
        elif kalan <= 3:
            sonuc.append({"fatura": f, "seviye": "yakin", "metin": f"{f.get('tur')} faturasına {kalan} gün kaldı"})
    sira = {"gecikti": 0, "bugun": 1, "yarin": 2, "yakin": 3}
    return sorted(sonuc, key=lambda x: sira[x["seviye"]])


def duzenli_hatirlatmalari(duzenliler: list[dict], bugun: dt.date | None = None) -> list[dict]:
    """Bu ay ödenmemiş düzenli ödemeler: ödeme gününden 1 gün önce, gününde ve sonrasında hatırlat."""
    bugun = bugun or hb.simdi().date()
    ay = bugun.strftime("%Y-%m")
    sonuc = []
    for d in duzenliler:
        if not d.get("aktif", True) or d.get("son_odenen") == ay:
            continue
        gun = min(int(d.get("gun") or 1), 28 if bugun.month == 2 else 30 if bugun.month in (4, 6, 9, 11) else 31)
        kalan = gun - bugun.day
        if kalan <= 1:
            metin = (f"{d['ad']} ödemesi {'bugün' if kalan == 0 else 'yarın' if kalan == 1 else f'{-kalan} gün gecikti'}"
                     f" ({hb.tl(d.get('tutar'))})")
            sonuc.append({"duzenli": d, "seviye": "gecikti" if kalan < 0 else ("bugun" if kalan == 0 else "yarin"),
                          "metin": metin})
    return sonuc


# ----------------------------------------------------------------------------
# Yazıyla / sesle hızlı ekleme
# ----------------------------------------------------------------------------

def hizli_ekle_coz(metin: str, kategoriler: list[str], gelir_turleri: list[str], api_anahtari: str) -> list[dict]:
    bugun = hb.simdi()
    istem = f"""Kullanıcı Türkçe olarak bir veya birden çok harcama/gelir yazdı (konuşmadan yazıya çevrilmiş olabilir).
Bugün: {bugun:%d.%m.%Y %A %H:%M}. Metin: "{metin}"
YALNIZCA şu JSON'u döndür: {{"kayitlar": [{{"tur": "Gider|Gelir", "tutar": 45.0, "firma": "BİM", "urun": "Ekmek",
"miktar": "3 adet", "kategori": "listeden biri", "tarih": "GG.AA.YYYY SS:DD"}}]}}
Gider kategorileri: {json.dumps(kategoriler, ensure_ascii=False)}
Gelir türleri: {json.dumps(gelir_turleri, ensure_ascii=False)}
Kurallar: "dün", "sabah" gibi ifadeleri tarihe çevir; tarih belirtilmemişse şimdiki zamanı yaz. "3 ekmek 45 lira" tutar=45 (toplam).
"tanesi 15" gibi birim fiyat söylendiyse tutarı adetle çarp. Firma yoksa boş bırak. Tutarı olmayan kalemi yazma."""
    j = gemini(istem, api_anahtari)
    sonuc = []
    for k in (j.get("kayitlar") if isinstance(j, dict) else j) or []:
        t = hb.tutar_coz(k.get("tutar"))
        if not t:
            continue
        tur = "Gelir" if k.get("tur") == "Gelir" else "Gider"
        liste = gelir_turleri if tur == "Gelir" else kategoriler
        kat = k.get("kategori") if k.get("kategori") in liste else ("Diğer Gelir" if tur == "Gelir" and "Diğer Gelir" in liste
                                                                     else ("Diğer" if tur == "Gider" else liste[0]))
        sonuc.append({"tur": tur, "tutar": abs(t), "firma": (k.get("firma") or "").strip() or None,
                      "urun": (k.get("urun") or "").strip() or None, "miktar": (k.get("miktar") or "").strip() or None,
                      "kategori": kat, "tarih": hb.tarih_coz(k.get("tarih")) if k.get("tarih") else bugun})
    return sonuc


# ----------------------------------------------------------------------------
# Soru-cevap ve dönem yorumu
# ----------------------------------------------------------------------------

def veri_baglami(islemler: list[dict], adlar: dict[str, str], baslik: str, satir_siniri: int = 900) -> str:
    oz = hb.donem_ozeti(islemler)
    satirlar = [f"### {baslik}", f"Toplam gelir: {oz['gelir']:.2f} TL, toplam gider: {oz['gider']:.2f} TL",
                "Kategori giderleri: " + "; ".join(f"{k}: {v:.2f}" for k, v in oz["kategoriler"].items()),
                "Kayıtlar (tarih | tür | firma | ürün | kategori | tutar | kasa | ekleyen):"]
    for i in islemler[:satir_siniri]:
        d = hb.tarih_yerel(i.get("tarih"))
        satirlar.append(f"{d:%d.%m.%Y} | {i.get('tur')} | {i.get('firma') or ''} | {i.get('urun') or ''} | "
                        f"{i.get('kategori') or ''} | {float(i.get('tutar') or 0):.2f} | {adlar.get(i.get('kasa_sahibi'), '')} | "
                        f"{i.get('ekleyen_ad') or ''}")
    return "\n".join(satirlar)


def soru_cevapla(soru: str, baglam: str, api_anahtari: str) -> str:
    istem = f"""Sen bir aile bütçesi asistanısın. Aşağıdaki gerçek harcama verilerine dayanarak soruyu Türkçe, kısa ve net cevapla.
Hesap gerekiyorsa verilerden topla ve sonucu TL olarak ver (1.234,56 TL biçiminde). Verilerde olmayan bir şeyi uydurma;
bilgi yoksa açıkça söyle. Gerekirse en fazla 5 maddelik liste kullan.

{baglam}

SORU: {soru}"""
    return gemini(istem, api_anahtari, json_mod=False, sicaklik=0.2)


def donem_karsilastir(simdiki: list[dict], onceki: list[dict]) -> list[dict]:
    a = hb.donem_ozeti(simdiki)["kategoriler"]
    b = hb.donem_ozeti(onceki)["kategoriler"]
    sonuc = []
    for k in set(a) | set(b):
        s, o = a.get(k, 0.0), b.get(k, 0.0)
        sonuc.append({"kategori": k, "simdi": s, "onceki": o, "fark": s - o,
                      "yuzde": ((s - o) / o * 100) if o else None})
    return sorted(sonuc, key=lambda x: -abs(x["fark"]))


def donem_yorumu(ozet_metni: str, api_anahtari: str) -> str:
    istem = f"""Bir ailenin iki bütçe dönemini karşılaştıran verileri aşağıda. Türkçe, samimi ve somut bir dönem raporu yaz:
1) 2 cümlelik genel değerlendirme, 2) en çok artan/azalan 3 kalem ve olası sebebi, 3) uygulanabilir 3 tasarruf önerisi
(gerçek rakamlarla, örn. "abur cubura haftada 300 TL gidiyor; yarıya inerse dönemde ~600 TL kalır"). En fazla 170 kelime.
Başlık kullanma, maddeler için • kullan.

{ozet_metni}"""
    return gemini(istem, api_anahtari, json_mod=False, sicaklik=0.4)


# ----------------------------------------------------------------------------
# Fiyat takibi
# ----------------------------------------------------------------------------

def _benzerlik(a: str, b: str) -> float:
    a, b = hb.urun_anahtari(a), hb.urun_anahtari(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(re.findall(r"[a-zçğıöşü0-9]+", a)), set(re.findall(r"[a-zçğıöşü0-9]+", b))
    ortak = len(ta & tb) / max(len(ta | tb), 1)
    return max(ortak, difflib.SequenceMatcher(None, a, b).ratio() * 0.95)


def _birim_fiyat(k: dict) -> float:
    bf = k.get("birim_fiyat")
    try:
        if bf and float(bf) > 0:
            return float(bf)
    except Exception:
        pass
    return float(k.get("tutar") or 0)


def fiyat_gecmisi(gecmis: list[dict], urun: str, esik: float = 0.72, en_fazla: int = 30) -> list[dict]:
    eslesen = [dict(k, benzerlik=_benzerlik(urun, k.get("urun") or "")) for k in gecmis]
    eslesen = [k for k in eslesen if k["benzerlik"] >= esik]
    eslesen.sort(key=lambda k: str(k.get("tarih") or ""), reverse=True)
    return eslesen[:en_fazla]


def fiyat_ozeti(gecmis: list[dict], urun: str, simdiki_fiyat: float | None = None, haric_bugun=True) -> str | None:
    """Fiş düzenleyicide ürün altına yazılacak tek satırlık kıyas."""
    kayitlar = fiyat_gecmisi(gecmis, urun, esik=0.8, en_fazla=40)
    if haric_bugun:
        bugun = hb.simdi().date()
        kayitlar = [k for k in kayitlar if hb.tarih_yerel(k.get("tarih")).date() != bugun]
    if not kayitlar:
        return None
    son = kayitlar[0]
    en_ucuz = min(kayitlar, key=_birim_fiyat)
    parca = [f"Son: {son.get('firma') or '?'} {hb.tl(_birim_fiyat(son))} ({hb.tarih_yerel(son.get('tarih')):%d.%m})"]
    if en_ucuz is not son:
        parca.append(f"En ucuz: {en_ucuz.get('firma') or '?'} {hb.tl(_birim_fiyat(en_ucuz))}")
    if simdiki_fiyat:
        y = _yuzde(simdiki_fiyat, _birim_fiyat(son))
        if y is not None and abs(y) >= 3:
            parca.append(("▲ %" if y > 0 else "▼ %") + f"{abs(y):.0f}")
    return " • ".join(parca)


def fiyat_listesi(gecmis: list[dict], arama: str = "", en_fazla: int = 60) -> list[dict]:
    """Ürün bazında özet: son fiyat, en ucuz market, kaç kez alındı."""
    gruplar: dict[str, list[dict]] = {}
    for k in gecmis:
        anahtar = hb.urun_anahtari(k.get("urun"))
        if not anahtar or (arama and hb.urun_anahtari(arama) not in anahtar):
            continue
        gruplar.setdefault(anahtar, []).append(k)
    sonuc = []
    for anahtar, ks in gruplar.items():
        ks.sort(key=lambda k: str(k.get("tarih") or ""), reverse=True)
        son, ucuz = ks[0], min(ks, key=_birim_fiyat)
        ilk = ks[-1]
        sonuc.append({"urun": son.get("urun"), "adet": len(ks), "son_fiyat": _birim_fiyat(son), "son_firma": son.get("firma"),
                      "son_tarih": son.get("tarih"), "en_ucuz": _birim_fiyat(ucuz), "en_ucuz_firma": ucuz.get("firma"),
                      "degisim": _yuzde(_birim_fiyat(son), _birim_fiyat(ilk)) if len(ks) > 1 else None, "kayitlar": ks})
    sonuc.sort(key=lambda x: (-x["adet"], str(x["urun"])))
    return sonuc[:en_fazla]


def alisveris_eslestir(liste: list[dict], urun_adlari: list[str], esik: float = 0.6) -> list[int]:
    """Fişteki ürünlerle eşleşen alışveriş listesi maddelerinin id'leri."""
    ids = []
    for m in liste:
        if m.get("alindi"):
            continue
        ad = hb.urun_anahtari(m.get("urun"))
        for u in urun_adlari:
            uk = hb.urun_anahtari(u)
            if ad and (ad in uk.split() or ad in uk or _benzerlik(ad, uk) >= esik):
                ids.append(m["id"])
                break
    return ids


# ----------------------------------------------------------------------------
# Raporlar: Excel ve PDF
# ----------------------------------------------------------------------------

def rapor_xlsx(islemler: list[dict], adlar: dict[str, str], baslik: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "İşlemler"
    ws.append([baslik])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    basliklar = ["Tarih", "Tür", "Kasa", "Firma", "Ürün / Açıklama", "Kategori", "Miktar", "Birim fiyat", "Tutar", "Ekleyen"]
    ws.append(basliklar)
    for c in range(1, len(basliklar) + 1):
        h = ws.cell(row=3, column=c)
        h.font = Font(bold=True, color="FFFFFF")
        h.fill = PatternFill("solid", fgColor="0F766E")
        h.alignment = Alignment(horizontal="center")
    for i in sorted(islemler, key=lambda x: str(x.get("tarih") or "")):
        d = hb.tarih_yerel(i.get("tarih")).replace(tzinfo=None)
        kasa = adlar.get(i.get("kasa_sahibi"), "")
        if i.get("tur") == "Aktarım":
            kasa = f"{kasa} → {adlar.get(i.get('hedef_kasa'), '')}"
        ws.append([d, i.get("tur"), kasa, i.get("firma"), i.get("urun") or i.get("aciklama"), i.get("kategori"),
                   i.get("miktar"), float(i["birim_fiyat"]) if i.get("birim_fiyat") else None,
                   float(i.get("tutar") or 0), i.get("ekleyen_ad")])
    son = ws.max_row
    for r in range(4, son + 1):
        ws.cell(row=r, column=1).number_format = "DD.MM.YYYY HH:MM"
        ws.cell(row=r, column=8).number_format = '#,##0.00 "₺"'
        ws.cell(row=r, column=9).number_format = '#,##0.00 "₺"'
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "Toplam gider", f'=SUMIF(B4:B{son},"Gider",I4:I{son})'])
    ws.append(["", "", "", "", "", "", "", "Toplam gelir", f'=SUMIF(B4:B{son},"Gelir",I4:I{son})'])
    for r in (son + 2, son + 3):
        ws.cell(row=r, column=8).font = Font(bold=True)
        ws.cell(row=r, column=9).font = Font(bold=True)
        ws.cell(row=r, column=9).number_format = '#,##0.00 "₺"'
    for c, w in enumerate([17, 9, 18, 20, 34, 30, 12, 13, 14, 13], start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:J{son}"

    k = wb.create_sheet("Kategori özeti")
    k.append(["Kategori", "Tutar", "Pay"])
    for c in range(1, 4):
        k.cell(row=1, column=c).font = Font(bold=True, color="FFFFFF")
        k.cell(row=1, column=c).fill = PatternFill("solid", fgColor="0F766E")
    kategoriler = hb.donem_ozeti(islemler)["kategoriler"]
    for n, (ad, v) in enumerate(kategoriler.items(), start=2):
        k.append([ad, round(v, 2), f"=B{n}/SUM($B$2:$B${len(kategoriler) + 1})"])
        k.cell(row=n, column=2).number_format = '#,##0.00 "₺"'
        k.cell(row=n, column=3).number_format = "0.0%"
    k.column_dimensions["A"].width = 36
    k.column_dimensions["B"].width = 16
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def _font(kalin=False, boyut=22):
    from PIL import ImageFont
    ad = "DejaVuSans-Bold.ttf" if kalin else "DejaVuSans.ttf"
    for yol in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", ad),
                os.path.join(os.getcwd(), "assets", "fonts", ad), f"/usr/share/fonts/truetype/dejavu/{ad}"):
        if os.path.exists(yol):
            return ImageFont.truetype(yol, boyut)
    return ImageFont.load_default()


def rapor_pdf(islemler: list[dict], adlar: dict[str, str], baslik: str, kategori_renkleri: dict[str, str] | None = None,
              yorum: str | None = None) -> bytes:
    """Pillow ile A4 sayfalar çizip çok sayfalı PDF üretir (Türkçe karakter desteği için DejaVu)."""
    from PIL import Image, ImageDraw

    G, Y = 1240, 1754  # A4 @150dpi
    kenar = 80
    sayfalar = []

    def yeni():
        s = Image.new("RGB", (G, Y), "white")
        sayfalar.append(s)
        return s, ImageDraw.Draw(s)

    s, d = yeni()
    d.rectangle([0, 0, G, 190], fill="#0f766e")
    d.text((kenar, 50), "Hane Bütçesi – Dönem Raporu", font=_font(True, 44), fill="white")
    d.text((kenar, 118), baslik, font=_font(False, 26), fill="#ccfbf1")
    oz = hb.donem_ozeti(islemler)
    y = 230
    kutular = [("Gelir", oz["gelir"], "#16a34a"), ("Gider", oz["gider"], "#dc2626"), ("Net", oz["net"], "#0f766e")]
    gk = (G - 2 * kenar - 40) // 3
    for n, (ad, v, r) in enumerate(kutular):
        x = kenar + n * (gk + 20)
        d.rounded_rectangle([x, y, x + gk, y + 120], 18, fill="#f1f5f9")
        d.text((x + 24, y + 18), ad, font=_font(False, 24), fill="#64748b")
        d.text((x + 24, y + 56), hb.tl(v), font=_font(True, 32), fill=r)
    y += 170
    d.text((kenar, y), "Kategorilere göre giderler", font=_font(True, 30), fill="#0f172a")
    y += 56
    kategoriler = list(oz["kategoriler"].items())
    enb = max([v for _, v in kategoriler] or [1])
    for ad, v in kategoriler[:16]:
        renk = (kategori_renkleri or {}).get(ad, "#14b8a6")
        d.text((kenar, y), ad[:34], font=_font(False, 22), fill="#0f172a")
        bx = kenar + 470
        bw = int((G - kenar - bx - 220) * v / enb)
        d.rounded_rectangle([bx, y + 4, bx + max(bw, 6), y + 26], 8, fill=renk)
        d.text((G - kenar - 200, y), hb.tl(v), font=_font(True, 22), fill="#0f172a")
        y += 42
    if yorum:
        y += 20
        d.text((kenar, y), "Yapay zeka yorumu", font=_font(True, 30), fill="#0f172a")
        y += 50
        for satir in _sar(yorum, _font(False, 22), G - 2 * kenar, d):
            if y > Y - 100:
                s, d = yeni()
                y = kenar
            d.text((kenar, y), satir, font=_font(False, 22), fill="#334155")
            y += 32

    # İşlem listesi
    s, d = yeni()
    y = kenar
    sutunlar = [("Tarih", 0), ("Firma", 150), ("Ürün / Açıklama", 420), ("Kategori", 760), ("Tutar", 1000)]

    def baslik_ciz(d, y):
        d.rectangle([kenar - 10, y - 6, G - kenar + 10, y + 34], fill="#0f766e")
        for ad, x in sutunlar:
            d.text((kenar + x, y), ad, font=_font(True, 20), fill="white")
        return y + 48

    y = baslik_ciz(d, y)
    for n, i in enumerate(sorted(islemler, key=lambda x: str(x.get("tarih") or ""))):
        if y > Y - kenar:
            s, d = yeni()
            y = baslik_ciz(d, kenar)
        if n % 2:
            d.rectangle([kenar - 10, y - 4, G - kenar + 10, y + 28], fill="#f8fafc")
        isaret = "+" if i.get("tur") == "Gelir" else ("" if i.get("tur") == "Aktarım" else "-")
        degerler = [hb.tarih_yerel(i.get("tarih")).strftime("%d.%m %H:%M"), (i.get("firma") or "")[:20],
                    (i.get("urun") or i.get("aciklama") or i.get("tur") or "")[:28], (i.get("kategori") or "")[:20],
                    isaret + hb.tl(i.get("tutar"))]
        for (ad, x), v in zip(sutunlar, degerler):
            d.text((kenar + x, y), str(v), font=_font(False, 19),
                   fill="#16a34a" if (ad == "Tutar" and isaret == "+") else "#0f172a")
        y += 32
    for n, sy in enumerate(sayfalar, start=1):
        ImageDraw.Draw(sy).text((G - kenar - 120, Y - 50), f"Sayfa {n}/{len(sayfalar)}", font=_font(False, 18), fill="#94a3b8")
    tampon = io.BytesIO()
    sayfalar[0].save(tampon, format="PDF", save_all=True, append_images=sayfalar[1:], resolution=150)
    return tampon.getvalue()


def _sar(metin: str, font, genislik: int, d) -> list[str]:
    satirlar = []
    for paragraf in metin.split("\n"):
        kelimeler, satir = paragraf.split(), ""
        for k in kelimeler:
            dene = f"{satir} {k}".strip()
            if d.textlength(dene, font=font) <= genislik:
                satir = dene
            else:
                satirlar.append(satir)
                satir = k
        satirlar.append(satir)
    return satirlar
