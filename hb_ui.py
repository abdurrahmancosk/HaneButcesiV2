"""Hane Bütçesi v2 – ortak arayüz parçaları, renk paleti (açık/koyu tema)."""
import inspect

import flet as ft

import hb_core as hb

# ---------------------------------------------------------------------------
# Renkler
# ---------------------------------------------------------------------------
ANA = "#0d9488"          # turkuaz (iki temada da okunur)
GELIR = "#16a34a"
GIDER = "#dc2626"
AKTARIM = "#2563eb"
ALTIN = "#f5b841"        # vurgu: ekle düğmesi, rozetler
KOYU = False
ARKA = KART = YAZI = SOLUK = CIZGI = ZEMIN2 = UYARI_ZEMIN = BILGI_ZEMIN = None
VURGU = KASA_ZEMIN = KASA_IC = KASA_SOLUK = NAV_ZEMIN = GELIR_Y = GIDER_Y = None
YAZI_TIPI = "Inter"


def tema_uygula(koyu: bool):
    """“Gece” görsel dili: açık ve koyu iki palet. Ekranlar yeniden çizildiğinde yeni renkler kullanılır."""
    global KOYU, ARKA, KART, YAZI, SOLUK, CIZGI, ZEMIN2, UYARI_ZEMIN, BILGI_ZEMIN
    global VURGU, KASA_ZEMIN, KASA_IC, KASA_SOLUK, NAV_ZEMIN, GELIR_Y, GIDER_Y
    KOYU = koyu
    if koyu:
        ARKA, KART, YAZI, SOLUK = "#0b1220", "#121b2d", "#e8edf5", "#94a3b8"
        CIZGI, ZEMIN2, UYARI_ZEMIN, BILGI_ZEMIN = "#1f2a40", "#0e1626", "#3b1d1d", "#172554"
        VURGU, KASA_ZEMIN, KASA_IC, KASA_SOLUK = "#2dd4bf", "#121b2d", "#0e1626", "#94a3b8"
        NAV_ZEMIN, GELIR_Y, GIDER_Y = "#0e1626", "#4ade80", "#fca5a5"
    else:
        ARKA, KART, YAZI, SOLUK = "#f3f5f9", "#ffffff", "#0f172a", "#5b6678"
        CIZGI, ZEMIN2, UYARI_ZEMIN, BILGI_ZEMIN = "#e3e8ef", "#f1f4f8", "#fee2e2", "#dbeafe"
        VURGU, KASA_ZEMIN, KASA_IC, KASA_SOLUK = "#0d9488", "#0f1b33", "#1a2844", "#a5b4cb"
        NAV_ZEMIN, GELIR_Y, GIDER_Y = "#ffffff", "#15803d", "#b91c1c"


tema_uygula(False)


# ---------------------------------------------------------------------------
# Flet sürüm uyumluluğu (0.2x ve 1.x)
# ---------------------------------------------------------------------------
def _param_var(cls, ad):
    try:
        return ad in inspect.signature(cls.__init__).parameters
    except Exception:
        return False


def buton(metin, on_click=None, ikon=None, tip="filled", **kw):
    cls = {"filled": ft.FilledButton, "outlined": ft.OutlinedButton, "text": ft.TextButton,
           "tonal": getattr(ft, "FilledTonalButton", ft.FilledButton)}[tip]
    if _param_var(cls, "text"):
        return cls(text=metin, icon=ikon, on_click=on_click, **kw)
    return cls(content=metin, icon=ikon, on_click=on_click, **kw)


_SECENEK = getattr(ft, "DropdownOption", None) or ft.dropdown.Option


def acilir(etiket, secenekler, deger=None, **kw):
    return ft.Dropdown(label=etiket, value=deger, options=[_SECENEK(key=s, text=s) for s in secenekler], **kw)


def kenar(renk=None, kalinlik=1):
    renk = renk or CIZGI
    try:
        if hasattr(ft, "Border") and hasattr(ft.Border, "all"):
            return ft.Border.all(kalinlik, renk)
        return ft.border.all(kalinlik, renk)
    except Exception:
        return None


