"""
Hane Bütçesi v2 - çekirdek katman (arayüzden bağımsız).

- Bütçe dönemi hesabı (ayın 15'i -> sonraki ayın 14'ü)
- Türk Lirası biçimlendirme / tutar ayrıştırma
- Supabase: kimlik doğrulama, REST, RPC, Storage
- Supabase Realtime (anlık senkronizasyon) istemcisi
- Gemini ile fiş / fatura analizi
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import io
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ----------------------------------------------------------------------------
# Yapılandırma
# ----------------------------------------------------------------------------
SUPABASE_URL = "https://ivngkowxxafkyvvzhdob.supabase.co"
SUPABASE_KEY = "sb_publishable_0pVRLE1ceJ0FlI32XGzbsw_Z_mldcXe"
EPOSTA_ALANI = "hane.app"          # kullanıcı adı -> abdurrahman@hane.app
FIS_KOVASI = "hb-fisler"
TZ = dt.timezone(dt.timedelta(hours=3))  # Türkiye (yaz saati yok)

VARSAYILAN_KATEGORILER = [
    "Market & Temel Gıda", "Abur Cubur & Atıştırmalık", "Kira & Aidat & Faturalar", "Ev",
    "Temizlik & Hijyen & Kişisel Bakım", "Giyim, Ayakkabı & Aksesuar", "Sağlık, İlaç & Medikal",
    "Eğitim, Okul & Kırtasiye", "Ulaşım & Toplu Taşıma", "Dışarıda Yemek & Kafe & Restoran",
    "Eğlence, Kültür & Etkinlik", "Elektronik & Teknoloji", "Ev Eşyası & Mobilya & Beyaz Eşya",
    "Tadilat, Tamirat & Yapı Market", "Evcil Hayvan (Pamuk)", "Sigara/Tütün",
    "Tatil & Seyahat & Konaklama", "Hediye, Bağış & Yardımlaşma", "Kredi Kartı, Kredi Ödemesi & Borç",
    "Vergi, Harç & Resmi İşlemler", "Yatırım & Altın & Döviz", "Poşet", "Oyuncak", "Diğer",
]
VARSAYILAN_GELIR_TURLERI = ["Maaş", "Ek Gelir", "Kira Geliri", "Prim / İkramiye",
                            "Borç Tahsilatı", "Hediye", "Açılış Bakiyesi", "Diğer Gelir"]

AYLAR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def veri_klasoru() -> str:
    import sys
    if os.environ.get("FLET_APP_STORAGE_DATA"):
        d = os.environ["FLET_APP_STORAGE_DATA"]
    elif getattr(sys, "frozen", False):  # Windows .exe: kalıcı kullanıcı klasörü
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "HaneButcesi")
    else:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veri")
    os.makedirs(d, exist_ok=True)
    return d


# ----------------------------------------------------------------------------
# Tarih / dönem
# ----------------------------------------------------------------------------
def simdi() -> dt.datetime:
    return dt.datetime.now(TZ)


def _ay_kaydir(yil: int, ay: int, n: int) -> tuple[int, int]:
    t = yil * 12 + (ay - 1) + n
    return t // 12, t % 12 + 1


def butce_donemi(ref: dt.date | None = None, ofset: int = 0) -> tuple[dt.date, dt.date]:
    """Bugün ayın 15'i veya sonrasıysa: bu ayın 15'i - gelecek ayın 14'ü.
    Bugün ayın 14'ü veya öncesiyse: geçen ayın 15'i - bu ayın 14'ü.
    ofset: -1 önceki dönem, +1 sonraki dönem."""
    ref = ref or simdi().date()
    y, a = ref.year, ref.month
    if ref.day < 15:
        y, a = _ay_kaydir(y, a, -1)
    y, a = _ay_kaydir(y, a, ofset)
    bas = dt.date(y, a, 15)
    ny, na = _ay_kaydir(y, a, 1)
    bit = dt.date(ny, na, 14)
    return bas, bit


def donem_etiketi(bas: dt.date, bit: dt.date) -> str:
    return f"{bas.day} {AYLAR[bas.month-1]} {bas.year} – {bit.day} {AYLAR[bit.month-1]} {bit.year}"


def iso_tarih(d: dt.datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.isoformat(timespec="seconds")


def tarih_coz(metin: str | None, varsayilan: dt.datetime | None = None) -> dt.datetime:
    """'15.11.2026', '15.11.2026 14:30', '2026-11-15', '15/11/2026' biçimlerini anlar."""
    varsayilan = varsayilan or simdi()
    if not metin or not str(metin).strip():
        return varsayilan
    s = str(metin).strip().replace("/", ".").replace("-", ".")
    saat, dakika = varsayilan.hour, varsayilan.minute
    m_saat = re.search(r"(\d{1,2})[:.](\d{2})\s*$", s) if " " in s else None
    if m_saat:
        saat, dakika = int(m_saat.group(1)), int(m_saat.group(2))
        s = s[: m_saat.start()].strip()
    parcalar = [p for p in s.split(".") if p]
    try:
        if len(parcalar[0]) == 4:  # YYYY.MM.DD
            y, a, g = int(parcalar[0]), int(parcalar[1]), int(parcalar[2])
        else:
            g, a, y = int(parcalar[0]), int(parcalar[1]), int(parcalar[2])
            if y < 100:
                y += 2000
        return dt.datetime(y, a, g, min(saat, 23), min(dakika, 59), tzinfo=TZ)
    except Exception:
        return varsayilan


def tarih_yerel(iso: str | None) -> dt.datetime:
    if not iso:
        return simdi()
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d.astimezone(TZ)
    except Exception:
        return simdi()


def tarih_goster(iso: str | None, saat: bool = True) -> str:
    d = tarih_yerel(iso)
    return d.strftime("%d.%m.%Y %H:%M") if saat else d.strftime("%d.%m.%Y")


# ----------------------------------------------------------------------------
# Para
# ----------------------------------------------------------------------------
def tl(x: float | int | str | None, isaret: bool = False) -> str:
    try:
        v = float(x or 0)
    except Exception:
        v = 0.0
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    on = "-" if v < 0 else ("+" if isaret and v > 0 else "")
    return f"{on}{s} ₺"


def tutar_coz(metin) -> float | None:
    """'1.234,56' / '1234.56' / '1234,5' / '250' / '₺ 1.250' -> float"""
    if metin is None:
        return None
    if isinstance(metin, (int, float)):
        return float(metin)
    s = re.sub(r"[^\d,.\-]", "", str(metin))
    if not s or s in "-.,":
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def urun_anahtari(ad: str | None) -> str:
    s = str(ad or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i").replace("̇", "")
    return re.sub(r"\s+", " ", s).strip()


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
def _ssl_baglami():
    try:
        import certifi  # Android'de kök sertifikalar için
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL = _ssl_baglami()


class ApiHatasi(Exception):
    def __init__(self, durum: int, mesaj: str):
        super().__init__(mesaj)
        self.durum = durum
        self.mesaj = mesaj


def _http(method: str, url: str, *, govde=None, basliklar: dict | None = None, ham: bool = False,
          zaman_asimi: int = 30):
    h = dict(basliklar or {})
    veri = None
    if govde is not None:
        if isinstance(govde, (bytes, bytearray)):
            veri = bytes(govde)
        else:
            veri = json.dumps(govde, ensure_ascii=False).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
    istek = urllib.request.Request(url, data=veri, headers=h, method=method)
    try:
        with urllib.request.urlopen(istek, timeout=zaman_asimi, context=SSL) as yanit:
            icerik = yanit.read()
            if ham:
                return icerik
            if not icerik:
                return None
            return json.loads(icerik.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            gv = e.read().decode("utf-8", "replace")
            j = json.loads(gv)
            mesaj = j.get("msg") or j.get("message") or j.get("error_description") or j.get("error") or gv
        except Exception:
            mesaj = str(e)
        raise ApiHatasi(e.code, str(mesaj)) from None
    except urllib.error.URLError as e:
        raise ApiHatasi(0, f"Bağlantı hatası: {e.reason}") from None
    except (TimeoutError, OSError) as e:
        raise ApiHatasi(0, f"Bağlantı hatası: {e}") from None


# ----------------------------------------------------------------------------
# Supabase istemcisi
# ----------------------------------------------------------------------------
class Supabase:
    def __init__(self, url: str = SUPABASE_URL, anahtar: str = SUPABASE_KEY):
        self.url = url.rstrip("/")
        self.anahtar = anahtar
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.bitis: float = 0
        self.kullanici_id: str | None = None
        self._kilit = threading.Lock()
        self._oturum_dosyasi = os.path.join(veri_klasoru(), "hb_oturum.json")

    # ---- oturum ----
    @staticmethod
    def eposta(kullanici_adi: str) -> str:
        k = urun_anahtari(kullanici_adi).replace(" ", "")
        k = (k.replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c"))
        return k if "@" in k else f"{k}@{EPOSTA_ALANI}"

    def _oturumu_al(self, j: dict):
        self.access_token = j["access_token"]
        self.refresh_token = j.get("refresh_token") or self.refresh_token
        self.bitis = time.time() + int(j.get("expires_in") or 3600)
        self.kullanici_id = (j.get("user") or {}).get("id") or self.kullanici_id

    def giris(self, kullanici_adi: str, sifre: str, hatirla: bool = True):
        j = _http("POST", f"{self.url}/auth/v1/token?grant_type=password",
                  govde={"email": self.eposta(kullanici_adi), "password": sifre},
                  basliklar={"apikey": self.anahtar})
        self._oturumu_al(j)
        if hatirla:
            self.oturumu_kaydet()

    def kurulum_durumu(self) -> dict[str, bool]:
        """{'abdurrahman': True/False, 'hatice': ...} -> şifresi belirlenmiş mi"""
        j = _http("POST", f"{self.url}/rest/v1/rpc/hb_kurulum_durumu", govde={},
                  basliklar={"apikey": self.anahtar})
        return {x["kullanici_adi"]: bool(x["hazir"]) for x in (j or [])}

    def ilk_sifre_belirle(self, kullanici_adi: str, sifre: str):
        k = self.eposta(kullanici_adi).split("@")[0]
        _http("POST", f"{self.url}/rest/v1/rpc/hb_ilk_sifre", govde={"p_kullanici": k, "p_sifre": sifre},
              basliklar={"apikey": self.anahtar})

    def sifre_degistir(self, yeni_sifre: str):
        self._istek("PUT", "/auth/v1/user", govde={"password": yeni_sifre})

    def yenile(self):
        if not self.refresh_token:
            raise ApiHatasi(401, "Oturum yok")
        j = _http("POST", f"{self.url}/auth/v1/token?grant_type=refresh_token",
                  govde={"refresh_token": self.refresh_token}, basliklar={"apikey": self.anahtar})
        self._oturumu_al(j)
        if os.path.exists(self._oturum_dosyasi):
            self.oturumu_kaydet()

    def taze_token(self) -> str:
        with self._kilit:
            if not self.access_token or time.time() > self.bitis - 120:
                self.yenile()
            return self.access_token  # type: ignore[return-value]

    def oturumu_kaydet(self):
        try:
            with open(self._oturum_dosyasi, "w", encoding="utf-8") as f:
                json.dump({"refresh_token": self.refresh_token, "kullanici_id": self.kullanici_id}, f)
        except Exception:
            pass

    def kayitli_oturumu_ac(self) -> bool:
        try:
            with open(self._oturum_dosyasi, "r", encoding="utf-8") as f:
                j = json.load(f)
            self.refresh_token = j.get("refresh_token")
            self.kullanici_id = j.get("kullanici_id")
            if not self.refresh_token:
                return False
            try:
                self.yenile()
            except ApiHatasi as e:
                if e.durum != 0 or not self.kullanici_id:
                    raise
                self.cevrimdisi = True  # internet yok: önbellekle açılır, bağlantı gelince token yenilenir
            return True
        except Exception:
            return False

    def cikis(self):
        try:
            if self.access_token:
                _http("POST", f"{self.url}/auth/v1/logout",
                      basliklar={"apikey": self.anahtar, "Authorization": f"Bearer {self.access_token}"})
        except Exception:
            pass
        self.access_token = self.refresh_token = self.kullanici_id = None
        try:
            os.remove(self._oturum_dosyasi)
        except Exception:
            pass

    # ---- yetkili istek ----
    def _istek(self, method: str, yol: str, *, govde=None, basliklar=None, ham=False, zaman_asimi=30):
        for deneme in range(2):
            h = {"apikey": self.anahtar, "Authorization": f"Bearer {self.taze_token()}"}
            h.update(basliklar or {})
            try:
                return _http(method, self.url + yol, govde=govde, basliklar=h, ham=ham, zaman_asimi=zaman_asimi)
            except ApiHatasi as e:
                if e.durum == 401 and deneme == 0:
                    with self._kilit:
                        self.yenile()
                    continue
                raise

    # ---- veri ----
    def profiller(self) -> list[dict]:
        return self._istek("GET", "/rest/v1/hb_profiller?select=*&order=ad") or []

    def islemler(self, bas: dt.date, bit: dt.date) -> list[dict]:
        b = iso_tarih(dt.datetime(bas.year, bas.month, bas.day, tzinfo=TZ))
        sonraki = bit + dt.timedelta(days=1)
        s = iso_tarih(dt.datetime(sonraki.year, sonraki.month, sonraki.day, tzinfo=TZ))
        q = urllib.parse.quote
        yol = (f"/rest/v1/hb_islemler?select=*&tarih=gte.{q(b)}&tarih=lt.{q(s)}"
               f"&order=tarih.desc,id.desc&limit=5000")
        return self._istek("GET", yol) or []

    def bakiyeler(self) -> list[dict]:
        return self._istek("POST", "/rest/v1/rpc/hb_bakiyeler", govde={}) or []

    def islem_ekle(self, kayitlar: list[dict]) -> list[dict]:
        return self._istek("POST", "/rest/v1/hb_islemler", govde=kayitlar,
                           basliklar={"Prefer": "return=representation"}) or []

    def islem_guncelle(self, islem_id: int, alanlar: dict):
        return self._istek("PATCH", f"/rest/v1/hb_islemler?id=eq.{int(islem_id)}", govde=alanlar,
                           basliklar={"Prefer": "return=representation"})

    def islem_sil(self, islem_id: int):
        return self._istek("DELETE", f"/rest/v1/hb_islemler?id=eq.{int(islem_id)}")

    def fis_grubu_sil(self, fis_grup: str):
        return self._istek("DELETE", f"/rest/v1/hb_islemler?fis_grup=eq.{urllib.parse.quote(str(fis_grup))}")

    def ayar_oku(self, anahtar: str):
        r = self._istek("GET", f"/rest/v1/hb_ayarlar?anahtar=eq.{urllib.parse.quote(anahtar)}&select=deger")
        return r[0]["deger"] if r else None

    def ayar_yaz(self, anahtar: str, deger: str):
        return self._istek("POST", "/rest/v1/hb_ayarlar?on_conflict=anahtar",
                           govde=[{"anahtar": anahtar, "deger": deger}],
                           basliklar={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def kategori_eslemeleri(self) -> dict[str, str]:
        r = self._istek("GET", "/rest/v1/hb_kategori_eslemeleri?select=urun_anahtar,kategori&limit=10000") or []
        return {x["urun_anahtar"]: x["kategori"] for x in r}

    def kategori_eslemesi_kaydet(self, eslemeler: dict[str, str]):
        if not eslemeler:
            return
        govde = [{"urun_anahtar": k, "kategori": v, "guncelleme": iso_tarih(simdi())} for k, v in eslemeler.items()]
        return self._istek("POST", "/rest/v1/hb_kategori_eslemeleri?on_conflict=urun_anahtar", govde=govde,
                           basliklar={"Prefer": "resolution=merge-duplicates,return=minimal"})

    # ---- genel tablo yardımcıları ----
    def tablo(self, ad: str, sorgu: str = "select=*") -> list[dict]:
        return self._istek("GET", f"/rest/v1/{ad}?{sorgu}") or []

    def tablo_ekle(self, ad: str, kayit: dict | list) -> list[dict]:
        return self._istek("POST", f"/rest/v1/{ad}", govde=kayit if isinstance(kayit, list) else [kayit],
                           basliklar={"Prefer": "return=representation"}) or []

    def aktuel_ekle(self, kayitlar: list[dict]):
        return self._istek("POST", "/rest/v1/hb_aktuel?on_conflict=market,urun,bas", govde=kayitlar,
                           basliklar={"Prefer": "resolution=ignore-duplicates,return=minimal"})

    def tablo_guncelle(self, ad: str, kayit_id, alanlar: dict):
        return self._istek("PATCH", f"/rest/v1/{ad}?id=eq.{int(kayit_id)}", govde=alanlar,
                           basliklar={"Prefer": "return=representation"})

    def tablo_guncelle_filtre(self, ad: str, filtre: str, alanlar: dict):
        return self._istek("PATCH", f"/rest/v1/{ad}?{filtre}", govde=alanlar, basliklar={"Prefer": "return=minimal"})

    def tablo_sil_filtre(self, ad: str, filtre: str):
        return self._istek("DELETE", f"/rest/v1/{ad}?{filtre}")

    def tablo_sil(self, ad: str, kayit_id):
        return self._istek("DELETE", f"/rest/v1/{ad}?id=eq.{int(kayit_id)}")

    def butce_yaz(self, kategori: str, limit_tutar: float | None):
        if limit_tutar:
            return self._istek("POST", "/rest/v1/hb_butceler?on_conflict=kategori",
                               govde=[{"kategori": kategori, "limit_tutar": limit_tutar, "guncelleme": iso_tarih(simdi())}],
                               basliklar={"Prefer": "resolution=merge-duplicates,return=minimal"})
        return self._istek("DELETE", f"/rest/v1/hb_butceler?kategori=eq.{urllib.parse.quote(kategori)}")

    def rpc(self, ad: str, govde: dict | None = None):
        return self._istek("POST", f"/rest/v1/rpc/{ad}", govde=govde or {}) or []

    # ---- storage ----
    def fis_yukle(self, veri: bytes, uzanti: str = "jpg", mime: str = "image/jpeg") -> str:
        yol = f"{self.kullanici_id}/{simdi():%Y%m}/{uuid.uuid4().hex}.{uzanti}"
        self._istek("POST", f"/storage/v1/object/{FIS_KOVASI}/{yol}", govde=veri,
                    basliklar={"Content-Type": mime, "x-upsert": "false"}, zaman_asimi=60)
        return yol

    def fis_adresi(self, yol: str, sure: int = 3600) -> str:
        j = self._istek("POST", f"/storage/v1/object/sign/{FIS_KOVASI}/{urllib.parse.quote(yol)}",
                        govde={"expiresIn": sure})
        imzali = (j or {}).get("signedURL") or (j or {}).get("signedUrl") or ""
        if imzali.startswith("http"):
            return imzali
        return f"{self.url}/storage/v1{imzali}"


# ----------------------------------------------------------------------------
# Realtime (Phoenix kanal protokolü) – anlık senkronizasyon
# ----------------------------------------------------------------------------
class CanliBaglanti:
    """hb_islemler tablosundaki her ekleme/güncelleme/silmede geri çağırma yapar."""

    def __init__(self, supa: Supabase, degisince, durum_degisince=None):
        self.supa = supa
        self.degisince = degisince            # async def f(olay: dict)
        self.durum_degisince = durum_degisince  # async def f(bagli: bool)
        self.bagli = False
        self._calisiyor = False
        self._ref = 0
        self.tablolar = ["hb_islemler", "hb_alisveris", "hb_faturalar", "hb_duzenli", "hb_borclar", "hb_hedefler",
                         "hb_bildirimler"]

    def _sonraki_ref(self) -> str:
        self._ref += 1
        return str(self._ref)

    async def _durum(self, b: bool):
        if b != self.bagli:
            self.bagli = b
            if self.durum_degisince:
                try:
                    await self.durum_degisince(b)
                except Exception:
                    pass

    def durdur(self):
        self._calisiyor = False

    async def calistir(self):
        try:
            import websockets
        except Exception:
            print("websockets paketi yok; yalnızca periyodik yenileme kullanılacak")
            return
        self._calisiyor = True
        bekleme = 2
        adres = (self.supa.url.replace("https://", "wss://") +
                 f"/realtime/v1/websocket?apikey={self.supa.anahtar}&vsn=1.0.0")
        while self._calisiyor:
            try:
                token = await asyncio.to_thread(self.supa.taze_token)
                async with websockets.connect(adres, ssl=SSL, ping_interval=None, open_timeout=15) as ws:
                    katil = self._sonraki_ref()
                    await ws.send(json.dumps({
                        "topic": "realtime:hb_islemler", "event": "phx_join", "ref": katil, "join_ref": katil,
                        "payload": {
                            "config": {
                                "broadcast": {"ack": False, "self": False},
                                "presence": {"key": ""},
                                "postgres_changes": [{"event": "*", "schema": "public", "table": t}
                                                     for t in self.tablolar],
                                "private": False,
                            },
                            "access_token": token,
                        },
                    }))
                    son_token = time.time()

                    async def kalp_atisi():
                        nonlocal son_token
                        while True:
                            await asyncio.sleep(25)
                            await ws.send(json.dumps({"topic": "phoenix", "event": "heartbeat",
                                                      "payload": {}, "ref": self._sonraki_ref()}))
                            if time.time() - son_token > 1500:  # ~25 dk'da bir token tazele
                                t = await asyncio.to_thread(self.supa.taze_token)
                                await ws.send(json.dumps({"topic": "realtime:hb_islemler", "event": "access_token",
                                                          "payload": {"access_token": t},
                                                          "ref": self._sonraki_ref(), "join_ref": katil}))
                                son_token = time.time()

                    kalp = asyncio.create_task(kalp_atisi())
                    try:
                        async for ham in ws:
                            if not self._calisiyor:
                                break
                            try:
                                m = json.loads(ham)
                            except Exception:
                                continue
                            olay = m.get("event")
                            if olay == "phx_reply" and m.get("ref") == katil:
                                ok = (m.get("payload") or {}).get("status") == "ok"
                                if not ok and len(self.tablolar) > 1:
                                    # yeni tablolar henüz kurulmamış olabilir: yalnızca işlemlerle devam et
                                    print("Realtime: tablolar kurulmamış, sadece hb_islemler dinlenecek")
                                    self.tablolar = ["hb_islemler"]
                                    bekleme = 0
                                    break
                                await self._durum(ok)
                                bekleme = 2
                            elif olay == "postgres_changes":
                                await self.degisince((m.get("payload") or {}).get("data") or {})
                            elif olay in ("phx_error", "phx_close"):
                                break
                            elif olay == "system" and (m.get("payload") or {}).get("status") == "error":
                                print("Realtime sistem hatası:", m.get("payload"))
                    finally:
                        kalp.cancel()
            except Exception as e:
                print("Realtime bağlantı hatası:", e)
            await self._durum(False)
            if self._calisiyor:
                await asyncio.sleep(bekleme)
                bekleme = min(max(bekleme, 1) * 2, 60)


# ----------------------------------------------------------------------------
# Gemini fiş analizi
# ----------------------------------------------------------------------------
GEMINI_TABAN = "https://generativelanguage.googleapis.com/v1beta"
YEDEK_MODELLER = ["gemini-3.5-flash", "gemini-3-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"]
_model_onbellek: dict[str, list[str]] = {}


def gorseli_hazirla(veri: bytes) -> tuple[bytes, str]:
    """Telefon fotoğrafını döndürür (EXIF), 1600px'e küçültür, JPEG yapar."""
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(veri))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        # Genişlik 1600'e, (çok sayfalı uzun fişler için) yükseklik 8000'e kadar
        o = min(1.0, 1600 / im.size[0], 8000 / im.size[1])
        if o < 1.0:
            im = im.resize((max(1, int(im.size[0] * o)), max(1, int(im.size[1] * o))))
        tampon = io.BytesIO()
        im.save(tampon, format="JPEG", quality=85, optimize=True)
        return tampon.getvalue(), "image/jpeg"
    except Exception as e:
        print("Görsel optimizasyonu atlandı:", e)
        if veri[:4] == b"%PDF":
            return veri, "application/pdf"
        if veri[:8] == b"\x89PNG\r\n\x1a\n":
            return veri, "image/png"
        return veri, "image/jpeg"


