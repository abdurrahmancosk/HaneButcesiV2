"""
Hane Bütçesi v2 – akıllı özellikler (arayüzden bağımsız)
- Gemini: fatura okuma, yazıyla hızlı ekleme, soru-cevap, dönem yorumu
- Fatura karşılaştırma (zam mı, kullanım mı?)
- Fiyat takibi, alışveriş listesi eşleştirme
- Excel / PDF dönem raporu
"""
from __future__ import annotations

import base64
import calendar
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


def _dusunmesiz(govde: dict, model: str) -> dict:
    """Fiş/fatura okumada uzun 'düşünme' gereksiz ve yavaş: mümkünse kapat / en aza indir."""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", model)
    surum = float(m.group(1)) if m else 0
    if surum < 2.5 or "flash" not in model:
        return govde
    g = dict(govde)
    g["generationConfig"] = dict(govde.get("generationConfig") or {})
    g["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0} if surum < 3 else {"thinkingLevel": "low"}
    return g


def gemini(prompt: str, api_anahtari: str, gorsel: bytes | None = None, mime: str = "image/jpeg",
           json_mod: bool = True, sicaklik: float = 0.2, internet: bool = False):
    if not api_anahtari:
        raise hb.ApiHatasi(400, "Gemini API anahtarı ayarlanmamış (Menü > Ayarlar).")
    parcalar = [{"text": prompt}]
    if gorsel is not None:
        parcalar.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(gorsel).decode()}})
    ayar = {"temperature": sicaklik}
    if json_mod and not internet:  # Google arama aracıyla JSON modu birlikte kullanılamıyor
        ayar["responseMimeType"] = "application/json"
    govde = {"contents": [{"parts": parcalar}], "generationConfig": ayar}
    if internet:
        govde["tools"] = [{"google_search": {}}]
    hatalar = []
    for model in hb.gemini_model_sirasi(api_anahtari):
        try:
            g = _dusunmesiz(govde, model)
            try:
                j = hb.gemini_istegi(model, g, api_anahtari)
            except hb.ApiHatasi as e:
                if g is govde or e.durum != 400 or "think" not in e.mesaj.lower():
                    raise
                j = hb.gemini_istegi(model, govde, api_anahtari)
            metin = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]).strip()
            if not json_mod:
                return metin
            metin = re.sub(r"^```(?:json)?|```$", "", metin).strip()
            if internet:
                m = re.search(r"[\[{].*[\]}]", metin, re.S)
                metin = m.group(0) if m else metin
            return json.loads(metin)
        except hb.ApiHatasi as e:
            hatalar.append((model, e))
            if e.durum in (401, 403) or "API key not valid" in e.mesaj:
                raise hb.ApiHatasi(e.durum, "Gemini API anahtarı geçersiz.") from None
        except Exception as e:
            hatalar.append((model, e))
    raise hb.gemini_hata_mesaji(hatalar, "Yapay zeka yanıt veremedi")


# ----------------------------------------------------------------------------
# Faturalar
# ----------------------------------------------------------------------------
FATURA_TURLERI = ["Elektrik", "Su", "Doğalgaz", "İnternet", "Telefon", "Aidat", "Yakıt", "Kira", "Kredi kartı", "Sigorta", "Diğer"]
_AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _tarih_al(v) -> str | None:
    d = hb.tarih_kesin(v)
    return d.isoformat() if d else None


def fatura_analiz_et(gorsel: bytes, mime: str, api_anahtari: str, turler: list[str] | None = None) -> dict:
    turler = turler or FATURA_TURLERI
    istem = f"""Bu bir Türk fatura belgesi (elektrik, su, doğalgaz, internet, telefon, aidat vb.). Bilgileri oku ve YALNIZCA JSON döndür:
{{"tur": "{'/'.join(turler)} değerlerinden biri",
 "kurum": "Fatura kesen kurum (örn: Aras Elektrik, ESKİ, Palen Doğalgaz, Türk Telekom)",
 "abone_no": "abone / tesisat / müşteri no (yoksa boş)",
 "donem": "Fatura dönemi, örn: Ekim 2026",
 "fatura_tarihi": "GG.AA.YYYY",
 "son_odeme": "GG.AA.YYYY (son ödeme tarihi)",
 "tuketim": 310.5, "birim": "kWh / m³ / GB / dk (tüketim birimi; yoksa boş)",
 "birim_fiyat": 2.85, "tutar": 977.00}}
Kurallar: tutar ödenecek toplam tutardır (KDV dahil). tuketim faturadaki dönem tüketimidir (endeks farkı).
birim_fiyat yoksa null bırak. Sayılar nokta ondalıklı sayı olsun."""
    j = gemini(istem, api_anahtari, gorsel, mime, sicaklik=0.1)
    tur = j.get("tur") if j.get("tur") in turler else "Diğer"
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
        kart = f.get("tur") == "Kredi kartı"
        if kart:
            tahmini = str(f.get("mail_id") or "").endswith(":tahmin")
            ad = f"💳 Kart ekstresi{' (tahmini)' if tahmini else ''}{' • ' + f['kurum'] if f.get('kurum') else ''}"
            ek = {"sayfa": "taksitler"}
        else:
            ad, ek = f"{f.get('tur')} faturası", {}
        tl = f" ({hb.tl(f.get('tutar'))})" if f.get("tutar") is not None else ""
        if kalan < 0:
            sonuc.append({"fatura": f, "seviye": "gecikti", "metin": f"{ad}: son ödeme {-kalan} gün geçti!{tl}", **ek})
        elif kalan == 0:
            sonuc.append({"fatura": f, "seviye": "bugun", "metin": f"{ad}: SON ÖDEME GÜNÜ BUGÜN{tl}", **ek})
        elif kalan == 1:
            sonuc.append({"fatura": f, "seviye": "yarin", "metin": f"{ad}: son ödeme günü YARIN{tl}", **ek})
        elif kalan <= 3:
            sonuc.append({"fatura": f, "seviye": "yakin", "metin": f"{ad}: son ödemeye {kalan} gün kaldı{tl}", **ek})
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


def hizli_ekle_ses(ses: bytes, mime: str, kategoriler: list[str], gelir_turleri: list[str], api_anahtari: str) -> tuple[str, list[dict]]:
    """Ses kaydını dinleyip (çözümlenen metin, kayıtlar) döndürür."""
    j = gemini(f"""Bu Türkçe bir ses kaydı. Önce söyleneni aynen yazıya dök, sonra içindeki harcama/gelirleri çıkar.
YALNIZCA JSON: {{"metin": "duyduğun cümle", "kayitlar": [{{"tur": "Gider|Gelir", "tutar": 45.0, "firma": "", "urun": "",
"miktar": "", "kategori": "listeden biri", "tarih": "GG.AA.YYYY SS:DD"}}]}}
Bugün: {hb.simdi():%d.%m.%Y %A %H:%M}. Gider kategorileri: {json.dumps(kategoriler, ensure_ascii=False)}
Gelir türleri: {json.dumps(gelir_turleri, ensure_ascii=False)}. Tutarı olmayan kalemi yazma.""", api_anahtari, ses, mime, sicaklik=0.1)
    metin = (j.get("metin") or "").strip() if isinstance(j, dict) else ""
    sonuc = []
    for k in (j.get("kayitlar") if isinstance(j, dict) else []) or []:
        t = hb.tutar_coz(k.get("tutar"))
        if not t:
            continue
        tur = "Gelir" if k.get("tur") == "Gelir" else "Gider"
        liste = gelir_turleri if tur == "Gelir" else kategoriler
        kat = k.get("kategori") if k.get("kategori") in liste else ("Diğer" if tur == "Gider" else liste[-1])
        sonuc.append({"tur": tur, "tutar": abs(t), "firma": (k.get("firma") or "").strip() or None,
                      "urun": (k.get("urun") or "").strip() or None, "miktar": (k.get("miktar") or "").strip() or None,
                      "kategori": kat, "tarih": hb.tarih_coz(k.get("tarih")) if k.get("tarih") else hb.simdi()})
    return metin, sonuc


def sesi_yaziya_dok(ses: bytes, mime: str, api_anahtari: str) -> str:
    return gemini("Bu Türkçe ses kaydında söyleneni noktalama ile aynen yazıya dök. Sadece metni yaz.", api_anahtari, ses,
                  mime, json_mod=False, sicaklik=0.1).strip()


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


_BIRIM_KELIMELERI = {"kg", "gr", "g", "lt", "l", "ml", "cl", "adet", "ad", "paket", "pk", "kutu", "şişe", "sise", "demet",
                     "metre", "m", "cm", "x", "li", "lu", "lü", "lı", "tane", "dilim", "porsiyon", "kilo", "litre", "gram"}


_IYELIK_EKLERI = {"i", "u", "ü", "si", "su", "sü", "yi", "yu", "yü", "ni", "nu", "nü"}
_ZARARSIZ = {"ici", "içi", "dilimi", "tanesi"}   # 'ceviz içi' hâlâ cevizdir


def _kelimeler(metin) -> list[str]:
    s = hb.urun_anahtari(metin).replace("'", " ").replace("’", " ")
    return re.findall(r"[a-zçğıöşü]+", s.replace("ı", "i"))


def _tamlama_mi(k: str) -> bool:
    """'tozu', 'suyu', 'salçası', 'ezmesi' gibi önceki kelimeyle başka bir ürün oluşturan tamlama kelimesi mi?"""
    return len(k) >= 3 and k not in _BIRIM_KELIMELERI and bool(re.search(r"(s|y)?[iuü]$", k)) and \
        bool(re.search(r"(si|su|sü|yi|yu|yü|i|u|ü)$", k))


def alisveris_eslesir(madde: str, urun: str) -> bool:
    """Alışveriş listesi maddesi bu fiş / harcama satırıyla AYNI ürün mü? Sıkı kural (benzer isimler eşleşmez):
    maddenin her kelimesi üründe TAM kelime olarak geçmeli ('süt' ≠ 'sütlaç', 'sütlü'); son kelimeden hemen sonra
    'tozu / suyu / salçası / ezmesi' gibi bir tamlama geliyorsa başka üründür ('süt' ≠ 'süt tozu', 'domates' ≠
    'domates salçası'). Sayı ve birimler ('2 lt', '30'lu') yok sayılır."""
    mk = [k for k in _kelimeler(madde) if k not in _BIRIM_KELIMELERI]
    uk = _kelimeler(urun)
    if not mk or not uk:
        return False
    def ayni(k, u):  # 'deterjan' = 'deterjanı' (tamlama eki), ama 'süt' ≠ 'sütlaç'
        return u == k or (u.startswith(k) and u[len(k):] in _IYELIK_EKLERI)

    for k in mk:
        if not any(ayni(k, u) for u in uk):
            return False
    son = max(i for i, u in enumerate(uk) if ayni(mk[-1], u))
    sonraki = uk[son + 1] if son + 1 < len(uk) else None
    if sonraki and sonraki not in mk and sonraki not in _ZARARSIZ and _tamlama_mi(sonraki):
        return False
    return True


def alisveris_eslestir(liste: list[dict], urunler: list, en_erken_fark_saat: float = 2) -> list[tuple[int, dict | None]]:
    """Alınmamış liste maddelerini harcama satırlarıyla eşleştirir -> [(madde_id, eşleşen satır)].
    urunler: ürün adları (str) ya da harcama kayıtları (dict: urun, firma, tarih, id, tutar...). Kayıt, madde listeye
    eklenmeden önce alınmışsa (2 saatten eski) sayılmaz. Bir satır yalnızca bir maddeyi işaretler."""
    sonuc, kullanilan = [], set()
    for m in liste:
        if m.get("alindi"):
            continue
        try:
            eklenme = hb.tarih_yerel(m.get("olusturma")) if m.get("olusturma") else None
        except Exception:
            eklenme = None
        for n, u in enumerate(urunler):
            if n in kullanilan:
                continue
            kayit = u if isinstance(u, dict) else None
            ad = (kayit.get("urun") if kayit else u) or ""
            if kayit and kayit.get("tur", "Gider") != "Gider":
                continue
            if kayit and eklenme and kayit.get("tarih"):
                try:
                    if hb.tarih_yerel(kayit["tarih"]) < eklenme - dt.timedelta(hours=en_erken_fark_saat):
                        continue
                except Exception:
                    pass
            if alisveris_eslesir(m.get("urun") or "", ad):
                sonuc.append((m["id"], kayit))
                kullanilan.add(n)
                break
    return sonuc


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


