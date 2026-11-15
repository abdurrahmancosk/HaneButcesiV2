"""
Hane Bütçesi v2 – Abdurrahman & Hatice
Flet (Android/Windows) + Supabase (giriş, veritabanı, anlık senkron, fiş deposu) + Gemini (fiş analizi)
"""
import asyncio
import inspect
import uuid

import flet as ft

import hb_core as hb

SURUM = "2.0.0-deneme1"

# ---------------------------------------------------------------------------
# Renkler
# ---------------------------------------------------------------------------
ANA = "#0f766e"
ARKA = "#f1f5f9"
KART = "#ffffff"
YAZI = "#0f172a"
SOLUK = "#64748b"
GELIR = "#16a34a"
GIDER = "#dc2626"
AKTARIM = "#2563eb"


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


def kart(icerik, renk=KART, dolgu=14, **kw):
    return ft.Container(content=icerik, bgcolor=renk, padding=dolgu, border_radius=14, **kw)


def yazi(metin, boyut=14, kalin=False, renk=YAZI, **kw):
    return ft.Text(metin, size=boyut, weight=ft.FontWeight.BOLD if kalin else None, color=renk, **kw)


# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------
class Uygulama:
    def __init__(self, page: ft.Page):
        self.page = page
        self.supa = hb.Supabase()
        self.ben: dict | None = None
        self.profiller: dict[str, dict] = {}
        self.yonetici = False
        self.kategoriler = list(hb.VARSAYILAN_KATEGORILER)
        self.gelir_turleri = list(hb.VARSAYILAN_GELIR_TURLERI)
        self.gemini_anahtari = ""
        self.eslemeler: dict[str, str] | None = None
        self.donem_ofset = 0
        self.islemler: list[dict] = []
        self.bakiyeler: list[dict] = []
        self.sekme = 0
        self.canli: hb.CanliBaglanti | None = None
        self._yenileme_planli = False
        self._yeni_bildirimler: list[dict] = []
        self.filtre = {"arama": "", "tur": "Tümü", "kasa": "Hepsi"}
        self.fis: dict | None = None
        self.picker = None
        self._nesil = 0

        page.title = "Hane Bütçesi"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.theme = ft.Theme(color_scheme_seed=ANA)
        page.bgcolor = ARKA
        page.padding = 0
        try:
            page.window.width, page.window.height = 430, 880
        except Exception:
            pass
        try:
            self.picker = ft.FilePicker()
            if hasattr(page, "services"):
                page.services.append(self.picker)
            else:
                page.overlay.append(self.picker)
        except Exception as e:
            print("FilePicker eklenemedi:", e)

        self.govde = ft.Container(expand=True)
        page.add(ft.SafeArea(content=self.govde, expand=True))

    # ------------------------------------------------------------ yardımcılar
    def guncelle(self):
        try:
            self.page.update()
        except Exception as e:
            print("Arayüz güncellenemedi:", e)

    def dialog_ac(self, d):
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(d)
        elif hasattr(self.page, "open"):
            self.page.open(d)
        else:
            self.page.dialog = d
            d.open = True
            self.guncelle()

    def dialog_kapat(self, d=None):
        try:
            if hasattr(self.page, "pop_dialog"):
                self.page.pop_dialog()
            elif hasattr(self.page, "close") and d is not None:
                self.page.close(d)
            elif d is not None:
                d.open = False
                self.guncelle()
        except Exception:
            pass

    def bildir(self, metin, renk=None):
        self.dialog_ac(ft.SnackBar(content=ft.Text(metin, color="white"), bgcolor=renk or "#334155"))

    def ad(self, kisi_id):
        return (self.profiller.get(kisi_id) or {}).get("ad", "?")

    @property
    def diger(self):
        for pid, p in self.profiller.items():
            if pid != self.ben["id"]:
                return p
        return None

    def izinli(self, islem):
        return self.yonetici or islem.get("ekleyen") == self.ben["id"]

    async def arka(self, f, *a):
        return await asyncio.to_thread(f, *a)

    # ------------------------------------------------------------ başlangıç
    async def baslat(self):
        self.govde.content = ft.Column([ft.ProgressRing(), yazi("Yükleniyor...", renk=SOLUK)],
                                       horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                       alignment=ft.MainAxisAlignment.CENTER, expand=True)
        self.guncelle()
        if await self.arka(self.supa.kayitli_oturumu_ac):
            try:
                await self.oturum_basla()
                return
            except Exception as e:
                print("Kayıtlı oturum açılamadı:", e)
        self.giris_ekrani()

    def giris_ekrani(self, hata=""):
        self.page.navigation_bar = None
        k_adi = ft.TextField(label="Kullanıcı adı", hint_text="Abdurrahman veya Hatice", autofocus=True)
        sifre = ft.TextField(label="Şifre", password=True, can_reveal_password=True)
        hatirla = ft.Checkbox(label="Beni hatırla", value=True)
        hata_y = yazi(hata, 12, renk=GIDER)
        bekle = ft.ProgressRing(visible=False, width=22, height=22)

        async def giris(e):
            if not k_adi.value or not sifre.value:
                hata_y.value = "Kullanıcı adı ve şifre gerekli."
                self.guncelle()
                return
            bekle.visible, hata_y.value = True, ""
            self.guncelle()
            try:
                await self.arka(self.supa.giris, k_adi.value.strip(), sifre.value, hatirla.value)
                await self.oturum_basla()
            except hb.ApiHatasi as ex:
                bekle.visible = False
                hata_y.value = ("Kullanıcı adı veya şifre hatalı." if ex.durum in (400, 401)
                                else f"Giriş yapılamadı: {ex.mesaj}")
                self.guncelle()
            except Exception as ex:
                bekle.visible = False
                hata_y.value = f"Giriş yapılamadı: {ex}"
                self.guncelle()

        sifre.on_submit = giris
        self.govde.content = ft.ListView(padding=24, spacing=14, controls=[
            ft.Container(height=40),
            ft.Row([ft.Icon(ft.Icons.SAVINGS, size=64, color=ANA)], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([yazi("Hane Bütçesi", 28, True)], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([yazi("Abdurrahman & Hatice", 13, renk=SOLUK)], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=10),
            kart(ft.Column([k_adi, sifre, hatirla, buton("Giriş Yap", giris, ft.Icons.LOGIN, expand=True),
                            ft.Row([bekle, hata_y])], spacing=12)),
            ft.Row([yazi(f"Sürüm {SURUM}", 11, renk=SOLUK)], alignment=ft.MainAxisAlignment.CENTER),
        ])
        self.guncelle()

    async def oturum_basla(self):
        profiller = await self.arka(self.supa.profiller)
        self.profiller = {p["id"]: p for p in profiller}
        self.ben = self.profiller.get(self.supa.kullanici_id)
        if not self.ben:
            self.supa.cikis()
            self.giris_ekrani("Profil bulunamadı. Supabase'de 'supabase_kurulum.sql' betiğini çalıştırın.")
            return
        self.yonetici = self.ben.get("rol") == "yonetici"
        await self.ayarlari_yukle()

        self.page.navigation_bar = ft.NavigationBar(
            selected_index=0, on_change=self.sekme_degisti,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.DASHBOARD_OUTLINED, selected_icon=ft.Icons.DASHBOARD, label="Özet"),
                ft.NavigationBarDestination(icon=ft.Icons.RECEIPT_LONG_OUTLINED, selected_icon=ft.Icons.RECEIPT_LONG, label="İşlemler"),
                ft.NavigationBarDestination(icon=ft.Icons.ADD_CIRCLE_OUTLINE, selected_icon=ft.Icons.ADD_CIRCLE, label="Ekle"),
                ft.NavigationBarDestination(icon=ft.Icons.DOCUMENT_SCANNER_OUTLINED, selected_icon=ft.Icons.DOCUMENT_SCANNER, label="Fiş"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Ayarlar"),
            ])
        self.sekme = 0
        await self.verileri_yenile(ciz=False)
        self.ekrani_ciz()

        self.canli = hb.CanliBaglanti(self.supa, self.canli_degisiklik, self.canli_durum)
        self.page.run_task(self.canli.calistir)
        self._nesil += 1
        self.page.run_task(self.periyodik_yenile, self._nesil)

    async def ayarlari_yukle(self):
        import json as _json
        try:
            k = await self.arka(self.supa.ayar_oku, "kategoriler")
            if k:
                self.kategoriler = _json.loads(k)
            g = await self.arka(self.supa.ayar_oku, "gelir_turleri")
            if g:
                self.gelir_turleri = _json.loads(g)
            self.gemini_anahtari = (await self.arka(self.supa.ayar_oku, "gemini_api_key")) or ""
        except Exception as e:
            print("Ayarlar okunamadı:", e)
        if "Diğer" not in self.kategoriler:
            self.kategoriler.append("Diğer")

    # ------------------------------------------------------------ veri / senkron
    @property
    def donem(self):
        return hb.butce_donemi(ofset=self.donem_ofset)

    async def verileri_yenile(self, ciz=True):
        bas, bit = self.donem
        try:
            self.islemler, self.bakiyeler = await asyncio.gather(
                self.arka(self.supa.islemler, bas, bit), self.arka(self.supa.bakiyeler))
        except Exception as e:
            print("Veri yenileme hatası:", e)
            if ciz:
                self.bildir(f"Veriler alınamadı: {e}", GIDER)
        if ciz and self.sekme in (0, 1):
            self.ekrani_ciz()

    async def canli_degisiklik(self, veri: dict):
        kayit = veri.get("record") or {}
        if veri.get("type") == "INSERT" and kayit.get("ekleyen") and kayit.get("ekleyen") != self.ben["id"]:
            self._yeni_bildirimler.append(kayit)
        if self._yenileme_planli:
            return
        self._yenileme_planli = True
        await asyncio.sleep(0.8)  # fişten gelen çoklu satırları tek yenilemede topla
        self._yenileme_planli = False
        await self.verileri_yenile()
        if self._yeni_bildirimler:
            y = self._yeni_bildirimler
            self._yeni_bildirimler = []
            kim = y[0].get("ekleyen_ad") or "Eşiniz"
            toplam = sum(float(x.get("tutar") or 0) for x in y)
            if len(y) == 1:
                x = y[0]
                self.bildir(f"🔔 {kim}: {x.get('tur')} • {x.get('urun') or x.get('kategori') or ''} • {hb.tl(toplam)}")
            else:
                self.bildir(f"🔔 {kim} {len(y)} kayıt ekledi • {hb.tl(toplam)}")

    async def canli_durum(self, bagli: bool):
        if self.sekme == 0:
            self.ekrani_ciz()

    async def periyodik_yenile(self, nesil):
        while self.ben and nesil == self._nesil:
            await asyncio.sleep(20 if not (self.canli and self.canli.bagli) else 120)
            if self.ben and self.sekme in (0, 1):
                await self.verileri_yenile()

    # ------------------------------------------------------------ gezinme
    async def sekme_degisti(self, e):
        self.sekme = int(e.control.selected_index)
        self.ekrani_ciz()

    def sekmeye_git(self, i):
        self.sekme = i
        if self.page.navigation_bar:
            self.page.navigation_bar.selected_index = i
        self.ekrani_ciz()

    def ekrani_ciz(self, **kw):
        ciziciler = [self.ozet_ekrani, self.islemler_ekrani, self.ekle_ekrani, self.fis_ekrani, self.ayarlar_ekrani]
        try:
            self.govde.content = ciziciler[self.sekme](**kw)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.govde.content = ft.ListView(padding=16, controls=[yazi(f"Ekran hatası: {e}", renk=GIDER)])
        self.guncelle()

    # ------------------------------------------------------------ ortak parçalar
    def donem_cubugu(self):
        bas, bit = self.donem

        async def kaydir(n):
            self.donem_ofset = 0 if n == 0 else self.donem_ofset + n
            await self.verileri_yenile()

        async def geri(e):
            await kaydir(-1)

        async def ileri(e):
            await kaydir(1)

        async def bugun(e):
            await kaydir(0)

        return kart(ft.Row([
            ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=geri, tooltip="Önceki dönem"),
            ft.Column([yazi("Bütçe dönemi" + ("" if self.donem_ofset == 0 else " (geçmiş/gelecek)"), 11, renk=SOLUK),
                       yazi(hb.donem_etiketi(bas, bit), 15, True)],
                      spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True),
            ft.IconButton(icon=ft.Icons.TODAY, on_click=bugun, tooltip="Bu döneme dön",
                          visible=self.donem_ofset != 0),
            ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=ileri, tooltip="Sonraki dönem"),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), dolgu=4)

    def islem_satiri(self, i):
        tur = i.get("tur")
        if tur == "Gelir":
            renk, ikon, isaret = GELIR, ft.Icons.SOUTH_WEST, "+"
        elif tur == "Gider":
            renk, ikon, isaret = GIDER, ft.Icons.NORTH_EAST, "-"
        else:
            renk, ikon = AKTARIM, ft.Icons.SWAP_HORIZ
            isaret = "+" if (not self.yonetici and i.get("hedef_kasa") == self.ben["id"]) else ("-" if not self.yonetici else "")
        if tur == "Aktarım":
            baslik = f"{self.ad(i.get('kasa_sahibi'))} ➜ {self.ad(i.get('hedef_kasa'))}"
            alt = [i.get("aciklama") or "Para aktarımı"]
        else:
            baslik = i.get("urun") or i.get("kategori") or tur
            alt = [i.get("firma"), i.get("kategori")]
        alt.append(hb.tarih_goster(i.get("tarih")))
        etiketler = [ft.Icon(ft.Icons.PERSON, size=13, color=SOLUK), yazi(i.get("ekleyen_ad") or "?", 11, renk=SOLUK)]
        if self.yonetici and tur != "Aktarım":
            etiketler += [ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=13, color=SOLUK),
                          yazi(f"{self.ad(i.get('kasa_sahibi'))} kasası", 11, renk=SOLUK)]
        if i.get("fis_gorsel"):
            etiketler += [ft.Icon(ft.Icons.RECEIPT, size=13, color=ANA)]

        return ft.Container(
            content=ft.Row([
                ft.Container(content=ft.Icon(ikon, color=renk, size=20), bgcolor="#1f" + renk[1:], padding=8, border_radius=20),
                ft.Column([yazi(baslik, 14, True, max_lines=1),
                           yazi(" • ".join(x for x in alt if x), 11, renk=SOLUK, max_lines=1),
                           ft.Row(etiketler, spacing=3)], spacing=1, expand=True),
                yazi(f"{isaret}{hb.tl(i.get('tutar'))}", 14, True, renk=renk),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=KART, padding=10, border_radius=12,
            on_click=lambda e, i=i: self.islem_detay(i))

    # ------------------------------------------------------------ 0) ÖZET
    def ozet_ekrani(self):
        bas, bit = self.donem
        canli = self.canli and self.canli.bagli
        ust = ft.Row([
            ft.Column([yazi(f"Merhaba {self.ben['ad']} 👋", 20, True),
                       yazi("Yönetici" if self.yonetici else "Kendi kasanızı görüyorsunuz", 12, renk=SOLUK)],
                      spacing=0, expand=True),
            ft.Container(content=ft.Row([ft.Icon(ft.Icons.CIRCLE, size=10, color=GELIR if canli else "#94a3b8"),
                                 yazi("Canlı" if canli else "Bağlanıyor", 11, renk=SOLUK)], spacing=4),
                         bgcolor=KART, padding=8, border_radius=20),
        ])
        bak = {b["kisi"]: float(b.get("bakiye") or 0) for b in self.bakiyeler}
        kontroller = [ust, self.donem_cubugu()]

        if self.yonetici:
            toplam = sum(bak.values())
            kontroller.append(kart(ft.Column([
                yazi("Toplam Kasa", 13, renk="#ccfbf1"),
                yazi(hb.tl(toplam), 30, True, renk="white"),
                ft.Row([self._mini_kasa(self.ad(pid), deger) for pid, deger in bak.items()], spacing=10),
            ], spacing=6), renk=ANA, dolgu=18))
        else:
            kontroller.append(kart(ft.Column([
                yazi("Kasam", 13, renk="#ccfbf1"),
                yazi(hb.tl(bak.get(self.ben["id"], 0)), 30, True, renk="white"),
            ], spacing=4), renk=ANA, dolgu=18))

        oz = hb.donem_ozeti(self.islemler, None if self.yonetici else self.ben["id"])
        kontroller.append(ft.Row([
            self._ozet_kutu("Dönem geliri", oz["gelir"], GELIR, ft.Icons.TRENDING_UP),
            self._ozet_kutu("Dönem gideri", oz["gider"], GIDER, ft.Icons.TRENDING_DOWN),
        ], spacing=10))
        if not self.yonetici and (oz["aktarim_giris"] or oz["aktarim_cikis"]):
            kontroller.append(kart(ft.Row([
                yazi("Aktarımlar", 13, True, expand=True),
                yazi(f"Gelen {hb.tl(oz['aktarim_giris'])}", 12, renk=GELIR),
                yazi(f"Giden {hb.tl(oz['aktarim_cikis'])}", 12, renk=GIDER)], spacing=10)))

        if self.yonetici:
            satirlar = []
            for pid in self.profiller:
                o = hb.donem_ozeti(self.islemler, pid)
                satirlar.append(ft.Row([yazi(self.ad(pid), 13, True, expand=True),
                                        yazi(f"+{hb.tl(o['gelir'])}", 12, renk=GELIR),
                                        yazi(f"-{hb.tl(o['gider'])}", 12, renk=GIDER)], spacing=10))
            kontroller.append(kart(ft.Column([yazi("Kişi bazında bu dönem", 13, True)] + satirlar, spacing=8)))

        if oz["kategoriler"]:
            enb = max(oz["kategoriler"].values()) or 1
            kat_sat = [yazi("Harcama kategorileri", 13, True)]
            for k, v in list(oz["kategoriler"].items())[:8]:
                kat_sat.append(ft.Column([
                    ft.Row([yazi(k, 12, expand=True, max_lines=1), yazi(hb.tl(v), 12, True)]),
                    ft.ProgressBar(value=v / enb, color=ANA, bgcolor="#e2e8f0"),
                ], spacing=3))
            kontroller.append(kart(ft.Column(kat_sat, spacing=10)))

        son = self.islemler[:8]
        kontroller.append(ft.Row([yazi("Son işlemler", 15, True, expand=True),
                                  buton("Tümü", lambda e: self.sekmeye_git(1), tip="text")]))
        if son:
            kontroller += [self.islem_satiri(i) for i in son]
        else:
            kontroller.append(kart(yazi("Bu dönemde henüz kayıt yok. 'Ekle' veya 'Fiş' sekmesinden başlayın.",
                                        13, renk=SOLUK)))
        return ft.ListView(padding=14, spacing=10, controls=kontroller, expand=True)

    def _mini_kasa(self, ad, deger):
        return ft.Container(content=ft.Column([yazi(ad, 11, renk="#ccfbf1"), yazi(hb.tl(deger), 15, True, renk="white")],
                                      spacing=0), bgcolor="#115e59", padding=10, border_radius=10, expand=True)

    def _ozet_kutu(self, baslik, deger, renk, ikon):
        return kart(ft.Column([ft.Row([ft.Icon(ikon, color=renk, size=18), yazi(baslik, 12, renk=SOLUK)], spacing=4),
                               yazi(hb.tl(deger), 17, True, renk=renk)], spacing=4), expand=True)

    # ------------------------------------------------------------ 1) İŞLEMLER
    def islemler_ekrani(self):
        liste = ft.Column(spacing=8)

        def doldur():
            f = self.filtre
            ara = hb.urun_anahtari(f["arama"])
            sonuc = []
            for i in self.islemler:
                if f["tur"] != "Tümü" and i.get("tur") != f["tur"]:
                    continue
                if self.yonetici and f["kasa"] != "Hepsi":
                    kid = next((p for p, v in self.profiller.items() if v["ad"] == f["kasa"]), None)
                    if i.get("kasa_sahibi") != kid and i.get("hedef_kasa") != kid:
                        continue
                if ara:
                    metin = hb.urun_anahtari(" ".join(str(i.get(k) or "") for k in
                                                      ("urun", "firma", "kategori", "aciklama", "ekleyen_ad")))
                    if ara not in metin:
                        continue
                sonuc.append(i)
            toplam_gider = sum(float(x.get("tutar") or 0) for x in sonuc if x.get("tur") == "Gider")
            toplam_gelir = sum(float(x.get("tutar") or 0) for x in sonuc if x.get("tur") == "Gelir")
            liste.controls = [ft.Row([yazi(f"{len(sonuc)} kayıt", 12, renk=SOLUK, expand=True),
                                      yazi(f"+{hb.tl(toplam_gelir)}", 12, renk=GELIR),
                                      yazi(f"-{hb.tl(toplam_gider)}", 12, renk=GIDER)], spacing=8)]
            liste.controls += [self.islem_satiri(i) for i in sonuc[:400]] or [
                kart(yazi("Kayıt bulunamadı.", 13, renk=SOLUK))]

        def arama_degisti(e):
            self.filtre["arama"] = e.control.value or ""
            doldur()
            self.guncelle()

        def tur_degisti(e):
            self.filtre["tur"] = e.control.value
            doldur()
            self.guncelle()

        def kasa_degisti(e):
            self.filtre["kasa"] = e.control.value
            doldur()
            self.guncelle()

        arama = ft.TextField(value=self.filtre["arama"], hint_text="Ara: ürün, market, kategori, kişi...",
                             prefix_icon=ft.Icons.SEARCH, on_change=arama_degisti, bgcolor=KART, border_radius=12)
        turler = ft.RadioGroup(value=self.filtre["tur"], on_change=tur_degisti, content=ft.Row(
            [ft.Radio(value=t, label=t) for t in ("Tümü", "Gider", "Gelir", "Aktarım")], wrap=True, spacing=0))
        filtreler = [arama, turler]
        if self.yonetici:
            filtreler.append(ft.RadioGroup(value=self.filtre["kasa"], on_change=kasa_degisti, content=ft.Row(
                [ft.Radio(value="Hepsi", label="Tüm kasalar")] +
                [ft.Radio(value=p["ad"], label=p["ad"]) for p in self.profiller.values()], wrap=True, spacing=0)))
        doldur()
        return ft.ListView(padding=14, spacing=10, expand=True,
                           controls=[self.donem_cubugu(), kart(ft.Column(filtreler, spacing=4), dolgu=8), liste])

    def islem_detay(self, i):
        tur = i.get("tur")
        satirlar = [("Tür", tur), ("Tutar", hb.tl(i.get("tutar"))), ("Tarih", hb.tarih_goster(i.get("tarih")))]
        if tur == "Aktarım":
            satirlar += [("Gönderen", self.ad(i.get("kasa_sahibi"))), ("Alan", self.ad(i.get("hedef_kasa")))]
        else:
            satirlar += [("Kasa", self.ad(i.get("kasa_sahibi"))), ("Kategori", i.get("kategori")),
                         ("Firma", i.get("firma")), ("Ürün / Açıklama", i.get("urun")), ("Miktar", i.get("miktar"))]
            if i.get("birim_fiyat"):
                satirlar.append(("Birim fiyat", hb.tl(i.get("birim_fiyat"))))
        satirlar += [("Not", i.get("aciklama")), ("Ekleyen", i.get("ekleyen_ad")),
                     ("Eklenme", hb.tarih_goster(i.get("olusturma")))]
        if i.get("fis_grup"):
            ayni = [x for x in self.islemler if x.get("fis_grup") == i.get("fis_grup")]
            satirlar.append(("Fiş", f"{len(ayni)} ürün • {hb.tl(sum(float(x.get('tutar') or 0) for x in ayni))}"))

        icerik = ft.Column([ft.Row([yazi(k, 12, renk=SOLUK, width=110), yazi(str(v), 13, expand=True)])
                            for k, v in satirlar if v not in (None, "")], tight=True, spacing=6,
                           scroll=ft.ScrollMode.AUTO)
        d = ft.AlertDialog(title=yazi("İşlem detayı", 17, True), content=icerik)

        async def fis_goster(e):
            self.dialog_kapat(d)
            await self.fis_gorseli_goster(i.get("fis_gorsel"))

        def duzenle(e):
            self.dialog_kapat(d)
            self.sekme = 2
            if self.page.navigation_bar:
                self.page.navigation_bar.selected_index = 2
            self.ekrani_ciz(duzenlenen=i)

        async def sil(e, tum_fis=False):
            self.dialog_kapat(d)
            try:
                if tum_fis:
                    await self.arka(self.supa.fis_grubu_sil, i["fis_grup"])
                else:
                    await self.arka(self.supa.islem_sil, i["id"])
                self.bildir("Silindi.")
                await self.verileri_yenile()
            except Exception as ex:
                self.bildir(f"Silinemedi: {ex}", GIDER)

        def sil_onay(tum_fis=False):
            async def evet(e):
                self.dialog_kapat(o)
                await sil(e, tum_fis)
            o = ft.AlertDialog(title=yazi("Emin misiniz?", 16, True),
                               content=yazi("Fişteki tüm ürünler silinecek." if tum_fis else "Bu kayıt silinecek."),
                               actions=[buton("Vazgeç", lambda e: self.dialog_kapat(o), tip="text"),
                                        buton("Sil", evet)])
            self.dialog_kapat(d)
            self.dialog_ac(o)

        eylemler = []
        if i.get("fis_gorsel"):
            eylemler.append(buton("Fişi gör", fis_goster, ft.Icons.IMAGE, tip="text"))
        if self.izinli(i):
            eylemler.append(buton("Düzenle", duzenle, ft.Icons.EDIT, tip="text"))
            eylemler.append(buton("Sil", lambda e: sil_onay(False), ft.Icons.DELETE, tip="text"))
            if i.get("fis_grup"):
                eylemler.append(buton("Fişi tümden sil", lambda e: sil_onay(True), ft.Icons.DELETE_SWEEP, tip="text"))
        eylemler.append(buton("Kapat", lambda e: self.dialog_kapat(d), tip="text"))
        d.actions = eylemler
        self.dialog_ac(d)

    async def fis_gorseli_goster(self, yol):
        if not yol:
            return
        try:
            adres = await self.arka(self.supa.fis_adresi, yol)
        except Exception as e:
            self.bildir(f"Fiş görseli açılamadı: {e}", GIDER)
            return
        resim = ft.Image(src=adres)
        if hasattr(ft, "InteractiveViewer"):
            resim = ft.InteractiveViewer(content=resim, min_scale=1, max_scale=5)
        d = ft.AlertDialog(content=ft.Container(content=resim, width=380, height=560),
                           actions=[buton("Kapat", lambda e: self.dialog_kapat(d), tip="text")])
        self.dialog_ac(d)

    # ------------------------------------------------------------ 2) EKLE / DÜZENLE
    def ekle_ekrani(self, duzenlenen=None, tur=None):
        d = duzenlenen or {}
        tur = tur or d.get("tur") or "Gider"
        ben = self.ben["id"]
        kisiler = list(self.profiller.values())

        tutar = ft.TextField(label="Tutar (₺)", value=(f"{float(d['tutar']):.2f}".replace(".", ",") if d.get("tutar") else ""),
                             keyboard_type=ft.KeyboardType.NUMBER, autofocus=not d, text_size=22)
        tarih = ft.TextField(label="Tarih (GG.AA.YYYY SS:DD)",
                             value=hb.tarih_goster(d.get("tarih")) if d else hb.simdi().strftime("%d.%m.%Y %H:%M"))
        aciklama = ft.TextField(label="Not (isteğe bağlı)", value=d.get("aciklama") or "")
        firma = ft.TextField(label="Firma / Market" if tur == "Gider" else "Kaynak (işveren, kişi...)",
                             value=d.get("firma") or "")
        urun = ft.TextField(label="Ürün / Hizmet" if tur == "Gider" else "Açıklama", value=d.get("urun") or "")
        miktar = ft.TextField(label="Miktar (örn: 2 adet, 1.5 kg)", value=d.get("miktar") or "")
        if tur == "Gider":
            kategori = acilir("Kategori", self.kategoriler, d.get("kategori") or "Market & Temel Gıda")
        else:
            kategori = acilir("Gelir türü", self.gelir_turleri, d.get("kategori") or self.gelir_turleri[0])

        varsayilan_kasa = d.get("kasa_sahibi") or ben
        kasa = ft.RadioGroup(value=varsayilan_kasa, content=ft.Row(
            [ft.Radio(value=p["id"], label=p["ad"]) for p in kisiler], wrap=True))

        def tur_degisti(e):
            self.govde.content = self.ekle_ekrani(duzenlenen=duzenlenen, tur=e.control.value)
            self.guncelle()

        tur_sec = ft.RadioGroup(value=tur, on_change=tur_degisti, content=ft.Row(
            [ft.Radio(value=t, label=t) for t in ("Gider", "Gelir", "Aktarım")], wrap=True))

        hata = yazi("", 12, renk=GIDER)
        kaydet_btn = None

        async def kaydet(e):
            t = hb.tutar_coz(tutar.value)
            if not t or t <= 0:
                hata.value = "Geçerli bir tutar girin."
                self.guncelle()
                return
            sahip = kasa.value if self.yonetici else ben
            kayit = {"tur": tur, "tutar": t, "tarih": hb.iso_tarih(hb.tarih_coz(tarih.value)),
                     "aciklama": aciklama.value.strip() or None, "kasa_sahibi": sahip}
            if tur == "Aktarım":
                hedef = next((p["id"] for p in kisiler if p["id"] != sahip), None)
                if not hedef:
                    hata.value = "Aktarım için ikinci kullanıcı bulunamadı."
                    self.guncelle()
                    return
                kayit.update({"hedef_kasa": hedef, "kategori": "Transfer / Birikim",
                              "firma": None, "urun": None, "miktar": None})
            else:
                kayit.update({"hedef_kasa": None, "kategori": kategori.value, "firma": firma.value.strip() or None,
                              "urun": urun.value.strip() or None,
                              "miktar": (miktar.value.strip() or None) if tur == "Gider" else None})
            kaydet_btn.disabled = True
            self.guncelle()
            try:
                if d.get("id"):
                    await self.arka(self.supa.islem_guncelle, d["id"], kayit)
                    self.bildir("Güncellendi ✓", GELIR)
                else:
                    await self.arka(self.supa.islem_ekle, [kayit])
                    self.bildir(f"{tur} kaydedildi ✓ {hb.tl(t)}", GELIR)
                await self.verileri_yenile(ciz=False)
                self.sekmeye_git(1 if d.get("id") else 0)
            except Exception as ex:
                kaydet_btn.disabled = False
                hata.value = f"Kaydedilemedi: {ex}"
                self.guncelle()

        kaydet_btn = buton("Güncelle" if d.get("id") else "Kaydet", kaydet, ft.Icons.CHECK, expand=True)

        alanlar = [yazi("Kaydı düzenle" if d.get("id") else "Yeni kayıt", 20, True)]
        if not d.get("id"):
            alanlar.append(tur_sec)
        alanlar.append(tutar)
        if tur == "Aktarım":
            if self.yonetici:
                alanlar += [yazi("Gönderen kasa (diğerine aktarılır):", 12, renk=SOLUK), kasa]
            else:
                diger = self.diger
                alanlar.append(kart(yazi(f"{self.ben['ad']} kasasından ➜ {diger['ad'] if diger else '?'} kasasına",
                                         13, True, renk=AKTARIM), renk="#dbeafe"))
            alanlar += [aciklama, tarih]
        else:
            alanlar += [kategori, firma, urun]
            if tur == "Gider":
                alanlar.append(miktar)
            if self.yonetici:
                alanlar += [yazi("Hangi kasa?", 12, renk=SOLUK), kasa]
            alanlar += [tarih, aciklama]
        alanlar += [hata, ft.Row([kaydet_btn])]
        if d.get("id"):
            alanlar.append(ft.Row([buton("Vazgeç", lambda e: self.sekmeye_git(1), tip="text")]))
        return ft.ListView(padding=14, expand=True, controls=[kart(ft.Column(alanlar, spacing=12))])

    # ------------------------------------------------------------ 3) FİŞ TARA
    def fis_ekrani(self):
        f = self.fis
        if f is None:
            return ft.ListView(padding=14, spacing=12, expand=True, controls=[
                yazi("Fiş / Fatura Ekle", 20, True),
                kart(ft.Column([
                    ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, color=ANA), yazi("Yapay zeka ile otomatik okuma", 14, True)]),
                    yazi("Fişin fotoğrafını seçin. Ürünler, fiyatlar ve kategoriler otomatik çıkarılır; "
                         "kaydetmeden önce düzeltebilirsiniz. Görsel buluta kaydedilir.", 12, renk=SOLUK),
                    buton("Galeriden fiş fotoğrafı seç", lambda e: self.page.run_task(self.fis_sec, "resim"),
                          ft.Icons.PHOTO_LIBRARY, expand=True),
                    buton("PDF fatura seç", lambda e: self.page.run_task(self.fis_sec, "pdf"),
                          ft.Icons.PICTURE_AS_PDF, tip="outlined", expand=True),
                    yazi("İpucu: Önce telefonun kamerasıyla fişi düz ve aydınlık şekilde çekin.", 11, renk=SOLUK),
                ], spacing=10)),
                *([] if self.gemini_anahtari else [kart(yazi(
                    "⚠️ Gemini API anahtarı ayarlı değil. " +
                    ("Ayarlar sekmesinden ekleyin." if self.yonetici else "Abdurrahman'ın Ayarlar'dan eklemesi gerekiyor."),
                    12, renk=GIDER), renk="#fee2e2")]),
            ])
        if f.get("durum") == "isleniyor":
            return ft.Column([ft.ProgressRing(), yazi(f.get("mesaj", "İşleniyor..."), 14, renk=SOLUK)],
                             horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                             alignment=ft.MainAxisAlignment.CENTER, expand=True)
        return self._fis_duzenleyici()

    async def fis_sec(self, tip):
        if not self.picker:
            self.bildir("Dosya seçici kullanılamıyor.", GIDER)
            return
        kw = dict(allow_multiple=False)
        if tip == "pdf":
            kw.update(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])
        else:
            kw.update(file_type=ft.FilePickerFileType.IMAGE)
        try:
            try:
                sonuc = self.picker.pick_files(with_data=True, **kw)
            except TypeError:
                sonuc = self.picker.pick_files(**kw)
            if inspect.isawaitable(sonuc):
                sonuc = await sonuc
        except Exception as e:
            self.bildir(f"Dosya seçilemedi: {e}", GIDER)
            return
        dosyalar = sonuc if isinstance(sonuc, list) else getattr(sonuc, "files", None)
        if not dosyalar:
            return
        dosya = dosyalar[0]
        veri = getattr(dosya, "bytes", None)
        if not veri and getattr(dosya, "path", None):
            try:
                with open(dosya.path, "rb") as fp:
                    veri = fp.read()
            except Exception as e:
                self.bildir(f"Dosya okunamadı: {e}", GIDER)
                return
        if not veri:
            self.bildir("Dosya içeriği alınamadı.", GIDER)
            return
        await self.fis_isle(bytes(veri), tip)

    async def fis_isle(self, veri: bytes, tip: str):
        self.fis = {"durum": "isleniyor", "mesaj": "Görsel hazırlanıyor..."}
        self.ekrani_ciz()
        if tip == "pdf":
            hazir, mime, uzanti = veri, "application/pdf", "pdf"
        else:
            hazir, mime = await self.arka(hb.gorseli_hazirla, veri)
            uzanti = "pdf" if mime == "application/pdf" else ("png" if mime == "image/png" else "jpg")

        self.fis["mesaj"] = "Yükleniyor ve yapay zeka ile okunuyor..."
        self.ekrani_ciz()
        if self.eslemeler is None:
            try:
                self.eslemeler = await self.arka(self.supa.kategori_eslemeleri)
            except Exception:
                self.eslemeler = {}

        async def yukle():
            return await self.arka(self.supa.fis_yukle, hazir, uzanti, mime)

        async def analiz():
            return await self.arka(hb.fis_analiz_et, hazir, mime, self.gemini_anahtari, self.kategoriler,
                                   self.eslemeler)

        yol_s, analiz_s = await asyncio.gather(yukle(), analiz(), return_exceptions=True)
        uyari = []
        if isinstance(yol_s, Exception):
            uyari.append(f"Görsel yüklenemedi: {yol_s}")
            yol_s = None
        if isinstance(analiz_s, Exception):
            uyari.append(f"Otomatik okuma başarısız: {analiz_s}. Ürünleri elle girebilirsiniz.")
            analiz_s = {"firma": "", "tarih_dt": hb.simdi(), "urunler": [], "toplam_tutar": None}
        urunler = analiz_s.get("urunler") or [{"urun": "", "miktar": "", "birim_fiyat": None, "tutar": None,
                                               "kategori": "Market & Temel Gıda"}]
        for u in urunler:
            u["ai_kategori"] = u.get("kategori")
        self.fis = {"durum": "duzenle", "yol": yol_s, "firma": analiz_s.get("firma") or "",
                    "tarih": analiz_s["tarih_dt"].strftime("%d.%m.%Y %H:%M"),
                    "toplam": analiz_s.get("toplam_tutar"), "model": analiz_s.get("model"),
                    "urunler": urunler, "uyari": uyari, "kasa": self.ben["id"]}
        self.ekrani_ciz()
        if not uyari:
            self.bildir(f"{len(urunler)} ürün okundu ✓", GELIR)

    def _fis_duzenleyici(self):
        f = self.fis
        firma = ft.TextField(label="Firma / Market", value=f["firma"])
        tarih = ft.TextField(label="Tarih", value=f["tarih"])
        toplam_y = yazi("", 16, True)
        satir_kutusu = ft.Column(spacing=8)
        satirlar = []  # (urun_tf, tutar_tf, kategori_dd, miktar, birim, ai_kat)

        def toplami_hesapla(e=None):
            t = sum(hb.tutar_coz(s[1].value) or 0 for s in satirlar)
            fark = ""
            if f.get("toplam") and abs(t - float(f["toplam"])) > 0.05:
                fark = f"  (fiş toplamı {hb.tl(f['toplam'])})"
            toplam_y.value = f"Toplam: {hb.tl(t)}{fark}"
            toplam_y.color = GIDER if fark else YAZI
            if e is not None:
                self.guncelle()

        def satir_ekle(u):
            urun_tf = ft.TextField(label="Ürün", value=u.get("urun") or "", dense=True)
            tutar_tf = ft.TextField(label="Tutar", width=110, dense=True, keyboard_type=ft.KeyboardType.NUMBER,
                                    value=(f"{float(u['tutar']):.2f}".replace(".", ",") if u.get("tutar") is not None else ""),
                                    on_change=toplami_hesapla)
            kat_dd = acilir("Kategori", self.kategoriler,
                            u.get("kategori") if u.get("kategori") in self.kategoriler else "Diğer", expand=True)
            kayit = [urun_tf, tutar_tf, kat_dd, u.get("miktar"), u.get("birim_fiyat"), u.get("ai_kategori")]
            kutu = kart(None, dolgu=8, renk="#f8fafc")

            def kaldir(e):
                satirlar.remove(kayit)
                satir_kutusu.controls.remove(kutu)
                toplami_hesapla(e)

            ust = [urun_tf]
            kutu.content = ft.Column([
                ft.Row([ft.Container(content=urun_tf, expand=True),
                        ft.IconButton(icon=ft.Icons.CLOSE, icon_size=18, on_click=kaldir, tooltip="Satırı sil")]),
                ft.Row([tutar_tf, kat_dd], spacing=8),
                *([yazi(f"Miktar: {u['miktar']}", 11, renk=SOLUK)] if u.get("miktar") else []),
            ], spacing=6)
            satirlar.append(kayit)
            satir_kutusu.controls.append(kutu)
            return ust

        for u in f["urunler"]:
            satir_ekle(u)
        toplami_hesapla()

        def yeni_satir(e):
            satir_ekle({"urun": "", "tutar": None, "kategori": "Market & Temel Gıda"})
            self.guncelle()

        kasa = ft.RadioGroup(value=f["kasa"], content=ft.Row(
            [ft.Radio(value=p["id"], label=p["ad"]) for p in self.profiller.values()], wrap=True))

        def vazgec(e):
            self.fis = None
            self.ekrani_ciz()

        async def kaydet(e):
            kayitlar, ogrenilen = [], {}
            grup = str(uuid.uuid4())
            zaman = hb.iso_tarih(hb.tarih_coz(tarih.value))
            sahip = kasa.value if self.yonetici else self.ben["id"]
            for urun_tf, tutar_tf, kat_dd, mik, birim, ai_kat in satirlar:
                t = hb.tutar_coz(tutar_tf.value)
                if not t or t <= 0:
                    continue
                ad = (urun_tf.value or "").strip() or "Ürün"
                kayitlar.append({"tur": "Gider", "tarih": zaman, "firma": firma.value.strip() or None, "urun": ad,
                                 "kategori": kat_dd.value or "Diğer", "miktar": mik or None,
                                 "birim_fiyat": birim, "tutar": t, "kasa_sahibi": sahip, "hedef_kasa": None,
                                 "fis_grup": grup, "fis_gorsel": f.get("yol")})
                if kat_dd.value and kat_dd.value != ai_kat:
                    ogrenilen[hb.urun_anahtari(ad)] = kat_dd.value
            if not kayitlar:
                self.bildir("Kaydedilecek geçerli satır yok.", GIDER)
                return
            try:
                await self.arka(self.supa.islem_ekle, kayitlar)
                if ogrenilen:
                    try:
                        await self.arka(self.supa.kategori_eslemesi_kaydet, ogrenilen)
                        (self.eslemeler or {}).update(ogrenilen)
                    except Exception as ex:
                        print("Eşleme kaydedilemedi:", ex)
                self.fis = None
                self.bildir(f"Fiş kaydedildi ✓ {len(kayitlar)} ürün • "
                            f"{hb.tl(sum(k['tutar'] for k in kayitlar))}", GELIR)
                await self.verileri_yenile(ciz=False)
                self.sekmeye_git(0)
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        bilgi = []
        for u in f.get("uyari") or []:
            bilgi.append(kart(yazi("⚠️ " + u, 12, renk=GIDER), renk="#fee2e2", dolgu=10))
        alt_bilgi = " • ".join(x for x in [f"Model: {f['model']}" if f.get("model") else "",
                                            f"Fiş toplamı: {hb.tl(f['toplam'])}" if f.get("toplam") else ""] if x)
        ust_kontroller = [ft.Row([yazi("Fişi kontrol et", 20, True, expand=True),
                                  *([buton("Görsel", lambda e: self.page.run_task(self.fis_gorseli_goster, f["yol"]),
                                           ft.Icons.IMAGE, tip="text")] if f.get("yol") else [])]),
                          *bilgi, kart(ft.Column([firma, tarih] + (
                              [yazi("Hangi kasadan ödendi?", 12, renk=SOLUK), kasa] if self.yonetici else []) +
                              ([yazi(alt_bilgi, 11, renk=SOLUK)] if alt_bilgi else []), spacing=10))]
        return ft.ListView(padding=14, spacing=10, expand=True, controls=ust_kontroller + [
            satir_kutusu,
            buton("Satır ekle", yeni_satir, ft.Icons.ADD, tip="outlined"),
            kart(toplam_y),
            ft.Row([buton("Vazgeç", vazgec, tip="text"), buton("Kaydet", kaydet, ft.Icons.SAVE, expand=True)]),
        ])

    # ------------------------------------------------------------ 4) AYARLAR
    def ayarlar_ekrani(self):
        canli = self.canli and self.canli.bagli
        kontroller = [yazi("Ayarlar", 20, True), kart(ft.Column([
            ft.Row([ft.Icon(ft.Icons.ACCOUNT_CIRCLE, size=40, color=ANA),
                    ft.Column([yazi(self.ben["ad"], 16, True),
                               yazi("Yönetici – tüm kasaları görür" if self.yonetici else "Üye – kendi kasasını görür",
                                    12, renk=SOLUK)], spacing=0)]),
            ft.Row([ft.Icon(ft.Icons.CIRCLE, size=10, color=GELIR if canli else "#94a3b8"),
                    yazi("Anlık senkronizasyon açık" if canli else "Anlık bağlantı kuruluyor (20 sn'de bir yenileniyor)",
                         12, renk=SOLUK)]),
        ], spacing=10))]

        if self.yonetici:
            anahtar = ft.TextField(label="Gemini API anahtarı", value=self.gemini_anahtari, password=True,
                                   can_reveal_password=True)

            async def anahtar_kaydet(e):
                try:
                    await self.arka(self.supa.ayar_yaz, "gemini_api_key", anahtar.value.strip())
                    self.gemini_anahtari = anahtar.value.strip()
                    self.bildir("API anahtarı kaydedildi ✓ (iki telefon da kullanır)", GELIR)
                except Exception as ex:
                    self.bildir(f"Kaydedilemedi: {ex}", GIDER)

            yeni_kat = ft.TextField(label="Yeni gider kategorisi")

            async def kat_ekle(e):
                import json as _json
                k = (yeni_kat.value or "").strip()
                if not k or k in self.kategoriler:
                    return
                yeni = self.kategoriler[:-1] + [k, "Diğer"] if self.kategoriler[-1] == "Diğer" else self.kategoriler + [k]
                try:
                    await self.arka(self.supa.ayar_yaz, "kategoriler", _json.dumps(yeni, ensure_ascii=False))
                    self.kategoriler = yeni
                    self.bildir(f"'{k}' eklendi ✓", GELIR)
                    self.ekrani_ciz()
                except Exception as ex:
                    self.bildir(f"Eklenemedi: {ex}", GIDER)

            kontroller += [
                kart(ft.Column([yazi("Yapay zeka (fiş okuma)", 14, True),
                                yazi("aistudio.google.com adresinden ücretsiz alınabilir.", 11, renk=SOLUK),
                                anahtar, buton("Anahtarı kaydet", anahtar_kaydet, ft.Icons.KEY)], spacing=10)),
                kart(ft.Column([yazi(f"Kategoriler ({len(self.kategoriler)})", 14, True),
                                yazi(", ".join(self.kategoriler), 11, renk=SOLUK),
                                ft.Row([ft.Container(content=yeni_kat, expand=True),
                                        ft.IconButton(icon=ft.Icons.ADD, on_click=kat_ekle)])], spacing=10)),
            ]

        async def yenile(e):
            await self.ayarlari_yukle()
            await self.verileri_yenile(ciz=False)
            self.bildir("Yenilendi ✓")

        async def cikis(e):
            if self.canli:
                self.canli.durdur()
            await self.arka(self.supa.cikis)
            self.ben, self.islemler, self.bakiyeler, self.fis = None, [], [], None
            self.giris_ekrani()

        kontroller += [buton("Verileri yenile", yenile, ft.Icons.REFRESH, tip="outlined"),
                       buton("Çıkış yap", cikis, ft.Icons.LOGOUT, tip="outlined"),
                       ft.Row([yazi(f"Hane Bütçesi {SURUM}", 11, renk=SOLUK)], alignment=ft.MainAxisAlignment.CENTER)]
        return ft.ListView(padding=14, spacing=12, expand=True, controls=kontroller)


async def main(page: ft.Page):
    uyg = Uygulama(page)
    await uyg.baslat()


if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