def gorselleri_birlestir(gorseller: list[bytes]) -> bytes:
    """Uzun fişin birden çok fotoğrafını alt alta tek görsele birleştirir."""
    if len(gorseller) == 1:
        return gorseller[0]
    try:
        from PIL import Image, ImageOps
        resimler = []
        for g in gorseller:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(g)))
            resimler.append(im.convert("RGB"))
        genislik = min(1600, max(im.size[0] for im in resimler))
        olcekli = [im.resize((genislik, max(1, int(im.size[1] * genislik / im.size[0])))) for im in resimler]
        bosluk = 12
        tuval = Image.new("RGB", (genislik, sum(im.size[1] for im in olcekli) + bosluk * (len(olcekli) - 1)), "white")
        y = 0
        for im in olcekli:
            tuval.paste(im, (0, y))
            y += im.size[1] + bosluk
        tampon = io.BytesIO()
        tuval.save(tampon, format="JPEG", quality=88)
        return tampon.getvalue()
    except Exception as e:
        print("Görseller birleştirilemedi, ilk sayfa kullanılacak:", e)
        return gorseller[0]


def gemini_modelleri(api_anahtari: str) -> list[str]:
    if api_anahtari in _model_onbellek:
        return _model_onbellek[api_anahtari]
    try:
        j = _http("GET", f"{GEMINI_TABAN}/models?pageSize=200", basliklar={"x-goog-api-key": api_anahtari},
                  zaman_asimi=15)
        adaylar = []
        for m in (j or {}).get("models", []):
            ad = m.get("name", "").replace("models/", "")
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if "flash" not in ad or any(x in ad for x in ("image", "tts", "live", "audio", "embedding", "thinking")):
                continue
            surum = re.search(r"gemini-(\d+(?:\.\d+)?)", ad)
            v = float(surum.group(1)) if surum else 0
            ceza = (1 if ("preview" in ad or "exp" in ad) else 0) + (0.5 if "lite" in ad else 0)
            adaylar.append((-v, ceza, ad))
        sirali = [a for _, _, a in sorted(adaylar)][:4] or YEDEK_MODELLER
    except ApiHatasi as e:
        if e.durum in (400, 401, 403):
            raise
        sirali = YEDEK_MODELLER
    _model_onbellek[api_anahtari] = sirali
    return sirali


