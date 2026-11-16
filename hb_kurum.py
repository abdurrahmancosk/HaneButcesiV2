"""
Hane Bütçesi v2 – kurumların herkese açık borç sorgulama sayfalarından güncel borç okuma.
Şu an: ESKİ (Erzurum Su ve Kanalizasyon İdaresi) – tesisat no + müşteri no ile, giriş/şifre gerekmez.
Not: Resmi bir servis değildir; sayfa değişirse sorgu çalışmayabilir (uygulama bunu kullanıcıya söyler).
"""
from __future__ import annotations

import datetime as dt
import html
import http.cookiejar
import re
import urllib.parse
import urllib.request

import hb_core as hb

ESKI_URL = "https://port2.eski.gov.tr/WebTahsilat/FrmBorcSorgula.aspx"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Mobile Safari/537.36"

KURUMLAR = {  # baglanti anahtarı: (görünen ad, fatura türü, gerekli alanlar)
    "eski": ("ESKİ – Erzurum Su", "Su", ("Tesisat no", "Müşteri no")),
}


class KurumHatasi(Exception):
    pass


def _gizli_alanlar(sayfa: str) -> dict:
    alanlar = {}
    for etiket in re.findall(r"<input[^>]*>", sayfa, re.I):
        if not re.search(r'type="hidden"', etiket, re.I):
            continue
        ad = re.search(r'name="([^"]+)"', etiket)
        deger = re.search(r'value="([^"]*)"', etiket)
        if ad:
            alanlar[ad.group(1)] = html.unescape(deger.group(1)) if deger else ""
    return alanlar


def _metin(parca: str) -> str:
    parca = re.sub(r"(?is)<(script|style).*?</\1>", " ", parca)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", parca))).strip()


def _etiket(sayfa: str, kimlik: str) -> str | None:
    m = re.search(rf'id="{kimlik}"[^>]*>(.*?)</', sayfa, re.S)
    return _metin(m.group(1)) if m else None


def eski_borc_sorgula(tesisat_no: str, musteri_no: str) -> dict:
    """-> {"borc_yok": bool, "ana": float, "gecikme": float, "toplam": float, "kalemler": [..], "bilgi": str}"""
    tesisat_no, musteri_no = str(tesisat_no).strip(), str(musteri_no).strip()
    if not tesisat_no.isdigit() or not musteri_no.isdigit():
        raise KurumHatasi("Tesisat ve müşteri numarası yalnızca rakam olmalı")
    cerez = http.cookiejar.CookieJar()
    acici = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cerez),
                                        urllib.request.HTTPSHandler(context=hb.SSL))
    basliklar = {"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9", "Referer": ESKI_URL}

    def iste(veri=None):
        govde = urllib.parse.urlencode(veri).encode() if veri is not None else None
        istek = urllib.request.Request(ESKI_URL, data=govde, headers=dict(
            basliklar, **({"Content-Type": "application/x-www-form-urlencoded"} if govde else {})))
        try:
            with acici.open(istek, timeout=25) as y:
                return y.read().decode("utf-8", "replace")
        except Exception as e:
            raise KurumHatasi(f"ESKİ sayfasına ulaşılamadı: {e}") from None

    s1 = iste()
    s2 = iste(dict(_gizli_alanlar(s1), __EVENTTARGET="btnMusteriSorgula", __EVENTARGUMENT="",
                   txtTesisatNo=tesisat_no, txtMusteriNo=""))
    if f'value="{musteri_no}"' not in s2:
        if "ddlMusteri" not in s2:
            raise KurumHatasi("Tesisat numarası bulunamadı ya da ESKİ sayfası değişmiş")
        raise KurumHatasi("Bu tesisatta bu müşteri numarası yok")
    s3 = iste(dict(_gizli_alanlar(s2), __EVENTTARGET="ddlMusteri", __EVENTARGUMENT="",
                   txtTesisatNo=tesisat_no, txtMusteriNo="", ddlMusteri=musteri_no))
    bilgi = _etiket(s3, "lblBorcBilgi") or ""
    ana = hb.tutar_coz(_etiket(s3, "lblToplamAnaBorc")) or 0.0
    gecikme = hb.tutar_coz(_etiket(s3, "lblToplamGecikmeBorc")) or 0.0
    toplam = hb.tutar_coz(_etiket(s3, "lblToplamBorc")) or 0.0
    if "lblToplamBorc" not in s3:
        raise KurumHatasi("ESKİ borç sayfası beklenen biçimde değil (sayfa değişmiş olabilir)")
    kalemler = []
    m = re.search(r'class="table-wrap"(.*?)<div class="summary"', s3, re.S)
    if m:
        for satir in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
            hucreler = [_metin(h) for h in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", satir, re.S)]
            hucreler = [h for h in hucreler if h]
            if not hucreler or any("Tutar" in h or "Dönem" in h for h in hucreler[:2]) and not re.search(r"\d+,\d{2}", " ".join(hucreler)):
                continue
            tutarlar = [hb.tutar_coz(x) for x in re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", " ".join(hucreler))]
            tarihler = [hb.tarih_kesin(x) for x in re.findall(r"\d{2}[./]\d{2}[./]\d{4}", " ".join(hucreler))]
            tarihler = [t for t in tarihler if t]
            if not tutarlar:
                continue
            kalemler.append({"metin": " | ".join(hucreler), "tutar": max(tutarlar),
                             "son_odeme": max(tarihler).isoformat() if tarihler else None,
                             "donem": next((h for h in hucreler if re.search(r"\b20\d{2}\b", h) and not re.search(r"\d+,\d{2}", h)), None)})
    borc_yok = "bulunmamaktad" in bilgi.lower() or (toplam == 0 and not kalemler)
    if not toplam and kalemler:
        toplam = round(sum(k["tutar"] for k in kalemler), 2)
    return {"borc_yok": borc_yok, "ana": ana, "gecikme": gecikme, "toplam": 0.0 if borc_yok else toplam,
            "kalemler": [] if borc_yok else kalemler, "bilgi": bilgi, "zaman": hb.iso_tarih(hb.simdi())}


def borc_sorgula(baglanti: str, abone_no: str, musteri_no: str | None) -> dict:
    if baglanti == "eski":
        return eski_borc_sorgula(abone_no, musteri_no or "")
    raise KurumHatasi("Bu kurum için otomatik sorgu yok")
