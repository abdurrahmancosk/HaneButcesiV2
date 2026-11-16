"""
Hane Bütçesi v2 – Abdurrahman & Hatice
Flet (Android/Windows) + Supabase (giriş, veritabanı, anlık senkron, fiş deposu) + Gemini (fiş analizi)
"""
import asyncio
import datetime as dt
import inspect
import urllib.parse
import uuid

import flet as ft

import hb_akil as ak
import hb_core as hb

SURUM = "2.12.1"

import hb_ui as ui
from hb_ek import EkOzellikler
from hb_ek2 import EkOzellikler2
from hb_ek3 import EkOzellikler3
from hb_ek4 import EkOzellikler4
from hb_ui import (ANA, GELIR, GIDER, AKTARIM, _param_var, buton, acilir, kart, yazi, KATEGORI_STIL, GUNLER, AYLAR_UZUN, ikon, kat_stil, saydam, golge, degrade, ORTA, simge_kutusu, cip, gun_basligi, fis_anahtari, grupla)


# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------
class Uygulama(EkOzellikler, EkOzellikler2, EkOzellikler3, EkOzellikler4):
    def __init__(self, page: ft.Page):
        self.page = page
        self.supa = hb.Supabase()
        self.ben: dict | None = None
        self.profiller: dict[str, dict] = {}
        self.yonetici = False
        self.kategoriler = list(hb.VARSAYILAN_KATEGORILER)
        self.gelir_turleri = list(hb.VARSAYILAN_GELIR_TURLERI)
        self.gemini_anahtari = ""
        self.gizli_varsayilan = False
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
        self._kamera_acik = False
        p = str(getattr(page, "platform", "") or "").lower()
        self.mobil = "android" in p or "ios" in p
        self.ek_varsayilan()
        self.ek2_kur()
        self.ek3_kur()
        self.ek4_kur()
        self.tum_islemler = None
        self._alt_kaynak = None

        page.title = "Hane Bütçesi"
        try:
            page.window.icon = "icon.ico"
        except Exception:
            pass
        try:
            page.fonts = {"Inter": "fonts/Inter-Regular.otf", "InterSB": "fonts/Inter-SemiBold.otf",
                          "InterB": "fonts/Inter-Bold.otf", "InterXB": "fonts/Inter-ExtraBold.otf"}
        except Exception:
            pass
        self.tema_modu_uygula()  # varsayılan: cihazın teması
        try:
            page.on_platform_brightness_change = self.sistem_temasi_degisti
        except Exception:
            pass
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
        self.alt_menu = ft.Container(visible=False, padding=ft.Padding(6, 0, 6, 6))
        self.yenile_bar = ft.ProgressBar(visible=False, color=ANA, bgcolor="#00000000")
        page.add(ft.SafeArea(content=ft.Column([self.yenile_bar, self.govde, self.alt_menu], spacing=0, expand=True),
                             expand=True))

    # ------------------------------------------------------------ yardımcılar
    def guncelle(self):
        try:
            self.page.update()
        except Exception as e:
            print("Arayüz güncellenemedi:", e)

    def dialog_ac(self, d):
        if not isinstance(d, getattr(ft.SnackBar, "__wrapped__", ft.SnackBar)):
            self._dialoglar = [x for x in getattr(self, "_dialoglar", []) if getattr(x, "open", True)] + [d]
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(d)
        elif hasattr(self.page, "open"):
            self.page.open(d)
        else:
            self.page.dialog = d
            d.open = True
            self.guncelle()

    def dialog_kapat(self, d=None):
        """Belirtilen (ya da en son açılan) pencereyi kapatır. Üstte bir bildirim (SnackBar) varken onu değil,
        pencerenin kendisini kapatır."""
        yigin = getattr(self, "_dialoglar", [])
        if d is None:
            d = yigin[-1] if yigin else None
        if d is not None and d in yigin:
            yigin.remove(d)
        try:
            if d is None:
                if hasattr(self.page, "pop_dialog"):
                    self.page.pop_dialog()
                return
            if hasattr(self.page, "close") and not hasattr(self.page, "show_dialog"):
                self.page.close(d)  # Flet 0.2x
                return
            d.open = False
            try:
                d.update()
            except Exception:
                self.guncelle()
        except Exception as e:
            print("Pencere kapatılamadı:", e)
            try:
                if hasattr(self.page, "pop_dialog"):
                    self.page.pop_dialog()
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

    def uyeler(self):
        return [pid for pid, p in self.profiller.items() if p.get("rol") != "yonetici"]

    def uyeye_acik(self, i, gizli_say=True):
        """Kayıt üye (Hatice) tarafından görülür mü? Sunucudaki kuralın aynısı: gelirler (kendi kasasınınkiler
        hariç) ve “Hatice'den gizle” işaretli kayıtlar dışında her şey görünür."""
        if gizli_say and i.get("gizli"):
            return False
        return i.get("tur") != "Gelir" or i.get("kasa_sahibi") in set(self.uyeler())

    def gorunur(self, kayitlar):
        """Üyede (Hatice) sunucudaki kurala ek güvence: gizli kayıtlar, başka kasaların gelirleri ve aktarımları
        hiçbir ekrana gelmez. Yöneticide olduğu gibi döner."""
        if not self.ben or self.yonetici or self.ben.get("rol") == "yonetici":
            return kayitlar or []
        ben = self.ben["id"]
        return [i for i in (kayitlar or []) if not i.get("gizli") and (i.get("tur") != "Gelir" or i.get("kasa_sahibi") == ben)]

    def rapor_kayitlari(self, kayitlar):
        """Rapor / yapay zeka bağlamı: üyede gelir kayıtları hiç yer almaz (hanenin harcama raporu)."""
        kayitlar = self.gorunur(kayitlar)
        return kayitlar if self.yonetici else [i for i in kayitlar if i.get("tur") != "Gelir"]

    def sahip_yetkili(self, x):
        """Öde / düzenle / sil / sat yetkisi: yönetici ya da kaydın kendi kasasına ait olması. Hatice başkasının
        faturasını, düzenli ödemesini, taksidini, hedefini, borcunu, varlığını görür ama değiştiremez."""
        return self.yonetici or (x or {}).get("kasa_sahibi") == (self.ben or {}).get("id")

    def fatura_yetkili(self, f):
        return self.sahip_yetkili(f)

    def sahip_etiketi(self, x):
        """Başkasının kasasına ait kayıtta sahibin adı (tek kişilik hanede boş)."""
        s = (x or {}).get("kasa_sahibi")
        return self.ad(s) if s and len(self.profiller) > 1 and s != (self.ben or {}).get("id") else None

    def salt_okunur(self, x, ne="kayıt"):
        """Yetkisiz işlem denemesinde uyarır; True dönerse işlem yapılmaz."""
        if self.sahip_yetkili(x):
            return False
        self.bildir(f"Bu {ne} {self.ad(x.get('kasa_sahibi'))} kasasına ait; yalnızca görüntüleyebilirsiniz.", GIDER)
        return True

    async def arka(self, f, *a):
        return await asyncio.to_thread(f, *a)

    # ------------------------------------------------------------ başlangıç
    async def baslat(self):
        self.govde.content = ft.Column([ft.ProgressRing(), yazi("Yükleniyor...", renk=ui.SOLUK)],
                                       horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                       alignment=ft.MainAxisAlignment.CENTER, expand=True)
        self.guncelle()
        if await self.arka(self.supa.kayitli_oturumu_ac):
            try:
                if self._yerel_ayar().get("pin") or (self._yerel_ayar().get("biyometrik") and self.yerel_kimlik is not None):
                    self.pin_ekrani(self.oturum_basla)
                else:
                    await self.oturum_basla()
                return
            except Exception as e:
                print("Kayıtlı oturum açılamadı:", e)
        self.giris_ekrani()

    def giris_ekrani(self, hata=""):
        self._hazir = False
        self.page.navigation_bar = None
        self.page.floating_action_button = None
        self.alt_menu.visible = False
        k_adi = ft.TextField(label="Kullanıcı adı", hint_text="Abdurrahman veya Hatice", autofocus=True,
                             prefix_icon=ft.Icons.PERSON_ROUNDED)
        sifre = ft.TextField(label="Şifre", password=True, can_reveal_password=True, prefix_icon=ft.Icons.LOCK_ROUNDED)
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
        kurulum_kutusu = ft.Column(spacing=10)
        self.govde.content = ft.ListView(padding=0, spacing=14, controls=[
            ft.Container(content=ft.Column([
                ft.Container(height=24),
                ft.Container(content=ft.Image(src="icon.png", width=96, height=96, border_radius=28),
                             width=96, height=96, border_radius=28, shadow=golge(1.4)),
                yazi("Hane Bütçesi", 30, True, renk="white"),
                yazi("Abdurrahman & Hatice • ortak kasa", 13, renk="#ccfbf1"),
                ft.Container(height=36)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                gradient=degrade(["#0f766e", "#0d9488", "#2dd4bf"]), bgcolor=ANA, padding=20,
                border_radius=ft.BorderRadius(0, 0, 36, 36) if hasattr(ft, "BorderRadius") else 0),
            ft.Container(content=ft.Column([
                kurulum_kutusu,
                kart(ft.Column([yazi("Giriş yap", 18, True), k_adi, sifre, hatirla,
                                buton("Giriş Yap", giris, ft.Icons.LOGIN_ROUNDED, expand=True, height=50),
                                ft.Row([bekle, hata_y])], spacing=12), dolgu=20, shadow=golge(1)),
                ft.Row([yazi(f"Sürüm {SURUM}", 11, renk=ui.SOLUK)], alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=14), padding=ft.Padding(20, 0, 20, 20)),
        ])
        self.guncelle()
        self.page.run_task(self._kurulum_kontrol, kurulum_kutusu)

    async def _kurulum_kontrol(self, kutu):
        """Şifresi henüz belirlenmemiş kullanıcı varsa giriş ekranında 'şifre belirle' seçeneği gösterir."""
        try:
            durum = await self.arka(self.supa.kurulum_durumu)
        except hb.ApiHatasi as e:
            if e.durum == 404 or "hb_kurulum_durumu" in e.mesaj:
                kutu.controls = [kart(yazi("⚠️ Veritabanı henüz kurulmamış. Supabase > SQL Editor'de "
                                           "'supabase_kurulum.sql' dosyasını bir kez çalıştırın, sonra uygulamayı "
                                           "yeniden açın.", 12, renk=GIDER), renk=ui.UYARI_ZEMIN)]
                self.guncelle()
            return
        except Exception:
            return
        eksik = [k for k, hazir in durum.items() if not hazir]
        if not eksik:
            return
        kutu.controls = [kart(ft.Column([
            ft.Row([ft.Icon(ft.Icons.KEY, color=ANA), yazi("İlk kullanım: şifrenizi belirleyin", 14, True)]),
            yazi("Şifresi henüz belirlenmemiş kullanıcılar:", 12, renk=ui.SOLUK),
            *[buton(f"{k.capitalize()} için şifre belirle", lambda e, k=k: self.sifre_belirle_ekrani(k),
                    ft.Icons.PERSON_ADD, tip="tonal", expand=True) for k in eksik],
        ], spacing=8), renk="#ccfbf1")]
        self.guncelle()

    def sifre_belirle_ekrani(self, kullanici):
        ad = kullanici.capitalize()
        s1 = ft.TextField(label="Yeni şifre (en az 6 karakter)", password=True, can_reveal_password=True,
                          autofocus=True)
        s2 = ft.TextField(label="Şifre tekrar", password=True, can_reveal_password=True)
        hata_y = yazi("", 12, renk=GIDER)
        bekle = ft.ProgressRing(visible=False, width=22, height=22)

        async def kaydet(e):
            if len(s1.value or "") < 6:
                hata_y.value = "Şifre en az 6 karakter olmalı."
            elif s1.value != s2.value:
                hata_y.value = "Şifreler aynı değil."
            else:
                hata_y.value = ""
                bekle.visible = True
                self.guncelle()
                try:
                    await self.arka(self.supa.ilk_sifre_belirle, kullanici, s1.value)
                    await self.arka(self.supa.giris, kullanici, s1.value, True)
                    self.bildir(f"Hoş geldin {ad}! Şifren kaydedildi ✓", GELIR)
                    await self.oturum_basla()
                    return
                except hb.ApiHatasi as ex:
                    hata_y.value = f"Kaydedilemedi: {ex.mesaj}"
                except Exception as ex:
                    hata_y.value = f"Kaydedilemedi: {ex}"
                bekle.visible = False
            self.guncelle()

        s2.on_submit = kaydet
        self.govde.content = ft.ListView(padding=24, spacing=14, controls=[
            ft.Container(height=30),
            ft.Row([ft.Icon(ft.Icons.LOCK_RESET, size=56, color=ANA)], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([yazi(f"{ad} için şifre belirle", 22, True)], alignment=ft.MainAxisAlignment.CENTER),
            kart(ft.Column([
                yazi(f"Bundan sonra kullanıcı adı olarak '{ad}' ve bu şifreyle giriş yapılacak.", 12, renk=ui.SOLUK),
                s1, s2, buton("Şifreyi kaydet ve giriş yap", kaydet, ft.Icons.CHECK, expand=True),
                ft.Row([bekle, hata_y]),
                buton("Geri", lambda e: self.giris_ekrani(), tip="text"),
            ], spacing=12)),
        ])
        self.guncelle()

    async def oturum_basla(self):
        try:
            profiller = await self.arka(self.supa.profiller)
            self.profiller = {p["id"]: p for p in profiller}
        except hb.ApiHatasi as e:
            o = self._yerel_oku("onbellek") or {}
            if e.durum != 0 or not o.get("profiller"):
                raise
            self.profiller = o["profiller"]
            self.cevrimdisi = True
        self.ben = self.profiller.get(self.supa.kullanici_id)
        if not self.ben:
            self.supa.cikis()
            self.giris_ekrani("Profil bulunamadı. Supabase'de 'supabase_kurulum.sql' betiğini çalıştırın.")
            return
        self.yonetici = self.ben.get("rol") == "yonetici"
        await self.ayarlari_yukle()

        self.page.navigation_bar = None
        self.page.floating_action_button = None
        self.alt_menu.visible = True
        self.alt_menu_ciz()
        self.sekme = 0
        await self.verileri_yenile(ciz=False)
        self._hazir = True
        self.ekrani_ciz()

        self.page.run_task(self.bildirim_acilis)
        self.page.run_task(self.sunucu_gorevleri)
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
            ft_ = await self.arka(self.supa.ayar_oku, "fatura_turleri")
            self.ozel_fatura_turleri = _json.loads(ft_) if ft_ else (self._yerel_ayar().get("fatura_turleri") or [])
            if self.yonetici:
                self.gizli_varsayilan = (await self.arka(self.supa.ayar_oku, "gizli_varsayilan")) == "1"
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
            self.islemler, self.bakiyeler, _, _ = await asyncio.gather(
                self.arka(self.supa.islemler, bas, bit), self.arka(self.supa.bakiyeler), self.ek_verileri_yenile(),
                self.bildirimleri_yukle())
            self.islemler = self.gorunur(self.islemler)
            onceki_cevrimdisi = self.cevrimdisi
            self.cevrimdisi = False
            if self.donem_ofset == 0:
                self.onbellege_yaz()
            if self.tum_zamanlar:
                self.tum_islemler = self.gorunur(await self.arka(self.supa.tablo, "hb_islemler",
                                                                 "select=*&order=tarih.desc,id.desc&limit=20000"))
            if self.bekleyenler:
                self.page.run_task(self.bekleyenleri_gonder)
            if getattr(self, "_hazir", False) and self.ben:
                try:
                    self.gunluk_limit_uyar()
                except Exception as e:
                    print("Günlük limit uyarısı:", e)
            elif onceki_cevrimdisi and ciz:
                self.bildir("🌐 İnternet bağlantısı geri geldi", GELIR)
        except Exception as e:
            print("Veri yenileme hatası:", e)
            if isinstance(e, hb.ApiHatasi) and e.durum == 0:
                if not self.cevrimdisi and not self.islemler:
                    self.onbellekten_oku()
                self.cevrimdisi = True
            elif ciz:
                self.bildir(f"Veriler alınamadı: {e}", GIDER)
        if ciz and (self.sekme in (0, 1, 5) or (self.sekme == 4 and self.alt_sayfa in
                                             ("faturalar", "alisveris", "butceler", "hedefler", "borclar", "varliklar", "taksitler"))):
            self.ekrani_ciz()

    async def canli_degisiklik(self, veri: dict):
        kayit = veri.get("record") or {}
        tablo = veri.get("table") or "hb_islemler"
        if tablo == "hb_bildirimler":
            if veri.get("type") == "INSERT":
                await self.yeni_bildirim(kayit)
            return
        if tablo == "hb_mesajlar":
            await self.mesaj_canli(veri)
            return
        baskasi = veri.get("type") == "INSERT" and kayit.get("ekleyen") and kayit.get("ekleyen") != self.ben["id"]
        if self.bildirim_tablosu:
            baskasi = False  # bildirimler artık sunucudan, ayrı kanaldan geliyor
        if baskasi and tablo == "hb_alisveris":
            self.bildir(f"🛒 {kayit.get('ekleyen_ad') or 'Eşiniz'} listeye ekledi: {kayit.get('urun')}")
        elif baskasi and tablo == "hb_faturalar":
            self.bildir(f"🧾 {kayit.get('ekleyen_ad') or 'Eşiniz'} {kayit.get('tur')} faturası yükledi: {hb.tl(kayit.get('tutar'))}")
        elif baskasi and tablo == "hb_islemler":
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
            if self.ben and (self.sekme in (0, 1) or self.bekleyenler or self.cevrimdisi):
                await self.verileri_yenile()

    # ------------------------------------------------------------ gezinme
    async def sekme_degisti(self, e):
        self.sekme = int(e.control.selected_index)
        if self.sekme == 4:
            self.alt_sayfa = None
        self.ekrani_ciz()

    def sekmeye_git(self, i):
        if i != 4 or not self.alt_sayfa:
            self._alt_kaynak = None
        self.sekme = i
        self.alt_menu_ciz()
        self.ekrani_ciz()


    def ekrani_ciz(self, **kw):
        if getattr(self, "_kamera_acik", False):
            return  # kamera açıkken arka plan yenilemeleri ekranı bozmasın
        if not self.ben or not getattr(self, "_hazir", False):
            return  # açılış, giriş ve kilit ekranında arka plan olayları ekranı çizmesin
        ciziciler = [self.ozet_ekrani, self.islemler_ekrani, self.ekle_ekrani, self.fis_ekrani, self.menu_ekrani,
                     self.planla_ekrani]
        self.page.bgcolor = ui.ARKA
        self._yanipsonen = []  # yanıp sönen uyarılar her çizimde yeniden toplanır
        try:
            self.govde.content = ciziciler[self.sekme](**kw)
            self._yanip_kok = self.govde.content
            if self.sekme in (0, 1, 4, 5):
                self.yenileme_bagla(self.govde.content)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.govde.content = ft.ListView(padding=16, controls=[yazi(f"Ekran hatası: {e}", renk=GIDER)])
        self.guncelle()

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

        etiket = "Bu dönem" if self.donem_ofset == 0 else ("Geçmiş dönem" if self.donem_ofset < 0 else "Gelecek dönem")
        if self.tum_zamanlar:
            ilk = min((hb.tarih_yerel(i["tarih"]).date() for i in (self.tum_islemler or [])), default=None)
            return ft.Container(content=ft.Row([
                ft.Icon(ft.Icons.ALL_INCLUSIVE_ROUNDED, color="#7c3aed"),
                ft.Column([yazi("Tüm zamanlar", 14, True),
                           yazi(f"{ilk.strftime('%d.%m.%Y')} – bugün • {len(self.tum_islemler or [])} kayıt" if ilk
                                else "Yükleniyor…", 11, renk=ui.SOLUK)], spacing=0, expand=True),
                self.tum_zamanlar_cipi()], spacing=10), bgcolor=ui.KART, border_radius=16,
                padding=ft.Padding(14, 8, 8, 8), shadow=golge(0.6))
        return ft.Row([self._donem_satiri(etiket, bas, bit, geri, ileri, bugun), self.tum_zamanlar_cipi()], spacing=8,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _donem_satiri(self, etiket, bas, bit, geri, ileri, bugun):
        return ft.Container(content=ft.Row([
            ft.IconButton(icon=ft.Icons.CHEVRON_LEFT_ROUNDED, on_click=geri, tooltip="Önceki dönem"),
            ft.Column([yazi(etiket, 10.5, renk=ui.SOLUK), yazi(hb.donem_etiketi(bas, bit), 13.5, "sb")],
                      spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True),
            ft.IconButton(icon=ft.Icons.TODAY_ROUNDED, on_click=bugun, tooltip="Bu döneme dön",
                          visible=self.donem_ofset != 0, icon_color=ANA),
            ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, on_click=ileri, tooltip="Sonraki dönem"),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=0), bgcolor=ui.KART, border_radius=16, padding=2,
            shadow=None if ui.KOYU else golge(0.4), border=ui.kenar() if ui.KOYU else None, expand=True)


    def islem_satiri(self, i, tarih_goster=True):
        tur = i.get("tur")
        simge, renk = kat_stil(i.get("kategori"), tur)
        if tur == "Gelir":
            isaret, tutar_renk = "+", GELIR
        elif tur == "Gider":
            isaret, tutar_renk = "-", ui.YAZI
        else:
            tutar_renk = AKTARIM
            isaret = "+" if (not self.yonetici and i.get("hedef_kasa") == self.ben["id"]) else ("-" if not self.yonetici else "")
        if tur == "Aktarım":
            baslik = f"{self.ad(i.get('kasa_sahibi'))} ➜ {self.ad(i.get('hedef_kasa'))}"
            alt = [i.get("aciklama") or "Para aktarımı"]
        else:
            baslik = i.get("urun") or i.get("kategori") or tur
            alt = [i.get("firma"), i.get("kategori") if tur == "Gider" else (i.get("kategori") or "Gelir")]
        d = hb.tarih_yerel(i.get("tarih"))
        alt.append(d.strftime("%d.%m %H:%M") if tarih_goster else d.strftime("%H:%M"))
        kr = self.kisi_renk(i.get("ekleyen")) if i.get("ekleyen") in self.profiller else ui.CIZGI
        etiketler = [ft.Icon(ft.Icons.PERSON_ROUNDED, size=12, color=kr if kr != ui.CIZGI else ui.SOLUK),
                     yazi(i.get("ekleyen_ad") or "?", 10.5, renk=ui.SOLUK)]
        if len(self.profiller) > 1 and tur != "Aktarım":
            etiketler += [ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, size=12, color=ui.SOLUK),
                          yazi(self.ad(i.get("kasa_sahibi")), 10.5, renk=ui.SOLUK)]
        if i.get("fis_gorsel"):
            etiketler.append(ft.Icon(ft.Icons.RECEIPT_ROUNDED, size=12, color=ANA))
        if i.get("gizli"):
            etiketler += [ft.Icon(ft.Icons.LOCK_ROUNDED, size=12, color="#b45309"), yazi("Gizli", 10.5, renk="#b45309")]
        return ft.Container(
            content=ft.Row([
                ft.Container(width=4, height=40, border_radius=2, bgcolor=kr),
                simge_kutusu(simge, renk),
                ft.Column([yazi(baslik, 14, True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                           yazi(" • ".join(x for x in alt if x), 11, renk=ui.SOLUK, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                           ft.Row(etiketler, spacing=3)], spacing=1, expand=True),
                yazi(f"{isaret}{hb.tl(i.get('tutar'))}", 14, True, renk=tutar_renk),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            bgcolor=ui.KART, padding=12, border_radius=18, shadow=None if ui.KOYU else golge(0.4),
            border=ui.kenar() if ui.KOYU else None,
            on_click=(lambda e, i=i: self.islem_detay(i)) if i.get("id") != -1 else None)

    def ozet_ekrani(self):
        bas, bit = self.donem
        canli = self.canli and self.canli.bagli
        bak = {b["kisi"]: float(b.get("bakiye") or 0) for b in self.bakiyeler}
        saat = hb.simdi().hour
        selam = "Günaydın" if 5 <= saat < 12 else ("İyi günler" if 12 <= saat < 18 else "İyi akşamlar")

        ust = ft.Row([
            self.kisi_rozeti(self.ben["id"], boyut=44),
            ft.Column([yazi(selam, 12.5, renk=ui.SOLUK), yazi(self.ben["ad"], 19, "xb")], spacing=0, expand=True),
            ft.Container(content=ft.Row([ft.Icon(ft.Icons.CIRCLE, size=8, color=GELIR if canli else "#94a3b8"),
                                         yazi("Canlı" if canli else "Bağlanıyor", 11, renk=ui.SOLUK)], spacing=5, tight=True),
                         padding=ft.Padding(10, 6, 10, 6), border_radius=20, border=ui.kenar(),
                         tooltip="Dokunun ya da ekranı aşağı çekin: yenile", on_click=self.cekip_yenile),
            *([self.sohbet_dugmesi()] if len(self.profiller) > 1 else []),
            self.zil_dugmesi(),
        ], spacing=10)

        # --- Kasa kartı (iki temada da koyu lacivert: “Gece” imzası) ---
        acik_yazi, soluk = "#e8edf5", ui.KASA_SOLUK
        if self.yonetici:
            toplam = sum(bak.values())
            kasalar = [self._mini_kasa(self.ad(pid), deger, pid) for pid, deger in bak.items()]
            kasa_icerik = [ft.Row([yazi("TOPLAM KASA", 12, "sb", renk=soluk, expand=True),
                                   yazi("Geçmiş ›", 12, "sb", renk="#5eead4")]),
                           ui.para(toplam, 40, acik_yazi, soluk),
                           ft.Row(kasalar, spacing=10)]
            hs = self.harcanabilir_satiri(None)
            if hs:
                kasa_icerik.append(hs)
        else:
            kasa_icerik = [ft.Row([yazi("KASAM", 12, "sb", renk=soluk, expand=True),
                                   yazi("Bana gelenler ›", 12, "sb", renk="#5eead4")]),
                           ui.para(bak.get(self.ben["id"], 0), 40, acik_yazi, soluk)]
            hs = self.harcanabilir_satiri(self.ben["id"])
            if hs:
                kasa_icerik.append(hs)
        kasa_karti = ft.Container(content=ft.Column(kasa_icerik, spacing=12), padding=20, border_radius=26,
                                  bgcolor=ui.KASA_ZEMIN, border=ui.kenar() if ui.KOYU else None,
                                  shadow=None if ui.KOYU else golge(1.2),
                                  on_click=lambda e: self.kasa_ac(self.ben["id"]), tooltip="Kasa hareketleri")

        tum = self.tum_zamanlar and self.tum_islemler is not None
        kaynak = self.tum_islemler if tum else self.islemler
        oz = hb.donem_ozeti(kaynak, None)  # hane harcamaları (üyeye başka kasaların gelirleri hiç gelmez)
        oz_ben = oz if self.yonetici else hb.donem_ozeti(kaynak, self.ben["id"])
        ek_kartlar = []
        if self.cevrimdisi or self.bekleyenler:
            ek_kartlar.append(kart(ft.Row([
                ft.Icon(ft.Icons.CLOUD_OFF_ROUNDED, color="#b45309"),
                yazi(("İnternet yok – son kaydedilen veriler gösteriliyor. " if self.cevrimdisi else "") +
                     (f"⏳ {len(self.bekleyenler)} kayıt bağlantı gelince gönderilecek." if self.bekleyenler else
                      "Yeni kayıtlarınız telefonda bekletilir."), 12, renk="#b45309", expand=True)], spacing=10),
                renk=ui.UYARI_ZEMIN, dolgu=12))
        butce_kartlari = []
        for pid in ([self.ben["id"]] if not self.yonetici else list(self.profiller)):
            kb = self.kisi_butce_karti(pid)
            if kb:
                butce_kartlari.append(kb)
        try:
            gk = None if tum else self.gunluk_limit_karti()
        except Exception as e:
            print("Günlük limit kartı:", e)
            gk = None
        kontroller = [ust, *ek_kartlar, kasa_karti, *([gk] if gk else []), *butce_kartlari, *self.ozet_ekleri(),
                      self.donem_cubugu()]

        if self.yonetici:
            kontroller.append(ft.Row([
                self._ozet_kutu("Gelir", oz["gelir"], GELIR, ft.Icons.SOUTH_WEST_ROUNDED),
                self._ozet_kutu("Gider", oz["gider"], GIDER, ft.Icons.NORTH_EAST_ROUNDED),
                self._ozet_kutu("Net", oz["net"], ANA if oz["net"] >= 0 else GIDER, ft.Icons.BALANCE_ROUNDED),
            ], spacing=8))
        else:
            kontroller.append(ft.Row([
                self._ozet_kutu("Hane gideri", oz["gider"], GIDER, ft.Icons.HOME_ROUNDED),
                self._ozet_kutu("Benim giderim", oz_ben["gider"], self.kisi_renk(self.ben["id"]), ft.Icons.PERSON_ROUNDED),
            ], spacing=8))

        # --- Harcama temposu + günlük grafik ---
        bugun = hb.simdi().date()
        toplam_gun = (bit - bas).days + 1
        gecen_gun = min(max((bugun - bas).days + 1, 1), toplam_gun) if bugun >= bas else 0
        gunluk = {}
        for i in self.islemler:
            if i.get("tur") != "Gider":
                continue
            g = hb.tarih_yerel(i.get("tarih")).date()
            gunluk[g] = gunluk.get(g, 0) + float(i.get("tutar") or 0)
        if gecen_gun and not tum:
            ort = oz["gider"] / gecen_gun
            tahmin = ort * toplam_gun
            gelir_var = self.yonetici and oz["gelir"]
            oran = (oz["gider"] / oz["gelir"]) if gelir_var else None
            tempo = [
                ft.Row([yazi("Harcama temposu", 15, True, expand=True),
                        yazi(f"{gecen_gun}/{toplam_gun}. gün", 11, renk=ui.SOLUK)]),
                ft.Row([
                    ft.Stack([ft.ProgressRing(value=min(gecen_gun / toplam_gun, 1), width=58, height=58,
                                              stroke_width=6, color=ANA, bgcolor=ui.CIZGI),
                              ft.Container(content=yazi(f"%{int(100 * gecen_gun / toplam_gun)}", 12, True),
                                           width=58, height=58, alignment=ORTA)], width=58, height=58),
                    ft.Column([
                        ft.Row([yazi("Günlük ortalama", 12, renk=ui.SOLUK, expand=True), yazi(hb.tl(ort), 13, True)]),
                        ft.Row([yazi("Dönem sonu tahmini", 12, renk=ui.SOLUK, expand=True),
                                yazi(hb.tl(tahmin), 13, True, renk=GIDER if gelir_var and tahmin > oz["gelir"] else ui.YAZI)]),
                        *([ft.Row([yazi("Gelirin harcanan kısmı", 12, renk=ui.SOLUK, expand=True),
                                   yazi(f"%{int(oran * 100)}" if oran is not None else "—", 13, True,
                                        renk=GIDER if oran and oran > 0.9 else ui.YAZI)])] if self.yonetici else
                          [ft.Row([yazi("Benim payım", 12, renk=ui.SOLUK, expand=True),
                                   yazi(f"%{int(100 * oz_ben['gider'] / oz['gider'])}" if oz["gider"] else "—", 13,
                                        True)])]),
                    ], spacing=4, expand=True),
                ], spacing=14),
            ]
            enb = max(gunluk.values()) if gunluk else 0
            if enb:
                cubuklar = []
                for n in range(toplam_gun):
                    g = bas + dt.timedelta(days=n)
                    v = gunluk.get(g, 0)
                    cubuklar.append(ft.Container(
                        expand=1, height=max(3, 70 * v / enb) if v else 3, border_radius=3,
                        bgcolor=(ANA if g == bugun else "#5eead4") if v else ui.CIZGI,
                        tooltip=f"{g.day} {hb.AYLAR[g.month - 1]}: {hb.tl(v)}"))
                tempo += [ft.Container(height=4),
                          ft.Row(cubuklar, spacing=2, vertical_alignment=ft.CrossAxisAlignment.END, height=72),
                          ft.Row([yazi(f"{bas.day} {hb.AYLAR[bas.month - 1]}", 10, renk=ui.SOLUK, expand=True),
                                  yazi(f"{bit.day} {hb.AYLAR[bit.month - 1]}", 10, renk=ui.SOLUK)])]
            kontroller.append(kart(ft.Column(tempo, spacing=8), dolgu=16, shadow=golge(0.6)))
        if not tum and self.islemler:
            try:
                kontroller.append(self.takvim_karti())
            except Exception as e:
                print("Takvim çizilemedi:", e)

        if not self.yonetici and (oz_ben["aktarim_giris"] or oz_ben["aktarim_cikis"]):
            kontroller.append(kart(ft.Row([
                simge_kutusu(ft.Icons.SWAP_HORIZ_ROUNDED, AKTARIM, kutu=34, boyut=18),
                yazi("Aktarımlar", 13, True, expand=True),
                yazi(f"+{hb.tl(oz_ben['aktarim_giris'])}", 12, True, renk=GELIR),
                yazi(f"-{hb.tl(oz_ben['aktarim_cikis'])}", 12, True, renk=GIDER)], spacing=10), shadow=golge(0.5)))

        if len(self.profiller) > 1:
            satirlar = [yazi("Kim ne harcadı?", 15, True)]
            toplam_g = sum(hb.donem_ozeti(kaynak, p)["gider"] for p in self.profiller) or 1
            for pid in self.profiller:
                o = hb.donem_ozeti(kaynak, pid)
                kr = self.kisi_renk(pid)
                satirlar.append(ft.Column([
                    ft.Row([self.kisi_rozeti(pid, boyut=22), yazi(self.ad(pid), 13, True, expand=True),
                            yazi(hb.tl(o["gider"]), 13, True)]),
                    ft.ProgressBar(value=o["gider"] / toplam_g, color=kr, bgcolor=ui.CIZGI, height=6,
                                   border_radius=3) if _param_var(ft.ProgressBar, "border_radius")
                    else ft.ProgressBar(value=o["gider"] / toplam_g, color=kr, bgcolor=ui.CIZGI),
                ], spacing=4))
            kontroller.append(kart(ft.Column(satirlar, spacing=10), dolgu=16, shadow=golge(0.5)))

        halka = self.halka_karti(oz["kategoriler"]) if oz["kategoriler"] else None
        if halka:
            kontroller.append(halka)
        if oz["kategoriler"] and (tum or not halka):
            toplam_kat = sum(oz["kategoriler"].values()) or 1
            kat_sat = [ft.Row([yazi("Kategoriler", 15, True, expand=True), yazi(f"{len(oz['kategoriler'])} kategori", 11, renk=ui.SOLUK)])]
            for k, v in list(oz["kategoriler"].items())[:8]:
                simge, renk = kat_stil(k)
                kat_sat.append(ft.Row([
                    simge_kutusu(simge, renk, boyut=17, kutu=34),
                    ft.Column([
                        ft.Row([yazi(k, 12.5, True, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                yazi(hb.tl(v), 12.5, True)]),
                        ft.Row([ft.Row([ft.Container(bgcolor=renk, border_radius=3, height=6,
                                                     expand=max(1, int(1000 * v / toplam_kat))),
                                        ft.Container(bgcolor=ui.ZEMIN2, border_radius=3, height=6,
                                                     expand=max(1, 1000 - int(1000 * v / toplam_kat)))],
                                       spacing=0, expand=True),
                                yazi(f"%{round(100 * v / toplam_kat)}", 10.5, renk=ui.SOLUK, width=34,
                                     text_align=ft.TextAlign.RIGHT)], spacing=6),
                    ], spacing=3, expand=True),
                ], spacing=10))
            kontroller.append(kart(ft.Column(kat_sat, spacing=12), dolgu=16, shadow=golge(0.5)))

        kontroller.append(ft.Row([yazi("Son işlemler", 16, True, expand=True),
                                  buton("Tümü", lambda e: self.sekmeye_git(1), tip="text")]))
        son = grupla(self.bekleyen_satirlari() + (kaynak if tum else self.islemler))[:8]
        if son:
            kontroller += [self.liste_ogesi(x) for x in son]
        else:
            kontroller.append(kart(ft.Column([
                ft.Icon(ft.Icons.INBOX_ROUNDED, size=40, color="#cbd5e1"),
                yazi("Bu dönemde henüz kayıt yok", 14, True),
                yazi("Sağ alttaki düğmeyle fişinizi tarayın ya da 'Ekle' sekmesinden kayıt girin.", 12, renk=ui.SOLUK,
                     text_align=ft.TextAlign.CENTER)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
                dolgu=24))
        kontroller.append(ft.Container(height=70))
        return ft.ListView(padding=16, spacing=12, controls=kontroller, expand=True)


    def _mini_kasa(self, ad, deger, pid=None):
        return ft.Container(content=ft.Column([
            ft.Row([ft.Container(width=8, height=8, border_radius=4, bgcolor=self.kisi_renk(pid) if pid else "white"),
                    yazi(ad, 11.5, "sb", renk="#cbd5e1")], spacing=6),
            yazi(hb.tl(deger), 16, "xb", renk="#e8edf5")], spacing=3), bgcolor=ui.KASA_IC, padding=12, border_radius=16,
            expand=True, on_click=(lambda e: self.kasa_ac(pid)) if pid else None)


    def _ozet_kutu(self, baslik, deger, renk, simge):
        renk = {GELIR: ui.GELIR_Y, GIDER: ui.GIDER_Y, ANA: ui.YAZI}.get(renk, renk)
        return kart(ft.Column([
            ft.Row([ft.Icon(simge, color=renk, size=15), yazi(baslik, 11.5, renk=ui.SOLUK)], spacing=4),
            yazi(hb.tl(deger).replace(",00 ₺", " ₺"), 14.5, "xb", renk=renk, max_lines=1)], spacing=4),
            dolgu=12, expand=True, shadow=golge(0.4), border_radius=18)

    def islemler_ekrani(self):
        liste = ft.Column(spacing=8)
        cipler = ft.Row(spacing=6, wrap=True)
        kasa_cipleri = ft.Row(spacing=6, wrap=True)

        def doldur():
            f = self.filtre
            ara = hb.urun_anahtari(f["arama"])
            sonuc = []
            kid = next((p for p, v in self.profiller.items() if v["ad"] == f["kasa"]), None)
            for i in (self.tum_islemler if self.tum_zamanlar and self.tum_islemler is not None else self.islemler):
                if f["tur"] != "Tümü" and i.get("tur") != f["tur"]:
                    continue
                if kid and i.get("kasa_sahibi") != kid and i.get("hedef_kasa") != kid:
                    continue
                if ara:
                    metin = hb.urun_anahtari(" ".join(str(i.get(k) or "") for k in
                                                      ("urun", "firma", "kategori", "aciklama", "ekleyen_ad")))
                    if ara not in metin:
                        continue
                sonuc.append(i)
            gider = sum(float(x.get("tutar") or 0) for x in sonuc if x.get("tur") == "Gider")
            gelir = sum(float(x.get("tutar") or 0) for x in sonuc if x.get("tur") == "Gelir")
            ogeler = [ft.Row([yazi(f"{len(sonuc)} kayıt", 12, renk=ui.SOLUK, expand=True),
                              yazi(f"+{hb.tl(gelir)}", 12, True, renk=GELIR),
                              yazi(f"-{hb.tl(gider)}", 12, True, renk=GIDER)], spacing=10)]
            # günlere böl, her günün içinde fişleri grupla
            gunler = {}
            for i in sonuc:
                gunler.setdefault(hb.tarih_yerel(i.get("tarih")).date(), []).append(i)
            sayac = 0
            for g in sorted(gunler, reverse=True):
                satirlar = gunler[g]
                g_gider = sum(float(x.get("tutar") or 0) for x in satirlar if x.get("tur") == "Gider")
                ogeler.append(ft.Container(content=ft.Row([
                    yazi(gun_basligi(g), 13, True, renk=ui.SOLUK, expand=True),
                    yazi(f"-{hb.tl(g_gider)}" if g_gider else "", 12, True, renk=ui.SOLUK)]), padding=ft.Padding(4, 10, 4, 0)))
                for x in grupla(satirlar):
                    ogeler.append(self.liste_ogesi(x, tarih_goster=False))
                    sayac += 1
                if sayac > 300:
                    ogeler.append(yazi("… daha eski kayıtlar için aramayı daraltın", 12, renk=ui.SOLUK))
                    break
            if not sonuc:
                ogeler.append(kart(ft.Column([ft.Icon(ft.Icons.SEARCH_OFF_ROUNDED, size=36, color="#cbd5e1"),
                                              yazi("Kayıt bulunamadı", 13, renk=ui.SOLUK)],
                                             horizontal_alignment=ft.CrossAxisAlignment.CENTER), dolgu=24))
            liste.controls = ogeler
            cipler.controls = [cip(t, f["tur"] == t, lambda e, t=t: sec("tur", t),
                                   {"Gider": GIDER, "Gelir": GELIR, "Aktarım": AKTARIM}.get(t, ANA))
                               for t in ("Tümü", "Gider", "Gelir", "Aktarım")]
            kasa_cipleri.controls = [cip(k, f["kasa"] == k, lambda e, k=k: sec("kasa", k), "#475569",
                                         ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED if k != "Hepsi" else None)
                                     for k in ["Hepsi"] + [p["ad"] for p in self.profiller.values()]]

        def sec(alan, deger):
            self.filtre[alan] = deger
            doldur()
            self.guncelle()

        def arama_degisti(e):
            self.filtre["arama"] = e.control.value or ""
            doldur()
            self.guncelle()

        arama = ft.TextField(value=self.filtre["arama"], hint_text="Ürün, market, kategori, kişi ara…",
                             prefix_icon=ft.Icons.SEARCH_ROUNDED, on_change=arama_degisti, bgcolor=ui.KART,
                             border_radius=16, border_color="transparent", dense=True)
        doldur()
        ust = [self.donem_cubugu(), ft.Container(content=arama, shadow=golge(0.4), border_radius=16), cipler]
        if len(self.profiller) > 1:
            ust.append(kasa_cipleri)
        return ft.ListView(padding=16, spacing=10, expand=True, controls=ust + [liste, ft.Container(height=70)])

    def fis_karti(self, satirlar, tarih_goster=True):
        ilk = satirlar[0]
        toplam = sum(float(x.get("tutar") or 0) for x in satirlar)
        kat = {}
        for x in satirlar:
            kat[x.get("kategori") or "Diğer"] = kat.get(x.get("kategori") or "Diğer", 0) + float(x.get("tutar") or 0)
        ana_kat = max(kat, key=kat.get)
        d = hb.tarih_yerel(ilk.get("tarih"))
        renkli = ft.Row([ft.Container(width=max(4, int(64 * v / (toplam or 1))), height=5, border_radius=3,
                                      bgcolor=kat_stil(k)[1]) for k, v in sorted(kat.items(), key=lambda kv: -kv[1])[:6]],
                        spacing=2)
        etiketler = [ft.Icon(ft.Icons.PERSON_ROUNDED, size=12, color=ui.SOLUK), yazi(ilk.get("ekleyen_ad") or "?", 10.5, renk=ui.SOLUK)]
        if len(self.profiller) > 1:
            etiketler += [ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, size=12, color=ui.SOLUK),
                          yazi(self.ad(ilk.get("kasa_sahibi")), 10.5, renk=ui.SOLUK)]
        if any(x.get("gizli") for x in satirlar):
            etiketler += [ft.Icon(ft.Icons.LOCK_ROUNDED, size=12, color="#b45309")]
        return ft.Container(
            content=ft.Row([
                simge_kutusu(ft.Icons.RECEIPT_LONG_ROUNDED, ANA),
                ft.Column([
                    yazi(ilk.get("firma") or "Fiş", 14, True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    yazi(f"{len(satirlar)} ürün • {ana_kat} • " +
                         (d.strftime("%d.%m %H:%M") if tarih_goster else d.strftime("%H:%M")), 11, renk=ui.SOLUK,
                         max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row([renkli, *etiketler], spacing=4),
                ], spacing=2, expand=True),
                ft.Column([yazi(f"-{hb.tl(toplam)}", 14, True),
                           ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=16, color=ui.SOLUK)],
                          horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            bgcolor=ui.KART, padding=12, border_radius=16, shadow=golge(0.5),
            on_click=lambda e, s=satirlar: self.fis_detay(s))

    def fis_detay(self, satirlar):
        ilk = satirlar[0]
        toplam = sum(float(x.get("tutar") or 0) for x in satirlar)
        d = ft.AlertDialog()

        def ac(i):
            self.dialog_kapat(d)
            self.islem_detay(i)

        liste = []
        for x in sorted(satirlar, key=lambda s: -float(s.get("tutar") or 0)):
            simge, renk = kat_stil(x.get("kategori"))
            liste.append(ft.Container(content=ft.Row([
                ft.Icon(simge, color=renk, size=18),
                ft.Column([yazi(x.get("urun") or "-", 13, max_lines=2),
                           yazi(" • ".join(v for v in [x.get("miktar"), x.get("kategori")] if v), 10.5, renk=ui.SOLUK)],
                          spacing=0, expand=True),
                yazi(hb.tl(x.get("tutar")), 13, True)], spacing=8), padding=6, border_radius=10,
                on_click=lambda e, i=x: ac(i)))

        async def gorsel(e):
            self.dialog_kapat(d)
            await self.fis_gorseli_goster(ilk.get("fis_gorsel"))

        async def tumunu_sil(e):
            self.dialog_kapat(d)
            try:
                if ilk.get("fis_grup"):
                    await self.arka(self.supa.fis_grubu_sil, ilk["fis_grup"])
                else:
                    for x in satirlar:
                        await self.arka(self.supa.islem_sil, x["id"])
                self.bildir("Fiş silindi.")
                await self.verileri_yenile()
            except Exception as ex:
                self.bildir(f"Silinemedi: {ex}", GIDER)

        def sil_onay(e):
            async def evet(ev):
                self.dialog_kapat(o)
                await tumunu_sil(ev)
            o = ft.AlertDialog(title=yazi("Fiş silinsin mi?", 16, True),
                               content=yazi(f"{len(satirlar)} ürün ({hb.tl(toplam)}) silinecek."),
                               actions=[buton("Vazgeç", lambda ev: self.dialog_kapat(o), tip="text"), buton("Sil", evet)])
            self.dialog_kapat(d)
            self.dialog_ac(o)

        d.title = ft.Column([yazi(ilk.get("firma") or "Fiş", 18, True),
                             yazi(f"{hb.tarih_goster(ilk.get('tarih'))} • {len(satirlar)} ürün • {ilk.get('ekleyen_ad') or ''}",
                                  12, renk=ui.SOLUK)], spacing=2, tight=True)
        d.content = ft.Container(content=ft.Column(liste + [ft.Divider(), ft.Row(
            [yazi("Toplam", 14, True, expand=True), yazi(hb.tl(toplam), 16, True, renk=ANA)])],
            scroll=ft.ScrollMode.AUTO, tight=True, spacing=2), width=380)
        eylemler = []
        if ilk.get("fis_gorsel"):
            eylemler.append(buton("Fişi gör", gorsel, ft.Icons.IMAGE_ROUNDED, tip="text"))
        if self.yonetici and self.uyeler() and ilk.get("id") not in (None, -1) and \
                all(self.uyeye_acik(x, gizli_say=False) for x in satirlar):
            hepsi_gizli = all(x.get("gizli") for x in satirlar)

            async def gizlilik(e):
                self.dialog_kapat(d)
                await self.gizlilik_degistir(satirlar, not hepsi_gizli)
            eylemler.append(buton("Göster" if hepsi_gizli else "Gizle", gizlilik,
                                  ft.Icons.LOCK_OPEN_ROUNDED if hepsi_gizli else ft.Icons.LOCK_ROUNDED, tip="text"))
        if all(self.izinli(x) for x in satirlar):
            eylemler.append(buton("Fişi sil", sil_onay, ft.Icons.DELETE_ROUNDED, tip="text"))
        if len(self.profiller) > 1 and ilk.get("id") not in (None, -1):
            def yorum(e):
                self.dialog_kapat(d)
                self.yorum_yaz(dict(ilk, tutar=sum(float(x.get("tutar") or 0) for x in satirlar),
                                    urun=f"Fiş ({len(satirlar)} kalem)"))
            eylemler.insert(0, buton("Yorum yaz", yorum, ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED, tip="text"))
        eylemler.append(buton("Kapat", lambda e: self.dialog_kapat(d), tip="text"))
        d.actions = eylemler
        self.dialog_ac(d)

    def liste_ogesi(self, x, tarih_goster=True):
        return self.fis_karti(x, tarih_goster) if isinstance(x, list) else self.islem_satiri(x, tarih_goster)

    def _buyuk_secenek(self, simge, baslik, aciklama, on_click, renk, vurgulu=False):
        return ft.Container(content=ft.Row([
            ft.Container(content=ft.Icon(simge, color="white" if vurgulu else renk, size=28),
                         bgcolor=renk if vurgulu else saydam(renk), width=56, height=56, border_radius=18, alignment=ORTA),
            ft.Column([yazi(baslik, 15, True), yazi(aciklama, 11.5, renk=ui.SOLUK)], spacing=2, expand=True),
            ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=ui.SOLUK)], spacing=14),
            bgcolor=ui.KART, padding=14, border_radius=20, shadow=golge(0.6), on_click=on_click)

    async def kamera_ekrani(self, mod="fis"):
        """Uygulama içi kamera: çok sayfalı çekim, flaş, önizleme; bitince yapay zeka analizine gönderir."""
        try:
            import flet_camera as fc
        except Exception:
            self.bildir("Kamera bileşeni bu sürümde yok; galeriden seçin.", GIDER)
            return
        fotolar: list[bytes] = []
        durum = {"flas": False, "hazir": False, "cekiliyor": False}
        bilgi = yazi("Kamera açılıyor…", 13, True, renk="white", text_align=ft.TextAlign.CENTER)
        kam = fc.Camera(expand=True, preview_enabled=True)
        kucukler = ft.Row(spacing=8, scroll=ft.ScrollMode.AUTO)
        devam_btn = ft.Container(content=ft.Row([yazi("Devam", 14, True, renk="white"),
                                                 ft.Icon(ft.Icons.ARROW_FORWARD_ROUNDED, color="white", size=18)],
                                                spacing=4, tight=True),
                                 bgcolor=ANA, border_radius=24, padding=ft.Padding(16, 12, 16, 12), visible=False)
        flas_btn = ft.IconButton(icon=ft.Icons.FLASH_OFF_ROUNDED, icon_color="white", tooltip="Flaş")

        def ui_yenile():
            devam_btn.visible = bool(fotolar)
            devam_btn.content.controls[0].value = f"Devam ({len(fotolar)})" if len(fotolar) > 1 else "Devam"
            kucukler.controls = []
            for n, b in enumerate(fotolar):
                kucukler.controls.append(ft.Stack([
                    ft.Image(src=b, width=48, height=64, border_radius=8),
                    ft.Container(content=ft.Icon(ft.Icons.CLOSE_ROUNDED, size=12, color="white"), bgcolor="#cc000000",
                                 width=18, height=18, border_radius=9, right=0, top=0, alignment=ORTA,
                                 on_click=lambda e, n=n: sil(n))], width=48, height=64))
            if durum["hazir"]:
                bilgi.value = ("Fişi çerçeveye sığdırıp çekin" if not fotolar else
                               f"{len(fotolar)} sayfa çekildi • fişin devamı varsa tekrar çekin")
            self.guncelle()

        def sil(n):
            if 0 <= n < len(fotolar):
                fotolar.pop(n)
                ui_yenile()

        async def cek(e):
            if not durum["hazir"] or durum["cekiliyor"]:
                return
            durum["cekiliyor"] = True
            bilgi.value = "Çekiliyor…"
            self.guncelle()
            try:
                veri = await kam.take_picture()
                if veri:
                    fotolar.append(bytes(veri) if not isinstance(veri, str) else __import__("base64").b64decode(veri))
            except Exception as ex:
                self.bildir(f"Fotoğraf çekilemedi: {ex}", GIDER)
            durum["cekiliyor"] = False
            ui_yenile()

        async def flas(e):
            try:
                mod = getattr(fc, "FlashMode", None)
                if mod is None:
                    return
                durum["flas"] = not durum["flas"]
                await kam.set_flash_mode(getattr(mod, "TORCH") if durum["flas"] else getattr(mod, "OFF"))
                flas_btn.icon = ft.Icons.FLASH_ON_ROUNDED if durum["flas"] else ft.Icons.FLASH_OFF_ROUNDED
                flas_btn.icon_color = "#fde047" if durum["flas"] else "white"
                self.guncelle()
            except Exception as ex:
                self.bildir(f"Flaş kullanılamıyor: {ex}")

        def kapat(e=None):
            self._kamera_kapat()
            self.ekrani_ciz()

        async def galeri(e):
            self._kamera_kapat()
            self.ekrani_ciz()
            if mod == "fatura":
                await self.fatura_sec("resim")
            elif mod == "ekstre":
                veri = await self.dosya_sec("resim")
                if veri:
                    await self.ekstre_isle(veri, "resim")
            else:
                await self.fis_sec("resim")

        async def devam(e):
            if not fotolar:
                return
            secilen = list(fotolar)
            self._kamera_kapat()
            birlesik = await self.arka(hb.gorselleri_birlestir, secilen)
            if mod == "fatura":
                self.ekrani_ciz()
                await self.fatura_isle(birlesik, "resim")
            elif mod == "ekstre":
                self.ekrani_ciz()
                await self.ekstre_isle(birlesik, "resim")
            else:
                await self.fis_isle(birlesik, "resim")

        flas_btn.on_click = flas
        devam_btn.on_click = devam
        deklansor = ft.Container(content=ft.Container(bgcolor="white", width=60, height=60, border_radius=30),
                                 width=76, height=76, border_radius=38, bgcolor="#55ffffff", alignment=ORTA,
                                 on_click=cek)
        cerceve = ft.Container(border=ft.Border.all(2, "#ccffffff") if hasattr(ft, "Border") and hasattr(ft.Border, "all")
                               else ft.border.all(2, "#ccffffff"), border_radius=16, left=24, right=24, top=90, bottom=190)
        ust_bar = ft.Container(content=ft.Row([
            ft.IconButton(icon=ft.Icons.CLOSE_ROUNDED, icon_color="white", on_click=kapat, tooltip="Kapat"),
            ft.Container(content=bilgi, expand=True),
            flas_btn]), top=0, left=0, right=0, padding=ft.Padding(8, 8, 8, 8), bgcolor="#66000000")
        alt_bar = ft.Container(content=ft.Column([
            kucukler,
            ft.Row([ft.IconButton(icon=ft.Icons.PHOTO_LIBRARY_ROUNDED, icon_color="white", icon_size=28,
                                  on_click=galeri, tooltip="Galeriden seç"),
                    deklansor, devam_btn], alignment=ft.MainAxisAlignment.SPACE_AROUND,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER)], spacing=10),
            bottom=0, left=0, right=0, padding=ft.Padding(12, 10, 12, 24), bgcolor="#88000000")

        self._kamera_acik = True
        self.alt_menu.visible = False
        self.govde.content = ft.Container(bgcolor="black", expand=True,
                                          content=ft.Stack([ft.Container(content=kam, left=0, right=0, top=0, bottom=0),
                                                           cerceve, ust_bar, alt_bar], expand=True))
        self.guncelle()
        try:
            await asyncio.sleep(0.3)  # önizleme yüzeyi sayfaya yerleşsin
            kameralar = await kam.get_available_cameras()
            if not kameralar:
                raise RuntimeError("Cihazda kamera bulunamadı")
            arka = next((c for c in kameralar if "back" in str(getattr(c, "lens_direction", "")).lower()), kameralar[0])
            rp = fc.ResolutionPreset
            preset = getattr(rp, "VERY_HIGH", None) or getattr(rp, "HIGH", None) or getattr(rp, "MEDIUM")
            ifg = getattr(getattr(fc, "ImageFormatGroup", None), "JPEG", None)
            try:
                await kam.initialize(description=arka, resolution_preset=preset, enable_audio=False,
                                     image_format_group=ifg)
            except TypeError:
                await kam.initialize(arka, preset)
            durum["hazir"] = True
            ui_yenile()
        except Exception as ex:
            m = str(ex)
            if "ccess" in m or "ermission" in m or "izin" in m.lower():
                bilgi.value = "Kamera izni verilmedi. Telefon Ayarları > Uygulamalar > Hane Bütçesi > İzinler'den kameraya izin verin."
            else:
                bilgi.value = f"Kamera açılamadı: {m}"
            self.guncelle()

    def _kamera_kapat(self):
        self._kamera_acik = False
        self.alt_menu.visible = bool(self.ben)

    async def hizli_fis(self, e=None):
        self.sekmeye_git(3)
        if self.fis is None:
            if self.mobil:
                await self.kamera_ekrani()
            else:
                await self.fis_sec("resim")

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
        if self.yonetici and self.uyeler():
            satirlar.append(("Görünürlük", "🔒 Hatice'den gizli" if i.get("gizli") else "Hatice görebilir"
                             if self.uyeye_acik(i) else "Hatice görmez (gelir)"))
        satirlar += [("Not", i.get("aciklama")), ("Ekleyen", i.get("ekleyen_ad")),
                     ("Eklenme", hb.tarih_goster(i.get("olusturma")))]
        if i.get("fis_grup"):
            ayni = [x for x in self.islemler if x.get("fis_grup") == i.get("fis_grup")]
            satirlar.append(("Fiş", f"{len(ayni)} ürün • {hb.tl(sum(float(x.get('tutar') or 0) for x in ayni))}"))

        icerik = ft.Column([ft.Row([yazi(k, 12, renk=ui.SOLUK, width=110), yazi(str(v), 13, expand=True)])
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
        if self.yonetici and self.uyeler() and i.get("id") not in (None, -1) and self.uyeye_acik(i, gizli_say=False):
            grup = [x for x in self.islemler if i.get("fis_grup") and x.get("fis_grup") == i.get("fis_grup")] or [i]

            async def gizlilik(e):
                self.dialog_kapat(d)
                await self.gizlilik_degistir(grup, not i.get("gizli"))
            eylemler.append(buton("Göster" if i.get("gizli") else "Gizle", gizlilik,
                                  ft.Icons.LOCK_OPEN_ROUNDED if i.get("gizli") else ft.Icons.LOCK_ROUNDED, tip="text"))
        if self.izinli(i):
            eylemler.append(buton("Düzenle", duzenle, ft.Icons.EDIT, tip="text"))
            eylemler.append(buton("Sil", lambda e: sil_onay(False), ft.Icons.DELETE, tip="text"))
            if i.get("fis_grup"):
                eylemler.append(buton("Fişi tümden sil", lambda e: sil_onay(True), ft.Icons.DELETE_SWEEP, tip="text"))
        if len(self.profiller) > 1 and i.get("id") not in (None, -1):
            def yorum(e):
                self.dialog_kapat(d)
                self.yorum_yaz(i)
            eylemler.insert(0, buton("Yorum yaz", yorum, ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED, tip="text"))
        eylemler.append(buton("Kapat", lambda e: self.dialog_kapat(d), tip="text"))
        d.actions = eylemler
        self.dialog_ac(d)

    async def gizlilik_degistir(self, kayitlar, gizli):
        """Yönetici: kaydı (fişse fişin tüm satırlarını) Hatice'den gizler ya da gösterir."""
        try:
            grup = kayitlar[0].get("fis_grup") if kayitlar else None
            if grup and len(kayitlar) > 1:
                await self.arka(self.supa.tablo_guncelle_filtre, "hb_islemler",
                                f"fis_grup=eq.{urllib.parse.quote(str(grup))}", {"gizli": bool(gizli)})
            else:
                for x in kayitlar:
                    await self.arka(self.supa.islem_guncelle, x["id"], {"gizli": bool(gizli)})
            self.bildir(("🔒 Hatice'den gizlendi" if gizli else "🔓 Hatice artık görebilir") +
                        (f" ({len(kayitlar)} satır)" if len(kayitlar) > 1 else ""), GELIR)
            await self.verileri_yenile()
        except Exception as ex:
            self.bildir(f"Değiştirilemedi: {ex}", GIDER)

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

    def ekle_ekrani(self, duzenlenen=None, tur=None, onceki=None):
        d = duzenlenen or {}
        onceki = onceki or {}
        tur = tur or d.get("tur") or "Gider"
        ben = self.ben["id"]
        kisiler = list(self.profiller.values())
        tur_renk = {"Gider": GIDER, "Gelir": GELIR, "Aktarım": AKTARIM}[tur]

        tutar_deger = onceki.get("tutar") or (f"{float(d['tutar']):.2f}".replace(".", ",") if d.get("tutar") else "")
        tutar = ft.TextField(value=tutar_deger, hint_text="0,00", keyboard_type=ft.KeyboardType.NUMBER,
                             autofocus=not d, text_size=34, text_align=ft.TextAlign.CENTER, border_color="transparent",
                             text_style=ft.TextStyle(weight=ft.FontWeight.BOLD, color=tur_renk),
                             **({"suffix_text": "₺"} if _param_var(ft.TextField, "suffix_text") else
                                {"suffix": ft.Text("₺", size=24, weight=ft.FontWeight.BOLD, color=tur_renk)}
                                if _param_var(ft.TextField, "suffix") else {}))
        tarih = ft.TextField(label="Tarih (GG.AA.YYYY SS:DD)", prefix_icon=ft.Icons.EVENT_ROUNDED, dense=True,
                             value=onceki.get("tarih") or (hb.tarih_goster(d.get("tarih")) if d
                                                           else hb.simdi().strftime("%d.%m.%Y %H:%M")))
        aciklama = ft.TextField(label="Not (isteğe bağlı)", value=d.get("aciklama") or "", dense=True,
                                prefix_icon=ft.Icons.NOTES_ROUNDED)
        firma = ft.TextField(label="Firma / Market" if tur == "Gider" else "Kaynak (işveren, kişi...)",
                             value=d.get("firma") or "", dense=True, prefix_icon=ft.Icons.STOREFRONT_ROUNDED)
        urun = ft.TextField(label="Ürün / Hizmet" if tur == "Gider" else "Açıklama", value=d.get("urun") or "",
                            dense=True, prefix_icon=ft.Icons.SHOPPING_BASKET_ROUNDED)
        miktar = ft.TextField(label="Miktar (örn: 2 adet, 1.5 kg)", value=d.get("miktar") or "", dense=True,
                              prefix_icon=ft.Icons.SCALE_ROUNDED)

        secim = {"kategori": d.get("kategori") if d.get("tur") == tur and d.get("kategori") else
                 ("Market & Temel Gıda" if tur == "Gider" else self.gelir_turleri[0]),
                 "kasa": d.get("kasa_sahibi") or ben}
        kat_kutusu = ft.Row(wrap=True, spacing=6, run_spacing=6)
        kasa_kutusu = ft.Row(wrap=True, spacing=6)
        secenekler = self.kategoriler if tur == "Gider" else self.gelir_turleri
        if secim["kategori"] not in secenekler:
            secenekler = secenekler + [secim["kategori"]]

        def ciz_secimler():
            kat_kutusu.controls = [cip(k, secim["kategori"] == k, lambda e, k=k: sec("kategori", k),
                                       kat_stil(k, tur)[1], kat_stil(k, tur)[0]) for k in secenekler]
            kasa_kutusu.controls = [cip(p["ad"], secim["kasa"] == p["id"], lambda e, i=p["id"]: sec("kasa", i), "#475569",
                                        ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED) for p in kisiler]

        def sec(alan, deger):
            secim[alan] = deger
            ciz_secimler()
            self.guncelle()

        ciz_secimler()

        def tur_degistir(t):
            self.govde.content = self.ekle_ekrani(duzenlenen=duzenlenen, tur=t,
                                                  onceki={"tutar": tutar.value, "tarih": tarih.value})
            self.guncelle()

        tur_sec = ft.Container(content=ft.Row([
            ft.Container(content=ft.Row([ft.Icon(sim, size=16, color="white" if t == tur else r), yazi(t, 13, True,
                                         renk="white" if t == tur else ui.YAZI)], spacing=4, tight=True,
                                        alignment=ft.MainAxisAlignment.CENTER),
                         bgcolor=r if t == tur else None, border_radius=12, padding=10, expand=True,
                         on_click=lambda e, t=t: tur_degistir(t), alignment=ORTA)
            for t, r, sim in (("Gider", GIDER, ft.Icons.NORTH_EAST_ROUNDED), ("Gelir", GELIR, ft.Icons.SOUTH_WEST_ROUNDED),
                              ("Aktarım", AKTARIM, ft.Icons.SWAP_HORIZ_ROUNDED))], spacing=4),
            bgcolor=ui.CIZGI, border_radius=14, padding=4)

        hata = yazi("", 12, renk=GIDER)
        kaydet_btn = None
        gizli_cb = ft.Checkbox(label="🔒 Hatice'den gizle", value=bool(d.get("gizli")) if d else self.gizli_varsayilan)

        async def kaydet(e):
            t = hb.tutar_coz(tutar.value)
            if not t or t <= 0:
                hata.value = "Geçerli bir tutar girin."
                self.guncelle()
                return
            sahip = secim["kasa"] if self.yonetici else ben
            kayit = {"tur": tur, "tutar": t, "tarih": hb.iso_tarih(hb.tarih_coz(tarih.value)),
                     "aciklama": aciklama.value.strip() or None, "kasa_sahibi": sahip}
            if self.yonetici:
                kayit["gizli"] = bool(gizli_cb.value)
            if tur == "Aktarım":
                hedef = next((p["id"] for p in kisiler if p["id"] != sahip), None)
                if not hedef:
                    hata.value = "Aktarım için ikinci kullanıcı bulunamadı."
                    self.guncelle()
                    return
                kayit.update({"hedef_kasa": hedef, "kategori": "Transfer / Birikim",
                              "firma": None, "urun": None, "miktar": None})
            else:
                kayit.update({"hedef_kasa": None, "kategori": secim["kategori"], "firma": firma.value.strip() or None,
                              "urun": urun.value.strip() or None,
                              "miktar": (miktar.value.strip() or None) if tur == "Gider" else None})
            kaydet_btn.disabled = True
            self.guncelle()
            try:
                if d.get("id"):
                    await self.arka(self.supa.islem_guncelle, d["id"], kayit)
                    self.bildir("Güncellendi ✓", GELIR)
                else:
                    if await self.kayit_ekle([kayit]):
                        self.bildir(f"{tur} kaydedildi ✓ {hb.tl(t)}", GELIR)
                await self.verileri_yenile(ciz=False)
                self.sekmeye_git(1 if d.get("id") else 0)
            except Exception as ex:
                kaydet_btn.disabled = False
                hata.value = f"Kaydedilemedi: {ex}"
                self.guncelle()

        kaydet_btn = buton("Güncelle" if d.get("id") else "Kaydet", kaydet, ft.Icons.CHECK_ROUNDED, expand=True,
                           height=50)

        ust = [yazi("Kaydı düzenle" if d.get("id") else "Yeni kayıt", 22, True)]
        if not d.get("id"):
            ust.append(tur_sec)
        ust.append(ft.Container(content=ft.Column([yazi("Tutar", 12, renk=ui.SOLUK), tutar], spacing=0,
                                                  horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                bgcolor=ui.KART, border_radius=20, padding=12, shadow=golge(0.6)))
        alanlar = []
        if tur == "Aktarım":
            if self.yonetici:
                alanlar += [yazi("Gönderen kasa (diğerine aktarılır)", 12, renk=ui.SOLUK), kasa_kutusu]
            else:
                diger = self.diger
                alanlar.append(ft.Container(content=ft.Row([
                    ft.Icon(ft.Icons.SWAP_HORIZ_ROUNDED, color=AKTARIM),
                    yazi(f"{self.ben['ad']} kasasından ➜ {diger['ad'] if diger else '?'} kasasına", 13, True,
                         renk=AKTARIM, expand=True)]), bgcolor=ui.BILGI_ZEMIN, border_radius=12, padding=12))
            alanlar += [aciklama, tarih]
        else:
            alanlar += [yazi("Kategori" if tur == "Gider" else "Gelir türü", 12, renk=ui.SOLUK), kat_kutusu,
                        ft.Container(height=4), firma, urun]
            if tur == "Gider":
                alanlar.append(miktar)
            if self.yonetici:
                alanlar += [yazi("Hangi kasa?", 12, renk=ui.SOLUK), kasa_kutusu]
            alanlar += [tarih, aciklama]
        if self.yonetici:
            alanlar.append(gizli_cb)
        alanlar += [hata]
        alt = [ft.Row([kaydet_btn])]
        if d.get("id"):
            alt.append(ft.Row([buton("Vazgeç", lambda e: self.sekmeye_git(1), tip="text")]))
        return ft.ListView(padding=16, spacing=12, expand=True, controls=ust + [
            kart(ft.Column(alanlar, spacing=10), dolgu=16, shadow=golge(0.6))] + alt + [ft.Container(height=20)])

    def fis_ekrani(self):
        f = self.fis
        if f is None:
            secenekler = []
            if self.mobil:
                secenekler.append(self._buyuk_secenek(ft.Icons.PHOTO_CAMERA_ROUNDED, "Kamerayla çek",
                                                      "Uzun fişlerde birden çok fotoğraf çekebilirsiniz",
                                                      lambda e: self.page.run_task(self.kamera_ekrani), ANA, True))
            secenekler += [
                self._buyuk_secenek(ft.Icons.PHOTO_LIBRARY_ROUNDED, "Galeriden seç", "Daha önce çekilmiş fiş fotoğrafı",
                                    lambda e: self.page.run_task(self.fis_sec, "resim"), "#6366f1"),
                self._buyuk_secenek(ft.Icons.PICTURE_AS_PDF_ROUNDED, "PDF fatura", "e-Fatura, e-Arşiv, banka dekontu",
                                    lambda e: self.page.run_task(self.fis_sec, "pdf"), "#e11d48"),
            ]
            uyari = [] if self.gemini_anahtari else [kart(ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=GIDER),
                yazi("Yapay zeka anahtarı ayarlı değil. " + ("Ayarlar sekmesinden ekleyin." if self.yonetici
                     else "Abdurrahman'ın Ayarlar'dan eklemesi gerekiyor."), 12, renk=GIDER, expand=True)]),
                renk=ui.UYARI_ZEMIN)]
            return ft.ListView(padding=16, spacing=12, expand=True, controls=[
                ft.Container(content=ft.Column([
                    ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color="white"), yazi("Akıllı Fiş Okuma", 20, True, renk="white")]),
                    yazi("Fişin fotoğrafını çekin; ürünler, fiyatlar ve kategoriler yapay zeka ile otomatik "
                         "çıkarılır. Kaydetmeden önce kontrol edip düzeltebilirsiniz.", 12.5, renk="#e0e7ff"),
                ], spacing=8), padding=20, border_radius=24, gradient=degrade(["#4f46e5", "#7c3aed", "#a855f7"]),
                    bgcolor="#6366f1", shadow=golge(1)),
                *uyari, *secenekler,
                kart(ft.Column([yazi("İyi sonuç için", 13, True),
                                *[ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=16, color=GELIR), yazi(t, 12, renk=ui.SOLUK, expand=True)])
                                  for t in ("Fişi düz bir zemine koyun, gölge düşürmeyin",
                                            "Yazıların tamamı kadrajda ve net olsun",
                                            "Uzun fişi parça parça çekin, uygulama birleştirir")]], spacing=6)),
            ])
        if f.get("durum") == "isleniyor":
            return ft.Column([
                ft.Container(content=ft.ProgressRing(width=56, height=56, stroke_width=5, color="#7c3aed"), padding=10),
                yazi(f.get("mesaj", "İşleniyor..."), 15, True),
                yazi("Bu işlem 5-20 saniye sürebilir", 12, renk=ui.SOLUK)],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, expand=True)
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
        if tip == "pdf":
            sifreli = await self.arka(ak.pdf_sifreli_mi, veri)
            metin = "" if sifreli else await self.arka(ak.pdf_metni, veri)
            if sifreli or ak.ekstre_mi(metin):
                # banka hesap özetleri genelde şifreli PDF'tir: fiş yerine ekstre olarak işle
                self.fis = None
                self.bildir("💳 Bu bir kart ekstresi; aylık ödeme tutarı çıkarılacak" if not sifreli else
                            "🔒 Şifreli PDF: kart ekstresi olarak açılıyor")
                self.alt_sayfa = "taksitler"
                self.sekmeye_git(4)
                await self.ekstre_isle(veri, "pdf")
                return
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

        yol_s, analiz_s, _ = await asyncio.gather(yukle(), analiz(), self.fiyat_verisi_yukle(), return_exceptions=True)
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
        mukerrer = None
        if analiz_s.get("firma") or analiz_s.get("toplam_tutar"):
            try:
                mukerrer = await self.mukerrer_kontrol(analiz_s.get("firma") or "", analiz_s["tarih_dt"],
                                                       analiz_s.get("toplam_tutar"), bool((analiz_s.get("saat") or "").strip()))
            except Exception as ex:
                print("Mükerrer kontrolü yapılamadı:", ex)
        self.fis = {"durum": "duzenle", "yol": yol_s, "firma": analiz_s.get("firma") or "", "mukerrer": mukerrer,
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
            toplam_y.color = GIDER if fark else ui.YAZI
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
            kutu = kart(None, dolgu=8, renk=ui.ZEMIN2)

            def kaldir(e):
                satirlar.remove(kayit)
                satir_kutusu.controls.remove(kutu)
                toplami_hesapla(e)

            ust = [urun_tf]
            kutu.content = ft.Column([
                ft.Row([ft.Container(content=urun_tf, expand=True),
                        ft.IconButton(icon=ft.Icons.CLOSE, icon_size=18, on_click=kaldir, tooltip="Satırı sil")]),
                ft.Row([tutar_tf, kat_dd], spacing=8),
                *([yazi(f"Miktar: {u['miktar']}", 11, renk=ui.SOLUK)] if u.get("miktar") else []),
                *([ft.Row([ft.Icon(ft.Icons.PRICE_CHECK_ROUNDED, size=14, color="#0891b2"), yazi(fo, 11, renk="#0891b2", expand=True)],
                          spacing=4)] if (fo := (ak.fiyat_ozeti(self.fiyat_verisi, u.get("urun") or "", u.get("birim_fiyat") or u.get("tutar"))
                                                 if self.fiyat_verisi and u.get("urun") else None)) else []),
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
        gizli_cb = ft.Checkbox(label="🔒 Hatice'den gizle", value=self.gizli_varsayilan)

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
                if self.yonetici:
                    kayitlar[-1]["gizli"] = bool(gizli_cb.value)
                if kat_dd.value and kat_dd.value != ai_kat:
                    ogrenilen[hb.urun_anahtari(ad)] = kat_dd.value
            if not kayitlar:
                self.bildir("Kaydedilecek geçerli satır yok.", GIDER)
                return
            m = f.get("mukerrer")
            if m and not f.get("mukerrer_onay"):
                async def yine_de(ev):
                    f["mukerrer_onay"] = True
                    self.dialog_kapat()
                    await kaydet(ev)

                self.dialog_ac(ft.AlertDialog(
                    title=yazi("⚠️ Mükerrer kayıt olabilir", 17, True, renk=GIDER),
                    content=yazi(f"Bu fiş daha önce eklenmiş görünüyor: {m.get('firma') or 'aynı market'} • "
                                 f"{hb.tarih_goster(m.get('tarih'))} • {hb.tl(m.get('toplam'))} ({m.get('adet')} kalem"
                                 f"{', ' + m['ekleyen'] + ' ekledi' if m.get('ekleyen') else ''}).\n\nYine de eklemek istiyor musunuz?",
                                 13),
                    actions=[buton("Vazgeç", lambda ev: self.dialog_kapat(), tip="text"),
                             buton("Yine de ekle", yine_de, ft.Icons.CONTENT_COPY_ROUNDED)]))
                return
            try:
                if not await self.kayit_ekle(kayitlar):
                    self.fis = None
                    self.sekmeye_git(0)
                    return
                if ogrenilen:
                    try:
                        await self.arka(self.supa.kategori_eslemesi_kaydet, ogrenilen)
                        (self.eslemeler or {}).update(ogrenilen)
                    except Exception as ex:
                        print("Eşleme kaydedilemedi:", ex)
                self.fis = None
                self.fiyat_verisi = None
                self.page.run_task(self.alisverisi_isaretle, [k["urun"] for k in kayitlar])
                self.bildir(f"Fiş kaydedildi ✓ {len(kayitlar)} ürün • "
                            f"{hb.tl(sum(k['tutar'] for k in kayitlar))}", GELIR)
                await self.verileri_yenile(ciz=False)
                self.sekmeye_git(0)
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        bilgi = []
        if f.get("mukerrer"):
            m = f["mukerrer"]
            bilgi.append(ft.Container(content=ft.Row([
                ft.Icon(ft.Icons.CONTENT_COPY_ROUNDED, color=GIDER),
                ft.Column([yazi("Mükerrer kayıt uyarısı", 13.5, True, renk=GIDER),
                           yazi(f"Bu fiş daha önce eklenmiş olabilir: {m.get('firma') or ''} • {hb.tarih_goster(m.get('tarih'))} • "
                                f"{hb.tl(m.get('toplam'))}" + (f" • {m['ekleyen']}" if m.get("ekleyen") else "") +
                                ". İsterseniz yine de kaydedebilirsiniz.", 11.5, renk=GIDER)], spacing=2, expand=True)],
                spacing=10), bgcolor=saydam(GIDER, "1a"), border_radius=14, padding=12,
                border=ft.Border.all(1, GIDER) if hasattr(ft, "Border") and hasattr(ft.Border, "all") else ft.border.all(1, GIDER)))
        for u in f.get("uyari") or []:
            bilgi.append(kart(yazi("⚠️ " + u, 12, renk=GIDER), renk=ui.UYARI_ZEMIN, dolgu=10))
        alt_bilgi = " • ".join(x for x in [f"Model: {f['model']}" if f.get("model") else "",
                                            f"Fiş toplamı: {hb.tl(f['toplam'])}" if f.get("toplam") else ""] if x)
        ust_kontroller = [ft.Row([yazi("Fişi kontrol et", 20, True, expand=True),
                                  *([buton("Görsel", lambda e: self.page.run_task(self.fis_gorseli_goster, f["yol"]),
                                           ft.Icons.IMAGE, tip="text")] if f.get("yol") else [])]),
                          *bilgi, kart(ft.Column([firma, tarih] + (
                              [yazi("Hangi kasadan ödendi?", 12, renk=ui.SOLUK), kasa, gizli_cb] if self.yonetici else []) +
                              ([yazi(alt_bilgi, 11, renk=ui.SOLUK)] if alt_bilgi else []), spacing=10))]
        return ft.ListView(padding=14, spacing=10, expand=True, controls=ust_kontroller + [
            satir_kutusu,
            buton("Satır ekle", yeni_satir, ft.Icons.ADD, tip="outlined"),
            kart(toplam_y),
            ft.Row([buton("Vazgeç", vazgec, tip="text"), buton("Kaydet", kaydet, ft.Icons.SAVE, expand=True)]),
        ])

    # ------------------------------------------------------------ 4) AYARLAR
    def ayarlar_ekrani(self):
        canli = self.canli and self.canli.bagli
        kontroller = [kart(ft.Column([
            ft.Row([ft.Icon(ft.Icons.ACCOUNT_CIRCLE, size=40, color=ANA),
                    ft.Column([yazi(self.ben["ad"], 16, True),
                               yazi("Yönetici – tüm kasaları görür" if self.yonetici else "Üye – kendi kasasını görür",
                                    12, renk=ui.SOLUK)], spacing=0)]),
            ft.Row([ft.Icon(ft.Icons.CIRCLE, size=10, color=GELIR if canli else "#94a3b8"),
                    yazi("Anlık senkronizasyon açık" if canli else "Anlık bağlantı kuruluyor (20 sn'de bir yenileniyor)",
                         12, renk=ui.SOLUK)]),
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

            async def gizli_degisti(e):
                deger = bool(e.control.value)
                try:
                    await self.arka(self.supa.ayar_yaz, "gizli_varsayilan", "1" if deger else "0")
                    self.gizli_varsayilan = deger
                    self.bildir("Kaydedildi ✓", GELIR)
                except Exception as ex:
                    self.bildir(f"Kaydedilemedi: {ex}", GIDER)

            kontroller.append(kart(ft.Column([
                yazi("Gizlilik", 14, True),
                yazi("Hatice gelirleri ve 'Gizli' işaretlediğiniz kayıtları görmez; geri kalan her şeyi (harcamalar, "
                     "aktarımlar, faturalar, düzenli ödemeler, taksitler, hedefler, borçlar, altın/döviz) görür ama "
                     "yalnızca kendi kasasınınkini değiştirebilir. Kasa bakiyeniz ve toplam kasa ona gösterilmez. Bir kaydı "
                     "ya da fişi gizlemek için ona dokunup “Gizle” deyin. Bu seçenek yalnızca sizde vardır.",
                     11, renk=ui.SOLUK),
                ft.Checkbox(label="Yeni kayıtlarımı varsayılan olarak Hatice'den gizle",
                            value=self.gizli_varsayilan, on_change=gizli_degisti),
            ], spacing=8)))

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
                                yazi("aistudio.google.com adresinden ücretsiz alınabilir.", 11, renk=ui.SOLUK),
                                anahtar, buton("Anahtarı kaydet", anahtar_kaydet, ft.Icons.KEY)], spacing=10)),
                kart(ft.Column([yazi(f"Kategoriler ({len(self.kategoriler)})", 14, True),
                                yazi(", ".join(self.kategoriler), 11, renk=ui.SOLUK),
                                ft.Row([ft.Container(content=yeni_kat, expand=True),
                                        ft.IconButton(icon=ft.Icons.ADD, on_click=kat_ekle)])], spacing=10)),
            ]

        try:
            kontroller.append(self.mail_karti())
            if self.yonetici:
                kontroller.append(self.harclik_karti())
            kontroller.append(self.konum_karti())
        except Exception as ex:
            print("Ek ayar kartları:", ex)

        yeni_sifre = ft.TextField(label="Yeni şifre (en az 6 karakter)", password=True, can_reveal_password=True)

        async def sifre_degis(e):
            if len(yeni_sifre.value or "") < 6:
                self.bildir("Şifre en az 6 karakter olmalı.", GIDER)
                return
            try:
                await self.arka(self.supa.sifre_degistir, yeni_sifre.value)
                yeni_sifre.value = ""
                self.bildir("Şifreniz değiştirildi ✓", GELIR)
            except Exception as ex:
                self.bildir(f"Değiştirilemedi: {ex}", GIDER)

        kontroller.append(kart(ft.Column([yazi("Şifremi değiştir", 14, True), yeni_sifre,
                                          buton("Şifreyi değiştir", sifre_degis, ft.Icons.LOCK, tip="outlined")],
                                         spacing=10)))

        async def yenile(e):
            await self.ayarlari_yukle()
            await self.verileri_yenile(ciz=False)
            self.bildir("Yenilendi ✓")

        async def cikis(e):
            if self.canli:
                self.canli.durdur()
            await self.push_cikis()
            await self.arka(self.supa.cikis)
            self.ben, self.islemler, self.bakiyeler, self.fis = None, [], [], None
            self.ek_varsayilan()
            self.giris_ekrani()

        kontroller.insert(1, self.tema_pin_karti())
        if self.yonetici:
            kontroller.insert(2, self.push_ayar_karti())
        kontroller += [buton("Verileri yenile", yenile, ft.Icons.REFRESH, tip="outlined"),
                       buton("Çıkış yap", cikis, ft.Icons.LOGOUT, tip="outlined"),
                       ft.Row([yazi(f"Hane Bütçesi {SURUM}", 11, renk=ui.SOLUK)], alignment=ft.MainAxisAlignment.CENTER)]
        return ft.ListView(padding=14, spacing=12, expand=True, controls=kontroller)


async def main(page: ft.Page):
    uyg = Uygulama(page)
    await uyg.baslat()


if __name__ == "__main__":
    import os as _os
    _varliklar = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "assets")
    if hasattr(ft, "run"):
        ft.run(main, assets_dir=_varliklar)
    else:
        ft.app(target=main, assets_dir=_varliklar)