def _fis_istemi(kategoriler: list[str]) -> str:
    return f"""Sen uzman bir Türk market fişi / fatura analiz asistanısın. Görseldeki belgeyi oku ve YALNIZCA geçerli JSON döndür.
JSON yapısı:
{{
  "firma": "Mağaza/kurum adı (örn: BİM, Migros, A101, ŞOK, Eczane, Aras Elektrik)",
  "tarih": "GG.AA.YYYY (bulunamazsa boş)",
  "saat": "SS:DD (bulunamazsa boş)",
  "urunler": [
    {{"urun": "Anlaşılır ürün adı (kısaltmaları aç)", "miktar": "örn: 1 Adet, 1.5 kg, 2 Paket",
      "birim_fiyat": 25.50, "tutar": 51.00, "kategori": "listeden biri"}}
  ],
  "toplam_tutar": 51.00
}}
KATEGORİ LİSTESİ (yalnızca bunlardan birini seç): {json.dumps(kategoriler, ensure_ascii=False)}
KURALLAR:
- Görsel birden çok fotoğrafın alt alta birleşimi olabilir (uzun fiş); aynı fişin devamı olarak oku, tekrar eden satırları iki kez yazma.
- Alışveriş poşetleri kesinlikle 'Poşet'.
- Çikolata, gofret, bisküvi, kek, cips, dondurma, şekerleme, kuruyemiş, gazlı içecek: 'Abur Cubur & Atıştırmalık'.
- Ekmek, süt, yoğurt, peynir, yumurta, yağ, bakliyat, et, tavuk, sebze, meyve, makarna, çay: 'Market & Temel Gıda'.
- Deterjan, şampuan, sabun, diş macunu, tuvalet kağıdı, peçete, ped, çöp torbası: 'Temizlik & Hijyen & Kişisel Bakım'.
- Elektrik/su/doğalgaz/internet/telefon faturası, kira, aidat: 'Kira & Aidat & Faturalar'.
- Aynı ürün birden fazla satırdaysa TEK satırda birleştir, miktarı topla.
- İndirimleri ilgili ürünün tutarından düş; ayrı negatif satır yazma. Tutarlar pozitif sayı (nokta ondalık) olsun.
- 'toplam_tutar' fişin ödenen genel toplamı olsun."""