# ----------------------------------------------------------------------------
# Mükerrer fiş kontrolü
# ----------------------------------------------------------------------------

def mukerrer_bul(adaylar: list[dict], firma: str, zaman, toplam: float | None, saat_biliniyor: bool) -> dict | None:
    """Aynı gün eklenmiş kayıtlar içinde aynı market + aynı saat (±10 dk) ya da aynı toplam olan fişi bulur."""
    gruplar: dict[str, list[dict]] = {}
    for k in adaylar:
        gruplar.setdefault(str(k.get("fis_grup") or f"{k.get('firma')}|{k.get('tarih')}"), []).append(k)
    en_iyi = None
    for satirlar in gruplar.values():
        ilk = satirlar[0]
        benz = _benzerlik(firma or "", ilk.get("firma") or "") if firma else 0.5
        if firma and benz < 0.55:
            continue
        t = sum(float(x.get("tutar") or 0) for x in satirlar)
        fark_dk = abs((hb.tarih_yerel(ilk.get("tarih")) - zaman).total_seconds()) / 60
        toplam_tutuyor = bool(toplam) and abs(t - float(toplam)) <= max(1.0, float(toplam) * 0.02)
        if (saat_biliniyor and fark_dk <= 10) or toplam_tutuyor:
            puan = (2 if toplam_tutuyor else 0) + (2 if saat_biliniyor and fark_dk <= 10 else 0) + benz
            if not en_iyi or puan > en_iyi["puan"]:
                en_iyi = {"puan": puan, "firma": ilk.get("firma"), "tarih": ilk.get("tarih"), "toplam": t,
                          "adet": len(satirlar), "ekleyen": ilk.get("ekleyen_ad")}
    return en_iyi


# ----------------------------------------------------------------------------
# Market fiyatları (marketfiyati.org.tr – TÜBİTAK; resmi olmayan erişim, değişebilir)
# ----------------------------------------------------------------------------
MF_TABAN = "https://api.marketfiyati.org.tr/api/v2"
MF_BASLIK = {"Accept": "application/json", "Origin": "https://marketfiyati.org.tr",
             "Referer": "https://marketfiyati.org.tr/", "Accept-Language": "tr-TR,tr;q=0.9",
             "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Mobile Safari/537.36"}
MARKET_ADLARI = {"bim": "BİM", "a101": "A101", "sok": "ŞOK", "migros": "Migros", "carrefour": "CarrefourSA",
                 "hakmar": "Hakmar", "tarim": "Tarım Kredi", "tarimkredi": "Tarım Kredi"}
_mf_depolar: dict = {}


def market_adi(depo_id: str, yedek: str | None = None) -> str:
    on = str(depo_id or "").split("-")[0].lower().replace("_", "")
    for k, v in MARKET_ADLARI.items():
        if on.startswith(k):
            return v
    return yedek or on.upper()


def mf_yakin_depolar(enlem: float, boylam: float, mesafe: int = 5) -> list[str]:
    anahtar = (round(enlem, 3), round(boylam, 3), mesafe)
    if anahtar in _mf_depolar:
        return _mf_depolar[anahtar]
    j = hb._http("POST", f"{MF_TABAN}/nearest", govde={"latitude": enlem, "longitude": boylam, "distance": mesafe},
                 basliklar=MF_BASLIK, zaman_asimi=20)
    liste = j if isinstance(j, list) else (j or {}).get("content") or (j or {}).get("data") or []
    ids = [d.get("id") or d.get("depotId") for d in liste if isinstance(d, dict)]
    _mf_depolar[anahtar] = [i for i in ids if i]
    return _mf_depolar[anahtar]


def mf_ara(kelime: str, enlem: float, boylam: float, mesafe: int = 5, adet: int = 12) -> list[dict]:
    """[{urun, marka, olcu, gorsel, fiyatlar: [{market, fiyat, sube}]}] – en ucuz fiyat önce."""
    govde = {"keywords": kelime, "latitude": enlem, "longitude": boylam, "distance": mesafe, "pages": 0, "size": adet}
    try:
        depolar = mf_yakin_depolar(enlem, boylam, mesafe)
        if depolar:
            govde["depots"] = depolar
    except Exception as e:
        print("Yakın market listesi alınamadı:", e)
    j = hb._http("POST", f"{MF_TABAN}/search", govde=govde, basliklar=MF_BASLIK, zaman_asimi=25)
    sonuc = []
    for u in (j or {}).get("content") or []:
        fiyatlar = []
        for d in u.get("productDepotInfoList") or []:
            f = hb.tutar_coz(d.get("price") if d.get("price") is not None else d.get("unitPrice"))
            if f:
                fiyatlar.append({"market": market_adi(d.get("depotId"), d.get("marketAdi")), "fiyat": f,
                                 "sube": d.get("depotName")})
        if not fiyatlar:
            continue
        # aynı marketin birden çok şubesi varsa en ucuzunu tut
        enucuz = {}
        for f in fiyatlar:
            if f["market"] not in enucuz or f["fiyat"] < enucuz[f["market"]]["fiyat"]:
                enucuz[f["market"]] = f
        sonuc.append({"urun": u.get("title") or "", "marka": u.get("brand"), "olcu": u.get("refinedVolumeOrWeight"),
                      "gorsel": u.get("imageUrl"), "fiyatlar": sorted(enucuz.values(), key=lambda f: f["fiyat"])})
    return sonuc


def liste_en_ucuz(maddeler: list[str], enlem: float, boylam: float, mesafe: int = 5) -> dict:
    """Alışveriş listesi için market market sepet toplamı ve her ürünün en ucuz seçeneği."""
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        sonuclar = list(ex.map(lambda m: (m, _guvenli(mf_ara, m, enlem, boylam, mesafe, 8)), maddeler))
    sepet: dict[str, dict] = {}
    urunler = []
    for madde, bulunan in sonuclar:
        bulunan = bulunan or []
        en_iyi = None
        market_min: dict[str, tuple] = {}
        for u in bulunan[:6]:
            for f in u["fiyatlar"]:
                if f["market"] not in market_min or f["fiyat"] < market_min[f["market"]][0]:
                    market_min[f["market"]] = (f["fiyat"], u["urun"])
                if not en_iyi or f["fiyat"] < en_iyi["fiyat"]:
                    en_iyi = {"market": f["market"], "fiyat": f["fiyat"], "urun": u["urun"], "olcu": u.get("olcu")}
        for m, (fiyat, ad) in market_min.items():
            s = sepet.setdefault(m, {"market": m, "toplam": 0.0, "bulunan": 0, "kalemler": []})
            s["toplam"] += fiyat
            s["bulunan"] += 1
            s["kalemler"].append((madde, ad, fiyat))
        urunler.append({"madde": madde, "en_iyi": en_iyi, "secenek": len(bulunan)})
    sirali = sorted(sepet.values(), key=lambda s: (-s["bulunan"], s["toplam"]))
    return {"marketler": sirali, "urunler": urunler, "madde_sayisi": len(maddeler)}


def _guvenli(f, *a):
    try:
        return f(*a)
    except Exception as e:
        print("Market araması başarısız:", e)
        return None


def konum_bul(adres: str) -> tuple[float, float, str] | None:
    """OpenStreetMap ile 'Palandöken, Erzurum' gibi bir adresin koordinatı."""
    q = hb.urllib.parse.quote(adres)
    j = hb._http("GET", f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1&countrycodes=tr",
                 basliklar={"User-Agent": "HaneButcesi/2.4 (aile butce uygulamasi)", "Accept-Language": "tr"},
                 zaman_asimi=15)
    if not j:
        return None
    return float(j[0]["lat"]), float(j[0]["lon"]), j[0].get("display_name", adres)


# ----------------------------------------------------------------------------
# Altın / döviz kurları (finans.truncgil.com – serbest piyasa)
# ----------------------------------------------------------------------------
VARLIK_TURLERI = {  # anahtar: (görünen ad, birim, olası kaynak anahtarları)
    "gram": ("Gram altın", "gr", ["GRA", "gram-altin", "GRAMALTIN", "gram altın"]),
    "ceyrek": ("Çeyrek altın", "adet", ["CEYREKALTIN", "ceyrek-altin", "çeyrek altın"]),
    "yarim": ("Yarım altın", "adet", ["YARIMALTIN", "yarim-altin", "yarım altın"]),
    "tam": ("Tam altın", "adet", ["TAMALTIN", "tam-altin", "tam altın"]),
    "cumhuriyet": ("Cumhuriyet altını", "adet", ["CUMHURIYETALTINI", "cumhuriyet-altini", "cumhuriyet altını"]),
    "ata": ("Ata altın", "adet", ["ATAALTIN", "ata-altin", "ata altın"]),
    "bilezik22": ("22 ayar bilezik", "gr", ["YIA", "22-ayar-bilezik", "22AYARBILEZIK", "22 ayar bilezik"]),
    "USD": ("Dolar", "$", ["USD"]), "EUR": ("Euro", "€", ["EUR"]), "GBP": ("Sterlin", "£", ["GBP"]),
}
_kur_onbellek = {"zaman": 0, "veri": {}}


HAREM_ANAHTARLARI = {"gram": ["KULCEALTIN"], "ceyrek": ["CEYREK_YENI", "CEYREK_ESKI"], "yarim": ["YARIM_YENI", "YARIM_ESKI"],
                     "tam": ["TEK_YENI", "TEK_ESKI"], "cumhuriyet": ["ATA_YENI", "ATA_ESKI"], "ata": ["ATA_YENI", "ATA_ESKI"],
                     "bilezik22": ["AYAR22"], "USD": ["USDTRY"], "EUR": ["EURTRY"], "GBP": ["GBPTRY"]}


def harem_kurlari() -> dict[str, dict]:
    """Harem Altın canlı fiyatları (Erzurum Kuyumcular Odası uygulamasının da baz aldığı kaynak)."""
    j = hb._http("POST", "https://www.haremaltin.com/dashboard/ajax/doviz", govde=b"dil_kodu=tr",
                 basliklar={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                            "X-Requested-With": "XMLHttpRequest", "Referer": "https://www.haremaltin.com/",
                            "Origin": "https://www.haremaltin.com", "Accept": "application/json, text/javascript, */*",
                            "User-Agent": MF_BASLIK["User-Agent"]}, zaman_asimi=15)
    veri = (j or {}).get("data") if isinstance(j, dict) else None
    if not isinstance(veri, dict):
        return {}
    sonuc = {}
    for tur, adaylar in HAREM_ANAHTARLARI.items():
        for a in adaylar:
            v = veri.get(a)
            if isinstance(v, dict):
                alis, satis = hb.tutar_coz(str(v.get("alis") or "")), hb.tutar_coz(str(v.get("satis") or ""))
                if alis or satis:
                    sonuc[tur] = {"alis": alis or satis, "satis": satis or alis, "degisim": None,
                                  "kaynak": "Harem Altın"}
                    break
    return sonuc