def kart(icerik, renk=None, dolgu=16, **kw):
    """Gece dili: koyuda ince çerçeveli düz kart, açıkta beyaz kart + yumuşak gölge."""
    ozel = renk is not None
    renk = renk or KART
    if KOYU and not ozel:
        kw.pop("shadow", None)
        kw.setdefault("border", kenar())
    kw.setdefault("border_radius", 20)
    return ft.Container(content=icerik, bgcolor=renk, padding=dolgu, **kw)


_AGIRLIK = {True: "InterB", "b": "InterB", "sb": "InterSB", "xb": "InterXB"}


def yazi(metin, boyut=14, kalin=False, renk=None, **kw):
    """kalin: False | True (kalın) | 'sb' (yarı kalın) | 'xb' (çok kalın – büyük rakamlar)."""
    renk = renk or YAZI
    aile = _AGIRLIK.get(kalin) if kalin else None
    if aile and "font_family" not in kw:
        kw["font_family"] = aile
    return ft.Text(metin, size=boyut, weight=ft.FontWeight.BOLD if kalin is True and not aile else None, color=renk, **kw)


def para(tutar, boyut=36, renk=None, soluk=None, isaret=False):
    """84.787,47 ₺ → büyük tam kısım + soluk kuruş."""
    m = hb.tl(tutar, isaret=isaret)
    tam, _, kurus = m.rpartition(",")
    renk = renk or YAZI
    if not tam:
        return yazi(m, boyut, "xb", renk=renk)
    try:
        return ft.Text(spans=[ft.TextSpan(tam, ft.TextStyle(size=boyut, font_family="InterXB", color=renk)),
                              ft.TextSpan("," + kurus, ft.TextStyle(size=boyut * 0.55, font_family="InterB",
                                                                    color=soluk or SOLUK))])
    except Exception:
        return yazi(m, boyut, "xb", renk=renk)


# ---------------------------------------------------------------------------
# Görsel dil: kategori simgeleri / renkleri, gölge, degrade
# ---------------------------------------------------------------------------
KATEGORI_STIL = {
    "Market & Temel Gıda": ("SHOPPING_CART", "#16a34a"),
    "Abur Cubur & Atıştırmalık": ("COOKIE", "#f59e0b"),
    "Kira & Aidat & Faturalar": ("RECEIPT_LONG", "#0284c7"),
    "Ev": ("HOME", "#8b5cf6"),
    "Temizlik & Hijyen & Kişisel Bakım": ("CLEANING_SERVICES", "#06b6d4"),
    "Giyim, Ayakkabı & Aksesuar": ("CHECKROOM", "#ec4899"),
    "Sağlık, İlaç & Medikal": ("MEDICAL_SERVICES", "#ef4444"),
    "Sağlık": ("MEDICAL_SERVICES", "#ef4444"),
    "Eğitim, Okul & Kırtasiye": ("SCHOOL", "#6366f1"),
    "Ulaşım & Toplu Taşıma": ("DIRECTIONS_BUS", "#0891b2"),
    "Dışarıda Yemek & Kafe & Restoran": ("RESTAURANT", "#f97316"),
    "Dışarıda Yemek / Eğlence": ("RESTAURANT", "#f97316"),
    "Eğlence, Kültür & Etkinlik": ("THEATER_COMEDY", "#a855f7"),
    "Elektronik & Teknoloji": ("DEVICES", "#475569"),
    "Ev Eşyası & Mobilya & Beyaz Eşya": ("CHAIR", "#7c3aed"),
    "Tadilat, Tamirat & Yapı Market": ("HANDYMAN", "#78716c"),
    "Evcil Hayvan (Pamuk)": ("PETS", "#d97706"),
    "Sigara/Tütün": ("SMOKING_ROOMS", "#57534e"),
    "Tatil & Seyahat & Konaklama": ("FLIGHT", "#0ea5e9"),
    "Hediye, Bağış & Yardımlaşma": ("CARD_GIFTCARD", "#db2777"),
    "Yardım": ("VOLUNTEER_ACTIVISM", "#db2777"),
    "Kredi Kartı, Kredi Ödemesi & Borç": ("CREDIT_CARD", "#dc2626"),
    "Vergi, Harç & Resmi İşlemler": ("ACCOUNT_BALANCE", "#334155"),
    "Transfer / Birikim": ("SWAP_HORIZ", "#2563eb"),
    "Yatırım & Altın & Döviz": ("SAVINGS", "#ca8a04"),
    "Poşet": ("SHOPPING_BAG", "#65a30d"),
    "Oyuncak": ("TOYS", "#f43f5e"),
    "Diğer": ("CATEGORY", "#64748b"),
}
_YEDEK_RENKLER = ["#0ea5e9", "#a855f7", "#f97316", "#14b8a6", "#e11d48", "#84cc16", "#6366f1", "#d946ef"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
AYLAR_UZUN = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
              "Kasım", "Aralık"]