def fis_analiz_et(gorsel: bytes, mime: str, api_anahtari: str, kategoriler: list[str],
                  eslemeler: dict[str, str] | None = None) -> dict:
    if not api_anahtari:
        raise ApiHatasi(400, "Gemini API anahtarı ayarlanmamış (Ayarlar ekranından Abdurrahman ekleyebilir).")
    govde = {
        "contents": [{"parts": [{"text": _fis_istemi(kategoriler)},
                                {"inline_data": {"mime_type": mime, "data": base64.b64encode(gorsel).decode()}}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    son_hata = "bilinmeyen hata"
    for model in gemini_modelleri(api_anahtari):
        try:
            j = _http("POST", f"{GEMINI_TABAN}/models/{model}:generateContent", govde=govde,
                      basliklar={"x-goog-api-key": api_anahtari}, zaman_asimi=90)
            metin = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
            metin = re.sub(r"^```(?:json)?|```$", "", metin.strip()).strip()
            sonuc = json.loads(metin)
            sonuc["model"] = model
            return fis_sonucunu_duzenle(sonuc, kategoriler, eslemeler or {})
        except ApiHatasi as e:
            son_hata = f"{model}: {e.mesaj}"
            if e.durum in (401, 403) or "API key not valid" in e.mesaj:
                raise ApiHatasi(e.durum, "Gemini API anahtarı geçersiz.") from None
        except Exception as e:
            son_hata = f"{model}: {e}"
    raise ApiHatasi(500, f"Fiş analiz edilemedi ({son_hata})")


def fis_sonucunu_duzenle(sonuc: dict, kategoriler: list[str], eslemeler: dict[str, str]) -> dict:
    kat_kucuk = {urun_anahtari(k): k for k in kategoriler}
    urunler = []
    for u in sonuc.get("urunler") or []:
        ad = str(u.get("urun") or "").strip()
        tutar = tutar_coz(u.get("tutar"))
        if not ad or tutar is None:
            continue
        kat = eslemeler.get(urun_anahtari(ad))  # öğrenilmiş kullanıcı tercihi önceliklidir
        if not kat:
            kat = kat_kucuk.get(urun_anahtari(u.get("kategori")), "Diğer")
        urunler.append({"urun": ad, "miktar": str(u.get("miktar") or "").strip(),
                        "birim_fiyat": tutar_coz(u.get("birim_fiyat")), "tutar": abs(tutar), "kategori": kat})
    sonuc["urunler"] = urunler
    tarih = (sonuc.get("tarih") or "").strip()
    saat = (sonuc.get("saat") or "").strip()
    sonuc["tarih_dt"] = tarih_coz(f"{tarih} {saat}".strip()) if tarih else simdi()
    sonuc["toplam_tutar"] = tutar_coz(sonuc.get("toplam_tutar")) or round(sum(u["tutar"] for u in urunler), 2)
    return sonuc


# ----------------------------------------------------------------------------
# Hesaplamalar
# ----------------------------------------------------------------------------
def donem_ozeti(islemler: list[dict], kisi_id: str | None = None) -> dict:
    """kisi_id verilirse yalnızca o kişinin kasasına göre hesaplar; verilmezse hane toplamı (aktarımlar hariç)."""
    gelir = gider = aktarim_giris = aktarim_cikis = 0.0
    kategoriler: dict[str, float] = {}
    for i in islemler:
        t = float(i.get("tutar") or 0)
        tur = i.get("tur")
        sahip, hedef = i.get("kasa_sahibi"), i.get("hedef_kasa")
        if tur == "Aktarım":
            if kisi_id:
                if sahip == kisi_id:
                    aktarim_cikis += t
                if hedef == kisi_id:
                    aktarim_giris += t
            continue
        if kisi_id and sahip != kisi_id:
            continue
        if tur == "Gelir":
            gelir += t
        elif tur == "Gider":
            gider += t
            k = i.get("kategori") or "Diğer"
            kategoriler[k] = kategoriler.get(k, 0) + t
    return {"gelir": round(gelir, 2), "gider": round(gider, 2), "net": round(gelir - gider, 2),
            "aktarim_giris": round(aktarim_giris, 2), "aktarim_cikis": round(aktarim_cikis, 2),
            "kategoriler": dict(sorted(kategoriler.items(), key=lambda kv: -kv[1]))}
