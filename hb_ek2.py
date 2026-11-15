"""
Hane Bütçesi v2 – bildirimler (uygulama içi + telefona anlık), sesli ekleme, parmak izi kilidi.
"""
import asyncio
import os
import tempfile
import time

import flet as ft

import hb_akil as ak
import hb_core as hb
import hb_ui as ui
from hb_ui import ANA, GELIR, GIDER, buton, golge, kart, saydam, yazi

KAYIT_RENGI = "#dc2626"


class EkOzellikler2:
    # ================================================================== kurulum
    def ek2_kur(self):
        self.bildirimler = []
        self.bildirim_tablosu = False
        self.onesignal = None
        self.kaydedici = None
        self.yerel_kimlik = None
        try:
            if not self.mobil:
                raise RuntimeError("masaüstü sürümünde eklenti yok")
            import flet_audio_recorder as far
            ayar = far.AudioRecorderConfiguration(encoder=far.AudioEncoder.WAV)
            for alan, deger in (("sample_rate", 16000), ("channels", 1)):
                try:
                    setattr(ayar, alan, deger)
                except Exception:
                    pass
            self.kaydedici = far.AudioRecorder(configuration=ayar)
            self.page.services.append(self.kaydedici)
        except Exception as e:
            print("Ses kaydedici yok:", e)
        if self.mobil:
            try:
                import flet_local_auth as la
                self.yerel_kimlik = la.LocalAuthentication()
                self.page.services.append(self.yerel_kimlik)
            except Exception as e:
                print("Parmak izi bileşeni yok:", e)
        try:
            self.page.on_app_lifecycle_state_change = self._yasam_dongusu
        except Exception:
            pass

    async def _yasam_dongusu(self, e):
        durum = str(getattr(e, "state", getattr(e, "data", ""))).lower()
        if "resume" in durum and self.ben:
            await self.tepsiyi_temizle()
            await self.verileri_yenile()

    # ================================================================== bildirimler
    async def bildirimleri_yukle(self):
        try:
            self.bildirimler = await self.arka(self.supa.tablo, "hb_bildirimler", "select=*&order=olusturma.desc&limit=80")
            self.bildirim_tablosu = True
        except Exception:
            self.bildirim_tablosu = False

    @property
    def okunmamis(self):
        return sum(1 for b in self.bildirimler if not b.get("okundu"))

    async def bildirim_acilis(self):
        """Açılışta: günün hatırlatmalarını üret (sunucu zamanlayıcısı yoksa diye), push'u kur, yeni bildirimleri söyle."""
        try:
            await self.arka(self.supa.rpc, "hb_hatirlatmalari_uret")
        except Exception:
            pass
        await self.bildirimleri_yukle()
        if self.okunmamis:
            self.bildir(f"🔔 {self.okunmamis} yeni bildiriminiz var", ANA)
        await self.push_baslat()

    async def yeni_bildirim(self, kayit):
        """Realtime ile gelen bildirim (yalnızca bu kullanıcıya ait olanlar gelir)."""
        if kayit.get("alici") != self.ben["id"]:
            return
        if not any(b.get("id") == kayit.get("id") for b in self.bildirimler):
            self.bildirimler.insert(0, kayit)
        self.bildir(f"{kayit.get('baslik')}" + (f" — {kayit['metin']}" if kayit.get("metin") else ""))
        if self.sekme == 0 or (self.sekme == 4 and self.alt_sayfa == "bildirimler"):
            self.ekrani_ciz()

    def zil_dugmesi(self):
        n = self.okunmamis
        return ft.Container(content=ft.Stack([
            ft.Container(content=ft.Icon(ft.Icons.NOTIFICATIONS_ROUNDED if n else ft.Icons.NOTIFICATIONS_NONE_ROUNDED,
                                         color=ANA if n else ui.SOLUK, size=22),
                         width=40, height=40, border_radius=20, bgcolor=ui.KART, alignment=ui.ORTA, shadow=golge(0.4)),
            ft.Container(content=yazi(str(min(n, 99)), 10, True, renk="white"), bgcolor=GIDER, border_radius=9,
                         padding=ft.Padding(5, 1, 5, 1), right=0, top=0, visible=bool(n))], width=42, height=42),
            on_click=lambda e: self.menu_ac("bildirimler"), tooltip="Bildirimler")

    def sayfa_bildirimler(self):
        async def okundu_yap():
            if self.okunmamis:
                try:
                    await self.arka(self.supa.tablo_guncelle_filtre, "hb_bildirimler", "okundu=eq.false", {"okundu": True})
                except Exception:
                    pass
                for b in self.bildirimler:
                    b["okundu"] = True
            await self.tepsiyi_temizle()

        async def temizle(e):
            try:
                await self.arka(self.supa.tablo_sil_filtre, "hb_bildirimler", "id=gt.0")
                self.bildirimler = []
                self.bildir("Bildirimler temizlendi")
                self.ekrani_ciz()
            except Exception as ex:
                self.bildir(f"Temizlenemedi: {ex}", GIDER)

        async def sil(b):
            try:
                await self.arka(self.supa.tablo_sil, "hb_bildirimler", b["id"])
                self.bildirimler = [x for x in self.bildirimler if x["id"] != b["id"]]
                self.ekrani_ciz()
            except Exception:
                pass

        if not self.bildirim_tablosu:
            return self._liste([kart(yazi("Bildirimler için Supabase'de 'guncelleme_4.sql' dosyasını bir kez çalıştırın.",
                                          12.5, renk=GIDER), renk=ui.UYARI_ZEMIN)])
        renkler = {"hatirlatma": "#d97706", "fatura": "#f59e0b", "alisveris": GELIR, "fis": "#7c3aed", "islem": ANA}
        simgeler = {"hatirlatma": ft.Icons.ALARM_ROUNDED, "fatura": ft.Icons.RECEIPT_LONG_ROUNDED,
                    "alisveris": ft.Icons.SHOPPING_CART_ROUNDED, "fis": ft.Icons.RECEIPT_ROUNDED, "islem": ft.Icons.PAYMENTS_ROUNDED}
        ogeler = []
        if self.bildirimler:
            ogeler.append(ft.Row([yazi(f"{len(self.bildirimler)} bildirim", 12, renk=ui.SOLUK, expand=True),
                                  buton("Tümünü temizle", temizle, ft.Icons.DELETE_SWEEP_ROUNDED, tip="text")]))
        for b in self.bildirimler:
            renk = renkler.get(b.get("tur"), ANA)
            yeni = not b.get("okundu")
            ogeler.append(ft.Container(content=ft.Row([
                ft.Container(content=ft.Icon(simgeler.get(b.get("tur"), ft.Icons.NOTIFICATIONS_ROUNDED), color=renk, size=20),
                             bgcolor=saydam(renk), width=38, height=38, border_radius=12, alignment=ui.ORTA),
                ft.Column([yazi(b.get("baslik") or "", 13.5, True), *([yazi(b["metin"], 12, renk=ui.SOLUK)] if b.get("metin") else []),
                           yazi(hb.tarih_goster(b.get("olusturma")), 10.5, renk=ui.SOLUK)], spacing=1, expand=True),
                ft.Container(width=8, height=8, border_radius=4, bgcolor=GIDER, visible=yeni),
                ft.IconButton(icon=ft.Icons.CLOSE_ROUNDED, icon_size=16, on_click=lambda e, b=b: self.page.run_task(sil, b))],
                spacing=10), bgcolor=saydam(ANA, "10") if yeni else ui.KART, border_radius=16, padding=10, shadow=golge(0.3)))
        if not self.bildirimler:
            ogeler.append(kart(ft.Column([ft.Icon(ft.Icons.NOTIFICATIONS_OFF_ROUNDED, size=36, color=ui.SOLUK),
                                          yazi("Bildirim yok", 13, renk=ui.SOLUK)],
                                         horizontal_alignment=ft.CrossAxisAlignment.CENTER), dolgu=24))
        self.page.run_task(okundu_yap)  # sayfa açılınca hepsi okundu sayılır; bir daha uyarı olarak gelmez
        return self._liste(ogeler)

    # ================================================================== telefona anlık bildirim (OneSignal)
    async def push_baslat(self):
        if not self.mobil or self.onesignal is not None:
            return
        try:
            app_id = await self.arka(self.supa.ayar_oku, "onesignal_app_id")
        except Exception:
            app_id = None
        if not app_id:
            return
        try:
            import flet_onesignal as fos
            self.onesignal = fos.OneSignal(app_id=app_id, on_notification_click=self._bildirim_tiklandi)
            self.page.services.append(self.onesignal)
            self.page.update()
            await asyncio.sleep(0.5)
            await self.onesignal.login(self.ben["id"])
            await self.onesignal.notifications.request_permission(fallback_to_settings=True)
            await self.tepsiyi_temizle()
        except Exception as e:
            print("Push başlatılamadı:", e)

    async def tepsiyi_temizle(self):
        """Telefonun bildirim çekmecesindeki eski uygulama bildirimlerini temizler."""
        if self.onesignal is None:
            return
        try:
            await self.onesignal.notifications.clear_all()
        except Exception:
            pass

    async def _bildirim_tiklandi(self, e):
        self.menu_ac("bildirimler")

    async def push_cikis(self):
        if self.onesignal is not None:
            try:
                await self.onesignal.logout()
            except Exception:
                pass

    def push_ayar_karti(self):
        app = ft.TextField(label="OneSignal App ID", dense=True)
        anahtar = ft.TextField(label="OneSignal REST API Key", dense=True, password=True, can_reveal_password=True)
        durum = yazi("Durum kontrol ediliyor…", 11.5, renk=ui.SOLUK)

        async def yukle():
            try:
                app.value = await self.arka(self.supa.ayar_oku, "onesignal_app_id") or ""
                hazir = await self.arka(self.supa.rpc, "hb_push_durumu")
                durum.value = "✅ Telefon bildirimleri açık" if hazir is True or hazir == [True] else "Henüz ayarlanmadı"
            except Exception:
                durum.value = "Önce 'guncelleme_4.sql' çalıştırılmalı"
            self.guncelle()

        async def kaydet(e):
            try:
                await self.arka(self.supa.rpc, "hb_push_ayarla", {"p_app_id": app.value or "", "p_api_key": anahtar.value or ""})
                anahtar.value = ""
                self.onesignal = None
                self.bildir("Kaydedildi ✓ Uygulamayı yeniden açınca telefon bildirimleri başlar", GELIR)
                await yukle()
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self.page.run_task(yukle)
        return kart(ft.Column([
            yazi("Telefon bildirimleri", 14, True),
            yazi("Uygulama kapalıyken de bildirim gelmesi için ücretsiz OneSignal hesabı gerekir (kurulum KURULUM.md'de). "
                 "API anahtarı sunucuda gizli tutulur, telefonlara gitmez.", 11.5, renk=ui.SOLUK),
            app, anahtar, ft.Row([durum, buton("Kaydet", kaydet, ft.Icons.SAVE_ROUNDED, tip="tonal")],
                                 alignment=ft.MainAxisAlignment.SPACE_BETWEEN)], spacing=10), shadow=golge(0.5))

    # ================================================================== sesli kayıt
    def ses_dugmesi(self, sonuc_cb, ipucu="Sesli söyle"):
        """Dokun: kayıt başlar; tekrar dokun: biter ve sonuc_cb(ses_bytes, mime) çağrılır."""
        durum = {"kayit": False, "yol": None, "bas": 0}
        dugme = ft.IconButton(icon=ft.Icons.MIC_ROUNDED, icon_color="#7c3aed", tooltip=ipucu)

        async def tikla(e):
            if self.kaydedici is None:
                self.bildir("Ses kaydı bu cihazda desteklenmiyor; klavyenin mikrofonunu kullanın.", GIDER)
                return
            if not durum["kayit"]:
                try:
                    izin = await self.kaydedici.has_permission()
                    if izin is False:
                        self.bildir("Mikrofon izni verilmedi (Ayarlar > Uygulamalar > Hane Bütçesi > İzinler).", GIDER)
                        return
                except Exception:
                    pass
                klasor = os.environ.get("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
                durum["yol"] = os.path.join(klasor, f"hb_ses_{int(time.time())}.wav")
                try:
                    basladi = await self.kaydedici.start_recording(output_path=durum["yol"])
                except Exception as ex:
                    self.bildir(f"Kayıt başlatılamadı: {ex}", GIDER)
                    return
                if basladi is False:
                    self.bildir("Kayıt başlatılamadı (mikrofon izni?)", GIDER)
                    return
                durum.update(kayit=True, bas=time.time())
                dugme.icon, dugme.icon_color, dugme.tooltip = ft.Icons.STOP_CIRCLE_ROUNDED, KAYIT_RENGI, "Bitir"
                self.bildir("🎙️ Dinliyorum… bitince tekrar dokunun")
                self.guncelle()
                return
            durum["kayit"] = False
            dugme.icon, dugme.icon_color, dugme.tooltip = ft.Icons.MIC_ROUNDED, "#7c3aed", ipucu
            self.guncelle()
            try:
                yol = await self.kaydedici.stop_recording() or durum["yol"]
                with open(yol, "rb") as f:
                    veri = f.read()
                try:
                    os.remove(yol)
                except Exception:
                    pass
            except Exception as ex:
                self.bildir(f"Kayıt alınamadı: {ex}", GIDER)
                return
            if time.time() - durum["bas"] < 0.8 or len(veri) < 2000:
                self.bildir("Kayıt çok kısa oldu.", GIDER)
                return
            await sonuc_cb(veri, "audio/wav")

        dugme.on_click = tikla
        return dugme

    async def sesli_hizli_ekle(self, veri, mime):
        self.bildir("🎧 Anlaşılıyor…")
        try:
            metin, kayitlar = await self.arka(ak.hizli_ekle_ses, veri, mime, self.kategoriler, self.gelir_turleri,
                                              self.gemini_anahtari)
        except Exception as ex:
            self.bildir(f"Anlaşılamadı: {ex}", GIDER)
            return
        if not kayitlar:
            self.bildir(f"Tutar duyulmadı: “{metin}”" if metin else "Ses anlaşılamadı, tekrar deneyin.", GIDER)
            return
        if metin:
            self.bildir(f"🗣️ “{metin}”")
        self.hizli_onay(kayitlar)

    # ================================================================== parmak izi
    async def biyometrik_dogrula(self) -> bool:
        if self.yerel_kimlik is None:
            return False
        try:
            if not await self.yerel_kimlik.is_device_supported():
                return False
            return bool(await self.yerel_kimlik.authenticate(reason="Hane Bütçesi'ni açmak için doğrulayın",
                                                             biometric_only=False, persist_across_backgrounding=True))
        except Exception as e:
            print("Biyometrik doğrulama:", e)
            return False

    async def biyometrik_destekli(self) -> bool:
        if self.yerel_kimlik is None:
            return False
        try:
            return bool(await self.yerel_kimlik.is_device_supported())
        except Exception:
            return False