def ikon(ad, varsayilan="CATEGORY"):
    return getattr(ft.Icons, ad, None) or getattr(ft.Icons, varsayilan)


def kat_stil(kategori, tur="Gider"):
    if tur == "Gelir":
        return ikon("PAYMENTS"), GELIR
    if tur == "Aktarım":
        return ikon("SWAP_HORIZ"), AKTARIM
    if kategori in KATEGORI_STIL:
        a, r = KATEGORI_STIL[kategori]
        return ikon(a), r
    r = _YEDEK_RENKLER[sum(map(ord, str(kategori or ""))) % len(_YEDEK_RENKLER)]
    return ikon("LABEL"), r


def saydam(renk, alfa="22"):
    """'#16a34a' -> '#2216a34a' (Flet: #AARRGGBB)"""
    return f"#{alfa}{renk.lstrip('#')}"


def golge(guc=1):
    try:
        if KOYU:
            return ft.BoxShadow(spread_radius=0, blur_radius=10 * guc, color="#30000000", offset=ft.Offset(0, 2 * guc))
        return ft.BoxShadow(spread_radius=0, blur_radius=18 * guc, color="#120f172a", offset=ft.Offset(0, 6 * guc))
    except Exception:
        return None


def degrade(renkler):
    try:
        return ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1), colors=renkler)
    except Exception:
        return None


ORTA = getattr(getattr(ft, "Alignment", None), "CENTER", None) or getattr(getattr(ft, "alignment", None), "center", None)


def simge_kutusu(simge, renk, boyut=20, kutu=40):
    return ft.Container(content=ft.Icon(simge, color=renk, size=boyut), bgcolor=saydam(renk, "2e" if KOYU else "1c"),
                        width=kutu, height=kutu, border_radius=kutu * 0.32, alignment=ORTA)


def cip(metin, secili, on_click, renk=ANA, simge=None):
    icerik = [yazi(metin, 12.5, "sb" if secili else False, renk="white" if secili else YAZI)]
    if simge is not None:
        icerik.insert(0, ft.Icon(simge, size=15, color="white" if secili else renk))
    return ft.Container(content=ft.Row(icerik, spacing=5, tight=True), on_click=on_click,
                        bgcolor=renk if secili else KART, border_radius=14, padding=ft.Padding(14, 9, 14, 9),
                        border=None if secili else kenar())


def gun_basligi(d):
    bugun = hb.simdi().date()
    if d == bugun:
        return "Bugün"
    if (bugun - d).days == 1:
        return "Dün"
    return f"{d.day} {AYLAR_UZUN[d.month - 1]} {GUNLER[d.weekday()]}"


def fis_anahtari(i):
    """Aynı fişten gelen satırları birlikte göstermek için anahtar."""
    if i.get("fis_grup"):
        return "g:" + str(i["fis_grup"])
    a = str(i.get("aciklama") or "")
    if i.get("tur") == "Gider" and a.startswith("AI Toplu Fiş"):
        return f"e:{a}|{i.get('tarih')}|{i.get('kasa_sahibi')}"
    return None


def grupla(islemler):
    """[islem | [islem, ...]] – fiş satırlarını tek karta toplar, sıra korunur."""
    sonuc, yer = [], {}
    for i in islemler:
        k = fis_anahtari(i)
        if not k:
            sonuc.append(i)
            continue
        if k in yer:
            yer[k].append(i)
        else:
            yer[k] = [i]
            sonuc.append(yer[k])
    return [x[0] if isinstance(x, list) and len(x) == 1 else x for x in sonuc]

