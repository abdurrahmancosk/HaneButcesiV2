"""
Hane Bütçesi v2 – ek özellik ekranları (Uygulama sınıfına karışım olarak eklenir)
Menü, bütçe limitleri, birikim hedefleri, faturalar + düzenli ödemeler, alışveriş listesi,
borç/alacak, fiyat takibi, akıllı rapor, asistan, Excel/PDF, hızlı ekleme, tema ve PIN.
"""
import asyncio
import datetime as dt
import hashlib
import inspect
import json
import os

import flet as ft

import hb_akil as ak
import hb_core as hb
import hb_ui as ui
from hb_ui import (ANA, AKTARIM, GELIR, GIDER, acilir, buton, cip, degrade, golge, kart, kat_stil, ORTA, saydam,
                   simge_kutusu, yazi)

FATURA_SIMGE = {"Elektrik": ("BOLT", "#f59e0b"), "Su": ("WATER_DROP", "#0ea5e9"), "Doğalgaz": ("LOCAL_FIRE_DEPARTMENT", "#f97316"),
                "İnternet": ("WIFI", "#6366f1"), "Telefon": ("PHONE_ANDROID", "#14b8a6"), "Aidat": ("APARTMENT", "#8b5cf6"),
                "Kira": ("HOME", "#0f766e"), "Diğer": ("RECEIPT_LONG", "#64748b")}

MENU = [  # anahtar, başlık, açıklama, simge, renk
    ("bildirimler", "Bildirimler", "Eşinizin eklediği kayıtlar, hatırlatmalar", "NOTIFICATIONS_ROUNDED", "#e11d48"),
    ("faturalar", "Faturalar", "Yükle, hatırlat, zam/kullanım analizi", "RECEIPT_LONG_ROUNDED", "#f59e0b"),
    ("alisveris", "Alışveriş listesi", "Ortak, anlık liste", "CHECKLIST_ROUNDED", "#16a34a"),
    ("butceler", "Bütçe limitleri", "Kategori sınırları ve uyarılar", "DONUT_LARGE_ROUNDED", "#e11d48"),
    ("hedefler", "Birikim hedefleri", "Tatil, araba, acil durum…", "SAVINGS_ROUNDED", "#ca8a04"),
    ("borclar", "Borç / alacak", "Kime ne verildi, kimden ne alınacak", "HANDSHAKE_ROUNDED", "#2563eb"),
    ("fiyatlar", "Fiyat takibi", "Ürün fiyatları, güncel market fiyatları", "PRICE_CHECK_ROUNDED", "#0891b2"),
    ("varliklar", "Altın & döviz", "Elinizdeki altın/döviz, güncel değeri", "DIAMOND_ROUNDED", "#ca8a04"),
    ("yil_ozeti", "Yıl özeti", "Yılın hikayesi: en çok, en büyük, en tasarruflu", "CELEBRATION_ROUNDED", "#0d9488"),
    ("kasa", "Kasa hareketleri", "Gelirler, aktarımlar, tüm geçmiş", "ACCOUNT_BALANCE_WALLET_ROUNDED", "#0f766e"),
    ("rapor", "Akıllı rapor", "Dönem karşılaştırma, Excel / PDF", "INSIGHTS_ROUNDED", "#7c3aed"),
    ("asistan", "Asistana sor", "“Bu ay sigaraya ne verdik?”", "AUTO_AWESOME_ROUNDED", "#a855f7"),
    ("ayarlar", "Ayarlar", "Tema, PIN, şifre, yapay zeka", "SETTINGS_ROUNDED", "#475569"),
]


_UZERI_CIZILI = getattr(getattr(ft, "TextDecoration", None), "LINE_THROUGH", None)


def _ikon(ad):
    return getattr(ft.Icons, ad, None) or ft.Icons.CIRCLE