def kurlar(zorla=False) -> dict[str, dict]:
    """{'gram': {'alis': .., 'satis': .., 'kaynak': ..}, ...} – 10 dk önbellekli. Önce Harem Altın, eksikler truncgil."""
    import time as _t
    if not zorla and _kur_onbellek["veri"] and _t.time() - _kur_onbellek["zaman"] < 600:
        return _kur_onbellek["veri"]
    try:
        harem = harem_kurlari()
    except Exception as e:
        print("Harem Altın:", e)
        harem = {}
    if len(harem) >= 8:
        _kur_onbellek.update(zaman=_t.time(), veri=harem)
        return harem
    j = None
    for url in ("https://finans.truncgil.com/v4/today.json", "https://finans.truncgil.com/today.json"):
        try:
            j = hb._http("GET", url, basliklar={"User-Agent": "HaneButcesi/2.4"}, zaman_asimi=15)
            if j:
                break
        except Exception as e:
            print("Kur kaynağı:", url, e)
    if not j:
        return _kur_onbellek["veri"]
    norm = {hb.urun_anahtari(k).replace(" ", "").replace("-", ""): v for k, v in j.items() if isinstance(v, dict)}
    sonuc = {}
    for anahtar, (_, _, adaylar) in VARLIK_TURLERI.items():
        for a in adaylar:
            v = j.get(a) or norm.get(hb.urun_anahtari(a).replace(" ", "").replace("-", ""))
            if isinstance(v, dict):
                alis = hb.tutar_coz(v.get("Buying") or v.get("Alış") or v.get("alis"))
                satis = hb.tutar_coz(v.get("Selling") or v.get("Satış") or v.get("satis"))
                if alis or satis:
                    sonuc[anahtar] = {"alis": alis or satis, "satis": satis or alis, "degisim": v.get("Change") or v.get("Değişim"),
                                      "kaynak": "truncgil"}
                    break
    sonuc.update(harem)
    if sonuc:
        _kur_onbellek.update(zaman=_t.time(), veri=sonuc)
    return sonuc or _kur_onbellek["veri"]


KUYUMCU_GRUBU = {"gram": "gram", "bilezik22": "gram", "ceyrek": "ceyrek", "yarim": "ceyrek", "tam": "ceyrek",
                 "cumhuriyet": "ceyrek", "ata": "ceyrek"}


def yerel_kurlar(kur: dict, farklar: dict | None) -> dict:
    """Erzurum kuyumcu fiyatına göre düzeltilmiş kurlar. farklar: {tur: {'alis_oran': 1.03, 'satis_oran': 1.01}}.
    Kendi oranı girilmemiş altın türleri aynı gruptaki (gram / sikke) oranı kullanır."""
    if not farklar:
        return kur
    sonuc = {}
    for tur, v in kur.items():
        f = farklar.get(tur) or farklar.get(KUYUMCU_GRUBU.get(tur, "-"))
        if f and tur in KUYUMCU_GRUBU:
            sonuc[tur] = dict(v, alis=round(v["alis"] * float(f.get("alis_oran") or 1), 2),
                              satis=round(v["satis"] * float(f.get("satis_oran") or 1), 2), yerel=True)
        else:
            sonuc[tur] = v
    return sonuc


# ----------------------------------------------------------------------------
# Marketlerin aktüel (haftalık indirim) katalogları – internette arayıp bulur
# ----------------------------------------------------------------------------
AKTUEL_MARKETLER = ["BİM", "A101", "ŞOK", "Migros", "CarrefourSA"]


def aktuel_bul(api_anahtari: str, market: str, bugun=None) -> list[dict]:
    """Gemini + Google Arama ile marketin bu haftaki aktüel kataloğunu bulur.
    -> [{market, urun, fiyat, bas, bit}] (bas/bit: 'YYYY-MM-DD')"""
    bugun = bugun or hb.simdi().date()
    istem = f"""Bugün {bugun.strftime('%d.%m.%Y')}. İnternette arama yaparak {market} marketlerinin ŞU AN GEÇERLİ ve önümüzdeki
günlerde başlayacak aktüel / haftalık indirim kataloğundaki (broşür, afiş, 'bu hafta', 'haftanın fırsatları') ürünleri bul.
Öncelik: gıda, içecek, temizlik, kişisel bakım, bebek, ev ihtiyacı ürünleri; ardından diğer ürünler.
Yalnızca kaynakta açıkça fiyatı yazan ürünleri yaz, fiyat uydurma. Eski haftaların kataloglarını ALMA.
Yanıtı sadece JSON dizi olarak ver, başka metin yazma:
[{{"urun": "ürün adı ve gramaj/adet", "fiyat": 0.0, "bas": "YYYY-MM-DD", "bit": "YYYY-MM-DD veya boş"}}]
En fazla 80 ürün."""
    sonuc = gemini(istem, api_anahtari, internet=True, sicaklik=0.1)
    if isinstance(sonuc, dict):
        sonuc = sonuc.get("urunler") or sonuc.get("items") or []
    temiz = []
    for u in sonuc or []:
        if not isinstance(u, dict):
            continue
        ad = str(u.get("urun") or "").strip()
        fiyat = hb.tutar_coz(u.get("fiyat"))
        if not ad or not fiyat or fiyat <= 0:
            continue
        def _t(x):
            try:
                return dt.date.fromisoformat(str(x)[:10]).isoformat()
            except Exception:
                return None
        bas = _t(u.get("bas")) or bugun.isoformat()
        bit = _t(u.get("bit"))
        if bit and bit < bugun.isoformat():
            continue
        if bas < (bugun - dt.timedelta(days=10)).isoformat():
            continue
        temiz.append({"market": market, "urun": ad[:120], "fiyat": round(fiyat, 2), "bas": bas,
                      "bit": bit or (dt.date.fromisoformat(bas) + dt.timedelta(days=7)).isoformat()})
    return temiz


def aktuel_eslestir(aktueller: list[dict], madde: str, esik: float = 0.5) -> list[dict]:
    """Alışveriş listesindeki bir madde için eşleşen geçerli aktüel ürünler (ucuzdan pahalıya)."""
    bugun = hb.simdi().date().isoformat()
    anahtar = hb.urun_anahtari(madde)
    ilk = anahtar.split(" ")[0] if anahtar else ""
    cikti = []
    for a in aktueller:
        if (a.get("bit") or "9999") < bugun:
            continue
        ua = hb.urun_anahtari(a.get("urun") or "")
        puan = _benzerlik(madde, a.get("urun") or "")
        if ilk and len(ilk) >= 3 and re.search(rf"\b{re.escape(ilk)}", ua):
            puan = max(puan, 0.6)
        if puan >= esik:
            cikti.append(dict(a, puan=puan))
    return sorted(cikti, key=lambda x: (float(x["fiyat"]), -x["puan"]))


# ----------------------------------------------------------------------------
# Halka (donut) grafik görseli
# ----------------------------------------------------------------------------

def halka_png(dilimler: list[tuple[str, float, str]], ust: str, alt: str, koyu: bool = False, boyut: int = 520) -> bytes:
    from PIL import Image, ImageDraw
    S = boyut * 2
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    toplam = sum(v for _, v, _ in dilimler) or 1
    bas = -90.0
    kutu = [S * 0.06, S * 0.06, S * 0.94, S * 0.94]
    for _, v, renk in dilimler:
        aci = 360 * v / toplam
        if aci >= 0.5:
            d.pieslice(kutu, bas, bas + max(aci - (1.2 if len(dilimler) > 1 else 0), 0.3), fill=renk)
        bas += aci
    ic = S * 0.25
    d.ellipse([ic, ic, S - ic, S - ic], fill=(0, 0, 0, 0))
    im2 = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    m = Image.new("L", (S, S), 255)
    ImageDraw.Draw(m).ellipse([ic, ic, S - ic, S - ic], fill=0)
    im2.paste(im, (0, 0), m)
    d2 = ImageDraw.Draw(im2)
    yazi_renk = (226, 232, 240) if koyu else (15, 23, 42)
    soluk = (148, 163, 184) if koyu else (100, 116, 139)
    d2.text((S / 2, S / 2 - S * 0.03), ust, font=_font(True, int(S * 0.075)), anchor="mm", fill=yazi_renk)
    d2.text((S / 2, S / 2 + S * 0.06), alt, font=_font(False, int(S * 0.045)), anchor="mm", fill=soluk)
    im2 = im2.resize((boyut, boyut), Image.LANCZOS)
    tampon = io.BytesIO()
    im2.save(tampon, format="PNG")
    return tampon.getvalue()


# ----------------------------------------------------------------------------
# Kredi kartı ekstresi (hesap özeti): PDF şifresi, metin, taksit çıkarma
# ----------------------------------------------------------------------------
class PdfSifreli(Exception):
    """PDF şifreli; doğru şifre gerekli (yanlis=True: girilen şifre tutmadı)."""
    def __init__(self, yanlis=False, desteklenmiyor=False):
        super().__init__("PDF şifreli")
        self.yanlis = yanlis
        self.desteklenmiyor = desteklenmiyor


def pdf_sifresini_coz(veri: bytes, sifre: str | None = None) -> bytes:
    """Şifreli PDF'i açıp şifresiz kopyasını döndürür; şifresizse aynen döner."""
    try:
        import pypdf
    except Exception:
        return veri
    try:
        okuyucu = pypdf.PdfReader(io.BytesIO(veri))
    except Exception:
        return veri
    if not okuyucu.is_encrypted:
        return veri
    try:
        sonuc = okuyucu.decrypt(sifre or "")
    except Exception as e:  # AES için kripto kütüphanesi yoksa
        if "cryptography" in str(e).lower() or "pycryptodome" in str(e).lower() or "dependency" in type(e).__name__.lower():
            raise PdfSifreli(desteklenmiyor=True) from None
        raise PdfSifreli(yanlis=bool(sifre)) from None
    if not sonuc:
        raise PdfSifreli(yanlis=bool(sifre))
    yazici = pypdf.PdfWriter()
    for sayfa in okuyucu.pages:
        yazici.add_page(sayfa)
    cikti = io.BytesIO()
    yazici.write(cikti)
    return cikti.getvalue()


def pdf_metni(veri: bytes, sayfa: int = 3) -> str:
    try:
        import pypdf
        okuyucu = pypdf.PdfReader(io.BytesIO(veri))
        if okuyucu.is_encrypted:
            return ""
        return "\n".join((p.extract_text() or "") for p in okuyucu.pages[:sayfa])
    except Exception:
        return ""


def pdf_sifreli_mi(veri: bytes) -> bool:
    try:
        import pypdf
        return bool(pypdf.PdfReader(io.BytesIO(veri)).is_encrypted)
    except Exception:
        return b"/Encrypt" in veri[:200000] or b"/Encrypt" in veri[-200000:]


_EKSTRE_IZLERI = ("hesap özeti", "hesap ozeti", "ekstre", "son ödeme tarihi", "son odeme tarihi", "asgari ödeme",
                  "asgari odeme", "dönem borcu", "donem borcu", "kart limiti", "hesap kesim")


def ekstre_mi(metin: str) -> bool:
    m = (metin or "").lower()
    return sum(1 for iz in _EKSTRE_IZLERI if iz in m) >= 2


# Eşleştirme hb.urun_anahtari ile küçültülmüş metinde yapılır (İ/I/ı → i)
_IADE_IZI = re.compile(r"\b(iade\w*|iptal\w*|ters\s*kayit\w*|geri\s*[öo]deme\w*|refund\w*|chargeback|cash\s*back|"
                       r"itiraz\w*|alacak\s*kayd\w*)")
_ODEME_IZI = re.compile(r"(te[şs]ekk[üu]r|otomatik\s*[öo]deme|hesaptan\s*[öo]deme|kart\s*[öo]demesi|bor[çc]\s*[öo]deme|"
                        r"^[öo]deme\b|\b[öo]demeniz\b|havale\s*ile|eft\s*ile|virman)")
_ODEME_KESIN = re.compile(r"(te[şs]ekk[üu]r|otomatik\s*[öo]deme|hesaptan\s*[öo]deme|[öo]demeniz\s*i[çc]in)")


def _iade_mi(ad: str) -> bool:
    return bool(_IADE_IZI.search(hb.urun_anahtari(ad)))


def _odeme_mi(ad: str, kesin: bool = False) -> bool:
    return bool((_ODEME_KESIN if kesin else _ODEME_IZI).search(hb.urun_anahtari(ad)))


