"""
Hane Bütçesi v2 – kasa hareketleri, altın/döviz varlıkları, market fiyatları, kişi bütçesi,
okul harçlığı ayarı, yıl özeti, harcama takvimi, halka grafik, kişi renkleri, internetsiz kayıt,
mükerrer fiş kontrolü, tüm zamanlar görünümü.
"""
import asyncio
import datetime as dt
import json
import os

import flet as ft

import hb_akil as ak
import hb_core as hb
import hb_ui as ui
from hb_ui import (ANA, AKTARIM, GELIR, GIDER, ORTA, acilir, buton, cip, degrade, golge, kart, kat_stil, saydam,
                   simge_kutusu, yazi)

KISI_RENKLERI = {"yonetici": "#2563eb", "uye": "#db2777"}
YEDEK_KISI = ["#0d9488", "#7c3aed", "#ea580c"]


class EkOzellikler3:
    # ================================================================== kurulum
    def ek3_kur(self):
        self.tum_zamanlar = False
        self.kasa_secili = None
        self.cevrimdisi = False
        self.bekleyenler = self._yerel_oku("bekleyen_kayitlar") or []
        self.varliklar = []
        self.yil = hb.simdi().year
        self.konum = None
        self.aktuel = []
        self.aktuel_durum = {"calisiyor": False, "son": None, "hata": None}
        self.kuyumcu_farki = None

    # ================================================================== yerel dosyalar
    def _yerel_yol(self, ad):
        return os.path.join(hb.veri_klasoru(), f"{ad}.json")

    def _yerel_oku(self, ad):
        try:
            with open(self._yerel_yol(ad), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _yerel_yaz(self, ad, veri):
        try:
            with open(self._yerel_yol(ad), "w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False, default=str)
        except Exception as e:
            print("Yerel kayıt yazılamadı:", e)

    # ================================================================== kişi renkleri
    def kisi_renk(self, pid):
        p = self.profiller.get(pid) or {}
        if p.get("rol") in KISI_RENKLERI:
            return KISI_RENKLERI[p["rol"]]
        return YEDEK_KISI[sum(map(ord, str(pid))) % len(YEDEK_KISI)]

    def kisi_rozeti(self, pid, ad=None, boyut=18):
        ad = ad or self.ad(pid)
        renk = self.kisi_renk(pid)
        return ft.Container(content=yazi((ad or "?")[:1], boyut * 0.55, True, renk="white"), width=boyut, height=boyut,
                            border_radius=boyut / 2, bgcolor=renk, alignment=ORTA, tooltip=ad)

    # ================================================================== internetsiz kayıt
    async def kayit_ekle(self, kayitlar: list[dict]) -> bool:
        """İnternet yoksa kayıtları telefonda bekletir; bağlantı gelince gönderir. True: hemen gönderildi."""
        try:
            await self.arka(self.supa.islem_ekle, kayitlar)
            return True
        except hb.ApiHatasi as e:
            if e.durum != 0:
                raise
        for k in kayitlar:
            k = dict(k)
            k["_yerel_id"] = f"y{hb.simdi().timestamp():.0f}{len(self.bekleyenler)}"
            self.bekleyenler.append(k)
        self._yerel_yaz("bekleyen_kayitlar", self.bekleyenler)
        self.bildir(f"📴 İnternet yok: {len(kayitlar)} kayıt telefonda bekliyor, bağlantı gelince gönderilecek")
        return False

    async def bekleyenleri_gonder(self):
        if not self.bekleyenler:
            return
        gonder = [{k: v for k, v in x.items() if not k.startswith("_")} for x in self.bekleyenler]
        try:
            await self.arka(self.supa.islem_ekle, gonder)
        except Exception as e:
            print("Bekleyen kayıtlar gönderilemedi:", e)
            return
        n = len(self.bekleyenler)
        self.bekleyenler = []
        self._yerel_yaz("bekleyen_kayitlar", [])
        self.bildir(f"✅ İnternet geldi: bekleyen {n} kayıt gönderildi", GELIR)
        await self.verileri_yenile()

    def bekleyen_satirlari(self):
        """Henüz gönderilmemiş kayıtları listede göstermek için (gönderilene kadar)."""
        sonuc = []
        for k in self.bekleyenler:
            x = dict(k)
            x.setdefault("ekleyen_ad", self.ben["ad"] if self.ben else "")
            x["id"] = -1
            x["aciklama"] = "⏳ İnternet gelince gönderilecek"
            sonuc.append(x)
        return sonuc

    def onbellege_yaz(self):
        self._yerel_yaz("onbellek", {"ben": self.ben, "profiller": self.profiller, "islemler": self.islemler,
                                     "bakiyeler": self.bakiyeler, "zaman": hb.iso_tarih(hb.simdi())})

    def onbellekten_oku(self):
        o = self._yerel_oku("onbellek")
        if not o:
            return False
        self.islemler = o.get("islemler") or []
        self.bakiyeler = o.get("bakiyeler") or []
        if not self.profiller:
            self.profiller = o.get("profiller") or {}
        if not self.ben:
            self.ben = o.get("ben")
        return True

    # ================================================================== tüm zamanlar
    def tum_zamanlar_cipi(self):
        async def degistir(e):
            self.tum_zamanlar = not self.tum_zamanlar
            await self.verileri_yenile()

        return cip("Tüm zamanlar", self.tum_zamanlar, degistir, "#7c3aed", ft.Icons.ALL_INCLUSIVE_ROUNDED)

    # ================================================================== kasa hareketleri
    def kasa_ac(self, pid=None):
        self.kasa_secili = pid or self.ben["id"]
        self.menu_ac("kasa")

    def sayfa_kasa(self):
        pid = self.kasa_secili or self.ben["id"]
        kutu = ft.Column(spacing=8)
        durum = {"filtre": "giris", "veri": None}
        cipler = ft.Row(spacing=6, wrap=True)

        def ciz():
            cipler.controls = [cip(a, durum["filtre"] == k, lambda e, k=k: sec(k), renk)
                               for k, a, renk in (("giris", "Para girişleri", GELIR), ("aktarim", "Aktarımlar", AKTARIM),
                                                  ("cikis", "Giderler", GIDER), ("tum", "Tümü", ANA))]
            if durum["veri"] is None:
                kutu.controls = [ft.Row([ft.ProgressRing(width=20, height=20), yazi("Kasa geçmişi yükleniyor…", 12, renk=ui.SOLUK)])]
                return
            satirlar = []
            for i in durum["veri"]:
                gelen = (i["tur"] == "Gelir" and i.get("kasa_sahibi") == pid) or (i["tur"] == "Aktarım" and i.get("hedef_kasa") == pid)
                giden = (i["tur"] == "Gider" and i.get("kasa_sahibi") == pid) or (i["tur"] == "Aktarım" and i.get("kasa_sahibi") == pid)
                f = durum["filtre"]
                if (f == "giris" and gelen) or (f == "aktarim" and i["tur"] == "Aktarım") or (f == "cikis" and giden) or \
                        (f == "tum" and (gelen or giden)):
                    satirlar.append((i, gelen))
            giris = sum(float(i["tutar"]) for i, g in satirlar if g)
            cikis = sum(float(i["tutar"]) for i, g in satirlar if not g)
            ogeler = [ft.Row([
                kart(ft.Column([yazi("Giren", 11.5, renk=ui.SOLUK), yazi(hb.tl(giris), 16, True, renk=GELIR)], spacing=2),
                     expand=True, shadow=golge(0.4)),
                kart(ft.Column([yazi("Çıkan", 11.5, renk=ui.SOLUK), yazi(hb.tl(cikis), 16, True, renk=GIDER)], spacing=2),
                     expand=True, shadow=golge(0.4))], spacing=10)]
            aylar = {}
            for i, g in satirlar:
                d = hb.tarih_yerel(i.get("tarih"))
                aylar.setdefault((d.year, d.month), []).append((i, g))
            for (y, a) in sorted(aylar, reverse=True):
                ks = aylar[(y, a)]
                net = sum(float(i["tutar"]) * (1 if g else -1) for i, g in ks)
                ogeler.append(ft.Container(content=ft.Row([yazi(f"{ui.AYLAR_UZUN[a - 1]} {y}", 13, True, renk=ui.SOLUK, expand=True),
                                                           yazi(hb.tl(net, isaret=True), 12, True,
                                                                renk=GELIR if net >= 0 else GIDER)]),
                                           padding=ft.Padding(4, 10, 4, 0)))
                for i, g in ks:
                    if i["tur"] == "Aktarım":
                        baslik = f"{self.ad(i.get('kasa_sahibi'))} ➜ {self.ad(i.get('hedef_kasa'))}"
                        simge, renk = ft.Icons.SWAP_HORIZ_ROUNDED, AKTARIM
                    else:
                        baslik = i.get("urun") or i.get("kategori") or i["tur"]
                        simge, renk = kat_stil(i.get("kategori"), i["tur"])
                    ogeler.append(ft.Container(content=ft.Row([
                        simge_kutusu(simge, renk, 18, 36),
                        ft.Column([yazi(baslik, 13, True, max_lines=1),
                                   yazi(" • ".join(x for x in [i.get("firma") or i.get("aciklama"),
                                                               hb.tarih_goster(i.get("tarih"))] if x), 11, renk=ui.SOLUK)],
                                  spacing=0, expand=True),
                        yazi(("+" if g else "-") + hb.tl(i["tutar"]), 13, True, renk=GELIR if g else ui.YAZI)], spacing=10),
                        bgcolor=ui.KART, border_radius=14, padding=10, on_click=lambda e, i=i: self.islem_detay(i)))
            if not satirlar:
                ogeler.append(kart(yazi("Kayıt yok.", 12.5, renk=ui.SOLUK)))
            kutu.controls = ogeler

        def sec(k):
            durum["filtre"] = k
            ciz()
            self.guncelle()

        async def yukle():
            q = hb.urllib.parse.quote
            sorgu = (f"select=*&or=" + q(f"(kasa_sahibi.eq.{pid},hedef_kasa.eq.{pid})") +
                     "&order=tarih.desc,id.desc&limit=5000")
            try:
                durum["veri"] = await self.arka(self.supa.tablo, "hb_islemler", sorgu)
            except Exception:
                durum["veri"] = [i for i in self.islemler if pid in (i.get("kasa_sahibi"), i.get("hedef_kasa"))]
            ciz()
            self.guncelle()

        bak = {b["kisi"]: float(b.get("bakiye") or 0) for b in self.bakiyeler}
        renk = self.kisi_renk(pid)
        ust = ft.Container(content=ft.Row([
            self.kisi_rozeti(pid, boyut=44),
            ft.Column([yazi(f"{self.ad(pid)} kasası", 14, renk="#e0f2fe"), yazi(hb.tl(bak.get(pid, 0)), 26, True, renk="white")],
                      spacing=0, expand=True)], spacing=12),
            bgcolor=renk, gradient=degrade([renk, ANA]), border_radius=20, padding=16, shadow=golge(1))
        secici = []
        if self.yonetici and len(self.profiller) > 1:
            secici = [ft.Row([cip(p["ad"], pid == p["id"], lambda e, i=p["id"]: self.kasa_ac(i), self.kisi_renk(p["id"]))
                              for p in self.profiller.values()], spacing=6)]
        self.page.run_task(yukle)
        ciz()
        return self._liste([ust, *secici, cipler, kutu])

    # ================================================================== varlıklar (altın / döviz)
    async def varliklari_yukle(self):
        try:
            self.varliklar = await self.arka(self.supa.tablo, "hb_varliklar", "select=*&order=durum,tarih.desc")
        except Exception:
            self.varliklar = []

    def sayfa_varliklar(self):
        kutu = ft.Column(spacing=10)
        durum = {"kur": None, "ham": None, "hata": None}

        def ciz():
            kur = durum["kur"] or {}
            elde = [v for v in self.varliklar if v.get("durum") == "elde"]
            toplam_deger = toplam_maliyet = 0.0
            gruplar = {}
            for v in elde:
                gruplar.setdefault(v["tur"], []).append(v)
            kartlar = []
            for tur, vs in gruplar.items():
                ad, birim, _ = ak.VARLIK_TURLERI.get(tur, (tur, "", []))
                miktar = sum(float(v["miktar"]) for v in vs)
                fiyat = (kur.get(tur) or {}).get("alis")
                deger = miktar * fiyat if fiyat else None
                maliyet = sum(float(v["miktar"]) * float(v["birim_maliyet"]) for v in vs if v.get("birim_maliyet"))
                bilinen = all(v.get("birim_maliyet") for v in vs)
                if deger:
                    toplam_deger += deger
                if bilinen:
                    toplam_maliyet += maliyet
                kz = (deger - maliyet) if (deger and bilinen and maliyet) else None
                kartlar.append(ft.Container(content=ft.Column([
                    ft.Row([simge_kutusu(ft.Icons.PAID_ROUNDED if tur in ("USD", "EUR", "GBP") else ft.Icons.DIAMOND_ROUNDED,
                                         "#ca8a04", 20, 40),
                            ft.Column([yazi(ad, 14, True), yazi(f"{miktar:g} {birim}" + (f" • birim {hb.tl(fiyat)}" if fiyat else ""),
                                                                 11.5, renk=ui.SOLUK)], spacing=0, expand=True),
                            ft.Column([yazi(hb.tl(deger) if deger else "—", 15, True),
                                       yazi((("+" if kz >= 0 else "") + hb.tl(kz) + f" (%{kz / maliyet * 100:.0f})") if kz is not None
                                            else ("maliyet girilmedi" if not bilinen else ""), 11, True,
                                            renk=GELIR if (kz or 0) >= 0 else GIDER)],
                                      horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0)], spacing=10),
                    ft.Row([buton("Aldım", lambda e, t=tur: self.varlik_ekle(t, True), ft.Icons.ADD_ROUNDED, tip="text"),
                            buton("Sattım", lambda e, t=tur, vs=vs: self.varlik_sat(t, vs, fiyat), ft.Icons.SELL_ROUNDED, tip="text"),
                            buton("Detay", lambda e, vs=vs: self.varlik_detay(vs), tip="text")],
                           alignment=ft.MainAxisAlignment.END, spacing=0)], spacing=4),
                    bgcolor=ui.KART, border_radius=18, padding=12, shadow=golge(0.5)))
            ust = ft.Container(content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.DIAMOND_ROUNDED, color="#fef3c7"), yazi("Altın & döviz varlığım", 13, renk="#fef3c7")]),
                yazi(hb.tl(toplam_deger), 30, True, renk="white"),
                yazi((("Kâr " if toplam_deger >= toplam_maliyet else "Zarar ") + hb.tl(abs(toplam_deger - toplam_maliyet))
                      + " • alış maliyeti " + hb.tl(toplam_maliyet)) if toplam_maliyet else "Güncel piyasa alış fiyatıyla",
                     12, renk="#fef9c3")], spacing=4),
                gradient=degrade(["#a16207", "#ca8a04", "#eab308"]), bgcolor="#ca8a04", border_radius=22, padding=18,
                shadow=golge(1))
            bilgi = []
            if durum["hata"]:
                bilgi.append(kart(yazi(f"Güncel kurlar alınamadı ({durum['hata']}); değerler gösterilemiyor.", 12, renk=GIDER),
                                  renk=ui.UYARI_ZEMIN))
            kur_satir = [yazi(f"{ak.VARLIK_TURLERI[k][0]}: {hb.tl(v['alis'])}", 11, renk=ui.SOLUK)
                         for k, v in kur.items() if k in ak.VARLIK_TURLERI][:8]
            f = self.kuyumcu_farki or {}
            kaynak = next((v.get("kaynak") for v in kur.values() if v.get("kaynak")), "")
            if f:
                kaynak_metni = (f"Altın: {kaynak} fiyatı Erzurum kuyumcu fiyatına göre düzeltildi "
                                f"({f.get('_tarih', '')} tarihinde eşitlendi). Döviz: {kaynak}.")
            else:
                kaynak_metni = (f"Kaynak: {kaynak or '—'} (Erzurum Kuyumcular Odası uygulaması da Harem Altın fiyatını baz alır). "
                                "Kuyumcu fiyatıyla birebir için “Erzurum fiyatıyla eşitle”.")
            esitle = ft.Container(content=ft.Row([
                ft.Icon(ft.Icons.STOREFRONT_ROUNDED, color="#a16207"),
                ft.Column([yazi("Erzurum fiyatıyla eşitle", 13.5, True),
                           yazi("Oda uygulamasındaki gram ve çeyrek fiyatını bir kez girin" if not f
                                else f"Son eşitleme: {f.get('_tarih', '')} – yenilemek için dokunun", 11, renk=ui.SOLUK)],
                          spacing=0, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=ui.SOLUK)], spacing=10),
                bgcolor=ui.KART, border_radius=16, padding=12, shadow=golge(0.4),
                on_click=lambda e: self.kuyumcu_esitle(durum.get("ham") or {}))
            kutu.controls = [ust, *bilgi,
                             ft.Row([buton("Mevcut varlığımı ekle", lambda e: self.varlik_ekle(None, False), ft.Icons.INVENTORY_2_ROUNDED,
                                           tip="outlined", expand=True),
                                     buton("Yeni aldım", lambda e: self.varlik_ekle(None, True), ft.Icons.ADD_SHOPPING_CART_ROUNDED,
                                           expand=True)], spacing=8),
                             *kartlar,
                             *([kart(yazi("Henüz varlık yok. Elinizdeki altın/dövizi “Mevcut varlığımı ekle” ile girin; kasadan düşmez. "
                                          "Yeni aldıklarınızı “Yeni aldım” ile girin; kasadan gider olarak düşer.", 12.5, renk=ui.SOLUK))]
                               if not kartlar else []),
                             esitle,
                             ft.Row(kur_satir, wrap=True, spacing=10),
                             yazi(kaynak_metni, 10.5, renk=ui.SOLUK)]

        async def yukle():
            await self.varliklari_yukle()
            await self.kuyumcu_farki_yukle()
            try:
                durum["ham"] = await self.arka(ak.kurlar)
                durum["kur"] = ak.yerel_kurlar(durum["ham"], self.kuyumcu_farki)
                if not durum["kur"]:
                    durum["hata"] = "kaynak yanıt vermedi"
            except Exception as e:
                durum["hata"] = str(e)
            ciz()
            self.guncelle()

        self.page.run_task(yukle)
        ciz()
        return self._liste([kutu])

    def varlik_ekle(self, tur=None, yeni_alim=True):
        turler = list(ak.VARLIK_TURLERI)
        tur_dd = acilir("Tür", [ak.VARLIK_TURLERI[t][0] for t in turler],
                        ak.VARLIK_TURLERI[tur][0] if tur else ak.VARLIK_TURLERI["ceyrek"][0])
        miktar = ft.TextField(label="Miktar (adet / gram / $…)", keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)
        fiyat = ft.TextField(label="Birim alış fiyatı (₺)" + ("" if yeni_alim else " – bilmiyorsanız boş bırakın"),
                             keyboard_type=ft.KeyboardType.NUMBER)
        tarih = ft.TextField(label="Alış tarihi (GG.AA.YYYY)", value=hb.simdi().strftime("%d.%m.%Y"))
        aciklama = ft.TextField(label="Not (isteğe bağlı)")
        kasa = self._kasa_secici()

        async def kaydet():
            m = hb.tutar_coz(miktar.value)
            f = hb.tutar_coz(fiyat.value)
            t = turler[[ak.VARLIK_TURLERI[x][0] for x in turler].index(tur_dd.value)]
            if not m or m <= 0 or (yeni_alim and not f):
                self.bildir("Miktar" + (" ve birim fiyat" if yeni_alim else "") + " gerekli.", GIDER)
                return False
            sahip = kasa.value if self.yonetici else self.ben["id"]
            islem_id = None
            try:
                if yeni_alim:
                    eklenen = await self.arka(self.supa.islem_ekle, [{
                        "tur": "Gider", "tutar": round(m * f, 2), "tarih": hb.iso_tarih(hb.tarih_coz(tarih.value)),
                        "urun": f"{m:g} {ak.VARLIK_TURLERI[t][1]} {ak.VARLIK_TURLERI[t][0]}", "kategori": "Yatırım & Altın & Döviz",
                        "miktar": f"{m:g} {ak.VARLIK_TURLERI[t][1]}", "birim_fiyat": f, "kasa_sahibi": sahip, "hedef_kasa": None,
                        "aciklama": (aciklama.value or "").strip() or "Varlık alımı"}])
                    islem_id = eklenen[0].get("id") if eklenen else None
                await self._islem(self.supa.tablo_ekle, "hb_varliklar", {
                    "tur": t, "miktar": m, "birim_maliyet": f, "tarih": hb.tarih_coz(tarih.value).date().isoformat(),
                    "aciklama": (aciklama.value or "").strip() or None, "kasa_sahibi": sahip, "islem_id": islem_id},
                    basari="Varlık eklendi ✓" + (" (kasadan düşüldü)" if yeni_alim else ""))
                await self.varliklari_yukle()
                self.ekrani_ciz()
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self._girdi_dialog("Yeni alım (kasadan düşer)" if yeni_alim else "Elimdeki varlık (kasayı etkilemez)",
                           [tur_dd, miktar, fiyat, tarih, aciklama] + ([yazi("Kimin kasası?", 12, renk=ui.SOLUK), kasa]
                                                                      if self.yonetici else []), kaydet)

    def varlik_sat(self, tur, vs, guncel):
        toplam = sum(float(v["miktar"]) for v in vs)
        miktar = ft.TextField(label=f"Satılan miktar (elde {toplam:g})", value=f"{toplam:g}", keyboard_type=ft.KeyboardType.NUMBER)
        fiyat = ft.TextField(label="Birim satış fiyatı (₺)", value=f"{guncel:.2f}".replace(".", ",") if guncel else "",
                             keyboard_type=ft.KeyboardType.NUMBER)

        async def kaydet():
            m, f = hb.tutar_coz(miktar.value), hb.tutar_coz(fiyat.value)
            if not m or not f or m > toplam + 1e-9:
                self.bildir("Geçerli miktar ve fiyat girin.", GIDER)
                return False
            kalan = m
            try:
                for v in sorted(vs, key=lambda v: v.get("tarih") or ""):  # önce eskiler
                    if kalan <= 0:
                        break
                    vm = float(v["miktar"])
                    if vm <= kalan + 1e-9:
                        await self.arka(self.supa.tablo_guncelle, "hb_varliklar", v["id"],
                                        {"durum": "satildi", "satis_fiyati": f, "satis_tarihi": hb.simdi().date().isoformat()})
                        kalan -= vm
                    else:
                        await self.arka(self.supa.tablo_guncelle, "hb_varliklar", v["id"], {"miktar": vm - kalan})
                        kalan = 0
                await self._islem(self.supa.islem_ekle, [{
                    "tur": "Gelir", "tutar": round(m * f, 2), "tarih": hb.iso_tarih(hb.simdi()),
                    "kategori": "Diğer Gelir", "firma": "Varlık satışı",
                    "urun": f"{m:g} {ak.VARLIK_TURLERI.get(tur, (tur, ''))[1]} {ak.VARLIK_TURLERI.get(tur, (tur,))[0]} satışı",
                    "kasa_sahibi": vs[0]["kasa_sahibi"], "hedef_kasa": None}], basari="Satış kaydedildi ✓ kasaya eklendi")
                await self.varliklari_yukle()
                self.ekrani_ciz()
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self._girdi_dialog(f"{ak.VARLIK_TURLERI.get(tur, (tur,))[0]} sattım", [miktar, fiyat], kaydet, "Sat")

    def varlik_detay(self, vs):
        satirlar = [ft.Row([yazi(dt.date.fromisoformat(v["tarih"]).strftime("%d.%m.%Y"), 12, renk=ui.SOLUK, width=90),
                            yazi(f"{float(v['miktar']):g}", 13, True, width=50),
                            yazi(hb.tl(v["birim_maliyet"]) if v.get("birim_maliyet") else "maliyet yok", 12, expand=True),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_size=18,
                                          on_click=lambda e, v=v: self.page.run_task(self._varlik_sil, v))]) for v in vs]
        self.dialog_ac(ft.AlertDialog(title=yazi("Alış kayıtları", 16, True),
                                      content=ft.Column(satirlar, tight=True, scroll=ft.ScrollMode.AUTO),
                                      actions=[buton("Kapat", lambda e: self.dialog_kapat(), tip="text")]))

    async def _varlik_sil(self, v):
        self.dialog_kapat()
        await self._islem(self.supa.tablo_sil, "hb_varliklar", v["id"], basari="Silindi (bağlı gider kaydı silinmedi)")
        await self.varliklari_yukle()
        self.ekrani_ciz()

    # ================================================================== konum + market fiyatları
    async def konum_al(self):
        if self.konum:
            return self.konum
        try:
            k = await self.arka(self.supa.ayar_oku, "ev_konumu")
            if k:
                self.konum = json.loads(k)
        except Exception:
            pass
        if not self.konum:
            self.konum = self._yerel_oku("ev_konumu")
        return self.konum

    def konum_karti(self):
        alan = ft.TextField(label="Ev konumu (örn: Palandöken, Erzurum)", dense=True)
        bilgi = yazi("", 11.5, renk=ui.SOLUK)

        async def yukle():
            k = await self.konum_al()
            bilgi.value = f"Kayıtlı: {k['ad'][:70]}" if k else "Henüz ayarlanmadı – market fiyatları için gerekli"
            self.guncelle()

        async def kaydet(e):
            if not (alan.value or "").strip():
                return
            try:
                sonuc = await self.arka(ak.konum_bul, (alan.value or "").strip())
            except Exception as ex:
                self.bildir(f"Konum bulunamadı: {ex}", GIDER)
                return
            if not sonuc:
                self.bildir("Konum bulunamadı; il ve ilçeyi yazmayı deneyin.", GIDER)
                return
            self.konum = {"enlem": sonuc[0], "boylam": sonuc[1], "ad": sonuc[2]}
            self._yerel_yaz("ev_konumu", self.konum)
            if self.yonetici:
                try:
                    await self.arka(self.supa.ayar_yaz, "ev_konumu", json.dumps(self.konum, ensure_ascii=False))
                except Exception:
                    pass
            self.bildir("Konum kaydedildi ✓", GELIR)
            await yukle()

        self.page.run_task(yukle)
        return kart(ft.Column([yazi("Market fiyatları için konum", 14, True), alan, bilgi,
                               buton("Konumu kaydet", kaydet, ft.Icons.PLACE_ROUNDED, tip="tonal")], spacing=8), shadow=golge(0.5))

    def market_arama_karti(self):
        alan = ft.TextField(hint_text="Güncel market fiyatı ara: süt 1 lt, yumurta 30…", dense=True, expand=True,
                            border_color="transparent")
        sonuc = ft.Column(spacing=6)

        async def ara(e=None):
            k = await self.konum_al()
            if not k:
                sonuc.controls = [kart(yazi("Önce Menü > Ayarlar'dan ev konumunu kaydedin.", 12, renk=GIDER), renk=ui.UYARI_ZEMIN)]
                self.guncelle()
                return
            if not (alan.value or "").strip():
                return
            sonuc.controls = [ft.Row([ft.ProgressRing(width=18, height=18), yazi("Marketlere bakılıyor…", 12, renk=ui.SOLUK)])]
            self.guncelle()
            try:
                bulunan = await self.arka(ak.mf_ara, (alan.value or "").strip(), k["enlem"], k["boylam"], 5, 15)
            except Exception as ex:
                sonuc.controls = [yazi(f"Market fiyatlarına ulaşılamadı: {ex}", 12, renk=GIDER)]
                self.guncelle()
                return
            sonuc.controls = [ft.Container(content=ft.Column([
                yazi(u["urun"] + (f" ({u['olcu']})" if u.get("olcu") else ""), 13, True, max_lines=2),
                ft.Row([ft.Container(content=yazi(f"{f['market']} {hb.tl(f['fiyat'])}", 11.5, True,
                                                  renk="white" if n == 0 else ui.YAZI),
                                     bgcolor=GELIR if n == 0 else ui.ZEMIN2, border_radius=10, padding=ft.Padding(8, 3, 8, 3))
                        for n, f in enumerate(u["fiyatlar"][:6])], wrap=True, spacing=4, run_spacing=4)], spacing=4),
                bgcolor=ui.KART, border_radius=14, padding=10) for u in bulunan[:12]] or \
                [yazi("Sonuç bulunamadı.", 12, renk=ui.SOLUK)]
            self.guncelle()

        alan.on_submit = ara
        return ft.Column([ft.Container(content=ft.Row([ft.Icon(ft.Icons.STOREFRONT_ROUNDED, color="#0891b2"), alan,
                                                       ft.IconButton(icon=ft.Icons.SEARCH_ROUNDED, on_click=ara)]),
                                       bgcolor=ui.KART, border_radius=16, padding=ft.Padding(12, 0, 4, 0), shadow=golge(0.4)),
                          yazi("Kaynak: marketfiyati.org.tr (TÜBİTAK) – yakınınızdaki BİM, A101, ŞOK, Migros, CarrefourSA, "
                               "Hakmar, Tarım Kredi şubeleri.", 10.5, renk=ui.SOLUK), sonuc], spacing=8)

    async def listeyi_en_ucuza(self, e=None):
        maddeler = [a["urun"] for a in self.ek["alisveris"] if not a.get("alindi")]
        if not maddeler:
            self.bildir("Listede alınacak ürün yok.")
            return
        k = await self.konum_al()
        if not k:
            self.bildir("Önce Menü > Ayarlar'dan ev konumunu kaydedin.", GIDER)
            return
        self.bildir(f"🛒 {len(maddeler)} ürün için marketlere bakılıyor…")
        try:
            r = await self.arka(ak.liste_en_ucuz, maddeler, k["enlem"], k["boylam"], 5)
        except Exception as ex:
            self.bildir(f"Market fiyatlarına ulaşılamadı: {ex}", GIDER)
            return
        satirlar = []
        for n, m in enumerate(r["marketler"][:7]):
            satirlar.append(ft.Container(content=ft.Row([
                yazi(("🏆 " if n == 0 else "") + m["market"], 14, True, expand=True),
                yazi(f"{m['bulunan']}/{r['madde_sayisi']} ürün", 11.5, renk=ui.SOLUK),
                yazi(hb.tl(m["toplam"]), 14, True, renk=GELIR if n == 0 else ui.YAZI)], spacing=10),
                bgcolor=saydam(GELIR, "18") if n == 0 else ui.ZEMIN2, border_radius=12, padding=10))
        satirlar.append(ft.Divider())
        satirlar.append(yazi("Her ürünün en ucuz seçeneği", 13, True))
        for u in r["urunler"]:
            b = u["en_iyi"]
            satirlar.append(ft.Row([yazi(u["madde"], 12.5, True, width=90),
                                    yazi(f"{b['market']}: {b['urun'][:40]}" if b else "bulunamadı", 11.5, renk=ui.SOLUK, expand=True),
                                    yazi(hb.tl(b["fiyat"]) if b else "", 12.5, True)]))
        aktuel_satir = []
        for m in maddeler:
            es = ak.aktuel_eslestir(self.aktuel, m, 0.6)
            if es:
                b = es[0]
                aktuel_satir.append(ft.Row([yazi(m, 12.5, True, width=90),
                                            yazi(f"{b['market']} aktüel: {b['urun'][:40]}", 11.5, renk=GELIR, expand=True),
                                            yazi(hb.tl(b["fiyat"]), 12.5, True, renk=GELIR)]))
        if aktuel_satir:
            satirlar += [ft.Divider(), yazi("🏷️ Bu hafta aktüelde olanlar", 13, True, renk=GELIR), *aktuel_satir]
        satirlar.append(yazi("Fiyatlar yakınınızdaki şubelerden; ürün eşleşmesi yaklaşık olabilir.", 10.5, renk=ui.SOLUK))
        self.dialog_ac(ft.AlertDialog(title=yazi("Listeyi en ucuza tamamla", 17, True),
                                      content=ft.Column(satirlar, tight=True, scroll=ft.ScrollMode.AUTO, spacing=6),
                                      actions=[buton("Kapat", lambda e: self.dialog_kapat(), tip="text")]))

    # ================================================================== kişi (harçlık) bütçesi
    def kisi_butcesi(self, pid):
        lim = self.ek["butceler"].get(f"kisi:{pid}")
        if not lim:
            return None
        harcanan = hb.donem_ozeti(self.donem_islemleri(), pid)["gider"]
        return harcanan, lim, harcanan / lim

    def donem_islemleri(self):
        return self.islemler  # tüm zamanlar görünümünde bile bütçe/takvim dönem içidir

    def kisi_butce_karti(self, pid):
        d = self.kisi_butcesi(pid)
        if not d:
            return None
        h, lim, oran = d
        renk = GIDER if oran >= 1 else ("#d97706" if oran >= 0.8 else self.kisi_renk(pid))
        from hb_ek import _ilerleme
        return ft.Container(content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, color=renk, size=18),
                    yazi(("Harçlık bütçem" if pid == self.ben["id"] else f"{self.ad(pid)} bütçesi") + " (bu dönem)", 13, True,
                         expand=True),
                    yazi(f"Kalan {hb.tl(max(lim - h, 0))}" if oran < 1 else f"{hb.tl(h - lim)} aşıldı", 12, True, renk=renk)]),
            _ilerleme(oran, renk), yazi(f"{hb.tl(h)} / {hb.tl(lim)}", 11, renk=ui.SOLUK)], spacing=6),
            bgcolor=ui.KART, border_radius=16, padding=14, shadow=golge(0.5))

    def kisi_butce_duzenle(self, pid):
        mevcut = self.ek["butceler"].get(f"kisi:{pid}")
        alan = ft.TextField(label="Dönem harçlık limiti (₺) – boş: kaldır", keyboard_type=ft.KeyboardType.NUMBER,
                            value=f"{mevcut:.0f}" if mevcut else "", autofocus=True)

        async def kaydet():
            t = hb.tutar_coz(alan.value)
            await self._islem(self.supa.butce_yaz, f"kisi:{pid}", t if t and t > 0 else None, basari="Kaydedildi ✓")

        self._girdi_dialog(f"{self.ad(pid)} – harçlık bütçesi", [alan, yazi(
            f"{self.ad(pid)} kendi ekranında kalan tutarı görür; %80'de ve aşılınca ikinize de bildirim gider.", 11.5,
            renk=ui.SOLUK)], kaydet)

    # ================================================================== okul harçlığı ayarı
    def harclik_karti(self):
        durum = {"a": None}
        aktif = ft.Switch(label="Okul günlerinde otomatik ekle")
        cocuk = ft.TextField(label="Çocuk sayısı", width=120, dense=True, keyboard_type=ft.KeyboardType.NUMBER)
        tutar = ft.TextField(label="Kişi başı (₺)", width=130, dense=True, keyboard_type=ft.KeyboardType.NUMBER)
        saat = ft.TextField(label="Saat", width=90, dense=True, value="08:30")
        kasa = self._kasa_secici()

        async def yukle():
            try:
                a = json.loads(await self.arka(self.supa.ayar_oku, "okul_harclik") or "{}")
            except Exception:
                a = {}
            aktif.value = bool(a.get("aktif"))
            cocuk.value = str(a.get("cocuk", 2))
            tutar.value = str(a.get("tutar", 10))
            saat.value = a.get("saat", "08:30")
            kasa.value = a.get("kasa") or self.ben["id"]
            durum["a"] = a
            self.guncelle()

        async def kaydet(e):
            a = {"aktif": bool(aktif.value), "cocuk": int(hb.tutar_coz(cocuk.value) or 1), "tutar": hb.tutar_coz(tutar.value) or 0,
                 "saat": (saat.value or "08:30").strip(), "kasa": kasa.value,
                 "baslangic": (durum["a"] or {}).get("baslangic") or hb.simdi().date().isoformat()}
            try:
                await self.arka(self.supa.ayar_yaz, "okul_harclik", json.dumps(a))
                durum["a"] = a
                self.bildir("Kaydedildi ✓ Okul günlerinde (tatiller hariç) otomatik eklenecek", GELIR)
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)

        self.page.run_task(yukle)
        return kart(ft.Column([yazi("Okul harçlığı otomatiği", 14, True),
                               yazi("Hafta içi okul günlerinde, MEB takvimindeki tatiller hariç, belirlenen saatte gider olarak eklenir.",
                                    11.5, renk=ui.SOLUK), aktif, ft.Row([cocuk, tutar, saat], spacing=8, wrap=True),
                               yazi("Hangi kasadan?", 12, renk=ui.SOLUK), kasa,
                               buton("Kaydet", kaydet, ft.Icons.SAVE_ROUNDED, tip="tonal")], spacing=8), shadow=golge(0.5))

    # ================================================================== özet görselleri
    def halka_karti(self, kategoriler: dict):
        if not kategoriler:
            return None
        toplam = sum(kategoriler.values()) or 1
        sirali = list(kategoriler.items())
        ana = sirali[:6]
        diger = sum(v for _, v in sirali[6:])
        dilimler = [(k, v, kat_stil(k)[1]) for k, v in ana] + ([("Diğerleri", diger, "#94a3b8")] if diger else [])
        try:
            png = ak.halka_png(dilimler, hb.tl(toplam).replace(",00", ""), "toplam gider", ui.KOYU, 440)
            if ui._param_var(ft.Image, "src_base64"):
                import base64
                gorsel = ft.Image(src_base64=base64.b64encode(png).decode(), width=200, height=200)
            else:
                gorsel = ft.Image(src=png, width=200, height=200)
        except Exception as e:
            print("Halka çizilemedi:", e)
            return None

        def kategoriye_git(k):
            self.filtre["arama"] = k if k != "Diğerleri" else ""
            self.filtre["tur"] = "Gider"
            self.sekmeye_git(1)

        efsane = [ft.Container(content=ft.Row([
            ft.Container(width=10, height=10, border_radius=5, bgcolor=r),
            yazi(k, 12, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            yazi(f"%{round(100 * v / toplam)}", 11.5, True, renk=ui.SOLUK)], spacing=6),
            on_click=lambda e, k=k: kategoriye_git(k), padding=ft.Padding(0, 3, 0, 3)) for k, v, r in dilimler]
        return kart(ft.Column([
            ft.Row([yazi("Harcama dağılımı", 15, True, expand=True), yazi("dokun: işlemler", 10.5, renk=ui.SOLUK)]),
            ft.ResponsiveRow([ft.Container(content=gorsel, alignment=ORTA, col={"xs": 12, "sm": 6}),
                              ft.Container(content=ft.Column(efsane, spacing=2), col={"xs": 12, "sm": 6},
                                           alignment=ORTA)], vertical_alignment=ft.CrossAxisAlignment.CENTER)
            if hasattr(ft, "ResponsiveRow") else ft.Row([gorsel, ft.Column(efsane, expand=True)])], spacing=10),
            dolgu=16, shadow=golge(0.6))

    def takvim_karti(self):
        bas, bit = self.donem
        bugun = hb.simdi().date()
        gunluk, gun_kayit = {}, {}
        for i in self.donem_islemleri():
            if i.get("tur") != "Gider" or (not self.yonetici and i.get("kasa_sahibi") != self.ben["id"]):
                continue
            g = hb.tarih_yerel(i.get("tarih")).date()
            gunluk[g] = gunluk.get(g, 0) + float(i.get("tutar") or 0)
            gun_kayit.setdefault(g, []).append(i)
        enb = max(gunluk.values()) if gunluk else 1
        tonlar = ["#ccfbf1", "#99f6e4", "#5eead4", "#2dd4bf", "#0d9488"]
        hucreler = [ft.Container(content=yazi(g, 10.5, True, renk=ui.SOLUK), alignment=ORTA, expand=1)
                    for g in ("Pt", "Sa", "Ça", "Pe", "Cu", "Ct", "Pz")]
        satirlar = [ft.Row(hucreler, spacing=4)]
        hafta = [ft.Container(expand=1, height=40) for _ in range(bas.weekday())]
        g = bas
        while g <= bit:
            v = gunluk.get(g, 0)
            ton = tonlar[min(int(4 * v / enb), 4)] if v else ui.ZEMIN2
            koyu_ton = v and v / enb > 0.55
            hafta.append(ft.Container(
                content=ft.Column([yazi(str(g.day), 11, g == bugun, renk="white" if koyu_ton else ui.YAZI),
                                   yazi(f"{v / 1000:.1f}b" if v >= 1000 else (f"{v:.0f}" if v else ""), 8.5,
                                        renk="white" if koyu_ton else ui.SOLUK)],
                                  spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER),
                expand=1, height=40, border_radius=8, bgcolor=ton, opacity=0.45 if g > bugun else 1,
                border=(ft.Border.all(2, ANA) if hasattr(ft, "Border") and hasattr(ft.Border, "all") else ft.border.all(2, ANA))
                if g == bugun else None,
                on_click=(lambda e, g=g: self.gun_detay(g, gun_kayit.get(g, []))) if v else None,
                tooltip=f"{g.day} {hb.AYLAR[g.month - 1]}: {hb.tl(v)}"))
            if len(hafta) == 7:
                satirlar.append(ft.Row(hafta, spacing=4))
                hafta = []
            g += dt.timedelta(days=1)
        if hafta:
            hafta += [ft.Container(expand=1, height=40) for _ in range(7 - len(hafta))]
            satirlar.append(ft.Row(hafta, spacing=4))
        return kart(ft.Column([ft.Row([yazi("Harcama takvimi", 15, True, expand=True),
                                       yazi("koyu = çok harcama", 10.5, renk=ui.SOLUK)]), *satirlar], spacing=4),
                    dolgu=14, shadow=golge(0.6))

    def gun_detay(self, g, kayitlar):
        from hb_ui import grupla
        ogeler = [self.liste_ogesi(x, tarih_goster=False) for x in grupla(kayitlar)]
        d = ft.AlertDialog(title=yazi(f"{g.day} {ui.AYLAR_UZUN[g.month - 1]} – {hb.tl(sum(float(i['tutar']) for i in kayitlar))}",
                                      16, True),
                           content=ft.Container(content=ft.Column(ogeler, scroll=ft.ScrollMode.AUTO, spacing=6, tight=True),
                                                width=400),
                           actions=[buton("Kapat", lambda e: self.dialog_kapat(), tip="text")])
        self.dialog_ac(d)

    # ================================================================== yıl özeti
    def sayfa_yil_ozeti(self):
        kutu = ft.Column(spacing=12)
        durum = {"veri": None}
        y = self.yil

        def ciz():
            v = durum["veri"]
            if v is None:
                kutu.controls = [ft.Row([ft.ProgressRing(width=20, height=20), yazi(f"{y} verileri yükleniyor…", 12, renk=ui.SOLUK)])]
                return
            giderler = [i for i in v if i["tur"] == "Gider"]
            oz = hb.donem_ozeti(v, None if self.yonetici else self.ben["id"])
            if not v:
                kutu.controls = [kart(yazi(f"{y} yılına ait kayıt yok.", 13, renk=ui.SOLUK))]
                return
            aylik = [0.0] * 12
            for i in giderler:
                aylik[hb.tarih_yerel(i["tarih"]).month - 1] += float(i["tutar"])
            enb = max(aylik) or 1
            gun_sayisi = len({hb.tarih_yerel(i["tarih"]).date() for i in v}) or 1
            marketler, urunler, fisler = {}, {}, {}
            for i in giderler:
                if i.get("firma"):
                    marketler[i["firma"]] = marketler.get(i["firma"], 0) + float(i["tutar"])
                if i.get("urun"):
                    k = hb.urun_anahtari(i["urun"])
                    urunler[k] = (urunler.get(k, (0, i["urun"]))[0] + 1, i["urun"])
                if i.get("fis_grup"):
                    f = fisler.setdefault(i["fis_grup"], {"t": 0, "firma": i.get("firma"), "tarih": i["tarih"]})
                    f["t"] += float(i["tutar"])
            en_pahali = max(fisler.values(), key=lambda f: f["t"]) if fisler else None
            ay_dolu = [(n, a) for n, a in enumerate(aylik) if a]
            tasarruflu = min(ay_dolu, key=lambda x: x[1]) if ay_dolu else None
            kisiler = {pid: hb.donem_ozeti(v, pid)["gider"] for pid in self.profiller} if self.yonetici else {}

            def hikaye(renkler, simge, baslik, buyuk, alt):
                return ft.Container(content=ft.Column([
                    ft.Row([ft.Icon(simge, color="white", size=20), yazi(baslik, 13, renk="#f8fafc")]),
                    yazi(buyuk, 26, True, renk="white"), *([yazi(alt, 12, renk="#e2e8f0")] if alt else [])], spacing=4),
                    gradient=degrade(renkler), bgcolor=renkler[0], border_radius=22, padding=18, shadow=golge(1))

            kartlar = [
                hikaye(["#0f766e", "#14b8a6"], ft.Icons.CELEBRATION_ROUNDED, f"{y} yılında toplam harcama", hb.tl(oz["gider"]),
                       f"Gelir {hb.tl(oz['gelir'])} • Net {hb.tl(oz['net'], isaret=True)}"),
                kart(ft.Column([yazi("Ay ay harcama", 15, True),
                                ft.Row([ft.Column([yazi(f"{a / 1000:.0f}b" if a >= 1000 else (f"{a:.0f}" if a else ""), 9, renk=ui.SOLUK),
                                                   ft.Container(height=max(4, 110 * a / enb), bgcolor="#14b8a6" if a != enb else GIDER,
                                                                border_radius=6, width=18),
                                                   yazi(hb.AYLAR[n][:3], 9.5, renk=ui.SOLUK)],
                                                  horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2,
                                                  alignment=ft.MainAxisAlignment.END, expand=1) for n, a in enumerate(aylik)],
                                       vertical_alignment=ft.CrossAxisAlignment.END, height=150, spacing=2)], spacing=8),
                     dolgu=14, shadow=golge(0.5)),
                hikaye(["#7c3aed", "#a855f7"], ft.Icons.CATEGORY_ROUNDED, "En çok harcanan kategori",
                       next(iter(oz["kategoriler"]), "—"),
                       " • ".join(f"{k} {hb.tl(t)}" for k, t in list(oz["kategoriler"].items())[:3])),
                hikaye(["#0369a1", "#0ea5e9"], ft.Icons.STOREFRONT_ROUNDED, "En sık alışveriş yeri",
                       max(marketler, key=marketler.get) if marketler else "—",
                       " • ".join(f"{k} {hb.tl(t)}" for k, t in sorted(marketler.items(), key=lambda kv: -kv[1])[:3])),
            ]
            if urunler:
                (adet, ad) = max(urunler.values())
                kartlar.append(hikaye(["#c2410c", "#f97316"], ft.Icons.SHOPPING_BASKET_ROUNDED, "En çok alınan ürün", ad,
                                      f"{adet} kez alındı"))
            if en_pahali:
                kartlar.append(hikaye(["#be123c", "#f43f5e"], ft.Icons.RECEIPT_LONG_ROUNDED, "Yılın en büyük fişi",
                                      hb.tl(en_pahali["t"]), f"{en_pahali['firma'] or ''} • {hb.tarih_goster(en_pahali['tarih'], False)}"))
            if tasarruflu:
                kartlar.append(hikaye(["#15803d", "#22c55e"], ft.Icons.SAVINGS_ROUNDED, "En tasarruflu ay",
                                      ui.AYLAR_UZUN[tasarruflu[0]], hb.tl(tasarruflu[1])))
            kartlar.append(hikaye(["#334155", "#64748b"], ft.Icons.TODAY_ROUNDED, "Kayıtlı gün başına ortalama",
                                  hb.tl(oz["gider"] / gun_sayisi), f"{len(v)} kayıt • {gun_sayisi} gün"))
            if kisiler and len(kisiler) > 1:
                kartlar.append(kart(ft.Column([yazi("Kim ne harcadı?", 15, True)] + [
                    ft.Row([self.kisi_rozeti(pid, boyut=24), yazi(self.ad(pid), 13, True, expand=True), yazi(hb.tl(t), 13, True)])
                    for pid, t in kisiler.items()], spacing=8), dolgu=14, shadow=golge(0.5)))
            kutu.controls = kartlar

        async def yukle():
            try:
                durum["veri"] = await self.arka(self.supa.islemler, dt.date(y, 1, 1), dt.date(y, 12, 31))
            except Exception:
                durum["veri"] = []
            ciz()
            self.guncelle()

        def yil_degistir(n):
            self.yil += n
            self.ekrani_ciz()

        self.page.run_task(yukle)
        ciz()
        return self._liste([ft.Row([ft.IconButton(icon=ft.Icons.CHEVRON_LEFT_ROUNDED, on_click=lambda e: yil_degistir(-1)),
                                    yazi(f"{y} yılının özeti", 18, True, expand=True, text_align=ft.TextAlign.CENTER),
                                    ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, on_click=lambda e: yil_degistir(1),
                                                  disabled=y >= hb.simdi().year)]), kutu])

    # ================================================================== mükerrer fiş
    async def mukerrer_kontrol(self, firma, zaman, toplam, saat_biliniyor):
        gun = zaman.date()
        q = hb.urllib.parse.quote
        bas = hb.iso_tarih(dt.datetime(gun.year, gun.month, gun.day, tzinfo=hb.TZ))
        son = hb.iso_tarih(dt.datetime(gun.year, gun.month, gun.day, tzinfo=hb.TZ) + dt.timedelta(days=1))
        try:
            adaylar = await self.arka(self.supa.tablo, "hb_islemler",
                                      f"select=id,firma,tarih,tutar,ekleyen_ad,fis_grup&tur=eq.Gider"
                                      f"&tarih=gte.{q(bas)}&tarih=lt.{q(son)}&limit=500")
        except Exception:
            return None
        return ak.mukerrer_bul(adaylar, firma, zaman, toplam, saat_biliniyor)

    # ================================================================== sunucu görevleri (uygulama açılışında)
    async def sunucu_gorevleri(self):
        """pg_cron yoksa ya da kaçırıldıysa: okul harçlığı ve haftalık özet açılışta tamamlanır."""
        await asyncio.sleep(3)
        eklenen = 0
        self.page.run_task(self.mesajlari_yukle)
        for ad in ("hb_harclik_tamamla", "hb_haftalik_ozet", "hb_taksit_hatirlat"):
            try:
                r = await self.arka(self.supa.rpc, ad, {})
                if ad == "hb_harclik_tamamla" and isinstance(r, (int, float)):
                    eklenen = int(r)
            except Exception as e:
                print(f"{ad} çalıştırılamadı:", e)
        if eklenen:
            self.bildir(f"🎒 {eklenen} günlük okul harçlığı otomatik eklendi")
            await self.verileri_yenile()
        await self.faturalari_esle(sessiz=True)  # önceden eklenmiş faturaları eski ödemelerle eşleştir
        self.page.run_task(self.kurumlari_sorgula, 12, True)
        if self.mail_otomatik(4):
            self.page.run_task(self.mail_kontrol, True)
        await self.aktuel_yukle()
        await self.aktuel_yenile()


    # ================================================================== Erzurum kuyumcu fiyatı
    async def kuyumcu_farki_yukle(self):
        if self.kuyumcu_farki is not None:
            return self.kuyumcu_farki
        f = None
        try:
            k = await self.arka(self.supa.ayar_oku, "kuyumcu_farki")
            f = json.loads(k) if k else None
        except Exception:
            pass
        self.kuyumcu_farki = f or self._yerel_oku("kuyumcu_farki") or {}
        return self.kuyumcu_farki

    def kuyumcu_esitle(self, ham: dict):
        if not ham:
            self.bildir("Güncel fiyatlar alınamadı; internet bağlantısını kontrol edin.", GIDER)
            return
        alanlar, satirlar = {}, []
        for tur in ("gram", "ceyrek", "yarim", "tam", "ata", "bilezik22"):
            if tur not in ham:
                continue
            ad = ak.VARLIK_TURLERI[tur][0]
            a = ft.TextField(label="Alış", dense=True, expand=True, keyboard_type=ft.KeyboardType.NUMBER,
                             hint_text=f"{ham[tur]['alis']:.0f}")
            st = ft.TextField(label="Satış", dense=True, expand=True, keyboard_type=ft.KeyboardType.NUMBER,
                              hint_text=f"{ham[tur]['satis']:.0f}")
            alanlar[tur] = (a, st)
            satirlar += [yazi(ad + ("" if tur in ("gram", "ceyrek") else " (isteğe bağlı)"), 12.5, True), ft.Row([a, st], spacing=8)]

        async def kaydet():
            f = {}
            for tur, (a, st) in alanlar.items():
                ga, gs = hb.tutar_coz(a.value), hb.tutar_coz(st.value)
                if not ga and not gs:
                    continue
                f[tur] = {"alis_oran": round((ga or gs) / ham[tur]["alis"], 5),
                          "satis_oran": round((gs or ga) / ham[tur]["satis"], 5)}
            if not f:
                self.bildir("En az bir fiyat girin (gram veya çeyrek alış).", GIDER)
                return False
            f["_tarih"] = hb.simdi().strftime("%d.%m.%Y")
            self.kuyumcu_farki = f
            self._yerel_yaz("kuyumcu_farki", f)
            try:
                await self.arka(self.supa.ayar_yaz, "kuyumcu_farki", json.dumps(f))
            except Exception as e:
                print("Kuyumcu farkı buluta yazılamadı (yalnız bu telefonda):", e)
            self.bildir("Erzurum fiyatına eşitlendi ✓ Değerler bundan sonra buna göre hesaplanır", GELIR)
            self.ekrani_ciz()

        def sifirla(d):
            async def sil(e):
                self.kuyumcu_farki = {}
                self._yerel_yaz("kuyumcu_farki", {})
                try:
                    await self.arka(self.supa.ayar_yaz, "kuyumcu_farki", "{}")
                except Exception:
                    pass
                self.dialog_kapat(d)
                self.ekrani_ciz()
            return buton("Sıfırla", sil, tip="text")

        self._girdi_dialog("Erzurum fiyatıyla eşitle", [
            yazi("Erzurum Kuyumcular Odası uygulamasında gördüğünüz fiyatları yazın. Kutulardaki soluk sayılar şu anki Harem "
                 "Altın fiyatıdır. Uygulama aradaki farkı öğrenir; fiyat değiştikçe değeriniz Erzurum fiyatına göre güncellenir. "
                 "Girmediğiniz sikkeler çeyreğin, bilezik gramın farkını kullanır.", 11.5, renk=ui.SOLUK), *satirlar],
            kaydet, "Eşitle", ek_eylem=sifirla if self.kuyumcu_farki else None)

    # ================================================================== aktüel kataloglar
    async def aktuel_yukle(self):
        try:
            self.aktuel = await self.arka(self.supa.tablo, "hb_aktuel",
                                          f"select=*&bit=gte.{hb.simdi().date().isoformat()}&order=fiyat&limit=3000")
            son = await self.arka(self.supa.tablo, "hb_aktuel", "select=olusturma&order=olusturma.desc&limit=1")
            self.aktuel_durum["son"] = son[0]["olusturma"] if son else None
        except Exception as e:
            print("Aktüel okunamadı:", e)

    async def aktuel_yenile(self, zorla=False):
        """Marketlerin aktüel kataloglarını internette bulur (günde en çok bir kez, iki telefon ortak)."""
        d = self.aktuel_durum
        if d["calisiyor"] or not self.gemini_anahtari:
            if zorla and not self.gemini_anahtari:
                self.bildir("Aktüel taraması için Menü > Ayarlar'da Gemini anahtarı gerekli.", GIDER)
            return
        if not zorla and d["son"] and (hb.simdi() - hb.tarih_yerel(d["son"])).total_seconds() < 20 * 3600:
            return
        d.update(calisiyor=True, hata=None)
        if zorla:
            self.bildir("🔎 Marketlerin aktüel katalogları internette aranıyor…")
            self.ekrani_ciz()
        toplam, hatalar = 0, []
        for market in ak.AKTUEL_MARKETLER:
            try:
                bulunan = await self.arka(ak.aktuel_bul, self.gemini_anahtari, market)
            except Exception as e:
                hatalar.append(f"{market}: {e}")
                continue
            tekil = {}
            for u in bulunan:
                u["urun"] = " ".join(u["urun"].split())
                tekil[(u["market"], u["urun"].lower(), u["bas"])] = u
            if tekil:
                try:
                    await self.arka(self.supa.aktuel_ekle, list(tekil.values()))
                    toplam += len(tekil)
                except Exception as e:
                    hatalar.append(f"{market}: {e}")
        try:
            await self.arka(self.supa.rpc, "hb_aktuel_temizle", {})
        except Exception:
            pass
        d.update(calisiyor=False, hata="; ".join(hatalar)[:300] if hatalar and not toplam else None)
        await self.aktuel_yukle()
        await self.aktuel_liste_duyur()
        if zorla:
            self.bildir(f"✓ {toplam} aktüel ürün bulundu" if toplam else f"Aktüel bulunamadı: {d['hata'] or 'sonuç yok'}",
                        GELIR if toplam else GIDER)
        self.ekrani_ciz()

    async def aktuel_liste_duyur(self):
        """Listede bekleyen ürün bir markette aktüelse ikinize (bir kez) bildirim gönderir."""
        for a in [x for x in self.ek.get("alisveris", []) if not x.get("alindi")]:
            es = ak.aktuel_eslestir(self.aktuel, a["urun"], 0.6)
            if not es:
                continue
            b = es[0]
            bit = dt.date.fromisoformat(b["bit"])
            try:
                await self.arka(self.supa.rpc, "hb_aktuel_duyur", {
                    "p_baslik": f"🏷️ {a['urun']} {b['market']} aktüelde",
                    "p_metin": f"{b['urun']} – {hb.tl(b['fiyat'])} (son gün {bit.day} {ui.AYLAR_UZUN[bit.month - 1]})",
                    "p_anahtar": f"{b['market']}:{hb.urun_anahtari(b['urun'])}:{b['bas']}:{a['id']}"})
            except Exception as e:
                print("Aktüel bildirimi:", e)
                return

    def aktuel_rozeti(self, madde):
        es = ak.aktuel_eslestir(self.aktuel, madde, 0.6) if self.aktuel else []
        if not es:
            return []
        b = es[0]
        bit = dt.date.fromisoformat(b["bit"])
        return [ft.Container(content=yazi(f"🏷️ {b['market']} aktüel: {b['urun'][:38]} {hb.tl(b['fiyat'])} • "
                                          f"son gün {bit.day} {ui.AYLAR_UZUN[bit.month - 1]}"
                                          + (f" (+{len(es) - 1} seçenek)" if len(es) > 1 else ""), 10.5, True, renk=GELIR),
                             bgcolor=saydam(GELIR, "18"), border_radius=8, padding=ft.Padding(6, 2, 6, 2),
                             margin=ft.Margin(0, 3, 0, 0) if hasattr(ft, "Margin") else None)]

    def aktuel_karti(self):
        d = self.aktuel_durum
        alan = ft.TextField(hint_text="Aktüellerde ara: deterjan, yağ, çay…", dense=True, expand=True, border_color="transparent")
        durum = {"market": "Tümü"}
        liste = ft.Column(spacing=6)
        cipler = ft.Row(spacing=6, wrap=True)

        def doldur():
            marketler = ["Tümü"] + sorted({a["market"] for a in self.aktuel})
            cipler.controls = [cip(m, durum["market"] == m, lambda e, m=m: sec(m), "#16a34a") for m in marketler]
            ara = (alan.value or "").strip()
            kayitlar = [a for a in self.aktuel if durum["market"] in ("Tümü", a["market"])]
            if ara:
                kayitlar = ak.aktuel_eslestir(kayitlar, ara, 0.45)
            if not kayitlar:
                liste.controls = [yazi("Henüz aktüel ürün yok. “Şimdi tara” ile internetten bulunur." if not self.aktuel
                                       else "Eşleşen ürün yok.", 12, renk=ui.SOLUK)]
                return
            liste.controls = []
            for a in kayitlar[:60]:
                bit = dt.date.fromisoformat(a["bit"])
                bas = dt.date.fromisoformat(a["bas"])
                basladi = bas <= hb.simdi().date()
                liste.controls.append(ft.Container(content=ft.Row([
                    ft.Container(content=yazi(a["market"], 10.5, True, renk="white"), bgcolor="#16a34a", border_radius=8,
                                 padding=ft.Padding(6, 3, 6, 3), width=78, alignment=ORTA),
                    ft.Column([yazi(a["urun"], 12.5, True, max_lines=2),
                               yazi((f"son gün {bit.day} {ui.AYLAR_UZUN[bit.month - 1]}" if basladi
                                     else f"başlangıç {bas.day} {ui.AYLAR_UZUN[bas.month - 1]}"), 10.5, renk=ui.SOLUK)],
                              spacing=0, expand=True),
                    yazi(hb.tl(a["fiyat"]), 13.5, True, renk=GELIR)], spacing=10),
                    bgcolor=ui.KART, border_radius=12, padding=10))

        def sec(m):
            durum["market"] = m
            doldur()
            self.guncelle()

        def ara(e=None):
            doldur()
            self.guncelle()

        alan.on_change = ara

        async def tara(e):
            await self.aktuel_yenile(zorla=True)

        son = hb.tarih_goster(d["son"]) if d["son"] else "henüz taranmadı"
        doldur()
        return ft.Column([
            ft.Row([yazi("Bu haftanın aktüel fırsatları", 16, True, expand=True),
                    ft.ProgressRing(width=18, height=18) if d["calisiyor"] else
                    buton("Şimdi tara", tara, ft.Icons.TRAVEL_EXPLORE_ROUNDED, tip="text")]),
            yazi(f"BİM, A101, ŞOK, Migros, CarrefourSA kataloglarından yapay zeka internette bulur • son tarama: {son}"
                 + (f" • ⚠️ {d['hata']}" if d.get("hata") else ""), 10.5, renk=ui.SOLUK),
            ft.Container(content=ft.Row([ft.Icon(ft.Icons.LOCAL_OFFER_ROUNDED, color="#16a34a"), alan]),
                         bgcolor=ui.KART, border_radius=16, padding=ft.Padding(12, 0, 4, 0), shadow=golge(0.4)),
            cipler, liste], spacing=8)

    # ================================================================== tema: sistem / açık / koyu
    def tema_modu(self):
        a = self._yerel_ayar()
        m = a.get("tema")
        if m not in ("sistem", "acik", "koyu"):
            m = "koyu" if a.get("koyu") else "sistem"
        return m

    def sistem_koyu_mu(self):
        b = getattr(self.page, "platform_brightness", None)
        return "DARK" in str(b).upper()

    def tema_modu_uygula(self):
        m = self.tema_modu()
        self.tema_ayarla(self.sistem_koyu_mu() if m == "sistem" else m == "koyu")

    def tema_degistir(self, mod):
        self._yerel_ayar_yaz(tema=mod, koyu=None)
        self.tema_modu_uygula()
        self.alt_menu_ciz()
        self.ekrani_ciz()

    async def sistem_temasi_degisti(self, e=None):
        if self.tema_modu() == "sistem":
            self.tema_modu_uygula()
            self.alt_menu_ciz()
            self.ekrani_ciz()

    def tema_secici(self):
        m = self.tema_modu()
        secenekler = [("sistem", "Cihaz", ft.Icons.BRIGHTNESS_AUTO_ROUNDED), ("acik", "Açık", ft.Icons.LIGHT_MODE_ROUNDED),
                      ("koyu", "Koyu", ft.Icons.DARK_MODE_ROUNDED)]
        return ft.Column([
            yazi("Tema", 13, "sb"),
            ft.Row([cip(a, m == k, lambda e, k=k: self.tema_degistir(k), ANA, s) for k, a, s in secenekler], spacing=8, wrap=True),
            yazi("“Cihaz”: telefonunuz koyu moddaysa uygulama da koyu açılır.", 11, renk=ui.SOLUK)], spacing=8)

    # ================================================================== alt menü (Özet · İşlemler · + · Planla · Menü)
    ALT_SEKMELER = [(0, "Özet", "SPACE_DASHBOARD"), (1, "İşlemler", "RECEIPT_LONG"), (None, "", ""),
                    (5, "Planla", "EVENT_NOTE"), (4, "Menü", "GRID_VIEW")]

    def _aktif_sekme(self):
        if self.sekme == 4 and getattr(self, "_alt_kaynak", None) == 5:
            return 5
        return self.sekme

    def alt_menu_ciz(self):
        if not getattr(self, "alt_menu", None):
            return
        aktif = self._aktif_sekme()
        ogeler = []
        for no, ad, simge in self.ALT_SEKMELER:
            if no is None:
                ogeler.append(ft.Container(content=ft.Container(
                    content=ft.Icon(ft.Icons.ADD_ROUNDED, color="#1a1203", size=30), width=58, height=58, border_radius=29,
                    bgcolor=ui.ALTIN, alignment=ORTA, on_click=self.ekle_menusu, tooltip="Ekle: fiş, gider, gelir…",
                    offset=ft.Offset(0, -0.22) if hasattr(ft, "Offset") else None,
                    shadow=ft.BoxShadow(blur_radius=18, color="#59f5b841", offset=ft.Offset(0, 6))),
                    expand=1, alignment=ORTA))
                continue
            secili = aktif == no
            renk = ui.VURGU if secili else ui.SOLUK
            ikon_adi = simge + ("_ROUNDED" if secili else "_OUTLINED")
            ogeler.append(ft.Container(content=ft.Column([
                ft.Container(content=ft.Icon(getattr(ft.Icons, ikon_adi, None) or getattr(ft.Icons, simge + "_ROUNDED", None)
                                             or ft.Icons.CIRCLE, color=renk, size=23),
                             bgcolor=saydam(ui.VURGU, "26") if secili else None, border_radius=12,
                             padding=ft.Padding(14, 3, 14, 3)),
                yazi(ad, 11, "sb" if secili else False, renk=renk)], spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
                expand=1, alignment=ORTA, on_click=lambda e, n=no: self.alt_sekme_tikla(n), padding=ft.Padding(0, 6, 0, 4)))
        self.alt_menu.content = ft.Row(ogeler, spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.alt_menu.bgcolor = ui.NAV_ZEMIN
        self.alt_menu.border = ft.Border(top=ft.BorderSide(1, ui.CIZGI)) if hasattr(ft, "Border") and hasattr(ft, "BorderSide") \
            else None

    def alt_sekme_tikla(self, n):
        if n == 4:
            self.alt_sayfa = None  # Menü'ye dokunmak her zaman menü listesini açar
        if n == 5 and self.sekme == 4 and getattr(self, "_alt_kaynak", None) == 5:
            self.alt_sayfa = None
        self.sekmeye_git(n)

    def ekle_menusu(self, e=None):
        sec = []

        def git(f):
            async def _(ev):
                self.dialog_kapat(alt)
                r = f()
                if asyncio.iscoroutine(r):
                    await r
            return _

        def ekle(tur):
            self.sekme = 2
            self.ekrani_ciz(tur=tur)
            self.alt_menu_ciz()

        async def galeri():
            self.sekmeye_git(3)
            await self.fis_sec("resim")

        async def pdf():
            self.sekmeye_git(3)
            await self.fis_sec("pdf")

        def kutu(simge, baslik, aciklama, renk, f, genis=False):
            return ft.Container(content=ft.Column([
                simge_kutusu(simge, renk, 22, 44), yazi(baslik, 14, True), yazi(aciklama, 11, renk=ui.SOLUK, max_lines=2)],
                spacing=6), bgcolor=ui.ZEMIN2, border_radius=18, padding=14, on_click=git(f),
                col={"xs": 12 if genis else 6})

        if self.mobil:
            sec.append(kutu(ft.Icons.DOCUMENT_SCANNER_ROUNDED, "Fiş tara", "Kamerayla çek, yapay zeka okusun", "#7c3aed",
                            self.hizli_fis))
        sec += [kutu(ft.Icons.PHOTO_LIBRARY_ROUNDED, "Galeriden fiş", "Fotoğraf seç", "#0891b2", galeri),
                kutu(ft.Icons.PICTURE_AS_PDF_ROUNDED, "PDF / e-fiş", "E-arşiv fatura, PDF fiş", "#e11d48", pdf),
                kutu(ft.Icons.NORTH_EAST_ROUNDED, "Gider", "Elle harcama girin", GIDER, lambda: ekle("Gider")),
                kutu(ft.Icons.SOUTH_WEST_ROUNDED, "Gelir", "Maaş, ek gelir…", GELIR, lambda: ekle("Gelir"))]
        if len(self.profiller) > 1:
            sec.append(kutu(ft.Icons.SWAP_HORIZ_ROUNDED, "Aktarım", "Kasalar arası para", AKTARIM, lambda: ekle("Aktarım")))
        sec.append(kutu(ft.Icons.RECEIPT_LONG_ROUNDED, "Fatura yükle", "Elektrik, su, doğalgaz…", "#d97706",
                        lambda: self.menu_ac("faturalar")))
        sec.append(kutu(ft.Icons.CREDIT_CARD_ROUNDED, "Kart ekstresi", "PDF hesap özetinden taksitler", "#4f46e5",
                        lambda: (self.planla_ac("taksitler"), self.ekstre_yukle())))
        izgara = ft.ResponsiveRow(sec, spacing=10, run_spacing=10) if hasattr(ft, "ResponsiveRow") else ft.Row(sec, wrap=True)
        icerik = ft.Container(content=ft.Column([
            ft.Row([yazi("Ne eklemek istersiniz?", 18, True, expand=True),
                    ft.IconButton(icon=ft.Icons.CLOSE_ROUNDED, on_click=lambda ev: self.dialog_kapat(alt), tooltip="Kapat")]),
            izgara, yazi("İpucu: Özet ekranındaki hızlı ekleme çubuğuna yazabilir ya da mikrofonla söyleyebilirsiniz.", 11,
                         renk=ui.SOLUK)], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(18, 14, 18, 24), bgcolor=ui.KART)
        kw = {}
        if ui._param_var(ft.BottomSheet, "show_drag_handle"):
            kw["show_drag_handle"] = True
        if ui._param_var(ft.BottomSheet, "bgcolor"):
            kw["bgcolor"] = ui.KART
        alt = ft.BottomSheet(content=icerik, **kw)
        self.dialog_ac(alt)

    # ================================================================== Planla sekmesi
    def planla_ac(self, anahtar):
        self._alt_kaynak = 5
        self.alt_sayfa = anahtar
        self.sekmeye_git(4)

    def planla_ekrani(self):
        from hb_ek import _ilerleme
        bas, bit = self.donem

        def bolum(simge, renk, baslik, sag_metin, anahtar, govde):
            return kart(ft.Column([
                ft.Row([simge_kutusu(simge, renk, 18, 36), yazi(baslik, 15, True, expand=True),
                        ft.Container(content=ft.Row([yazi(sag_metin, 12, "sb", renk=ui.VURGU),
                                                     ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=ui.VURGU, size=18)],
                                                    spacing=0, tight=True),
                                     on_click=lambda e: self.planla_ac(anahtar), padding=ft.Padding(6, 6, 0, 6))],
                       spacing=10), *govde], spacing=10), shadow=golge(0.5))

        k = []
        k.append(ft.Column([yazi("Planla", 26, "xb"),
                            yazi(f"{hb.donem_etiketi(bas, bit)} dönemi • ödemeler, bütçe, liste ve hedefler", 12, renk=ui.SOLUK)],
                           spacing=2))
        # yaklaşan ödemeler
        hat = self.hatirlatmalar()
        satir = []
        for h in hat[:5]:
            renk = {"gecikti": GIDER, "bugun": GIDER, "yarin": "#d97706"}.get(h["seviye"], ui.SOLUK)
            satir.append(ft.Row([ft.Container(width=8, height=8, border_radius=4, bgcolor=renk),
                                 yazi(h["metin"], 12.5, expand=True)], spacing=10))
        if not satir:
            satir = [yazi("Yaklaşan ödeme yok. Fatura yüklediğinizde son ödeme gününden önce hatırlatılır.", 12, renk=ui.SOLUK)]
        k.append(bolum(ft.Icons.EVENT_ROUNDED, "#d97706", "Yaklaşan ödemeler", "Faturalar", "faturalar", satir))
        # bütçe
        bsatir = []
        for pid in ([self.ben["id"]] if not self.yonetici else list(self.profiller)):
            d = self.kisi_butcesi(pid)
            if d:
                h, lim, oran = d
                r = GIDER if oran >= 1 else ("#d97706" if oran >= 0.8 else self.kisi_renk(pid))
                bsatir += [ft.Row([yazi(("Harçlık bütçem" if pid == self.ben["id"] and not self.yonetici
                                         else f"{self.ad(pid)} bütçesi"), 12.5, "sb", expand=True),
                                   yazi(f"{hb.tl(h)} / {hb.tl(lim)}", 11.5, renk=ui.SOLUK)]), _ilerleme(oran, r, 7)]
        for kat, h, lim, oran in self.butce_durumu()[:4]:
            r = GIDER if oran >= 1 else ("#d97706" if oran >= 0.8 else ANA)
            bsatir += [ft.Row([yazi(kat, 12.5, "sb", expand=True, max_lines=1),
                               yazi(f"{hb.tl(h)} / {hb.tl(lim)}", 11.5, renk=ui.SOLUK)]), _ilerleme(oran, r, 7)]
        if not bsatir:
            bsatir = [yazi("Henüz bütçe limiti yok. Market, dışarıda yemek gibi kategorilere dönem limiti koyabilirsiniz.", 12,
                           renk=ui.SOLUK)]
        k.append(bolum(ft.Icons.DONUT_LARGE_ROUNDED, "#e11d48", "Bütçe", "Limitler", "butceler", bsatir))
        # taksitler
        tsatir = []
        for (kartadi, sahip, vade), ts in self.taksit_gruplari()[:3]:
            if not self.yonetici and sahip != self.ben["id"]:
                continue
            tsatir.append(ft.Row([yazi(f"{kartadi} • {vade.day} {ui.AYLAR_UZUN[vade.month - 1]}", 12.5, "sb", expand=True),
                                  yazi(", ".join(t["ad"] for t in ts)[:28], 11.5, renk=ui.SOLUK),
                                  yazi(hb.tl(sum(float(t["aylik_tutar"]) for t in ts)), 12.5, "xb")], spacing=8))
        if not tsatir:
            tsatir = [yazi("Kredi kartı taksitlerinizi ekleyin; günü gelince hatırlatılır, “Ödedim” ile kasadan düşer.", 12,
                           renk=ui.SOLUK)]
        k.append(bolum(ft.Icons.CREDIT_CARD_ROUNDED, "#4f46e5", "Taksitler", "Tümü", "taksitler", tsatir))
        # alışveriş
        bekleyen = [a for a in self.ek["alisveris"] if not a.get("alindi")]
        asatir = [ft.Column([ft.Row([ft.Icon(ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED, size=16, color=ui.SOLUK),
                                     yazi(a["urun"], 13, expand=True)], spacing=8), *self.aktuel_rozeti(a["urun"])], spacing=2)
                  for a in bekleyen[:5]]
        if len(bekleyen) > 5:
            asatir.append(yazi(f"+{len(bekleyen) - 5} ürün daha", 11.5, renk=ui.SOLUK))
        if bekleyen:
            asatir.append(buton("Listeyi en ucuza tamamla", self.listeyi_en_ucuza, ft.Icons.SAVINGS_ROUNDED, tip="tonal"))
        else:
            asatir = [yazi("Liste boş. Eklediğiniz ürünler eşinizin telefonunda anında görünür.", 12, renk=ui.SOLUK)]
        k.append(bolum(ft.Icons.CHECKLIST_ROUNDED, GELIR, f"Alışveriş listesi ({len(bekleyen)})", "Listeyi aç", "alisveris",
                       asatir))
        # hedefler
        hsatir = []
        for hd in self.ek["hedefler"][:3]:
            biriken = float(self.ek["hedef_durum"].get(hd["id"], 0.0))
            hedef = float(hd.get("hedef_tutar") or 0) or 1
            hsatir += [ft.Row([yazi(hd.get("ad") or "Hedef", 12.5, "sb", expand=True),
                               yazi(f"{hb.tl(biriken)} / {hb.tl(hedef)}", 11.5, renk=ui.SOLUK)]),
                       _ilerleme(biriken / hedef, "#ca8a04", 7)]
        if not hsatir:
            hsatir = [yazi("Tatil, araba, acil durum fonu… bir hedef koyun, ne kadar kaldığını görün.", 12, renk=ui.SOLUK)]
        k.append(bolum(ft.Icons.SAVINGS_ROUNDED, "#ca8a04", "Birikim hedefleri", "Hedefler", "hedefler", hsatir))
        acik_borc = [b for b in self.ek["borclar"] if not b.get("kapandi")]
        if acik_borc:
            k.append(bolum(ft.Icons.HANDSHAKE_ROUNDED, AKTARIM, f"Açık borç / alacak ({len(acik_borc)})", "Tümü", "borclar",
                           [ft.Row([yazi(f"{b.get('kisi')}", 12.5, "sb", expand=True),
                                    yazi(("alacak " if b.get("yon") == "verdim" else "borç ") + hb.tl(b.get("tutar")), 12,
                                         renk=GELIR if b.get("yon") == "verdim" else GIDER)]) for b in acik_borc[:3]]))
        k.append(ft.Container(height=90))
        return ft.ListView(padding=ft.Padding(16, 14, 16, 16), spacing=12, expand=True, controls=k)