def _ilerleme(oran, renk, yukseklik=8):
    oran = max(0.0, min(oran, 1.0))
    return ft.Row([ft.Container(bgcolor=renk, height=yukseklik, border_radius=yukseklik // 2, expand=max(1, int(1000 * oran))),
                   ft.Container(bgcolor=ui.CIZGI, height=yukseklik, border_radius=yukseklik // 2,
                                expand=max(1, 1000 - int(1000 * oran)))], spacing=0)


class EkOzellikler:
    # ================================================================== veri
    def ek_varsayilan(self):
        self.ek = {"faturalar": [], "duzenli": [], "butceler": {}, "hedefler": [], "hedef_durum": {}, "alisveris": [],
                   "borclar": []}
        self.ek_hazir = None
        self.alt_sayfa = None
        self.fiyat_verisi = None
        self.sohbet = []

    async def ek_verileri_yenile(self):
        try:
            await self._ek_verileri_yenile()
        except Exception as e:
            print("Ek veriler alınamadı:", e)
            self.ek_hazir = False

    async def _ek_verileri_yenile(self):
        s = self.supa
        gecen_hafta = hb.iso_tarih(hb.simdi() - dt.timedelta(days=7))
        isler = {
            "faturalar": (s.tablo, "hb_faturalar", "select=*&order=son_odeme.desc.nullslast,id.desc&limit=300"),
            "duzenli": (s.tablo, "hb_duzenli", "select=*&order=gun"),
            "butceler": (s.tablo, "hb_butceler", "select=*"),
            "hedefler": (s.tablo, "hb_hedefler", "select=*&order=id"),
            "hedef_durum": (s.rpc, "hb_hedef_durumlari"),
            "alisveris": (s.tablo, "hb_alisveris", "select=*&order=alindi,olusturma.desc&or=" +
                          hb.urllib.parse.quote(f'(alindi.eq.false,alinma.gte."{gecen_hafta}")')),
            "borclar": (s.tablo, "hb_borclar", "select=*&order=kapandi,tarih.desc&limit=200"),
        }
        sonuclar = await asyncio.gather(*[self.arka(f, *a) for f, *a in isler.values()], return_exceptions=True)
        hata = 0
        for (anahtar, _), sonuc in zip(isler.items(), sonuclar):
            if isinstance(sonuc, Exception):
                hata += 1
                continue
            if anahtar == "butceler":
                self.ek[anahtar] = {b["kategori"]: float(b["limit_tutar"]) for b in sonuc}
            elif anahtar == "hedef_durum":
                self.ek[anahtar] = {d["hedef_id"]: float(d["biriken"] or 0) for d in sonuc}
            else:
                self.ek[anahtar] = sonuc
        self.ek_hazir = hata < len(isler)

    def hatirlatmalar(self):
        h = ak.fatura_hatirlatmalari(self.ek["faturalar"]) + ak.duzenli_hatirlatmalari(self.ek["duzenli"])
        sira = {"gecikti": 0, "bugun": 1, "yarin": 2, "yakin": 3}
        return sorted(h, key=lambda x: sira.get(x["seviye"], 9))

    def butce_durumu(self):
        """[(kategori, harcanan, limit, oran)] – dönem içi."""
        harcanan = hb.donem_ozeti(self.islemler, None if self.yonetici else self.ben["id"])["kategoriler"]
        sonuc = [(k, harcanan.get(k, 0.0), lim, harcanan.get(k, 0.0) / lim) for k, lim in self.ek["butceler"].items()
                 if not str(k).startswith("kisi:") and lim]
        return sorted(sonuc, key=lambda x: -x[3])

    # ================================================================== özet ekleri
    def ozet_ekleri(self):
        """Özet ekranının üstüne: hatırlatmalar, bütçe uyarıları, hızlı ekleme."""
        parcalar = []
        for h in self.hatirlatmalar()[:4]:
            renk = {"gecikti": GIDER, "bugun": GIDER, "yarin": "#d97706"}.get(h["seviye"], AKTARIM)
            parcalar.append(ft.Container(content=ft.Row([
                ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED, color=renk, size=20),
                yazi(h["metin"], 12.5, True, renk=renk, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=renk, size=18)], spacing=8),
                bgcolor=saydam(renk, "1f"), border_radius=14, padding=12,
                on_click=lambda e: self.menu_ac("faturalar")))
        asimlar = [b for b in self.butce_durumu() if b[3] >= 0.8][:3]
        for k, h, lim, oran in asimlar:
            renk = GIDER if oran >= 1 else "#d97706"
            parcalar.append(ft.Container(content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=renk, size=18),
                        yazi(f"{k}: limit {'aşıldı' if oran >= 1 else '%' + str(int(oran * 100)) + ' doldu'}", 12.5, True,
                             renk=renk, expand=True), yazi(f"{hb.tl(h)} / {hb.tl(lim)}", 11.5, renk=renk)]),
                _ilerleme(oran, renk, 6)], spacing=6), bgcolor=saydam(renk, "1a"), border_radius=14, padding=12,
                on_click=lambda e: self.menu_ac("butceler")))
        parcalar.append(self.hizli_ekleme_cubugu())
        return parcalar

    def hizli_ekleme_cubugu(self):
        alan = ft.TextField(hint_text="Hızlı ekle: “bimden 3 ekmek 45 lira, süt 40”", border_color="transparent",
                            dense=True, expand=True, text_size=13, multiline=False)
        bekle = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)

        async def gonder(e):
            metin = (alan.value or "").strip()
            if not metin:
                return
            bekle.visible = True
            self.guncelle()
            try:
                kayitlar = await self.arka(ak.hizli_ekle_coz, metin, self.kategoriler, self.gelir_turleri, self.gemini_anahtari)
            except Exception as ex:
                bekle.visible = False
                self.bildir(f"Anlaşılamadı: {ex}", GIDER)
                self.guncelle()
                return
            bekle.visible = False
            if not kayitlar:
                self.bildir("Metinde tutar bulunamadı. Örn: “A101 deterjan 189 lira”", GIDER)
                self.guncelle()
                return
            alan.value = ""
            self.hizli_onay(kayitlar)

        alan.on_submit = gonder
        return ft.Container(content=ft.Row([
            ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color="#7c3aed", size=20), alan, bekle,
            self.ses_dugmesi(self.sesli_hizli_ekle, "Sesli ekle: “bimden 3 ekmek 45 lira”"),
            ft.IconButton(icon=ft.Icons.SEND_ROUNDED, icon_color="#7c3aed", on_click=gonder, tooltip="Ekle")], spacing=6),
            bgcolor=ui.KART, border_radius=18, padding=ft.Padding(14, 2, 4, 2), shadow=golge(0.5))

    def hizli_onay(self, kayitlar):
        secili = [True] * len(kayitlar)
        kasa = {"id": self.ben["id"]}
        satirlar = []
        for n, k in enumerate(kayitlar):
            simge, renk = kat_stil(k["kategori"], k["tur"])
            satirlar.append(ft.Row([
                ft.Checkbox(value=True, on_change=lambda e, n=n: secili.__setitem__(n, bool(e.control.value))),
                ft.Icon(simge, color=renk, size=18),
                ft.Column([yazi(k.get("urun") or k["kategori"], 13, True),
                           yazi(" • ".join(x for x in [k.get("firma"), k.get("miktar"), k["kategori"],
                                                       k["tarih"].strftime("%d.%m %H:%M")] if x), 11, renk=ui.SOLUK)],
                          spacing=0, expand=True),
                yazi(("+" if k["tur"] == "Gelir" else "-") + hb.tl(k["tutar"]), 13, True,
                     renk=GELIR if k["tur"] == "Gelir" else ui.YAZI)], spacing=6))
        kasa_sec = []
        if self.yonetici:
            kasa_sec = [yazi("Kasa", 12, renk=ui.SOLUK), ft.RadioGroup(value=kasa["id"], on_change=lambda e: kasa.update(
                id=e.control.value), content=ft.Row([ft.Radio(value=p["id"], label=p["ad"]) for p in self.profiller.values()]))]
        d = ft.AlertDialog(title=yazi("Bunları ekleyeyim mi?", 17, True),
                           content=ft.Column(satirlar + kasa_sec, tight=True, scroll=ft.ScrollMode.AUTO, spacing=6))

        async def kaydet(e):
            self.dialog_kapat(d)
            liste = []
            for k, s in zip(kayitlar, secili):
                if not s:
                    continue
                kayit = {"tur": k["tur"], "tutar": k["tutar"], "tarih": hb.iso_tarih(k["tarih"]), "firma": k.get("firma"),
                         "urun": k.get("urun"), "miktar": k.get("miktar") if k["tur"] == "Gider" else None,
                         "kategori": k["kategori"], "kasa_sahibi": kasa["id"] if self.yonetici else self.ben["id"],
                         "hedef_kasa": None, "aciklama": "Hızlı ekleme"}
                if self.yonetici:
                    kayit["gizli"] = self.gizli_varsayilan
                liste.append(kayit)
            if not liste:
                return
            try:
                if await self.kayit_ekle(liste):
                    self.bildir(f"{len(liste)} kayıt eklendi ✓", GELIR)
                await self.verileri_yenile()
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        d.actions = [buton("Vazgeç", lambda e: self.dialog_kapat(d), tip="text"), buton("Ekle", kaydet, ft.Icons.CHECK_ROUNDED)]
        self.dialog_ac(d)

    # ================================================================== menü
    def menu_ac(self, anahtar):
        self.alt_sayfa = anahtar
        self.sekmeye_git(4)

    def menu_ekrani(self):
        if self.alt_sayfa:
            sayfa = getattr(self, f"sayfa_{self.alt_sayfa}", None)
            baslik = next((m[1] for m in MENU if m[0] == self.alt_sayfa), "")
            if sayfa:
                govde = sayfa()
                ust = ft.Row([ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, on_click=lambda e: self.menu_geri()),
                              yazi(baslik, 20, True, expand=True)])
                return ft.Column([ft.Container(content=ust, padding=ft.Padding(6, 6, 12, 0)),
                                  ft.Container(content=govde, expand=True)], expand=True, spacing=0)
        uyari = []
        if self.ek_hazir is False:
            uyari = [kart(yazi("⚠️ Yeni özellikler için Supabase'de 'guncelleme_3.sql' dosyasını bir kez çalıştırın.",
                               12.5, renk=GIDER), renk=ui.UYARI_ZEMIN)]
        rozet = {"bildirimler": self.okunmamis or None, "faturalar": len(self.hatirlatmalar()) or None,
                 "alisveris": sum(1 for a in self.ek["alisveris"] if not a.get("alindi")) or None,
                 "borclar": sum(1 for b in self.ek["borclar"] if not b.get("kapandi")) or None,
                 "butceler": sum(1 for b in self.butce_durumu() if b[3] >= 1) or None}
        kutular = []
        for anahtar, baslik, acik, simge, renk in MENU:
            r = rozet.get(anahtar)
            kutular.append(ft.Container(content=ft.Column([
                ft.Row([ft.Container(content=ft.Icon(_ikon(simge), color=renk, size=24), bgcolor=saydam(renk),
                                     width=46, height=46, border_radius=14, alignment=ORTA),
                        ft.Container(content=yazi(str(r), 11, True, renk="white"), bgcolor=GIDER, border_radius=10,
                                     padding=ft.Padding(7, 2, 7, 2), visible=bool(r))],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START),
                yazi(baslik, 14, True), yazi(acik, 11, renk=ui.SOLUK, max_lines=2)], spacing=6),
                bgcolor=ui.KART, border_radius=20, padding=14, shadow=golge(0.6), col={"xs": 6, "md": 4},
                on_click=lambda e, a=anahtar: self.menu_ac(a)))
        izgara = ft.ResponsiveRow(kutular, spacing=10, run_spacing=10) if hasattr(ft, "ResponsiveRow") else \
            ft.Row(kutular, wrap=True)
        return ft.ListView(padding=16, spacing=12, expand=True, controls=[yazi("Menü", 24, True), *uyari, izgara,
                                                                          ft.Container(height=20)])

    def menu_geri(self):
        self.alt_sayfa = None
        if getattr(self, "_alt_kaynak", None) == 5:
            self._alt_kaynak = None
            self.sekmeye_git(5)
            return
        self.ekrani_ciz()

    def _liste(self, kontroller):
        return ft.ListView(padding=ft.Padding(16, 8, 16, 16), spacing=10, expand=True,
                           controls=kontroller + [ft.Container(height=30)])

    def _girdi_dialog(self, baslik, alanlar, kaydet_cb, kaydet_metin="Kaydet", ek_eylem=None):
        d = ft.AlertDialog(title=yazi(baslik, 17, True), content=ft.Column(alanlar, tight=True, spacing=10,
                                                                             scroll=ft.ScrollMode.AUTO))

        async def tamam(e):
            sonuc = kaydet_cb()
            if inspect.isawaitable(sonuc):
                sonuc = await sonuc
            if sonuc is not False:
                self.dialog_kapat(d)

        d.actions = ([ek_eylem(d)] if ek_eylem else []) + [buton("Vazgeç", lambda e: self.dialog_kapat(d), tip="text"),
                                                           buton(kaydet_metin, tamam)]
        self.dialog_ac(d)

    async def _islem(self, f, *a, basari=None):
        try:
            sonuc = await self.arka(f, *a)
            if basari:
                self.bildir(basari, GELIR)
            await self.ek_verileri_yenile()
            await self.verileri_yenile(ciz=False)
            self.ekrani_ciz()
            return sonuc
        except Exception as ex:
            self.bildir(f"İşlem yapılamadı: {ex}", GIDER)
            return None

    def _kasa_secici(self, deger=None):
        return ft.RadioGroup(value=deger or self.ben["id"], content=ft.Row(
            [ft.Radio(value=p["id"], label=p["ad"]) for p in self.profiller.values()], wrap=True))

    # ================================================================== bütçe limitleri
    def sayfa_butceler(self):
        durum = {k: (h, lim, o) for k, h, lim, o in self.butce_durumu()}
        harcanan = hb.donem_ozeti(self.islemler, None if self.yonetici else self.ben["id"])["kategoriler"]
        bilgi = kart(yazi("Her kategori için dönem (15'i–14'ü) harcama sınırı belirleyin. %80'e gelince ve aşılınca "
                          "Özet ekranında uyarı çıkar." + ("" if self.yonetici else " Limitleri Abdurrahman belirler."),
                          12, renk=ui.SOLUK))
        satirlar = []
        kategoriler = sorted(set(self.kategoriler) | set(durum), key=lambda k: (k not in durum, -harcanan.get(k, 0)))
        for k in kategoriler:
            simge, renk = kat_stil(k)
            h = harcanan.get(k, 0.0)
            if k in durum:
                _, lim, oran = durum[k]
                r = GIDER if oran >= 1 else ("#d97706" if oran >= 0.8 else renk)
                alt = ft.Column([_ilerleme(oran, r), ft.Row([yazi(f"{hb.tl(h)} / {hb.tl(lim)}", 11.5, renk=ui.SOLUK, expand=True),
                                                             yazi(f"Kalan {hb.tl(max(lim - h, 0))}" if oran < 1 else
                                                                  f"{hb.tl(h - lim)} aşıldı", 11.5, True, renk=r)])], spacing=4)
            else:
                alt = yazi(f"Bu dönem {hb.tl(h)} • limit yok", 11.5, renk=ui.SOLUK)
            satirlar.append(ft.Container(content=ft.Row([simge_kutusu(simge, renk, 18, 36),
                                                         ft.Column([yazi(k, 13, True), alt], spacing=4, expand=True)], spacing=10),
                                         bgcolor=ui.KART, border_radius=16, padding=12, shadow=golge(0.4),
                                         on_click=(lambda e, k=k: self.butce_duzenle(k)) if self.yonetici else None))
        kisi = []
        if self.yonetici:
            kisi.append(yazi("Kişi (harçlık) bütçeleri", 15, True))
            for p in self.profiller.values():
                d = self.kisi_butcesi(p["id"])
                kisi.append(ft.Container(content=ft.Row([
                    self.kisi_rozeti(p["id"], boyut=30),
                    ft.Column([yazi(p["ad"], 13.5, True),
                               yazi(f"{hb.tl(d[0])} / {hb.tl(d[1])} bu dönem" if d else "Limit yok – dokunup belirleyin", 11.5,
                                    renk=ui.SOLUK)], spacing=0, expand=True),
                    ft.Icon(ft.Icons.EDIT_ROUNDED, size=18, color=ui.SOLUK)], spacing=10),
                    bgcolor=ui.KART, border_radius=16, padding=12, shadow=golge(0.4),
                    on_click=lambda e, i=p["id"]: self.kisi_butce_duzenle(i)))
        else:
            kb = self.kisi_butce_karti(self.ben["id"])
            if kb:
                kisi.append(kb)
        return self._liste(kisi + [bilgi] + satirlar)

    def butce_duzenle(self, kategori):
        mevcut = self.ek["butceler"].get(kategori)
        alan = ft.TextField(label="Dönem limiti (₺) – boş bırakırsanız kaldırılır", keyboard_type=ft.KeyboardType.NUMBER,
                            value=f"{mevcut:.0f}" if mevcut else "", autofocus=True)
        oneri = hb.donem_ozeti(self.islemler)["kategoriler"].get(kategori)

        async def kaydet():
            t = hb.tutar_coz(alan.value)
            await self._islem(self.supa.butce_yaz, kategori, t if t and t > 0 else None, basari="Limit kaydedildi ✓")

        self._girdi_dialog(kategori, [alan] + ([yazi(f"Bu dönem şu ana kadar: {hb.tl(oneri)}", 11.5, renk=ui.SOLUK)]
                                               if oneri else []), kaydet)

    # ================================================================== birikim hedefleri
    def sayfa_hedefler(self):
        ogeler = [buton("Yeni hedef", lambda e: self.hedef_duzenle(), ft.Icons.ADD_ROUNDED)]
        for h in self.ek["hedefler"]:
            biriken = self.ek["hedef_durum"].get(h["id"], 0.0)
            hedef = float(h["hedef_tutar"])
            oran = biriken / hedef if hedef else 0
            kalan_gun = None
            if h.get("hedef_tarih"):
                kalan_gun = (dt.date.fromisoformat(h["hedef_tarih"]) - hb.simdi().date()).days
            aylik = (hedef - biriken) / max(kalan_gun / 30, 1) if kalan_gun and kalan_gun > 0 and biriken < hedef else None
            ogeler.append(ft.Container(content=ft.Column([
                ft.Row([
                    ft.Stack([ft.ProgressRing(value=min(oran, 1), width=64, height=64, stroke_width=7,
                                              color="#ca8a04" if oran < 1 else GELIR, bgcolor=ui.CIZGI),
                              ft.Container(content=yazi(f"%{int(oran * 100)}", 13, True), width=64, height=64, alignment=ORTA)],
                             width=64, height=64),
                    ft.Column([yazi(h["ad"], 16, True), yazi(f"{hb.tl(biriken)} / {hb.tl(hedef)}", 13, renk=ui.SOLUK),
                               yazi(("🎉 Hedefe ulaşıldı!" if oran >= 1 else
                                     (f"{kalan_gun} gün kaldı • ayda {hb.tl(aylik)} biriktirmelisiniz" if aylik else
                                      (f"{kalan_gun} gün kaldı" if kalan_gun is not None else "Tarih belirtilmedi"))),
                                    11.5, renk=GELIR if oran >= 1 else ui.SOLUK),
                               *([yazi(f"Kasa: {self.ad(h['kasa_sahibi'])}", 11, renk=ui.SOLUK)] if self.yonetici else [])],
                              spacing=2, expand=True)], spacing=14),
                ft.Row([buton("Para koy", lambda e, h=h: self.hedef_hareket(h, "koy"), ft.Icons.ADD_CIRCLE_ROUNDED, tip="tonal"),
                        buton("Çek", lambda e, h=h: self.hedef_hareket(h, "cek"), ft.Icons.REMOVE_CIRCLE_ROUNDED, tip="text"),
                        ft.IconButton(icon=ft.Icons.EDIT_ROUNDED, on_click=lambda e, h=h: self.hedef_duzenle(h))],
                       alignment=ft.MainAxisAlignment.END)], spacing=8),
                bgcolor=ui.KART, border_radius=20, padding=16, shadow=golge(0.6)))
        if not self.ek["hedefler"]:
            ogeler.append(kart(yazi("Henüz hedef yok. Örn: “Yaz tatili – 40.000 ₺ – 1 Temmuz”. Hedefe koyduğunuz para "
                                    "kasadan düşer, hedefte birikir.", 12.5, renk=ui.SOLUK)))
        return self._liste(ogeler)

    def hedef_duzenle(self, h=None):
        h = h or {}
        ad = ft.TextField(label="Hedef adı", value=h.get("ad", ""), autofocus=not h)
        tutar = ft.TextField(label="Hedef tutar (₺)", value=f"{float(h['hedef_tutar']):.0f}" if h else "",
                             keyboard_type=ft.KeyboardType.NUMBER)
        tarih = ft.TextField(label="Hedef tarih (GG.AA.YYYY, isteğe bağlı)",
                             value=dt.date.fromisoformat(h["hedef_tarih"]).strftime("%d.%m.%Y") if h.get("hedef_tarih") else "")
        kasa = self._kasa_secici(h.get("kasa_sahibi"))

        async def kaydet():
            t = hb.tutar_coz(tutar.value)
            if not (ad.value or "").strip() or not t:
                self.bildir("Ad ve tutar gerekli.", GIDER)
                return False
            kayit = {"ad": ad.value.strip(), "hedef_tutar": t,
                     "hedef_tarih": hb.tarih_coz(tarih.value).date().isoformat() if (tarih.value or "").strip() else None,
                     "kasa_sahibi": kasa.value if self.yonetici else self.ben["id"]}
            if h.get("id"):
                await self._islem(self.supa.tablo_guncelle, "hb_hedefler", h["id"], kayit, basari="Hedef güncellendi ✓")
            else:
                await self._islem(self.supa.tablo_ekle, "hb_hedefler", kayit, basari="Hedef oluşturuldu ✓")

        def sil(d):
            async def sil_et(e):
                self.dialog_kapat(d)
                await self._islem(self.supa.tablo_sil, "hb_hedefler", h["id"], basari="Hedef silindi")
            return buton("Sil", sil_et, ft.Icons.DELETE_ROUNDED, tip="text")

        self._girdi_dialog("Hedefi düzenle" if h else "Yeni birikim hedefi",
                           [ad, tutar, tarih] + ([yazi("Kimin kasası?", 12, renk=ui.SOLUK), kasa] if self.yonetici else []),
                           kaydet, ek_eylem=sil if h.get("id") else None)

    def hedef_hareket(self, h, yon):
        tutar = ft.TextField(label="Tutar (₺)", keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)

        async def kaydet():
            t = hb.tutar_coz(tutar.value)
            if not t or t <= 0:
                return False
            kayit = {"tur": "Gider" if yon == "koy" else "Gelir", "tutar": t, "tarih": hb.iso_tarih(hb.simdi()),
                     "kategori": "Transfer / Birikim" if yon == "koy" else "Diğer Gelir", "urun": f"Birikim: {h['ad']}",
                     "aciklama": "Hedefe aktarım" if yon == "koy" else "Hedeften çekim", "kasa_sahibi": h["kasa_sahibi"],
                     "hedef_kasa": None, "hedef_id": h["id"]}
            await self._islem(self.supa.islem_ekle, [kayit], basari=("Hedefe eklendi ✓" if yon == "koy" else "Kasaya alındı ✓"))

        self._girdi_dialog(f"{h['ad']}: " + ("para koy" if yon == "koy" else "para çek"),
                           [tutar, yazi("Tutar " + (f"{self.ad(h['kasa_sahibi'])} kasasından düşer." if yon == "koy" else
                                                    f"{self.ad(h['kasa_sahibi'])} kasasına geri eklenir."), 11.5, renk=ui.SOLUK)],
                           kaydet)

    # ================================================================== faturalar + düzenli ödemeler
    def sayfa_faturalar(self):
        ogeler = []
        hat = self.hatirlatmalar()
        for h in hat:
            renk = {"gecikti": GIDER, "bugun": GIDER, "yarin": "#d97706"}.get(h["seviye"], AKTARIM)
            ogeler.append(ft.Container(content=ft.Row([ft.Icon(ft.Icons.ALARM_ROUNDED, color=renk), yazi(h["metin"], 13, True,
                                                                                                        renk=renk, expand=True)]),
                                       bgcolor=saydam(renk, "1f"), border_radius=14, padding=12))
        yukle = [buton("Fatura yükle", lambda e: self.page.run_task(self.fatura_sec, "resim"), ft.Icons.UPLOAD_FILE_ROUNDED,
                       expand=True),
                 buton("PDF", lambda e: self.page.run_task(self.fatura_sec, "pdf"), ft.Icons.PICTURE_AS_PDF_ROUNDED,
                       tip="outlined")]
        if self.mobil:
            yukle.insert(0, ft.IconButton(icon=ft.Icons.PHOTO_CAMERA_ROUNDED, icon_color="white", bgcolor="#f59e0b",
                                          on_click=lambda e: self.page.run_task(self.kamera_ekrani, "fatura"),
                                          tooltip="Kamerayla çek"))
        ogeler.append(ft.Row(yukle, spacing=8))

        # Düzenli ödemeler
        ay = hb.simdi().strftime("%Y-%m")
        ogeler.append(ft.Row([yazi("Düzenli ödemeler", 16, True, expand=True),
                              buton("Ekle", lambda e: self.duzenli_duzenle(), ft.Icons.ADD_ROUNDED, tip="text")]))
        for d in self.ek["duzenli"]:
            odendi = d.get("son_odenen") == ay
            simge, renk = kat_stil(d.get("kategori"))
            ogeler.append(ft.Container(content=ft.Row([
                simge_kutusu(simge, renk, 18, 36),
                ft.Column([yazi(d["ad"], 14, True), yazi(f"Her ayın {d['gun']}'i • {self.ad(d['kasa_sahibi'])}" if self.yonetici
                                                          else f"Her ayın {d['gun']}'i", 11.5, renk=ui.SOLUK)],
                          spacing=0, expand=True),
                ft.Column([yazi(hb.tl(d["tutar"]), 14, True),
                           ft.Container(content=yazi("Bu ay ödendi ✓" if odendi else "Öde", 11.5, True,
                                                     renk=GELIR if odendi else "white"),
                                        bgcolor=None if odendi else ANA, border_radius=12, padding=ft.Padding(10, 4, 10, 4),
                                        on_click=None if odendi else (lambda e, d=d: self.duzenli_ode(d)))],
                          horizontal_alignment=ft.CrossAxisAlignment.END, spacing=4)], spacing=10),
                bgcolor=ui.KART, border_radius=16, padding=12, shadow=golge(0.4),
                on_click=lambda e, d=d: self.duzenli_duzenle(d)))
        if not self.ek["duzenli"]:
            ogeler.append(kart(yazi("Kira, aidat gibi her ay ödenenleri ekleyin; günü gelince hatırlatılır, “Öde” deyince "
                                    "kasadan düşer. Zam gelince tutarı güncelleyebilirsiniz.", 12, renk=ui.SOLUK)))

        # Faturalar
        odenmemis = [f for f in self.ek["faturalar"] if not f.get("odendi")]
        odenmis = [f for f in self.ek["faturalar"] if f.get("odendi")]
        ogeler.append(yazi(f"Ödenmemiş faturalar ({len(odenmemis)})", 16, True))
        ogeler += [self.fatura_karti(f) for f in sorted(odenmemis, key=lambda f: f.get("son_odeme") or "9999")]
        if not odenmemis:
            ogeler.append(kart(yazi("Ödenmemiş fatura yok 👍", 12.5, renk=ui.SOLUK)))
        if odenmis:
            ogeler.append(yazi("Geçmiş faturalar", 16, True))
            turler = {}
            for f in odenmis:
                turler.setdefault(f["tur"], []).append(f)
            for tur, fs in turler.items():
                ogeler.append(self.fatura_trend(tur, fs))
                ogeler += [self.fatura_karti(f) for f in fs[:3]]
        return self._liste(ogeler)

    def fatura_karti(self, f):
        simge, renk = FATURA_SIMGE.get(f["tur"], FATURA_SIMGE["Diğer"])
        so = f.get("son_odeme")
        so_metin = dt.date.fromisoformat(so).strftime("%d.%m.%Y") if so else "—"
        kalan = (dt.date.fromisoformat(so) - hb.simdi().date()).days if so else None
        durum_renk = GELIR if f.get("odendi") else (GIDER if kalan is not None and kalan <= 1 else "#d97706")
        return ft.Container(content=ft.Column([
            ft.Row([simge_kutusu(_ikon(simge), renk, 20, 40),
                    ft.Column([yazi(f"{f['tur']} • {f.get('kurum') or ''}", 14, True, max_lines=1),
                               yazi(" • ".join(x for x in [f.get("donem"), (f"{float(f['tuketim']):g} {f.get('birim') or ''}"
                                                                           if f.get("tuketim") else None)] if x), 11.5,
                                    renk=ui.SOLUK)], spacing=0, expand=True),
                    ft.Column([yazi(hb.tl(f["tutar"]), 15, True),
                               yazi("Ödendi" if f.get("odendi") else f"Son gün {so_metin}", 11, True, renk=durum_renk)],
                              horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0)], spacing=10),
            *([ft.Container(content=yazi(f["analiz"], 11.5, renk=ui.YAZI), bgcolor=ui.ZEMIN2, border_radius=10, padding=10)]
              if f.get("analiz") else [])], spacing=8),
            bgcolor=ui.KART, border_radius=16, padding=12, shadow=golge(0.4), on_click=lambda e, f=f: self.fatura_detay(f))

    def fatura_trend(self, tur, fs):
        fs = sorted(fs, key=lambda f: f.get("fatura_tarihi") or f.get("son_odeme") or "")[-8:]
        enb = max(float(f["tutar"]) for f in fs) or 1
        _, renk = FATURA_SIMGE.get(tur, FATURA_SIMGE["Diğer"])
        cubuklar = [ft.Column([yazi(f"{float(f['tutar']):.0f}", 9.5, renk=ui.SOLUK),
                               ft.Container(height=max(4, 60 * float(f["tutar"]) / enb), width=26, bgcolor=renk, border_radius=6),
                               yazi((f.get("donem") or "")[:3], 9.5, renk=ui.SOLUK)],
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, alignment=ft.MainAxisAlignment.END)
                    for f in fs]
        return kart(ft.Column([yazi(f"{tur} – son {len(fs)} fatura", 12.5, True),
                               ft.Row(cubuklar, spacing=8, vertical_alignment=ft.CrossAxisAlignment.END, height=100,
                                      scroll=ft.ScrollMode.AUTO)], spacing=6), shadow=golge(0.4))

    def fatura_detay(self, f):
        d = ft.AlertDialog(title=yazi(f"{f['tur']} faturası", 17, True))
        satir = lambda k, v: ft.Row([yazi(k, 12, renk=ui.SOLUK, width=110), yazi(str(v), 13, expand=True)])
        icerik = [satir(k, v) for k, v in [("Kurum", f.get("kurum")), ("Abone no", f.get("abone_no")), ("Dönem", f.get("donem")),
                                           ("Tüketim", f"{float(f['tuketim']):g} {f.get('birim') or ''}" if f.get("tuketim") else None),
                                           ("Birim fiyat", f.get("birim_fiyat")), ("Tutar", hb.tl(f["tutar"])),
                                           ("Son ödeme", f.get("son_odeme")), ("Kasa", self.ad(f.get("kasa_sahibi"))),
                                           ("Ekleyen", f.get("ekleyen_ad")), ("Durum", "Ödendi" if f.get("odendi") else "Ödenmedi")]
                  if v]
        if f.get("analiz"):
            icerik.append(ft.Container(content=yazi(f["analiz"], 12), bgcolor=ui.ZEMIN2, border_radius=10, padding=10))
        d.content = ft.Column(icerik, tight=True, spacing=6, scroll=ft.ScrollMode.AUTO)

        async def ode(e):
            self.dialog_kapat(d)
            self.fatura_ode(f)

        async def gorsel(e):
            self.dialog_kapat(d)
            await self.fis_gorseli_goster(f.get("gorsel"))

        async def sil(e):
            self.dialog_kapat(d)
            await self._islem(self.supa.tablo_sil, "hb_faturalar", f["id"], basari="Fatura silindi")

        eylem = []
        if f.get("gorsel"):
            eylem.append(buton("Görsel", gorsel, ft.Icons.IMAGE_ROUNDED, tip="text"))
        eylem.append(buton("Sil", sil, ft.Icons.DELETE_ROUNDED, tip="text"))
        if not f.get("odendi"):
            eylem.append(buton("Ödendi", ode, ft.Icons.CHECK_ROUNDED))
        else:
            eylem.append(buton("Kapat", lambda e: self.dialog_kapat(d), tip="text"))
        d.actions = eylem
        self.dialog_ac(d)

    def fatura_ode(self, f):
        kasa = self._kasa_secici(f.get("kasa_sahibi"))

        async def kaydet():
            sahip = kasa.value if self.yonetici else self.ben["id"]
            kayit = {"tur": "Gider", "tutar": float(f["tutar"]), "tarih": hb.iso_tarih(hb.simdi()),
                     "firma": f.get("kurum"), "urun": f"{f['tur']} Faturası" + (f" ({f['donem']})" if f.get("donem") else ""),
                     "kategori": "Kira & Aidat & Faturalar", "kasa_sahibi": sahip, "hedef_kasa": None,
                     "fis_gorsel": f.get("gorsel"), "aciklama": "Fatura ödemesi"}
            try:
                eklenen = await self.arka(self.supa.islem_ekle, [kayit])
                await self._islem(self.supa.tablo_guncelle, "hb_faturalar", f["id"],
                                  {"odendi": True, "odeme_islem_id": (eklenen[0]["id"] if eklenen else None)},
                                  basari="Ödendi ✓ Kasadan düşüldü")
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self._girdi_dialog("Fatura ödendi", [yazi(f"{hb.tl(f['tutar'])} gider olarak kaydedilecek.", 13)] +
                           ([yazi("Hangi kasadan ödendi?", 12, renk=ui.SOLUK), kasa] if self.yonetici else []), kaydet, "Kaydet")

    async def fatura_sec(self, tip):
        dosya = await self.dosya_sec(tip)
        if dosya:
            await self.fatura_isle(dosya, tip)

    async def fatura_isle(self, veri, tip):
        self.bildir("Fatura okunuyor… (5-20 sn)")
        if tip == "pdf":
            hazir, mime, uzanti = veri, "application/pdf", "pdf"
        else:
            hazir, mime = await self.arka(hb.gorseli_hazirla, veri)
            uzanti = "jpg"
        yol, sonuc = await asyncio.gather(self.arka(self.supa.fis_yukle, hazir, uzanti, mime),
                                          self.arka(ak.fatura_analiz_et, hazir, mime, self.gemini_anahtari),
                                          return_exceptions=True)
        if isinstance(yol, Exception):
            yol = None
        if isinstance(sonuc, Exception):
            self.bildir(f"Otomatik okunamadı ({sonuc}); bilgileri elle girin.", GIDER)
            sonuc = {"tur": "Elektrik", "tutar": 0}
        self.fatura_onay(sonuc, yol)

    def fatura_onay(self, f, gorsel):
        tur = acilir("Fatura türü", ak.FATURA_TURLERI, f.get("tur") or "Diğer")
        kurum = ft.TextField(label="Kurum", value=f.get("kurum") or "", dense=True)
        donem = ft.TextField(label="Dönem", value=f.get("donem") or "", dense=True)
        tutar = ft.TextField(label="Tutar (₺)", value=f"{f.get('tutar') or 0:.2f}".replace(".", ","), dense=True,
                             keyboard_type=ft.KeyboardType.NUMBER)
        tuketim = ft.TextField(label="Tüketim", value=f"{f['tuketim']:g}" if f.get("tuketim") else "", dense=True, expand=True,
                               keyboard_type=ft.KeyboardType.NUMBER)
        birim = ft.TextField(label="Birim", value=f.get("birim") or "", dense=True, width=90)
        so = ft.TextField(label="Son ödeme (GG.AA.YYYY)", dense=True,
                          value=dt.date.fromisoformat(f["son_odeme"]).strftime("%d.%m.%Y") if f.get("son_odeme") else "")
        kasa = self._kasa_secici()

        async def kaydet():
            t = hb.tutar_coz(tutar.value)
            if t is None:
                self.bildir("Tutar gerekli.", GIDER)
                return False
            kayit = {"tur": tur.value, "kurum": kurum.value.strip() or None, "abone_no": f.get("abone_no"),
                     "donem": donem.value.strip() or None, "fatura_tarihi": f.get("fatura_tarihi"),
                     "son_odeme": hb.tarih_coz(so.value).date().isoformat() if (so.value or "").strip() else None,
                     "tuketim": hb.tutar_coz(tuketim.value), "birim": birim.value.strip() or None,
                     "birim_fiyat": f.get("birim_fiyat"), "tutar": t, "gorsel": gorsel,
                     "kasa_sahibi": kasa.value if self.yonetici else self.ben["id"]}
            onceki = next((x for x in sorted(self.ek["faturalar"], key=lambda x: x.get("fatura_tarihi") or x.get("son_odeme") or "",
                                             reverse=True) if x["tur"] == kayit["tur"]
                           and (not kayit["kurum"] or not x.get("kurum") or hb.urun_anahtari(x["kurum"])[:5] == hb.urun_anahtari(kayit["kurum"])[:5])),
                          None)
            kayit["analiz"] = ak.fatura_karsilastir(kayit, onceki)
            sonuc = await self._islem(self.supa.tablo_ekle, "hb_faturalar", kayit, basari="Fatura kaydedildi ✓")
            if sonuc is not None:
                self.dialog_ac(ft.AlertDialog(title=yazi("Fatura analizi", 17, True), content=yazi(kayit["analiz"], 13.5),
                                              actions=[buton("Tamam", lambda e: self.dialog_kapat(), tip="text")]))

        self._girdi_dialog("Faturayı kontrol et", [tur, kurum, donem, tutar, ft.Row([tuketim, birim], spacing=8), so] +
                           ([yazi("Kimin kasası?", 12, renk=ui.SOLUK), kasa] if self.yonetici else []), kaydet)

    def duzenli_duzenle(self, d=None):
        d = d or {}
        ad = ft.TextField(label="Ad (Kira, Aidat, Kreş…)", value=d.get("ad", ""), autofocus=not d)
        tutar = ft.TextField(label="Tutar (₺) – zam gelince buradan güncelleyin", keyboard_type=ft.KeyboardType.NUMBER,
                             value=f"{float(d['tutar']):.2f}".replace(".", ",") if d else "")
        gun = ft.TextField(label="Ayın kaçında ödenir?", value=str(d.get("gun", "")), keyboard_type=ft.KeyboardType.NUMBER)
        kategori = acilir("Kategori", self.kategoriler, d.get("kategori") or "Kira & Aidat & Faturalar")
        kasa = self._kasa_secici(d.get("kasa_sahibi"))

        async def kaydet():
            t = hb.tutar_coz(tutar.value)
            try:
                g = int(gun.value)
            except Exception:
                g = 0
            if not (ad.value or "").strip() or not t or not 1 <= g <= 31:
                self.bildir("Ad, tutar ve 1-31 arası gün gerekli.", GIDER)
                return False
            kayit = {"ad": ad.value.strip(), "tutar": t, "gun": g, "kategori": kategori.value,
                     "kasa_sahibi": kasa.value if self.yonetici else self.ben["id"]}
            if d.get("id"):
                eski = float(d["tutar"])
                await self._islem(self.supa.tablo_guncelle, "hb_duzenli", d["id"], kayit,
                                  basari=f"Güncellendi ✓" + (f" (zam %{(t - eski) / eski * 100:.0f})" if t != eski and eski else ""))
            else:
                await self._islem(self.supa.tablo_ekle, "hb_duzenli", kayit, basari="Düzenli ödeme eklendi ✓")

        def sil(dlg):
            async def sil_et(e):
                self.dialog_kapat(dlg)
                await self._islem(self.supa.tablo_sil, "hb_duzenli", d["id"], basari="Silindi")
            return buton("Sil", sil_et, ft.Icons.DELETE_ROUNDED, tip="text")

        self._girdi_dialog("Düzenli ödemeyi düzenle" if d else "Yeni düzenli ödeme",
                           [ad, tutar, gun, kategori] + ([yazi("Kimin kasası?", 12, renk=ui.SOLUK), kasa] if self.yonetici else []),
                           kaydet, ek_eylem=sil if d.get("id") else None)

    def duzenli_ode(self, d):
        tutar = ft.TextField(label="Ödenen tutar (₺)", value=f"{float(d['tutar']):.2f}".replace(".", ","),
                             keyboard_type=ft.KeyboardType.NUMBER)
        guncelle = ft.Checkbox(label="Bundan sonra bu tutar olsun (zam)", value=False)

        async def kaydet():
            t = hb.tutar_coz(tutar.value)
            if not t:
                return False
            kayit = {"tur": "Gider", "tutar": t, "tarih": hb.iso_tarih(hb.simdi()), "urun": d["ad"],
                     "kategori": d.get("kategori") or "Kira & Aidat & Faturalar", "kasa_sahibi": d["kasa_sahibi"],
                     "hedef_kasa": None, "aciklama": "Düzenli ödeme"}
            alan = {"son_odenen": hb.simdi().strftime("%Y-%m")}
            if guncelle.value:
                alan["tutar"] = t
            try:
                await self.arka(self.supa.islem_ekle, [kayit])
                await self._islem(self.supa.tablo_guncelle, "hb_duzenli", d["id"], alan, basari=f"{d['ad']} ödendi ✓")
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self._girdi_dialog(f"{d['ad']} ödemesi", [tutar, guncelle], kaydet, "Öde")

    # ================================================================== alışveriş listesi
    def sayfa_alisveris(self):
        urun = ft.TextField(hint_text="Ne lazım? (örn: süt 2 lt)", expand=True, dense=True, border_color="transparent")

        async def ekle(e=None):
            metin = (urun.value or "").strip()
            if not metin:
                return
            urun.value = ""
            parcalar = [p.strip() for p in metin.replace("\n", ",").split(",") if p.strip()]
            await self._islem(self.supa.tablo_ekle, "hb_alisveris", [{"urun": p} for p in parcalar])

        urun.on_submit = ekle

        async def degistir(a, deger):
            await self._islem(self.supa.tablo_guncelle, "hb_alisveris", a["id"],
                              {"alindi": deger, "alinma": hb.iso_tarih(hb.simdi()) if deger else None})

        async def temizle(e):
            for a in [a for a in self.ek["alisveris"] if a.get("alindi")]:
                try:
                    await self.arka(self.supa.tablo_sil, "hb_alisveris", a["id"])
                except Exception:
                    pass
            await self._islem(lambda: None)

        bekleyen = [a for a in self.ek["alisveris"] if not a.get("alindi")]
        alinan = [a for a in self.ek["alisveris"] if a.get("alindi")]
        ogeler = [ft.Container(content=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART_ROUNDED, color=GELIR), urun,
                                               ft.IconButton(icon=ft.Icons.ADD_CIRCLE_ROUNDED, icon_color=GELIR, on_click=ekle)]),
                               bgcolor=ui.KART, border_radius=18, padding=ft.Padding(14, 2, 4, 2), shadow=golge(0.5)),
                  yazi("Virgülle birden çok ürün ekleyebilirsiniz. Fiş kaydedilince eşleşen ürünler otomatik işaretlenir.",
                       11, renk=ui.SOLUK)]
        ogeler.append(yazi(f"Alınacaklar ({len(bekleyen)})", 15, True))
        for a in bekleyen:
            ogeler.append(ft.Container(content=ft.Row([
                ft.Checkbox(value=False, on_change=lambda e, a=a: self.page.run_task(degistir, a, True)),
                ft.Column([yazi(a["urun"], 14, True), yazi(f"{a.get('ekleyen_ad') or ''} ekledi • "
                                                          f"{hb.tarih_yerel(a.get('olusturma')):%d.%m %H:%M}", 10.5, renk=ui.SOLUK),
                           *self.aktuel_rozeti(a["urun"])],
                          spacing=0, expand=True),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_size=18,
                              on_click=lambda e, a=a: self.page.run_task(self._islem, self.supa.tablo_sil, "hb_alisveris", a["id"]))]),
                bgcolor=ui.KART, border_radius=14, padding=ft.Padding(4, 2, 4, 2)))
        if not bekleyen:
            ogeler.append(kart(yazi("Liste boş 🎉", 12.5, renk=ui.SOLUK)))
        if alinan:
            ogeler.append(ft.Row([yazi(f"Alındı ({len(alinan)})", 15, True, expand=True),
                                  buton("Temizle", temizle, ft.Icons.CLEANING_SERVICES_ROUNDED, tip="text")]))
            for a in alinan:
                ogeler.append(ft.Container(content=ft.Row([
                    ft.Checkbox(value=True, on_change=lambda e, a=a: self.page.run_task(degistir, a, False)),
                    yazi(a["urun"], 13, renk=ui.SOLUK, expand=True, style=ft.TextStyle(decoration=_UZERI_CIZILI))
                    if _UZERI_CIZILI is not None else yazi(a["urun"], 13, renk=ui.SOLUK, expand=True)]),
                    border_radius=14, padding=ft.Padding(4, 0, 4, 0)))
        if bekleyen:
            ogeler.insert(1, ft.Container(content=ft.Row([
                ft.Icon(ft.Icons.SAVINGS_ROUNDED, color="white"),
                ft.Column([yazi("Listeyi en ucuza tamamla", 14, True, renk="white"),
                           yazi("Yakınınızdaki marketlerin güncel fiyatlarıyla karşılaştır", 11, renk="#dcfce7")],
                          spacing=0, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color="white")], spacing=10),
                gradient=degrade(["#15803d", "#22c55e"]), bgcolor=GELIR, border_radius=18, padding=14, shadow=golge(0.8),
                on_click=self.listeyi_en_ucuza))
        return self._liste(ogeler)

    async def alisverisi_isaretle(self, urun_adlari):
        try:
            ids = ak.alisveris_eslestir(self.ek["alisveris"], urun_adlari)
            for i in ids:
                await self.arka(self.supa.tablo_guncelle, "hb_alisveris", i, {"alindi": True, "alinma": hb.iso_tarih(hb.simdi())})
            if ids:
                self.bildir(f"🛒 Alışveriş listesinden {len(ids)} ürün işaretlendi")
                await self.ek_verileri_yenile()
        except Exception as e:
            print("Alışveriş eşleştirme:", e)

    # ================================================================== borç / alacak
    def sayfa_borclar(self):
        acik = [b for b in self.ek["borclar"] if not b.get("kapandi")]
        alacak = sum(float(b["tutar"]) for b in acik if b["yon"] == "verdim")
        borc = sum(float(b["tutar"]) for b in acik if b["yon"] == "aldim")
        ogeler = [ft.Row([
            kart(ft.Column([yazi("Alacağım", 12, renk=ui.SOLUK), yazi(hb.tl(alacak), 18, True, renk=GELIR)], spacing=2),
                 expand=True, shadow=golge(0.5)),
            kart(ft.Column([yazi("Borcum", 12, renk=ui.SOLUK), yazi(hb.tl(borc), 18, True, renk=GIDER)], spacing=2),
                 expand=True, shadow=golge(0.5))], spacing=10),
            ft.Row([buton("Borç verdim", lambda e: self.borc_ekle("verdim"), ft.Icons.CALL_MADE_ROUNDED, expand=True),
                    buton("Borç aldım", lambda e: self.borc_ekle("aldim"), ft.Icons.CALL_RECEIVED_ROUNDED, tip="outlined",
                          expand=True)], spacing=8)]
        for b in self.ek["borclar"]:
            verdim = b["yon"] == "verdim"
            renk = GELIR if verdim else GIDER
            vade = b.get("vade")
            gecikti = vade and not b.get("kapandi") and dt.date.fromisoformat(vade) < hb.simdi().date()
            ogeler.append(ft.Container(content=ft.Row([
                simge_kutusu(ft.Icons.CALL_MADE_ROUNDED if verdim else ft.Icons.CALL_RECEIVED_ROUNDED, renk, 18, 36),
                ft.Column([yazi(b["kisi"], 14, True),
                           yazi(" • ".join(x for x in [("Alacak" if verdim else "Borç"), b.get("aciklama"),
                                                       dt.date.fromisoformat(b["tarih"]).strftime("%d.%m.%Y"),
                                                       (f"vade {dt.date.fromisoformat(vade):%d.%m}" if vade else None)] if x),
                                11, renk=GIDER if gecikti else ui.SOLUK)], spacing=0, expand=True),
                ft.Column([yazi(hb.tl(b["tutar"]), 14, True, renk=ui.SOLUK if b.get("kapandi") else renk),
                           yazi("Kapandı ✓" if b.get("kapandi") else ("Tahsil et" if verdim else "Öde"), 11.5, True,
                                renk=GELIR if b.get("kapandi") else ANA)],
                          horizontal_alignment=ft.CrossAxisAlignment.END, spacing=2)], spacing=10),
                bgcolor=ui.KART, border_radius=16, padding=12, shadow=golge(0.4), opacity=0.6 if b.get("kapandi") else 1,
                on_click=None if b.get("kapandi") else (lambda e, b=b: self.borc_kapat(b))))
        if not self.ek["borclar"]:
            ogeler.append(kart(yazi("Kayıt yok. Verdiğiniz/aldığınız borçları ekleyin; isterseniz kasaya da yansır.", 12.5,
                                    renk=ui.SOLUK)))
        return self._liste(ogeler)

    def borc_ekle(self, yon):
        kisi = ft.TextField(label="Kişi", autofocus=True)
        tutar = ft.TextField(label="Tutar (₺)", keyboard_type=ft.KeyboardType.NUMBER)
        aciklama = ft.TextField(label="Açıklama (isteğe bağlı)")
        vade = ft.TextField(label="Vade (GG.AA.YYYY, isteğe bağlı)")
        kasaya = ft.Checkbox(label="Kasaya yansıt (" + ("kasadan düşsün" if yon == "verdim" else "kasaya eklensin") + ")", value=True)
        kasa = self._kasa_secici()

        async def kaydet():
            t = hb.tutar_coz(tutar.value)
            if not (kisi.value or "").strip() or not t:
                self.bildir("Kişi ve tutar gerekli.", GIDER)
                return False
            sahip = kasa.value if self.yonetici else self.ben["id"]
            kayit = {"kisi": kisi.value.strip(), "yon": yon, "tutar": t, "aciklama": aciklama.value.strip() or None,
                     "vade": hb.tarih_coz(vade.value).date().isoformat() if (vade.value or "").strip() else None,
                     "kasa_sahibi": sahip}
            try:
                if kasaya.value:
                    await self.arka(self.supa.islem_ekle, [{
                        "tur": "Gider" if yon == "verdim" else "Gelir", "tutar": t, "tarih": hb.iso_tarih(hb.simdi()),
                        "kategori": "Kredi Kartı, Kredi Ödemesi & Borç" if yon == "verdim" else "Borç Tahsilatı",
                        "urun": f"Borç {'verildi' if yon == 'verdim' else 'alındı'}: {kayit['kisi']}", "kasa_sahibi": sahip,
                        "hedef_kasa": None, "aciklama": kayit["aciklama"]}])
                await self._islem(self.supa.tablo_ekle, "hb_borclar", kayit, basari="Kaydedildi ✓")
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self._girdi_dialog("Borç verdim" if yon == "verdim" else "Borç aldım",
                           [kisi, tutar, aciklama, vade, kasaya] + ([kasa] if self.yonetici else []), kaydet)

    def borc_kapat(self, b):
        verdim = b["yon"] == "verdim"
        kasaya = ft.Checkbox(label="Kasaya yansıt", value=True)

        async def kaydet():
            try:
                if kasaya.value:
                    await self.arka(self.supa.islem_ekle, [{
                        "tur": "Gelir" if verdim else "Gider", "tutar": float(b["tutar"]), "tarih": hb.iso_tarih(hb.simdi()),
                        "kategori": "Borç Tahsilatı" if verdim else "Kredi Kartı, Kredi Ödemesi & Borç",
                        "urun": f"Borç {'tahsil edildi' if verdim else 'ödendi'}: {b['kisi']}", "kasa_sahibi": b["kasa_sahibi"],
                        "hedef_kasa": None}])
                await self._islem(self.supa.tablo_guncelle, "hb_borclar", b["id"],
                                  {"kapandi": True, "kapanis": hb.iso_tarih(hb.simdi())}, basari="Kapatıldı ✓")
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self._girdi_dialog(f"{b['kisi']} – {'tahsil edildi' if verdim else 'ödendi'}",
                           [yazi(f"{hb.tl(b['tutar'])} {'tahsil edildi' if verdim else 'ödendi'} olarak kapatılacak.", 13),
                            kasaya], kaydet, "Kapat")

    # ================================================================== fiyat takibi
    async def fiyat_verisi_yukle(self, zorla=False):
        if self.fiyat_verisi is None or zorla:
            try:
                self.fiyat_verisi = await self.arka(self.supa.rpc, "hb_fiyat_gecmisi")
            except Exception:
                self.fiyat_verisi = [x for x in self.islemler if x.get("tur") == "Gider"]
        return self.fiyat_verisi

    def sayfa_fiyatlar(self):
        liste = ft.Column(spacing=8)
        durum = {"arama": ""}

        def doldur():
            if self.fiyat_verisi is None:
                liste.controls = [ft.Row([ft.ProgressRing(width=20, height=20), yazi("Fiyat geçmişi yükleniyor…", 12, renk=ui.SOLUK)])]
                return
            ogeler = ak.fiyat_listesi(self.fiyat_verisi, durum["arama"])
            liste.controls = []
            for o in ogeler:
                deg = o["degisim"]
                liste.controls.append(ft.Container(content=ft.Row([
                    ft.Column([yazi(o["urun"], 13.5, True, max_lines=1),
                               yazi(f"{o['adet']} kez alındı • en ucuz {o['en_ucuz_firma'] or '?'} {hb.tl(o['en_ucuz'])}", 11,
                                    renk=ui.SOLUK)], spacing=0, expand=True),
                    ft.Column([yazi(hb.tl(o["son_fiyat"]), 14, True), yazi(
                        (("▲ %" if deg > 0 else "▼ %") + f"{abs(deg):.0f}") if deg is not None and abs(deg) >= 1 else (o["son_firma"] or ""),
                        11, True, renk=GIDER if deg and deg > 0 else (GELIR if deg and deg < 0 else ui.SOLUK))],
                        horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0)]),
                    bgcolor=ui.KART, border_radius=14, padding=12, shadow=golge(0.3), on_click=lambda e, o=o: self.fiyat_detay(o)))
            if not ogeler:
                liste.controls.append(kart(yazi("Eşleşen ürün yok.", 12.5, renk=ui.SOLUK)))

        def ara(e):
            durum["arama"] = e.control.value or ""
            doldur()
            self.guncelle()

        async def yukle():
            await self.fiyat_verisi_yukle()
            doldur()
            self.guncelle()

        if self.fiyat_verisi is None:
            self.page.run_task(yukle)
        doldur()
        return self._liste([ft.Container(content=ft.TextField(hint_text="Ürün ara: yumurta, süt, deterjan…",
                                                              prefix_icon=ft.Icons.SEARCH_ROUNDED, on_change=ara, dense=True,
                                                              border_color="transparent", bgcolor=ui.KART, border_radius=16),
                                         shadow=golge(0.4), border_radius=16),
                            yazi("Kendi fişlerinizden fiyat geçmişi", 13, True, renk=ui.SOLUK), liste,
                            ft.Divider(), self.aktuel_karti(),
                            ft.Divider(), yazi("Güncel market fiyatları", 16, True), self.market_arama_karti()])

    def fiyat_detay(self, o):
        satirlar = [ft.Row([yazi(hb.tarih_yerel(k.get("tarih")).strftime("%d.%m.%Y"), 12, renk=ui.SOLUK, width=86),
                            yazi(k.get("firma") or "?", 12.5, expand=True), yazi(k.get("miktar") or "", 11, renk=ui.SOLUK),
                            yazi(hb.tl(ak._birim_fiyat(k)), 13, True)]) for k in o["kayitlar"][:40]]
        self.dialog_ac(ft.AlertDialog(title=yazi(o["urun"], 16, True),
                                      content=ft.Column(satirlar, tight=True, scroll=ft.ScrollMode.AUTO, spacing=6),
                                      actions=[buton("Kapat", lambda e: self.dialog_kapat(), tip="text")]))

    # ================================================================== akıllı rapor
    def sayfa_rapor(self):
        bas, bit = self.donem
        once_bas, once_bit = hb.butce_donemi(bas, -1)
        kutu = ft.Column(spacing=8)
        yorum_kutusu = ft.Column()
        durum = {"onceki": None}

        def ciz():
            if durum["onceki"] is None:
                kutu.controls = [ft.Row([ft.ProgressRing(width=20, height=20), yazi("Önceki dönem yükleniyor…", 12, renk=ui.SOLUK)])]
                return
            simdi_oz, once_oz = hb.donem_ozeti(self.islemler), hb.donem_ozeti(durum["onceki"])
            kutu.controls = [ft.Row([
                kart(ft.Column([yazi("Bu dönem gider", 11.5, renk=ui.SOLUK), yazi(hb.tl(simdi_oz["gider"]), 16, True)], spacing=2),
                     expand=True, shadow=golge(0.4)),
                kart(ft.Column([yazi("Önceki dönem", 11.5, renk=ui.SOLUK), yazi(hb.tl(once_oz["gider"]), 16, True)], spacing=2),
                     expand=True, shadow=golge(0.4))], spacing=10)]
            for s in ak.donem_karsilastir(self.islemler, durum["onceki"])[:12]:
                simge, renk = kat_stil(s["kategori"])
                artti = s["fark"] > 0
                kutu.controls.append(ft.Container(content=ft.Row([
                    ft.Icon(simge, color=renk, size=18),
                    ft.Column([yazi(s["kategori"], 12.5, True, max_lines=1),
                               yazi(f"{hb.tl(s['onceki'])} → {hb.tl(s['simdi'])}", 11, renk=ui.SOLUK)], spacing=0, expand=True),
                    yazi(("▲ " if artti else "▼ ") + hb.tl(abs(s["fark"])), 12.5, True, renk=GIDER if artti else GELIR)],
                    spacing=10), bgcolor=ui.KART, border_radius=14, padding=10))

        async def yukle():
            try:
                durum["onceki"] = await self.arka(self.supa.islemler, once_bas, once_bit)
            except Exception:
                durum["onceki"] = []
            ciz()
            self.guncelle()

        async def yorum(e):
            if durum["onceki"] is None:
                return
            yorum_kutusu.controls = [ft.Row([ft.ProgressRing(width=20, height=20), yazi("Yapay zeka yorumluyor…", 12, renk=ui.SOLUK)])]
            self.guncelle()
            adlar = {k: v["ad"] for k, v in self.profiller.items()}
            metin = "\n\n".join([ak.veri_baglami(self.islemler, adlar, f"Bu dönem {hb.donem_etiketi(bas, bit)}", 400),
                                 ak.veri_baglami(durum["onceki"], adlar, f"Önceki dönem {hb.donem_etiketi(once_bas, once_bit)}", 400)])
            try:
                cevap = await self.arka(ak.donem_yorumu, metin, self.gemini_anahtari)
                self._son_yorum = cevap
                yorum_kutusu.controls = [ft.Container(content=ft.Markdown(cevap) if hasattr(ft, "Markdown") else yazi(cevap, 13),
                                                      bgcolor=saydam("#7c3aed", "14"), border_radius=16, padding=14)]
            except Exception as ex:
                yorum_kutusu.controls = [yazi(f"Yorum alınamadı: {ex}", 12, renk=GIDER)]
            self.guncelle()

        async def indir(tur):
            adlar = {k: v["ad"] for k, v in self.profiller.items()}
            baslik = hb.donem_etiketi(bas, bit)
            try:
                if tur == "xlsx":
                    veri = await self.arka(ak.rapor_xlsx, self.islemler, adlar, baslik)
                else:
                    renkler = {k: kat_stil(k)[1] for k in self.kategoriler}
                    veri = await self.arka(ak.rapor_pdf, self.islemler, adlar, baslik, renkler, getattr(self, "_son_yorum", None))
                await self.dosya_kaydet(f"HaneButcesi_{bas:%d.%m.%Y}_{bit:%d.%m.%Y}.{tur}", veri)
            except Exception as ex:
                self.bildir(f"Rapor oluşturulamadı: {ex}", GIDER)

        self.page.run_task(yukle)
        ciz()
        return self._liste([
            self.donem_cubugu(),
            ft.Row([buton("Excel", lambda e: self.page.run_task(indir, "xlsx"), ft.Icons.TABLE_VIEW_ROUNDED, tip="tonal", expand=True),
                    buton("PDF", lambda e: self.page.run_task(indir, "pdf"), ft.Icons.PICTURE_AS_PDF_ROUNDED, tip="tonal",
                          expand=True)], spacing=8),
            ft.Container(content=ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color="white"),
                                         yazi("Yapay zeka dönem yorumu ve tasarruf önerileri", 13, True, renk="white", expand=True),
                                         ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color="white")]),
                         gradient=degrade(["#6d28d9", "#a855f7"]), bgcolor="#7c3aed", border_radius=16, padding=14,
                         on_click=yorum),
            yorum_kutusu, yazi("Kategori karşılaştırması (önceki döneme göre)", 15, True), kutu])

    # ================================================================== asistan
    def sayfa_asistan(self):
        mesajlar = ft.Column(spacing=10)
        alan = ft.TextField(hint_text="Sorunuzu yazın ya da 🎙️ ile sorun…", expand=True,
                            multiline=True, min_lines=1, max_lines=3, dense=True, border_color="transparent")

        def balon(m):
            ben = m["kim"] == "ben"
            return ft.Row([ft.Container(content=ft.Markdown(m["metin"]) if (not ben and hasattr(ft, "Markdown")) else
                                        yazi(m["metin"], 13.5, renk="white" if ben else ui.YAZI, selectable=True),
                                        bgcolor=ANA if ben else ui.KART, border_radius=16, padding=12, shadow=golge(0.3),
                                        width=300 if not ben else None)],
                          alignment=ft.MainAxisAlignment.END if ben else ft.MainAxisAlignment.START)

        def ciz():
            mesajlar.controls = [balon(m) for m in self.sohbet] or [kart(ft.Column([
                yazi("Verilerinize dayanarak cevap veririm. Örnekler:", 12.5, True),
                *[ft.Container(content=yazi(o, 12.5, renk=ANA), on_click=lambda e, o=o: self.page.run_task(sor, o), padding=4)
                  for o in ("Bu dönem sigaraya ne kadar verdik?", "En çok hangi markette alışveriş yaptık?",
                            "Geçen döneme göre neye fazla harcadık?", "Abur cubura günde ortalama ne gidiyor?")]], spacing=4))]

        async def sor(soru=None):
            soru = (soru or alan.value or "").strip()
            if not soru:
                return
            alan.value = ""
            self.sohbet.append({"kim": "ben", "metin": soru})
            self.sohbet.append({"kim": "ai", "metin": "…"})
            ciz()
            self.guncelle()
            bas, bit = self.donem
            once = hb.butce_donemi(bas, -1)
            try:
                onceki = await self.arka(self.supa.islemler, *once)
            except Exception:
                onceki = []
            adlar = {k: v["ad"] for k, v in self.profiller.items()}
            baglam = "\n\n".join([ak.veri_baglami(self.islemler, adlar, f"Bu dönem ({hb.donem_etiketi(bas, bit)})"),
                                  ak.veri_baglami(onceki, adlar, f"Önceki dönem ({hb.donem_etiketi(*once)})", 500)])
            try:
                cevap = await self.arka(ak.soru_cevapla, soru, baglam, self.gemini_anahtari)
            except Exception as ex:
                cevap = f"Cevap alınamadı: {ex}"
            self.sohbet[-1]["metin"] = cevap
            ciz()
            self.guncelle()

        async def gonder(e):
            await sor()

        alan.on_submit = gonder

        async def sesli_soru(veri, mime):
            self.bildir("🎧 Dinleniyor…")
            try:
                metin = await self.arka(ak.sesi_yaziya_dok, veri, mime, self.gemini_anahtari)
            except Exception as ex:
                self.bildir(f"Anlaşılamadı: {ex}", GIDER)
                return
            if metin:
                await sor(metin)

        ciz()
        return ft.Column([
            ft.Container(content=ft.ListView(controls=[mesajlar], padding=16, auto_scroll=True), expand=True),
            ft.Container(content=ft.Row([alan, self.ses_dugmesi(sesli_soru, "Sesli sor"),
                                         ft.IconButton(icon=ft.Icons.SEND_ROUNDED, icon_color=ANA, on_click=gonder)]),
                         bgcolor=ui.KART, border_radius=20, padding=ft.Padding(14, 2, 4, 2), margin=ft.Margin(12, 0, 12, 12)
                         if hasattr(ft, "Margin") else None, shadow=golge(0.6))], expand=True, spacing=0)

    # ================================================================== ayarlar (tema + PIN eklenmiş)
    def sayfa_ayarlar(self):
        return self.ayarlar_ekrani()

    # ================================================================== dosya seçme / kaydetme
    async def dosya_sec(self, tip):
        if not self.picker:
            self.bildir("Dosya seçici kullanılamıyor.", GIDER)
            return None
        kw = dict(allow_multiple=False)
        kw.update(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"]) if tip == "pdf" else \
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
            return None
        dosyalar = sonuc if isinstance(sonuc, list) else getattr(sonuc, "files", None)
        if not dosyalar:
            return None
        f = dosyalar[0]
        veri = getattr(f, "bytes", None)
        if not veri and getattr(f, "path", None):
            try:
                with open(f.path, "rb") as fp:
                    veri = fp.read()
            except Exception as e:
                self.bildir(f"Dosya okunamadı: {e}", GIDER)
                return None
        return bytes(veri) if veri else None

    async def dosya_kaydet(self, ad, veri: bytes):
        if not self.picker:
            raise RuntimeError("Dosya kaydedici yok")
        yol = None
        try:
            yol = self.picker.save_file(file_name=ad, src_bytes=veri)
        except TypeError:
            yol = self.picker.save_file(file_name=ad)
        if inspect.isawaitable(yol):
            yol = await yol
        if yol and isinstance(yol, str):
            try:
                if not os.path.exists(yol) or os.path.getsize(yol) == 0:
                    with open(yol, "wb") as f:
                        f.write(veri)
            except Exception:
                pass
            self.bildir(f"Kaydedildi ✓ {os.path.basename(yol)}", GELIR)
        elif yol is None:
            # bazı mobil sürümlerde kaydetme sonucu dönmez; dosya seçilen yere yazılmıştır
            self.bildir("Rapor hazırlandı ✓", GELIR)

    # ================================================================== tema + PIN
    def _yerel_ayar(self):
        try:
            with open(os.path.join(hb.veri_klasoru(), "yerel_ayarlar.json"), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _yerel_ayar_yaz(self, **kw):
        a = self._yerel_ayar()
        a.update(kw)
        try:
            with open(os.path.join(hb.veri_klasoru(), "yerel_ayarlar.json"), "w", encoding="utf-8") as f:
                json.dump(a, f)
        except Exception as e:
            print("Yerel ayar yazılamadı:", e)

    def tema_ayarla(self, koyu: bool):
        ui.tema_uygula(koyu)
        self.page.theme_mode = ft.ThemeMode.DARK if koyu else ft.ThemeMode.LIGHT
        self.page.bgcolor = ui.ARKA
        for alan in ("theme", "dark_theme"):
            try:
                kw = {"color_scheme_seed": ANA}
                if ui._param_var(ft.Theme, "font_family"):
                    kw["font_family"] = ui.YAZI_TIPI
                if ui._param_var(ft.Theme, "use_material3"):
                    kw["use_material3"] = True
                setattr(self.page, alan, ft.Theme(**kw))
            except Exception:
                pass

    @staticmethod
    def _pin_ozeti(pin):
        return hashlib.sha256(("hane-butcesi:" + pin).encode()).hexdigest()

    def pin_ekrani(self, devam):
        """Uygulama açılışında PIN sorar; doğruysa devam() çağrılır."""
        self.page.navigation_bar = None
        self.page.floating_action_button = None
        if getattr(self, "alt_menu", None):
            self.alt_menu.visible = False
        girilen = {"pin": ""}
        noktalar = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=14)
        hata = yazi("", 12, renk=GIDER)

        def ciz_nokta():
            noktalar.controls = [ft.Container(width=16, height=16, border_radius=8,
                                              bgcolor=ANA if i < len(girilen["pin"]) else ui.CIZGI) for i in range(4)]

        async def bas(r):
            if r == "sil":
                girilen["pin"] = girilen["pin"][:-1]
            elif len(girilen["pin"]) < 4:
                girilen["pin"] += r
            ciz_nokta()
            if len(girilen["pin"]) == 4:
                if self._pin_ozeti(girilen["pin"]) == self._yerel_ayar().get("pin"):
                    await devam()
                    return
                girilen["pin"] = ""
                hata.value = "PIN yanlış"
                ciz_nokta()
            self.guncelle()

        async def unuttum(e):
            self._yerel_ayar_yaz(pin=None, biyometrik=False)
            await self.arka(self.supa.cikis)
            self.giris_ekrani("Kilit sıfırlandı. Şifrenizle giriş yapın.")

        ayar = self._yerel_ayar()
        pin_var, parmak = bool(ayar.get("pin")), bool(ayar.get("biyometrik"))

        async def parmak_izi(e=None):
            if await self.biyometrik_dogrula():
                await devam()
            elif not pin_var:
                hata.value = "Doğrulanamadı. Tekrar deneyin."
                self.guncelle()

        tus = lambda r: ft.Container(content=yazi("⌫" if r == "sil" else r, 24, True), width=72, height=72, border_radius=36,
                                     bgcolor=ui.KART, alignment=ORTA, shadow=golge(0.4),
                                     on_click=lambda e: self.page.run_task(bas, r))
        parmak_tus = ft.Container(content=ft.Icon(ft.Icons.FINGERPRINT_ROUNDED, size=34, color=ANA), width=72, height=72,
                                  border_radius=36, bgcolor=ui.KART, alignment=ORTA, shadow=golge(0.4),
                                  on_click=lambda e: self.page.run_task(parmak_izi))
        ciz_nokta()
        govde = [ft.Container(height=40),
                 ft.Icon(ft.Icons.FINGERPRINT_ROUNDED if parmak and not pin_var else ft.Icons.LOCK_ROUNDED, size=56, color=ANA),
                 yazi("PIN girin" if pin_var else "Kilidi açın", 20, True)]
        if pin_var:
            govde += [noktalar, hata,
                      *[ft.Row([tus(r) for r in sira], alignment=ft.MainAxisAlignment.CENTER, spacing=18)
                        for sira in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"))],
                      ft.Row([parmak_tus if parmak else ft.Container(width=72), tus("0"), tus("sil")],
                             alignment=ft.MainAxisAlignment.CENTER, spacing=18)]
        else:
            govde += [hata, parmak_tus, yazi("Parmak izi / yüz / ekran kilidi ile", 12, renk=ui.SOLUK)]
        govde.append(buton("Kilidi açamıyorum", unuttum, tip="text"))
        self.govde.content = ft.Column(govde, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, expand=True,
                                       scroll=ft.ScrollMode.AUTO)
        self.guncelle()
        if parmak:
            self.page.run_task(parmak_izi)

    def tema_pin_karti(self):
        a = self._yerel_ayar()

        def tema_degisti(e):
            koyu = bool(e.control.value)
            self._yerel_ayar_yaz(koyu=koyu)
            self.tema_ayarla(koyu)
            self.ekrani_ciz()

        pin1 = ft.TextField(label="Yeni 4 haneli PIN", password=True, max_length=4, keyboard_type=ft.KeyboardType.NUMBER,
                            dense=True)

        def pin_kaydet(e):
            p = (pin1.value or "").strip()
            if len(p) != 4 or not p.isdigit():
                self.bildir("PIN 4 rakam olmalı.", GIDER)
                return
            self._yerel_ayar_yaz(pin=self._pin_ozeti(p))
            pin1.value = ""
            self.bildir("PIN kilidi açıldı ✓ (bu cihazda)", GELIR)
            self.ekrani_ciz()

        def pin_kaldir(e):
            self._yerel_ayar_yaz(pin=None)
            self.bildir("PIN kilidi kapatıldı")
            self.ekrani_ciz()

        sw = ft.Switch(label="Karanlık tema", value=bool(a.get("koyu")), on_change=tema_degisti)

        async def parmak_degisti(e):
            acik = bool(e.control.value)
            if acik and not await self.biyometrik_dogrula():
                e.control.value = False
                self.bildir("Doğrulama yapılamadı; telefonda parmak izi/ekran kilidi tanımlı mı?", GIDER)
                self.guncelle()
                return
            self._yerel_ayar_yaz(biyometrik=acik)
            self.bildir("Parmak izi kilidi " + ("açıldı ✓" if acik else "kapatıldı"), GELIR if acik else None)

        parmak_sw = ft.Switch(label="Parmak izi / yüz tanıma ile kilit", value=bool(a.get("biyometrik")),
                              on_change=parmak_degisti, visible=self.mobil and self.yerel_kimlik is not None)
        return kart(ft.Column([
            yazi("Görünüm ve güvenlik", 14, True), self.tema_secici(), parmak_sw,
            yazi("PIN kilidi: uygulama her açıldığında 4 haneli PIN sorar (bu cihaza özel).", 11.5, renk=ui.SOLUK),
            ft.Row([ft.Container(content=pin1, expand=True), buton("Kaydet", pin_kaydet, tip="tonal")]),
            *([buton("PIN kilidini kapat", pin_kaldir, ft.Icons.LOCK_OPEN_ROUNDED, tip="text")] if a.get("pin") else [])],
            spacing=10), shadow=golge(0.5))