def _isaretli_tutar(x) -> float | None:
    """'450,00-', '-450,00', '(450,00)', '450,00 A' gibi alacak yazımlarını eksi sayar."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = str(x).strip()
    eksi = m.startswith("-") or m.endswith("-") or (m.startswith("(") and m.endswith(")")) or \
        bool(re.search(r"\s(A|ALACAK|CR)$", m, re.I))
    t = hb.tutar_coz(m.strip("()-+ ").rstrip("AaBb ").strip())
    if t is None:
        return None
    return -abs(t) if eksi else t


def ekstre_analiz_et(veri: bytes, mime: str, api_anahtari: str, kategoriler: list[str] | None = None) -> dict:
    """Kart ekstresinden yalnızca gerekenleri çıkarır: bu ayın ödenecek tutarı + son ödeme tarihi, kalan taksitler
    (gelecek ayların tutarı için) ve iadeler (harcama sayılmasın diye). Ayrıntılı harcama listesi kullanıcıya gösterilmez."""
    istem = """Bu bir Türk bankasının kredi kartı hesap özeti (ekstre). Yalnızca şu JSON'u döndür:
{"banka": "banka adı", "kart": "kart adı (örn. Bonus, World, Axess, Maximum, CardFinans, Paraf)",
"kart_son4": "kart numarasının son 4 hanesi ya da null",
"hesap_kesim": "YYYY-MM-DD", "son_odeme": "YYYY-MM-DD",
"donem_borcu": 0.0, "asgari": 0.0, "odemeler": 0.0, "ucretler": 0.0,
"taksitler": [{"ad": "işyeri / ürün", "aylik_tutar": 0.0, "taksit_no": 3, "toplam_taksit": 6}],
"harcamalar": [{"ad": "işyeri", "tutar": 0.0}],
"iadeler": [{"ad": "işyeri / açıklama", "tutar": 0.0, "taksitli": false}],
"gelecek_donemler": [{"ay": "YYYY-MM", "tutar": 0.0}]}
Kurallar:
- "donem_borcu": bu ekstrenin son ödeme tarihine kadar ödenmesi gereken TOPLAM tutar ("Dönem borcu", "Hesap özeti borcu",
  "Ödenmesi gereken tutar", "Toplam borcunuz (bu dönem)"). İadeler ve yapılan ödemeler bu tutardan zaten düşülmüştür.
  Asgari ödeme tutarı DEĞİL; gelecek dönem taksitlerini de içeren "kalan toplam borç" DEĞİL. Kart alacaklıysa eksi yaz.
- "taksitler": bu ekstreye düşen TAKSİTLİ işlemler. "3/6", "3. taksit / 6", "Taksit 3/6" ifadelerinden taksit_no ve
  toplam_taksit çıkar. aylik_tutar bu ekstreye düşen taksit tutarıdır (işlemin toplamı değil), artı sayı.
  İade edilmiş / iptal edilmiş bir taksitli alışverişi buraya KOYMA (kalan taksitleri ödenmeyecek).
- "harcamalar": taksitsiz alışverişler, artı sayı.
- "iadeler": eksi (-) işaretli ya da "İADE", "İptal", "Ters kayıt", "Geri ödeme", "ParaPuan/Bonus iadesi" gibi kartınıza
  ALACAK yazılan kayıtlar. Tutarı artı sayı olarak yaz. Taksitli bir alışverişin iadesiyse "taksitli": true.
  İadeler ASLA "harcamalar" ya da "taksitler"e girmez.
- Kart borcu ödemeleri ("Ödeme - Teşekkür ederiz", "Otomatik ödeme", "Hesaptan ödeme") hiçbir listeye girmez;
  toplamlarını "odemeler"e yaz. Faiz, BSMV, KKDF, kart aidatı, gecikme ücreti toplamını "ucretler"e yaz.
- "gelecek_donemler": ekstrede "Gelecek dönem taksitleri", "Sonraki dönemlere ait taksit tutarları" gibi bir tablo varsa
  BU EKSTREDEN SONRAKİ dönemlerin ay ay toplamları (bu dönemi yazma); yoksa boş liste.
- Tutarlar sayı olsun (1.234,56 → 1234.56). Bulamadığın alanı null yap, uydurma."""
    sonuc = gemini(istem, api_anahtari, gorsel=veri, mime=mime, sicaklik=0.1)
    if not isinstance(sonuc, dict):
        raise hb.ApiHatasi(500, "Ekstre okunamadı")
    return ekstre_coz(sonuc)


def _iade_taksite_ait(iade: dict, t: dict) -> bool:
    """Taksitli iade bu taksitli alışverişe mi ait? (ad benzerliği + tutar uyumu)"""
    a = re.sub(r"[^a-zçğöşü0-9 ]", " ", _IADE_IZI.sub(" ", hb.urun_anahtari(iade["ad"]))).split()
    b = re.sub(r"[^a-zçğöşü0-9 ]", " ", hb.urun_anahtari(t["ad"])).split()
    if not a or not b:
        return False
    ia, ib = " ".join(a), " ".join(b)
    benzer = _benzerlik(ia, ib)
    if ia in ib or ib in ia:
        benzer = max(benzer, 0.8)
    ay, n, no = float(t["aylik_tutar"]), int(t["toplam_taksit"]), int(t["taksit_no"])
    tutar_uyar = any(abs(iade["tutar"] - x) <= 1.0 for x in (ay, ay * n, ay * (n - no + 1), ay * (n - no)) if x > 0)
    return benzer >= 0.85 or (benzer >= 0.5 and tutar_uyar)


def ekstre_coz(sonuc: dict) -> dict:
    """Gemini yanıtını temizler; iadeleri harcamalardan ayırır, bu ayın tutarını belirler."""
    def _t(x):
        try:
            return dt.date.fromisoformat(str(x)[:10])
        except Exception:
            return hb.tarih_kesin(x)

    taksitler, harcamalar, iadeler = [], [], []
    for x in sonuc.get("iadeler") or []:
        if isinstance(x, dict):
            t = _isaretli_tutar(x.get("tutar"))
            if t:
                iadeler.append({"ad": str(x.get("ad") or "İade").strip()[:60], "tutar": round(abs(t), 2),
                                "taksitli": bool(x.get("taksitli"))})
    for x in sonuc.get("taksitler") or []:
        if not isinstance(x, dict):
            continue
        ad = str(x.get("ad") or "Taksitli alışveriş").strip()[:60]
        t = _isaretli_tutar(x.get("aylik_tutar"))
        try:
            no, toplam = int(x.get("taksit_no") or 0), int(x.get("toplam_taksit") or 0)
        except Exception:
            no, toplam = 0, 0
        if not t:
            continue
        if t < 0 or _iade_mi(ad):  # yanlışlıkla taksit sanılan iade
            iadeler.append({"ad": ad, "tutar": round(abs(t), 2), "taksitli": True})
            continue
        if toplam < 1 or not 1 <= no <= toplam:
            harcamalar.append({"ad": ad, "tutar": round(t, 2)})
            continue
        taksitler.append({"ad": ad, "aylik_tutar": round(t, 2), "taksit_no": no, "toplam_taksit": toplam})
    odeme_ek = 0.0
    for x in sonuc.get("harcamalar") or sonuc.get("diger_harcamalar") or []:
        if not isinstance(x, dict):
            continue
        ad = str(x.get("ad") or "").strip()[:60]
        t = _isaretli_tutar(x.get("tutar"))
        if not t:
            continue
        if (t < 0 and _odeme_mi(ad)) or _odeme_mi(ad, kesin=True):
            odeme_ek += abs(t)  # kart borcu ödemesi: harcama da iade de değil
        elif t < 0 or _iade_mi(ad):
            iadeler.append({"ad": ad or "İade", "tutar": round(abs(t), 2), "taksitli": False})
        else:
            harcamalar.append({"ad": ad, "tutar": round(t, 2)})
    iade_toplami = round(sum(i["tutar"] for i in iadeler), 2)
    ucretler = abs(_isaretli_tutar(sonuc.get("ucretler")) or 0.0)
    hesap = round(sum(t["aylik_tutar"] for t in taksitler) + sum(h["tutar"] for h in harcamalar) + ucretler - iade_toplami, 2)
    # iade edilen taksitli alışverişin kalan taksitleri gelecek aylara yazılmasın
    for i in iadeler:
        if i["taksitli"]:
            taksitler = [t for t in taksitler if not _iade_taksite_ait(i, t)]
    borc = _isaretli_tutar(sonuc.get("donem_borcu"))
    if borc is not None and (borc != 0 or hesap <= 0):
        bu_ay, kaynak = borc, "banka"
    else:
        bu_ay, kaynak = hesap, "hesap"
    gelecek = []
    for g in sonuc.get("gelecek_donemler") or []:
        if isinstance(g, dict):
            t = _isaretli_tutar(g.get("tutar"))
            if t and t > 0:
                gelecek.append((str(g.get("ay") or "")[:7], round(t, 2)))
    son4 = re.sub(r"\D", "", str(sonuc.get("kart_son4") or ""))[-4:]
    return {"banka": (sonuc.get("banka") or "").strip(), "kart": (sonuc.get("kart") or "").strip(),
            "son4": son4 if len(son4) == 4 else "",
            "hesap_kesim": _t(sonuc.get("hesap_kesim")), "son_odeme": _t(sonuc.get("son_odeme")),
            "donem_borcu": borc, "asgari": abs(_isaretli_tutar(sonuc.get("asgari")) or 0.0) or None,
            "bu_ay": round(max(0.0, bu_ay), 2), "bu_ay_kaynak": kaynak, "alacakli": bu_ay < 0,
            "taksitler": taksitler, "harcama_toplami": round(sum(h["tutar"] for h in harcamalar), 2),
            "harcama_adedi": len(harcamalar), "iadeler": iadeler, "iade_toplami": iade_toplami,
            "ucretler": round(ucretler, 2),
            "odemeler": round(max(abs(_isaretli_tutar(sonuc.get("odemeler")) or 0.0), odeme_ek), 2),
            "gelecek_tablo": sorted(gelecek)}


def _is_gunu(d: dt.date) -> dt.date:
    """Hafta sonuna denk gelen son ödeme tarihini pazartesiye kaydırır (bankalar böyle yapar)."""
    return d + dt.timedelta(days=(7 - d.weekday()) % 7) if d.weekday() >= 5 else d


def ay_ekle(d: dt.date, n: int, gun: int | None = None) -> dt.date:
    ay = d.month - 1 + n
    y, m = d.year + ay // 12, ay % 12 + 1
    return dt.date(y, m, min(gun or d.day, calendar.monthrange(y, m)[1]))


def ekstre_plani(s: dict, son_odeme: dt.date, bu_ay: float, ay_siniri: int = 24) -> list[dict]:
    """[{sira, son_odeme, tutar, tahmini}] – sira 0: bu ekstre; 1..: kalan taksitlerden gelecek ay tahminleri
    (kartla yeni harcama yapılmayacağı varsayımıyla)."""
    plan = [{"sira": 0, "son_odeme": son_odeme, "tutar": round(max(0.0, bu_ay), 2), "tahmini": False}]
    yuk: dict[int, float] = {}
    for t in s.get("taksitler") or []:
        for j in range(1, min(int(t["toplam_taksit"]) - int(t["taksit_no"]), ay_siniri) + 1):
            yuk[j] = yuk.get(j, 0.0) + float(t["aylik_tutar"])
    if not yuk and s.get("gelecek_tablo"):  # kalemler yoksa bankanın "gelecek dönem taksitleri" tablosu
        for j, (_, tutar) in enumerate(s["gelecek_tablo"][:ay_siniri], start=1):
            yuk[j] = tutar
    for j in sorted(yuk):
        if yuk[j] > 0:
            plan.append({"sira": j, "son_odeme": _is_gunu(ay_ekle(son_odeme, j)), "tutar": round(yuk[j], 2),
                         "tahmini": True})
    return plan


# ----------------------------------------------------------------------------
# E-postadan fatura takibi (Gmail IMAP + uygulama şifresi)
# ----------------------------------------------------------------------------
GMAIL_IMAP = "imap.gmail.com"
# Bu tarihten önceki e-postalar hiç okunmaz (önceki faturalar uygulamaya zaten girilmiş; mükerrer kayıt olmasın)
MAIL_BASLANGIC = dt.date(2026, 11, 16)
MAIL_SORGU = 'after:{after} -in:chats -category:promotions (fatura OR "e-fatura" OR "e-arşiv" OR "son ödeme" ' \
             'OR "fatura tutarı" OR "ödenecek tutar" OR "hesap özeti" OR abone)'


def _mail_metin(msg) -> tuple[str, list[tuple[str, bytes]]]:
    """E-postanın düz metni (HTML'den arındırılmış) ve PDF ekleri."""
    import html as _html
    duz, htm, ekler = [], [], []
    for parca in msg.walk():
        tip = parca.get_content_type()
        dosya = parca.get_filename() or ""
        if parca.is_multipart():
            continue
        try:
            veri = parca.get_payload(decode=True) or b""
        except Exception:
            continue
        if tip == "application/pdf" or dosya.lower().endswith(".pdf"):
            if len(veri) < 8_000_000:
                ekler.append((dosya or "fatura.pdf", veri))
            continue
        if tip in ("text/plain", "text/html") and "attachment" not in str(parca.get("Content-Disposition") or ""):
            cs = parca.get_content_charset() or "utf-8"
            try:
                metin = veri.decode(cs, "replace")
            except Exception:
                metin = veri.decode("utf-8", "replace")
            (duz if tip == "text/plain" else htm).append(metin)
    metin = "\n".join(duz)
    if not metin.strip() and htm:
        h = "\n".join(htm)
        h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
        h = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", h)
        metin = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    metin = re.sub(r"[ \t\xa0]+", " ", metin)
    metin = re.sub(r"\n\s*\n+", "\n", metin).strip()
    return metin[:6000], ekler


def _baslik(deger) -> str:
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(deger or "")))
    except Exception:
        return str(deger or "")


