"""Hane Bütçesi v2 – ortak arayüz parçaları, renk paleti (açık/koyu tema)."""
import inspect

import flet as ft

import hb_core as hb

# ---------------------------------------------------------------------------
# Renkler
# ---------------------------------------------------------------------------
ANA = "#0f766e"
GELIR = "#16a34a"
GIDER = "#dc2626"
AKTARIM = "#2563eb"
KOYU = False
ARKA = KART = YAZI = SOLUK = CIZGI = ZEMIN2 = UYARI_ZEMIN = BILGI_ZEMIN = None


def tema_uygula(koyu: bool):
    """Paleti değiştirir; ekranlar yeniden çizildiğinde yeni renkler kullanılır."""
    global KOYU, ARKA, KART, YAZI, SOLUK, CIZGI, ZEMIN2, UYARI_ZEMIN, BILGI_ZEMIN
    KOYU = koyu
    if koyu:
        ARKA, KART, YAZI, SOLUK = "#0b1220", "#151e2e", "#e2e8f0", "#94a3b8"
        CIZGI, ZEMIN2, UYARI_ZEMIN, BILGI_ZEMIN = "#273449", "#1c2638", "#3b1d1d", "#172554"
    else:
        ARKA, KART, YAZI, SOLUK = "#f3f5f9", "#ffffff", "#0f172a", "#64748b"
        CIZGI, ZEMIN2, UYARI_ZEMIN, BILGI_ZEMIN = "#e2e8f0", "#f8fafc", "#fee2e2", "#dbeafe"


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


def kart(icerik, renk=None, dolgu=14, **kw):
    renk = renk or KART
    return ft.Container(content=icerik, bgcolor=renk, padding=dolgu, border_radius=14, **kw)


def yazi(metin, boyut=14, kalin=False, renk=None, **kw):
    renk = renk or YAZI
    return ft.Text(metin, size=boyut, weight=ft.FontWeight.BOLD if kalin else None, color=renk, **kw)


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
        return ft.BoxShadow(spread_radius=0, blur_radius=14 * guc, color="#40000000" if KOYU else "#140f172a",
                            offset=ft.Offset(0, 4 * guc))
    except Exception:
        return None


def degrade(renkler):
    try:
        return ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1), colors=renkler)
    except Exception:
        return None


ORTA = getattr(getattr(ft, "Alignment", None), "CENTER", None) or getattr(getattr(ft, "alignment", None), "center", None)


def simge_kutusu(simge, renk, boyut=20, kutu=40):
    return ft.Container(content=ft.Icon(simge, color=renk, size=boyut), bgcolor=saydam(renk), width=kutu,
                        height=kutu, border_radius=kutu // 2 - 4, alignment=ORTA)


def cip(metin, secili, on_click, renk=ANA, simge=None):
    icerik = [yazi(metin, 12, secili, renk="white" if secili else YAZI)]
    if simge is not None:
        icerik.insert(0, ft.Icon(simge, size=15, color="white" if secili else renk))
    return ft.Container(content=ft.Row(icerik, spacing=4, tight=True), on_click=on_click,
                        bgcolor=renk if secili else KART, border_radius=20, padding=ft.Padding(12, 7, 12, 7))


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