def mail_baglanti_dene(adres: str, sifre: str) -> str:
    import imaplib
    m = imaplib.IMAP4_SSL(GMAIL_IMAP, 993, ssl_context=hb.SSL)
    try:
        m.login(adres, sifre.replace(" ", ""))
        return "ok"
    finally:
        try:
            m.logout()
        except Exception:
            pass


def mail_faturalari_getir(adres: str, sifre: str, gun: int = 45, gorulen: set | None = None, en_fazla: int = 25) -> list[dict]:
    """Son {gun} gündeki fatura olabilecek e-postaları getirir (okunmadı olarak bırakır).
    -> [{"id", "kimden", "konu", "tarih", "metin", "pdfler": [(ad, bytes)]}]"""
    import email
    import imaplib
    from email.utils import parsedate_to_datetime
    gorulen = gorulen or set()
    m = imaplib.IMAP4_SSL(GMAIL_IMAP, 993, ssl_context=hb.SSL)
    sonuc = []
    try:
        m.login(adres, sifre.replace(" ", ""))
        klasor = '"INBOX"'
        typ, kutular = m.list()
        for k in kutular or []:
            s = k.decode("utf-8", "replace") if isinstance(k, bytes) else str(k)
            if "\\All" in s:  # Gmail "Tüm Postalar" (arşivlenenler dahil), dil fark etmez
                klasor = s.split(' "/" ')[-1].strip()
                break
        m.select(klasor, readonly=True)
        bas = max(MAIL_BASLANGIC, hb.simdi().date() - dt.timedelta(days=gun))
        # Gmail "after:" gün başını Pasifik saatine göre alır; bir gün önceden sorup tarihe göre ayrıca süzeriz
        m.literal = MAIL_SORGU.format(after=(bas - dt.timedelta(days=1)).strftime("%Y/%m/%d")).encode("utf-8")
        typ, veri = m.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
        uidler = (veri[0] or b"").split() if veri else []
        for uid in list(reversed(uidler))[:en_fazla * 2]:
            typ, d = m.uid("FETCH", uid, "(X-GM-MSGID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            ham = b"".join(x[1] for x in d if isinstance(x, tuple)) if d else b""
            mid = re.search(rb"X-GM-MSGID (\d+)", b" ".join(x[0] if isinstance(x, tuple) else x for x in d if x)) if d else None
            kimlik = (mid.group(1).decode() if mid else uid.decode())
            if kimlik in gorulen:
                continue
            typ, d = m.uid("FETCH", uid, "(BODY.PEEK[])")
            govde = next((x[1] for x in d if isinstance(x, tuple)), None) if d else None
            if not govde:
                continue
            msg = email.message_from_bytes(govde)
            metin, pdfler = _mail_metin(msg)
            try:
                tarih = parsedate_to_datetime(msg.get("Date")).astimezone(hb.TZ)
            except Exception:
                tarih = hb.simdi()
            if tarih.date() < bas:
                continue  # başlangıç tarihinden eski: atla
            sonuc.append({"id": kimlik, "kimden": _baslik(msg.get("From")), "konu": _baslik(msg.get("Subject")),
                          "tarih": tarih, "metin": metin, "pdfler": pdfler})
            if len(sonuc) >= en_fazla:
                break
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return sonuc


ABONELIK_TURLERI = {"Elektrik", "Su", "Doğalgaz", "İnternet", "Telefon", "Aidat", "Yakıt", "Kira", "Sigorta"}


def mail_fatura_coz(mail: dict, api_anahtari: str, turler: list[str] | None = None) -> dict:
    """Bir e-postayı sınıflandırır:
    cesit = 'abonelik' (ödenecek kurum faturası) | 'alisveris' (satın alınmış ürün/hizmet faturası, zaten ödenmiş)
            | 'ekstre' (kredi kartı hesap özeti) | 'degil' (reklam, dekont, kargo…)."""
    turler = turler or FATURA_TURLERI
    pdf = None
    for _, v in mail.get("pdfler") or []:
        try:
            v = pdf_sifresini_coz(v)
        except PdfSifreli:
            continue  # şifreli PDF: mail metniyle yetinilir
        pdf = v
        break
    istem = f"""Aşağıdaki e-postayı sınıflandır ve bilgilerini çıkar.
Kimden: {mail.get('kimden')}
Konu: {mail.get('konu')}
Tarih: {mail.get('tarih'):%d.%m.%Y}
Metin:
{mail.get('metin') or ''}
{'(PDF eki ekte.)' if pdf else ''}
YALNIZCA şu JSON'u döndür:
{{"cesit": "abonelik | alisveris | ekstre | degil",
"tur": "{'/'.join(turler)} değerlerinden biri", "kurum": "", "abone_no": "", "donem": "Ekim 2026",
"fatura_tarihi": "GG.AA.YYYY", "son_odeme": "GG.AA.YYYY", "tutar": 0.0, "tuketim": null, "birim": "", "birim_fiyat": null,
"urunler": "alışveriş faturasıysa kısa ürün listesi (örn. Philips buharlı ütü)"}}
Sınıflandırma kuralları (çok önemli):
- "abonelik": elektrik, su, doğalgaz, internet, sabit/mobil telefon, aidat, kira, sigorta gibi DÜZENLİ hizmet faturası.
  Bunlarda genelde abone/tesisat/müşteri numarası, fatura dönemi ve SON ÖDEME TARİHİ bulunur ve henüz ödenmemiştir.
- "alisveris": bir mağazadan, kişiden (şahıs firması) ya da internetten SATIN ALINMIŞ ürün/hizmetin e-arşiv / e-fatura
  belgesi (ütü, telefon cihazı, market, kıyafet, sipariş…). Bunlar alışverişte ÖDENMİŞTİR; son ödeme tarihi yoktur.
- "ekstre": kredi kartı hesap özeti. "degil": reklam, kampanya, ödeme dekontu/makbuz ("ödemeniz alındı"), kargo, bülten.
- abone_no: abone / tesisat / müşteri / hizmet numarası; GSM ya da ev interneti faturasında faturası kesilen telefon veya
  hizmet numarası (örn. 5xx xxx xx xx, 00177…).
- Emin değilsen "abonelik" DEME. Belgede açıkça yazmayan alanı null bırak; tarih UYDURMA."""
    j = gemini(istem, api_anahtari, gorsel=pdf, mime="application/pdf") if pdf else gemini(istem, api_anahtari)
    if not isinstance(j, dict):
        return {"cesit": "degil"}
    cesit = str(j.get("cesit") or "degil").strip().lower()
    tutar = hb.tutar_coz(j.get("tutar"))
    tur = j.get("tur") if j.get("tur") in turler else "Diğer"
    bilgi = {"tur": tur, "kurum": (j.get("kurum") or "").strip() or None,
             "abone_no": str(j.get("abone_no") or "").strip() or None, "donem": (j.get("donem") or "").strip() or None,
             "fatura_tarihi": _tarih_al(j.get("fatura_tarihi")), "son_odeme": _tarih_al(j.get("son_odeme")),
             "tutar": abs(tutar) if tutar else None, "tuketim": hb.tutar_coz(j.get("tuketim")),
             "birim": (j.get("birim") or "").strip() or None, "birim_fiyat": hb.tutar_coz(j.get("birim_fiyat")),
             "urunler": (j.get("urunler") or "").strip() or None, "pdf": pdf}
    if bilgi["abone_no"] and bilgi["abone_no"].lower() in ("null", "none", "-", "0"):
        bilgi["abone_no"] = None
    if cesit == "ekstre":
        return {"cesit": "ekstre", **bilgi}
    if not tutar or cesit not in ("abonelik", "alisveris"):
        return {"cesit": "degil"}
    if cesit == "abonelik":
        # güvenlik ağı: gerçek bir abonelik faturası tanınır türde olmalı ve abone no ya da son ödeme tarihi taşımalı
        ozel = tur not in FATURA_TURLERI  # kullanıcının eklediği tür
        if not (tur in ABONELIK_TURLERI or ozel) or not (bilgi["abone_no"] or bilgi["son_odeme"]):
            cesit = "alisveris"
    return {"cesit": cesit, **bilgi}



# ----------------------------------------------------------------------------
# PBY (Profesyonel Bina Yönetimi) ekran görüntüsünden aylık bina giderleri
# ----------------------------------------------------------------------------
def pby_analiz_et(gorsel: bytes, mime: str, api_anahtari: str) -> dict:
    """PBY uygulamasının borç/tahakkuk ekranından kalemleri okur.
    -> {"donem": "Kasım 2026", "kalemler": [{"ad", "tutar", "son_odeme", "cesit": yakit|aidat|elektrik|diger, "odendi"}]}"""
    istem = """Bu, bir apartman/site yönetim uygulamasının (PBY – Profesyonel Bina Yönetimi) ekran görüntüsü. Bu ayın
tahakkuk / borç kalemlerini oku. YALNIZCA şu JSON'u döndür:
{"donem": "Kasım 2026", "kalemler": [{"ad": "ekrandaki kalem adı", "tutar": 0.0, "son_odeme": "GG.AA.YYYY",
"cesit": "yakit | aidat | elektrik | diger", "odendi": false}]}
Kurallar:
- cesit: yakıt / ısınma / doğalgaz / kalorifer / mazot payı → "yakit"; aidat / yönetim gideri → "aidat";
  elektrik / ortak alan elektriği → "elektrik"; diğer her şey (su, demirbaş, asansör, temizlik…) → "diger".
- Ödenmiş görünen kalemler için odendi=true. Tutarları sayı yaz (1.234,56 → 1234.56).
- Ekranda açıkça görünmeyen tarih ya da tutarı null bırak; UYDURMA."""
    j = gemini(istem, api_anahtari, gorsel=gorsel, mime=mime, sicaklik=0.1)
    if not isinstance(j, dict):
        raise hb.ApiHatasi(500, "PBY ekranı okunamadı")
    kalemler = []
    for k in j.get("kalemler") or []:
        if not isinstance(k, dict):
            continue
        t = hb.tutar_coz(k.get("tutar"))
        if not t or t <= 0:
            continue
        cesit = str(k.get("cesit") or "diger").lower()
        if cesit not in ("yakit", "aidat", "elektrik", "diger"):
            cesit = "diger"
        kalemler.append({"ad": str(k.get("ad") or cesit).strip()[:60], "tutar": round(abs(t), 2),
                         "son_odeme": _tarih_al(k.get("son_odeme")), "cesit": cesit, "odendi": bool(k.get("odendi"))})
    return {"donem": (j.get("donem") or "").strip() or None, "kalemler": kalemler}


def pby_faturalara_cevir(sonuc: dict, aidata_dahil: set[str] | None = None) -> list[dict]:
    """Kural: yakıt → 'Yakıt' faturası; aidat + elektrik (+ seçilen diğerleri) toplamı → 'Aidat' faturası.
    Son ödeme: hepsinde yakıtın son ödeme tarihi (yoksa kalemlerdeki ilk tarih)."""
    aidata_dahil = aidata_dahil if aidata_dahil is not None else set()
    kalemler = [k for k in sonuc["kalemler"] if not k.get("odendi")]
    yakit = [k for k in kalemler if k["cesit"] == "yakit"]
    aidat = [k for k in kalemler if k["cesit"] in ("aidat", "elektrik") or k["ad"] in aidata_dahil]
    son = next((k["son_odeme"] for k in yakit if k.get("son_odeme")), None) or \
        next((k["son_odeme"] for k in kalemler if k.get("son_odeme")), None)
    faturalar = []
    if yakit:
        faturalar.append({"tur": "Yakıt", "tutar": round(sum(k["tutar"] for k in yakit), 2), "son_odeme": son,
                          "aciklama": " + ".join(k["ad"] for k in yakit)})
    if aidat:
        faturalar.append({"tur": "Aidat", "tutar": round(sum(k["tutar"] for k in aidat), 2), "son_odeme": son,
                          "aciklama": " + ".join(f"{k['ad']} {hb.tl(k['tutar'])}" for k in aidat)})
    return faturalar


# ----------------------------------------------------------------------------
# Alışkanlık analizi: hangi ürün ne sıklıkla, ne kadar alınıyor
# ----------------------------------------------------------------------------
def aliskanliklar(islemler: list[dict], bugun: dt.date | None = None, en_az: int = 3) -> list[dict]:
    bugun = bugun or hb.simdi().date()
    gruplar: dict[str, list] = {}
    for i in islemler:
        if i.get("tur") != "Gider" or not i.get("urun"):
            continue
        anahtar = hb.urun_anahtari(i["urun"])
        if len(anahtar) < 3:
            continue
        gruplar.setdefault(anahtar, []).append(i)
    sonuc = []
    for anahtar, ks in gruplar.items():
        ks = sorted(ks, key=lambda k: str(k.get("tarih") or ""))
        gunler = sorted({hb.tarih_yerel(k["tarih"]).date() for k in ks})
        if len(gunler) < en_az:
            continue
        araliklar = [(b - a).days for a, b in zip(gunler, gunler[1:]) if (b - a).days > 0]
        if not araliklar:
            continue
        ort_aralik = sum(araliklar) / len(araliklar)
        toplam = sum(float(k.get("tutar") or 0) for k in ks)
        ilk, son = gunler[0], gunler[-1]
        ay = max(1.0, ((bugun - ilk).days or 1) / 30.4)
        gecen = (bugun - son).days
        ad = max((k["urun"] for k in ks), key=lambda u: sum(1 for k in ks if k["urun"] == u))
        sonuc.append({"anahtar": anahtar, "ad": ad, "adet": len(gunler), "ort_aralik": round(ort_aralik, 1),
                      "ort_tutar": round(toplam / len(ks), 2), "aylik": round(toplam / ay, 2), "son": son.isoformat(),
                      "gecen_gun": gecen, "sonraki": (son + dt.timedelta(days=round(ort_aralik))).isoformat(),
                      "yakinda": gecen >= ort_aralik * 0.85 and gecen <= ort_aralik * 3,
                      "kategori": ks[-1].get("kategori"), "son_fiyat": float(ks[-1].get("birim_fiyat") or ks[-1].get("tutar") or 0),
                      "ilk_fiyat": float(ks[0].get("birim_fiyat") or ks[0].get("tutar") or 0)})
    return sorted(sonuc, key=lambda x: -x["aylik"])


def kategori_ortalamalari(islemler: list[dict], donemler: list[tuple[dt.date, dt.date]]) -> dict[str, float]:
    """Verilen tamamlanmış dönemlerde kategori başına ortalama harcama."""
    toplam: dict[str, float] = {}
    for bas, bit in donemler:
        for i in islemler:
            if i.get("tur") != "Gider":
                continue
            g = hb.tarih_yerel(i["tarih"]).date()
            if bas <= g <= bit:
                k = i.get("kategori") or "Diğer"
                toplam[k] = toplam.get(k, 0.0) + float(i.get("tutar") or 0)
    n = max(1, len(donemler))
    return {k: round(v / n, 2) for k, v in sorted(toplam.items(), key=lambda kv: -kv[1])}


# ----------------------------------------------------------------------------
# Harcama temposu: toplu (sabit) ödemeler ve büyük tek seferlik alışverişler günlük tempoya girmez
# ----------------------------------------------------------------------------
SABIT_KATEGORILER = {"Kira & Aidat & Faturalar", "Kredi Kartı, Kredi Ödemesi & Borç", "Yatırım & Altın & Döviz",
                     "Vergi, Harç & Resmi İşlemler", "Transfer / Birikim"}
SABIT_ACIKLAMALAR = {"Fatura ödemesi", "Kredi kartı taksidi", "Düzenli ödeme", "Hedefe aktarım", "Varlık alımı"}


def sabit_odeme_mi(i: dict) -> bool:
    """Fatura, kart, kira/aidat, taksit, birikim, yatırım gibi toplu ödemeler."""
    return (i.get("kategori") in SABIT_KATEGORILER or (i.get("aciklama") or "") in SABIT_ACIKLAMALAR
            or bool(i.get("hedef_id")))


def tempo_analizi(islemler: list[dict], bas: dt.date, bit: dt.date, bugun: dt.date,
                  kalan_sabit: float = 0.0, onceki: list[dict] | None = None) -> dict | None:
    """Dönemin harcamasını üçe ayırır: sabit ödemeler, büyük tek seferlik alışverişler, günlük harcamalar.
    Tahmin = ödenen sabit + büyük alışveriş + bu dönem kalan bilinen sabitler + tipik gün × kalan gün."""
    toplam_gun = (bit - bas).days + 1
    if bugun < bas:
        return None
    gecen = min((bugun - bas).days + 1, toplam_gun)

    def ayir(kayitlar, b, son_gun):
        alimlar = {}  # bir fiş = tek alışveriş
        sabit = 0.0
        gunluk_sabit = {}
        for i in kayitlar or []:
            if i.get("tur") != "Gider":
                continue
            g = hb.tarih_yerel(i.get("tarih")).date()
            if not (b <= g <= son_gun):
                continue
            t = float(i.get("tutar") or 0)
            if sabit_odeme_mi(i):
                sabit += t
                gunluk_sabit[g] = gunluk_sabit.get(g, 0) + t
                continue
            a = alimlar.setdefault(i.get("fis_grup") or f"k{i.get('id')}", {"gun": g, "tutar": 0.0})
            a["tutar"] += t
        tutarlar = sorted(a["tutar"] for a in alimlar.values() if a["tutar"] > 0)
        orta = tutarlar[(len(tutarlar) - 1) // 2] if tutarlar else 0.0  # tipik tek alışveriş
        esik = max(1500.0, 8 * orta)
        buyuk = [a for a in alimlar.values() if a["tutar"] > esik]
        gunluk = {}
        for a in alimlar.values():
            if a not in buyuk:
                gunluk[a["gun"]] = gunluk.get(a["gun"], 0) + a["tutar"]
        return sabit, gunluk_sabit, buyuk, gunluk

    sabit, gunluk_sabit, buyuk, gunluk = ayir(islemler, bas, bit)
    gunluk_top = sum(gunluk.values())
    tipik = gunluk_top / gecen if gecen else 0.0
    buyuk_top = sum(a["tutar"] for a in buyuk)
    tahmin = sabit + buyuk_top + max(0.0, kalan_sabit) + tipik * (toplam_gun - gecen)
    sonuc = {"toplam_gun": toplam_gun, "gecen": gecen, "sabit": sabit, "kalan_sabit": max(0.0, kalan_sabit),
             "buyuk": buyuk_top, "buyuk_adet": len(buyuk), "gunluk_toplam": gunluk_top, "tipik": tipik, "tahmin": tahmin,
             "gun_gunluk": gunluk, "gun_toplu": {**gunluk_sabit}, "karsilastirma": None}
    for a in buyuk:
        sonuc["gun_toplu"][a["gun"]] = sonuc["gun_toplu"].get(a["gun"], 0) + a["tutar"]
    if onceki:
        o_bas, _ = hb.butce_donemi(bas, -1)
        _, _, _, o_gunluk = ayir(onceki, o_bas, o_bas + dt.timedelta(days=gecen - 1))
        o_top = sum(o_gunluk.values())
        if o_top > 0:
            sonuc["karsilastirma"] = (gunluk_top - o_top) / o_top
    return sonuc


# ================================================================== ek ders tahmini (öğretmen)
# Brüt gündüz ek ders saat ücreti (kadrolu öğretmen, lisans) – ozkansoft.com EDUHEP 2026 ile hesaplandı (16.11.2026).
# Anahtar: (yıl, 1: Ocak-Haziran / 2: Temmuz-Aralık). Bilinmeyen dönemde en yakın önceki dönem kullanılır.
EK_DERS_BRUT = {(2026, 2): 220.5717, (2027, 1): round(220.5717 * 1.05, 4)}
# Haftalık program (puantaja göre, gün başına ödenen saat: gündüz + okul nöbeti + ek ders yerine geçen görevler)
# Ekim 2026 puantajı: Pzt 3 nöbet + 2 yer.geç. + 3 gündüz = 8; Çar 2; Per 2; Cum 2 yer.geç. + 2 gündüz = 4 → haftada 16.
EK_DERS_VARSAYILAN = {"program": {"0": 8, "1": 0, "2": 2, "3": 2, "4": 4},
                      "pansiyon_saat": 8, "ara_tatil_gunluk": 3, "diger_saat": 0,
                      "gv_orani": 20, "dv_orani": 0.759, "brut": None,   # Ekim 2026 bordrosu %20 dilimiyle kuruşu kuruşuna tuttu
                      # asgari ücret istisnası (2026 Temmuz–Aralık, ozkansoft EDUHEP): aylık gelir vergisi istisnası ve
                      # damga vergisi istisna matrahı. Maaşta kullanılmadığı için ek derste uygulanıyor (Ekim bordrosu).
                      "gv_istisna": 5615.10, "dv_istisna": 33030.0,
                      "odeme_bas": 5, "odeme_bit": 8, "nobetler": {}}
GUN_ADLARI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma"]
# hb_tatiller okunamazsa (internetsiz) kullanılacak 2026-2027 MEB takvimi
MEB_TATILLER = [("2026-06-27", "2026-09-06", "Yaz tatili"), ("2026-10-29", "2026-10-29", "Cumhuriyet Bayramı"), ("2026-11-16", "2026-11-20", "1. ara tatil"),
                ("2027-01-01", "2027-01-01", "Yılbaşı"), ("2027-01-25", "2027-02-05", "Yarıyıl tatili"),
                ("2027-03-08", "2027-03-12", "2. ara tatil / Ramazan Bayramı"), ("2027-04-23", "2027-04-23", "23 Nisan"),
                ("2027-05-01", "2027-05-01", "1 Mayıs"), ("2027-05-17", "2027-05-20", "Kurban Bayramı"),
                ("2027-05-19", "2027-05-19", "19 Mayıs"), ("2027-06-26", "2027-09-12", "Yaz tatili")]


def ek_ders_brut(yil: int, ay: int) -> float:
    anahtar = (yil, 1 if ay <= 6 else 2)
    onceki = [k for k in EK_DERS_BRUT if k <= anahtar]
    return EK_DERS_BRUT[max(onceki)] if onceki else EK_DERS_BRUT[min(EK_DERS_BRUT)]


def _tatil_turu(gun: dt.date, tatiller) -> str | None:
    """None: okul günü (resmî bayram günü de – puantajda ödeniyor), 'ara': ara tatil (günlük sabit ek ders),
    'uzun': yaz / yarıyıl tatili (ödeme yok)."""
    for t in tatiller or MEB_TATILLER:
        bas, bit, ad = (t.get("bas"), t.get("bit"), t.get("ad")) if isinstance(t, dict) else t
        try:
            b, s = dt.date.fromisoformat(str(bas)[:10]), dt.date.fromisoformat(str(bit)[:10])
        except Exception:
            continue
        if b <= gun <= s:
            ad = (ad or "").lower()
            if "ara tatil" in ad:
                return "ara"
            if "yaz" in ad or "yarıyıl" in ad or "yariyil" in ad or "sömestr" in ad:
                return "uzun"
    return None


EK_DERS_PANSIYON_EN_FAZLA = 8


def ek_ders_haftalari(yil: int, ay: int) -> tuple[dt.date, dt.date]:
    """Hafta bütünlüğü: perşembesi bu ayda olan haftalar bu aya sayılır (Ekim 2026 = 28 Eylül – 1 Kasım)."""
    ilk = dt.date(yil, ay, 1)
    pers = ilk + dt.timedelta(days=(3 - ilk.weekday()) % 7)          # ayın ilk perşembesi
    bas = pers - dt.timedelta(days=3)                                # o haftanın pazartesi
    son = dt.date(yil, ay, calendar.monthrange(yil, ay)[1])
    spers = son - dt.timedelta(days=(son.weekday() - 3) % 7)         # ayın son perşembesi
    return bas, spers + dt.timedelta(days=3)                         # o haftanın pazarı


def ek_ders_tahmini(ayar: dict | None, yil: int, ay: int, tatiller=None, pansiyon: int | None = None) -> dict:
    """Bir ayın tahmini ek ders ücreti. Hafta bütünlüğüyle aya ait haftalarda her okul günü programdaki saat kadar
    (resmî bayram günleri de ödenir), ara tatilde günlük sabit saat, yaz/yarıyıl tatilinde 0. Pansiyon nöbeti
    (belleticilik) = N × 8 saat (ayda en fazla 8). Gelir vergisi ve damga vergisinden asgari ücret istisnası düşülür.
    Ücret bir sonraki ayın 5–8'inde ödenir."""
    a = {**EK_DERS_VARSAYILAN, **(ayar or {})}
    program = {int(k): float(v or 0) for k, v in {**EK_DERS_VARSAYILAN["program"], **(a.get("program") or {})}.items()}
    bas, bit = ek_ders_haftalari(yil, ay)
    okul = ara = 0
    saat_ders = 0.0
    d = bas
    while d <= bit:
        if d.weekday() < 5:
            t = _tatil_turu(d, tatiller)
            if t is None:
                okul += 1
                saat_ders += program.get(d.weekday(), 0)
            elif t == "ara":
                ara += 1
        d += dt.timedelta(days=1)
    if pansiyon is None:
        pansiyon = int((a.get("nobetler") or {}).get(f"{yil}-{ay:02d}", 0) or 0)
    pansiyon = max(0, min(int(pansiyon), EK_DERS_PANSIYON_EN_FAZLA))
    saat_ara = round(float(a["ara_tatil_gunluk"]) * ara, 1)
    saat_pansiyon = float(pansiyon) * float(a["pansiyon_saat"])
    saat_diger = float(a.get("diger_saat") or 0)
    saat = round(saat_ders + saat_ara + saat_pansiyon + saat_diger, 1)
    pu = (a.get("puantajlar") or {}).get(f"{yil}-{ay:02d}")
    if pu:  # o ayın puantajı yüklendiyse tahmin değil, puantajdaki saatler
        t = pu.get("toplam") or {}
        bas, bit = dt.date.fromisoformat(pu["bas"]), dt.date.fromisoformat(pu["bit"])
        saat_pansiyon = float(t.get("belleticilik") or 0)
        pansiyon = int(round(saat_pansiyon / max(float(a["pansiyon_saat"]), 1)))
        saat_diger = float(t.get("diger") or 0)
        saat_ders = float(t.get("gunduz") or 0) + float(t.get("nobet") or 0) + float(t.get("yer_gec") or 0)
        saat_ara = 0.0
        saat = round(float(pu.get("toplam_saat") or (saat_ders + saat_pansiyon + saat_diger)), 1)
    brut_saat = float(a["brut"] or ek_ders_brut(yil, ay))
    gv_or, dv_or = float(a["gv_orani"]) / 100, float(a["dv_orani"]) / 100
    gv_ist, dv_ist = float(a.get("gv_istisna") or 0), float(a.get("dv_istisna") or 0)

    def hesap(sa):
        b = round(sa * brut_saat, 2)
        g = round(max(b * gv_or - gv_ist, 0), 2)
        v = round(max(b - dv_ist, 0) * dv_or, 2)
        return b, g, v, round(b - g - v, 2)

    brut, gv, dv, net = hesap(saat)
    pansiyonsuz = hesap(saat - saat_pansiyon)[3]
    tek = hesap(saat - saat_pansiyon + float(a["pansiyon_saat"]))[3] - pansiyonsuz
    oy, oa = (yil + 1, 1) if ay == 12 else (yil, ay + 1)
    return {"yil": yil, "ay": ay, "bas": bas, "bit": bit, "hafta": ((bit - bas).days + 1) // 7,
            "okul_gunu": okul, "ara_tatil_gunu": ara, "haftalik": sum(program.values()),
            "saat_ders": round(saat_ders, 1), "saat_ara": saat_ara, "pansiyon": pansiyon, "saat_pansiyon": saat_pansiyon,
            "saat_diger": saat_diger, "saat": saat, "puantaj": pu, "brut_saat": brut_saat, "brut": brut, "gv": gv, "dv": dv, "net": net,
            "pansiyon_net": round(tek, 2),
            "odeme_bas": dt.date(oy, oa, int(a["odeme_bas"])), "odeme_bit": dt.date(oy, oa, int(a["odeme_bit"]))}


def ek_ders_yatan(islemler: list[dict], tahmin: dict) -> float | None:
    """O ayın ek dersi olarak yatan gerçek tutar (ödeme günleri ±5 gün içindeki 'ek ders' gelirleri)."""
    bas, bit = tahmin["odeme_bas"] - dt.timedelta(days=5), tahmin["odeme_bit"] + dt.timedelta(days=5)
    toplam, var = 0.0, False
    for i in islemler or []:
        if i.get("tur") != "Gelir":
            continue
        metin = " ".join(str(i.get(k) or "") for k in ("kategori", "urun", "aciklama")).lower()
        if "ek ders" not in metin and "ekders" not in metin:
            continue
        try:
            g = hb_tarih(i.get("tarih"))
        except Exception:
            continue
        if bas <= g <= bit:
            toplam += float(i.get("tutar") or 0)
            var = True
    return round(toplam, 2) if var else None


def hb_tarih(iso) -> dt.date:
    s = str(iso)
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone(dt.timezone(dt.timedelta(hours=3)))
        return d.date()
    except Exception:
        return dt.date.fromisoformat(s[:10])


# ================================================================== maaş tahmini (bordro + ek ders, ortak vergi matrahı)
# Gelir vergisi tarifesi (ücret). 2026: 190.000 / 400.000 / 1.500.000 / 5.300.000 – Kasım 2026 bordrosuyla doğrulandı.
VERGI_DILIMLERI = {2026: [(190000, 15), (400000, 20), (1500000, 27), (5300000, 35), (None, 40)]}
# Asgari ücret (brüt) – damga istisna matrahı ve gelir vergisi istisnasının kaynağı (ozkansoft EDUHEP: 33.030 / 5.615,10).
ASGARI_BRUT = {2026: 33030.0}
DAMGA_ORANI = 0.759


def _dilimler(yil):
    return VERGI_DILIMLERI.get(yil) or VERGI_DILIMLERI[max(k for k in VERGI_DILIMLERI if k <= yil)] \
        if any(k <= yil for k in VERGI_DILIMLERI) else VERGI_DILIMLERI[min(VERGI_DILIMLERI)]


def gelir_vergisi(onceki: float, matrah: float, yil: int) -> float:
    """Kümülatif matrahı 'onceki' olan kişinin bu 'matrah' için ödeyeceği gelir vergisi (artan oranlı)."""
    vergi, alt, kalan, k = 0.0, 0.0, max(matrah, 0), max(onceki, 0)
    for ust, oran in _dilimler(yil):
        ust = float("inf") if ust is None else ust
        if k < ust and kalan > 0:
            pay = min(kalan, ust - k)
            vergi += pay * oran / 100
            kalan -= pay
            k += pay
        alt = ust
    return round(vergi, 2)


def asgari_istisna(yil: int, ay: int) -> tuple[float, float]:
    """(gelir vergisi istisnası ₺, damga vergisi istisnası ₺) – o takvim ayında ödenen tüm ücretler paylaşır."""
    brut = ASGARI_BRUT.get(yil) or ASGARI_BRUT[max(ASGARI_BRUT)]
    matrah = round(brut * 0.85, 2)                        # %14 SGK + %1 işsizlik düşülür
    gv = gelir_vergisi(matrah * (ay - 1), matrah, yil if yil in VERGI_DILIMLERI else max(VERGI_DILIMLERI))
    return gv, round(brut * DAMGA_ORANI / 100, 2)


def maas_profili(b: dict) -> dict:
    """Bordrodaki 8 rakamdan (Gelir Toplamı, Gelir V., Damga V., Net, Aylık Vergi Matrahı, Geçen Aylar Matrahı,
    Damga V. İstisna Tutarı, ay) sabit kesintiyi ve damga matrahını çıkarır."""
    gelir, gv, dv, net = (float(b.get(k) or 0) for k in ("gelir", "gv", "dv", "net"))
    return {**b, "sabit_kesinti": round(gelir - net - gv - dv, 2),
            "damga_matrah": round((dv + float(b.get("dv_ist") or 0)) / (DAMGA_ORANI / 100), 2),
            "kumulatif": round(float(b.get("gecen") or 0) + float(b.get("matrah") or 0), 2)}


def maas_zinciri(bordro: dict, ek_ders_ayar: dict | None, tatiller=None, ay_sayisi: int = 2) -> list[dict]:
    """Son bordrodan sonraki ödemeleri sırayla hesaplar: her ayın 5–8'inde geçen ayın ek dersi, 15'inde o ayın maaşı.
    Gelir vergisi istisnası önce ek derse, kalanı maaşa uygulanır; matrah yıl içinde birikir (Ocak'ta sıfırlanır).
    Maaş tutarı son bordrodaki gibi kabul edilir (Ocak / Temmuz zamları hariç)."""
    p = maas_profili(bordro)
    y, m = (int(x) for x in str(p["ay"]).split("-"))
    kum, kum_yil = p["kumulatif"], y
    sonuc = []
    for _ in range(ay_sayisi):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if y != kum_yil:
            kum, kum_yil = 0.0, y
        gv_ist, dv_ist = asgari_istisna(y, m)
        vy = y if y in VERGI_DILIMLERI else max(VERGI_DILIMLERI)
        # 1) geçen ayın ek dersi (5–8'i)
        ey, em = (y - 1, 12) if m == 1 else (y, m - 1)
        e = ek_ders_tahmini(ek_ders_ayar, ey, em, tatiller) if ek_ders_ayar is not None else None
        if e:
            b = e["brut"]
            ham = gelir_vergisi(kum, b, vy)
            e_gv = round(max(ham - gv_ist, 0), 2)
            gv_ist = round(max(gv_ist - ham, 0), 2)
            ham_dv = round(b * DAMGA_ORANI / 100, 2)
            e_dv = round(max(ham_dv - dv_ist, 0), 2)
            dv_ist = round(max(dv_ist - ham_dv, 0), 2)
            kum = round(kum + b, 2)
            sonuc.append({"tur": "ekders", "ait_yil": ey, "ait_ay": em, "odeme": e["odeme_bas"], "brut": b,
                          "gv": e_gv, "dv": e_dv, "net": round(b - e_gv - e_dv, 2), "saat": e["saat"],
                          "pansiyon": e["pansiyon"], "kumulatif_sonra": kum})
        # 2) bu ayın maaşı (15'i)
        mat = float(p["matrah"])
        ham = gelir_vergisi(kum, mat, vy)
        m_gv = round(max(ham - gv_ist, 0), 2)
        ham_dv = round(float(p["damga_matrah"]) * DAMGA_ORANI / 100, 2)
        m_dv = round(max(ham_dv - dv_ist, 0), 2)
        onceki_kum = kum
        kum = round(kum + mat, 2)
        net = round(float(p["gelir"]) - float(p["sabit_kesinti"]) - m_gv - m_dv, 2)
        oran = next(o for u, o in _dilimler(vy) if u is None or kum <= u)
        sonuc.append({"tur": "maas", "ait_yil": y, "ait_ay": m, "odeme": dt.date(y, m, 15), "brut": float(p["gelir"]),
                      "gv": m_gv, "dv": m_dv, "net": net, "istisna_gv": round(min(ham, gv_ist), 2), "dilim": oran,
                      "kumulatif_sonra": kum, "zam_haric": y != int(str(p["ay"])[:4]) or (m == 7)})
    return sonuc


# ---------------------------------------------------------------- e-Devlet "Personel Bordro Bilgileri" PDF'i
def bordro_mu(metin: str) -> bool:
    return "PERSONEL BORDRO" in (metin or "").upper() and "Net Ödenen" in (metin or "")


def bordro_coz(metin: str) -> dict | None:
    """e-Devlet bordro PDF metninden tahmin için gereken rakamlar (telefonda okunur, hiçbir yere gönderilmez).
    Kimlik / sicil gibi kişisel bilgiler alınmaz."""
    if not bordro_mu(metin):
        return None

    def sayi(desen):
        m = re.search(desen + r"\s*(-?\d+(?:\.\d+)?)", metin)
        return float(m.group(1)) if m else 0.0

    ay = re.search(r"Ait Olduğu Ay\s*(\d{1,2})", metin)
    yil = re.search(r"Bütçe Yılı\s*(\d{4})", metin)
    if not ay or not yil:
        return None
    b = {"ay": f"{yil.group(1)}-{int(ay.group(1)):02d}",
         "gelir": sayi(r"Gelir Toplamı"), "gv": sayi(r"Gelir Vergisi"), "dv": sayi(r"Damga Vergisi"),
         "net": sayi(r"Net Ödenen"), "matrah": sayi(r"Aylık Vergi Matrahı"),
         "gecen": sayi(r"Geçen Aylar Vergi Matrahı\s*(?:Toplamı)?"), "dv_ist": sayi(r"Damga Vergisi Istisna Tutarı")}
    b["kumulatif"] = round(b["gecen"] + b["matrah"], 2)
    return b if b["gelir"] > 0 and b["net"] > 0 else None


def bordro_sec(bordrolar: list[dict]) -> dict | None:
    """Birden çok bordrodan tahmine esas olanı seçer: en son ayın asıl bordrosu (en büyük gelirli). Aynı ay içindeki
    fark bordrolarının matrahı yılbaşından beri biriken matraha eklenir."""
    tekil = {}
    for b in bordrolar:  # aynı bordro iki kez yüklendiyse bir sayılır
        if b:
            k = (b["ay"], round(b["gelir"], 2), round(b["net"], 2), round(b["matrah"], 2))
            if k not in tekil or (b.get("kumulatif") or 0) > (tekil[k].get("kumulatif") or 0):
                tekil[k] = b
    bordrolar = list(tekil.values())
    if not bordrolar:
        return None
    son_ay = max(b["ay"] for b in bordrolar)
    ayni = [b for b in bordrolar if b["ay"] == son_ay]
    asil = dict(max(ayni, key=lambda b: b["gelir"]))
    kum = max(b.get("kumulatif") or (b["gecen"] + b["matrah"]) for b in ayni)
    asil["gecen"] = round(kum - asil["matrah"], 2)   # maas_profili kümülatifi buradan hesaplar
    asil["kumulatif"] = round(kum, 2)
    asil["fark_bordro"] = len(ayni) - 1
    return asil


# ---------------------------------------------------------------- ek ders puantaj takvimi (PDF / resim)
PUANTAJ_TURLERI = ("gunduz", "nobet", "yer_gec", "belleticilik", "diger")


def puantaj_mu(metin: str) -> bool:
    return "PUANTAJ" in (metin or "").upper() and "EK DERS" in (metin or "").upper()


def puantaj_analiz_et(veri: bytes, mime: str, api_anahtari: str) -> dict:
    """Okul Bilgi Sistemleri / MEBBİS 'Kişisel Ek Ders Puantajı' belgesini okur (Gemini; PDF ya da fotoğraf).
    Kimlik bilgileri istenmez; yalnızca günler ve saatler."""
    istem = """Bu, Okul Bilgi Sistemleri'nin 'Kişisel Ek Ders Puantajı (Kontrol Amaçlı)' belgesi: başlıkta
'<AY> <YIL> - EK DERS PUANTAJ TAKVİMİ', altında Pzt–Paz sütunlu bir takvim, en altta 'TOPLAM ÖZETLERİ' ve 'TOPLAM SAAT'.
Kişisel bilgileri (ad soyad, T.C. kimlik, telefon, kurum) YAZMA. YALNIZCA JSON döndür:
{"ay": "YYYY-MM (başlıktaki ay ve yıl)",
 "gunler": [{"tarih": "YYYY-MM-DD", "gunduz": 3, "nobet": 3, "yer_gec": 2, "belleticilik": 0, "diger": 0}],
 "toplamlar": {"gunduz": 45, "nobet": 15, "yer_gec": 20, "belleticilik": 48, "diger": 0},
 "toplam_saat": 128}
Kalem eşlemesi: 'Gündüz' → gunduz; 'Nöbet Görevi(Gündüz)' → nobet; 'Ek Ders Yer.Geç.Gör.(Gündüz)' → yer_gec;
'Belleticilik' → belleticilik; diğer her kalem (Gece, DYK, Kurs, Sınav, Hizmetiçi…) → diger.
Hücrelerde yıl yazmaz ('28 Eylül', '1 Kasım'): yılı başlıktan al; başlık Aralık ise 'Ocak' günleri sonraki yıl,
başlık Ocak ise 'Aralık' günleri önceki yıldır. Takvimde önceki / sonraki aydan günler de vardır (hafta bütünlüğü):
onları da kendi tarihleriyle yaz. '-' olan boş günleri yazma. toplamlar ve toplam_saat 'TOPLAM ÖZETLERİ' / 'TOPLAM SAAT'
bölümünden alınsın. Sayılar sayı olsun ('3 Saat' → 3)."""
    j = gemini(istem, api_anahtari, veri, mime)
    return puantaj_coz(j)


def puantaj_coz(j: dict) -> dict:
    gunler = {}
    for g in j.get("gunler") or []:
        try:
            d = dt.date.fromisoformat(str(g.get("tarih"))[:10])
        except Exception:
            continue
        gunler[d.isoformat()] = {k: float(hb.tutar_coz(g.get(k)) or 0) for k in PUANTAJ_TURLERI}
    if not gunler:
        raise ValueError("Puantajda gün bulunamadı")
    gun_top = {k: round(sum(v[k] for v in gunler.values()), 1) for k in PUANTAJ_TURLERI}
    belge_top = {k: float(hb.tutar_coz((j.get("toplamlar") or {}).get(k)) or 0) for k in PUANTAJ_TURLERI}
    toplam = belge_top if sum(belge_top.values()) > 0 else gun_top
    toplam_saat = float(hb.tutar_coz(j.get("toplam_saat")) or 0) or round(sum(toplam.values()), 1)
    bas, bit = min(gunler), max(gunler)
    ay = str(j.get("ay") or "")[:7]
    if not re.match(r"^\d{4}-\d{2}$", ay):  # perşembe kuralıyla: ortadaki günün ayı
        orta = dt.date.fromisoformat(bas) + (dt.date.fromisoformat(bit) - dt.date.fromisoformat(bas)) / 2
        ay = f"{orta.year}-{orta.month:02d}"
    y, m = (int(x) for x in ay.split("-"))
    hb_bas, hb_bit = ek_ders_haftalari(y, m)   # tablo ilk/son boş günleri göstermese de hafta bütünlüğü aralığı
    return {"ay": ay, "bas": min(bas, hb_bas.isoformat()), "bit": max(bit, hb_bit.isoformat()), "gunler": gunler,
            "toplam": toplam, "toplam_saat": toplam_saat, "gun_toplami": gun_top,
            "tutarli": abs(sum(gun_top.values()) - toplam_saat) < 0.6}


def puantajdan_program(p: dict) -> dict:
    """Puantajdan haftalık program: her hafta içi gün için en sık görülen (gündüz + nöbet + yer.geç.) saat."""
    from collections import Counter
    sayac = {g: Counter() for g in range(5)}
    for iso, v in p["gunler"].items():
        d = dt.date.fromisoformat(iso)
        if d.weekday() < 5:
            sayac[d.weekday()][v["gunduz"] + v["nobet"] + v["yer_gec"]] += 1
    prog = {}
    for g in range(5):
        prog[str(g)] = (sayac[g].most_common(1)[0][0] if sayac[g] else 0)
        prog[str(g)] = int(prog[str(g)]) if float(prog[str(g)]).is_integer() else prog[str(g)]
    return prog


_AY_ADLARI = ["OCAK", "ŞUBAT", "MART", "NİSAN", "MAYIS", "HAZİRAN", "TEMMUZ", "AĞUSTOS", "EYLÜL", "EKİM", "KASIM", "ARALIK"]


def puantaj_metinden(metin: str) -> dict | None:
    """Yazı katmanlı puantaj PDF'i telefonda okunur (Gemini'ye gitmez): başlıktaki ay + 'TOPLAM ÖZETLERİ'.
    Gün gün saatler alınmaz (haftalık program öğrenilmez); hafta aralığı hafta bütünlüğünden hesaplanır."""
    if not puantaj_mu(metin):
        return None
    ust = metin.upper().replace("İ", "İ")
    m = re.search(r"(" + "|".join(_AY_ADLARI) + r")\s+(\d{4})\s*-\s*EK DERS PUANTAJ", ust)
    if not m:
        return None
    ay = f"{m.group(2)}-{_AY_ADLARI.index(m.group(1)) + 1:02d}"
    ozet = metin[metin.upper().find("TOPLAM ÖZET"):] if "TOPLAM ÖZET" in metin.upper() else metin

    def saat(desen):
        x = re.search(desen + r"[^\d]{0,40}?(\d+(?:[.,]\d+)?)\s*Saat", ozet, re.I)
        return float(x.group(1).replace(",", ".")) if x else 0.0
    toplam = {"nobet": saat(r"Nöbet Görevi\s*\(Gündüz\)"), "yer_gec": saat(r"Ek Ders Yer\.?\s*Geç\.?\s*Gör\.?\s*\(Gündüz\)"),
              "belleticilik": saat(r"Belleticilik"), "gunduz": saat(r"(?<![(\w])Gündüz(?!\))"), "diger": 0.0}
    toplam_saat = saat(r"TOPLAM SAAT")
    if not toplam_saat:
        return None
    toplam["diger"] = round(max(toplam_saat - sum(toplam.values()), 0), 1)
    y, a = (int(x) for x in ay.split("-"))
    bas, bit = ek_ders_haftalari(y, a)
    return {"ay": ay, "bas": bas.isoformat(), "bit": bit.isoformat(), "gunler": {}, "toplam": toplam,
            "toplam_saat": toplam_saat, "gun_toplami": {}, "tutarli": True}
