"""
Hane Bütçesi v2 – kredi kartı taksitleri, "gerçekten harcanabilir para", hane sohbeti
(para isteği, kayda yorum, kısa notlar).
"""
import asyncio
import calendar
import datetime as dt

import flet as ft

import hb_core as hb
import hb_ui as ui
from hb_ui import (ANA, AKTARIM, GELIR, GIDER, ORTA, acilir, buton, golge, kart, saydam, simge_kutusu, yazi)


def taksit_vade(t: dict) -> dt.date:
    """Sıradaki taksidin tarihi (SQL'deki hb_taksit_vade ile aynı)."""
    ilk = dt.date.fromisoformat(str(t["ilk_odeme"])[:10])
    ay = ilk.month - 1 + int(t.get("odenen") or 0)
    y, a = ilk.year + ay // 12, ay % 12 + 1
    return dt.date(y, a, min(int(t.get("odeme_gunu") or ilk.day), calendar.monthrange(y, a)[1]))


def taksit_takvimi(t: dict, ay_sayisi: int = 6) -> list[tuple[dt.date, float]]:
    kalan = int(t["toplam_taksit"]) - int(t.get("odenen") or 0)
    sonuc = []
    for n in range(max(0, min(kalan, ay_sayisi + 2))):
        sonuc.append((taksit_vade(dict(t, odenen=int(t.get("odenen") or 0) + n)), float(t["aylik_tutar"])))
    return sonuc


class EkOzellikler4:
    def ek4_kur(self):
        self.mesajlar = []
        self.mesaj_hazir = None

    # ================================================================== taksitler
    @property
    def taksitler(self):
        return [t for t in self.ek.get("taksitler", []) if t.get("aktif", True) and
                int(t.get("odenen") or 0) < int(t["toplam_taksit"])]

    def taksit_gruplari(self, liste=None):
        """Aynı kart + aynı kasa + aynı vade = tek kart ödemesi."""
        gruplar = {}
        for t in (self.taksitler if liste is None else liste):
            anahtar = ((t.get("kart") or "Kart").strip() or "Kart", t["kasa_sahibi"], taksit_vade(t))
            gruplar.setdefault(anahtar, []).append(t)
        return sorted(gruplar.items(), key=lambda kv: kv[0][2])

    def taksit_hatirlatmalari(self):
        bugun = hb.simdi().date()
        sonuc = []
        for (kartadi, sahip, vade), ts in self.taksit_gruplari():
            if not self.yonetici and sahip != self.ben["id"]:
                continue
            kalan = (vade - bugun).days
            if kalan > 3:
                continue
            toplam = sum(float(t["aylik_tutar"]) for t in ts)
            if kalan < 0:
                seviye, ne = "gecikti", f"{-kalan} gün gecikti"
            elif kalan == 0:
                seviye, ne = "bugun", "BUGÜN"
            elif kalan == 1:
                seviye, ne = "yarin", "YARIN"
            else:
                seviye, ne = "yakin", f"{kalan} gün kaldı"
            sonuc.append({"seviye": seviye, "metin": f"💳 {kartadi} taksit ödemesi {ne} ({hb.tl(toplam)})",
                          "sayfa": "taksitler"})
        return sonuc

    def taksit_ay_yuku(self, ay_sayisi=6):
        bugun = hb.simdi().date()
        aylar = [(bugun.year + (bugun.month - 1 + n) // 12, (bugun.month - 1 + n) % 12 + 1) for n in range(ay_sayisi)]
        yuk = {a: 0.0 for a in aylar}
        for t in self.taksitler:
            if not self.yonetici and t["kasa_sahibi"] != self.ben["id"]:
                continue
            for vade, tutar in taksit_takvimi(t, ay_sayisi + 2):
                if (vade.year, vade.month) in yuk:
                    yuk[(vade.year, vade.month)] += tutar
        return yuk

    def sayfa_taksitler(self):
        gorunen = [t for t in self.taksitler if self.yonetici or t["kasa_sahibi"] == self.ben["id"]]
        kalan_borc = sum(float(t["aylik_tutar"]) * (int(t["toplam_taksit"]) - int(t.get("odenen") or 0)) for t in gorunen)
        yuk = self.taksit_ay_yuku()
        enb = max(yuk.values()) or 1
        bugun = hb.simdi().date()

        cubuklar = ft.Row([ft.Column([
            yazi(f"{v / 1000:.1f}b" if v >= 1000 else (f"{v:.0f}" if v else ""), 9.5, renk=ui.KASA_SOLUK),
            ft.Container(height=max(4, 64 * v / enb), width=22, border_radius=6,
                         bgcolor=ui.ALTIN if (y, a) == (bugun.year, bugun.month) else "#5eead4" if v else "#33ffffff"),
            yazi(hb.AYLAR[a - 1][:3], 10, renk=ui.KASA_SOLUK)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.END, spacing=3, expand=1)
            for (y, a), v in yuk.items()], vertical_alignment=ft.CrossAxisAlignment.END, height=104)
        ust = ft.Container(content=ft.Column([
            ft.Row([yazi("KALAN TAKSİT BORCU", 12, "sb", renk=ui.KASA_SOLUK, expand=True),
                    yazi(f"{len(gorunen)} taksit", 12, renk=ui.KASA_SOLUK)]),
            ui.para(kalan_borc, 32, "#e8edf5", ui.KASA_SOLUK),
            yazi("Önümüzdeki 6 ayın taksit yükü", 11.5, renk=ui.KASA_SOLUK), cubuklar], spacing=8),
            bgcolor=ui.KASA_ZEMIN, border_radius=24, padding=18, shadow=None if ui.KOYU else golge(1),
            border=ui.kenar() if ui.KOYU else None)

        ogeler = [ust, buton("Yeni taksit ekle", lambda e: self.taksit_duzenle(), ft.Icons.ADD_CARD_ROUNDED)]
        for (kartadi, sahip, vade), ts in self.taksit_gruplari(gorunen):
            toplam = sum(float(t["aylik_tutar"]) for t in ts)
            kalan = (vade - bugun).days
            renk = GIDER if kalan <= 0 else ("#d97706" if kalan <= 3 else ui.SOLUK)
            ne = ("bugün" if kalan == 0 else f"{-kalan} gün gecikti") if kalan <= 0 else \
                ("yarın" if kalan == 1 else f"{vade.day} {ui.AYLAR_UZUN[vade.month - 1]}")
            satirlar = []
            for t in ts:
                n = int(t.get("odenen") or 0) + 1
                satirlar.append(ft.Container(content=ft.Row([
                    ft.Column([yazi(t["ad"], 13.5, "sb"),
                               yazi(f"{n}/{t['toplam_taksit']}. taksit • {t.get('kategori') or 'Diğer'}"
                                    + (f" • {self.ad(t['kasa_sahibi'])}" if self.yonetici and len(self.profiller) > 1 else ""),
                                    11, renk=ui.SOLUK)], spacing=1, expand=True),
                    yazi(hb.tl(t["aylik_tutar"]), 13.5, "xb"),
                    ft.IconButton(icon=ft.Icons.MORE_VERT_ROUNDED, icon_size=18, tooltip="Düzenle / sil",
                                  on_click=lambda e, t=t: self.taksit_duzenle(t))], spacing=6),
                    padding=ft.Padding(0, 4, 0, 4)))
                satirlar.append(ft.Container(height=4, content=ft.Row([
                    ft.Container(expand=max(1, int(t.get("odenen") or 0)), height=4, border_radius=2, bgcolor=ANA),
                    ft.Container(expand=max(1, int(t["toplam_taksit"]) - int(t.get("odenen") or 0)), height=4, border_radius=2,
                                 bgcolor=ui.CIZGI)], spacing=2)))
            ogeler.append(kart(ft.Column([
                ft.Row([simge_kutusu(ft.Icons.CREDIT_CARD_ROUNDED, AKTARIM, 18, 36),
                        ft.Column([yazi(f"{kartadi} kartı", 15, True), yazi(f"Son ödeme: {ne}", 11.5, "sb", renk=renk)],
                                  spacing=0, expand=True),
                        yazi(hb.tl(toplam), 16, "xb")], spacing=10),
                *satirlar,
                ft.Row([buton("Ödedim" if len(ts) == 1 else f"Hepsini ödedim ({len(ts)})",
                              lambda e, ts=ts: self.taksit_ode(ts), ft.Icons.CHECK_ROUNDED)],
                       alignment=ft.MainAxisAlignment.END)], spacing=6), shadow=golge(0.5)))
        if not gorunen:
            ogeler.append(kart(yazi("Henüz taksit yok. Kredi kartı taksitlerinizi ekleyin; günü gelince ikinize de hatırlatılır, "
                                    "“Ödedim” deyince kasadan düşer ve harcamalara kendi kategorisiyle eklenir.", 12.5,
                                    renk=ui.SOLUK)))
        bitenler = [t for t in self.ek.get("taksitler", []) if int(t.get("odenen") or 0) >= int(t["toplam_taksit"])
                    and (self.yonetici or t["kasa_sahibi"] == self.ben["id"])]
        if bitenler:
            ogeler.append(yazi(f"Biten taksitler ({len(bitenler)})", 13, "sb", renk=ui.SOLUK))
            ogeler += [ft.Row([ft.Icon(ft.Icons.TASK_ALT_ROUNDED, color=GELIR, size=18), yazi(t["ad"], 12.5, expand=True),
                               yazi(f"{t['toplam_taksit']} × {hb.tl(t['aylik_tutar'])}", 11.5, renk=ui.SOLUK)])
                       for t in bitenler[:10]]
        return self._liste(ogeler)

    def taksit_duzenle(self, t=None):
        t = t or {}
        bugun = hb.simdi().date()
        kartlar = sorted({(x.get("kart") or "").strip() for x in self.ek.get("taksitler", []) if x.get("kart")})
        ad = ft.TextField(label="Ne alındı? (örn. Buzdolabı)", value=t.get("ad", ""), autofocus=not t)
        kart_tf = ft.TextField(label="Kart adı (örn. Bonus, World)", value=t.get("kart") or (kartlar[0] if kartlar else ""),
                               helper_text=("Kayıtlı: " + ", ".join(kartlar)) if kartlar else None)
        aylik = ft.TextField(label="Aylık taksit tutarı (₺)", keyboard_type=ft.KeyboardType.NUMBER,
                             value=f"{float(t['aylik_tutar']):.2f}".replace(".", ",") if t.get("aylik_tutar") else "")
        kalan_tf = ft.TextField(label="Kalan taksit sayısı", keyboard_type=ft.KeyboardType.NUMBER, width=150,
                                value=str(int(t["toplam_taksit"]) - int(t.get("odenen") or 0)) if t else "")
        toplam_tf = ft.TextField(label="Toplam taksit (isteğe bağlı)", keyboard_type=ft.KeyboardType.NUMBER, width=170,
                                 value=str(t["toplam_taksit"]) if t else "")
        gun = ft.TextField(label="Ayın kaçında ödeniyor?", keyboard_type=ft.KeyboardType.NUMBER, width=180,
                           value=str(t.get("odeme_gunu") or ""))
        kat = acilir("Harcama kategorisi", self.kategoriler,
                     t.get("kategori") if t.get("kategori") in self.kategoriler else "Diğer")
        kasa = self._kasa_secici(t.get("kasa_sahibi"))

        async def kaydet():
            a, tutar = (ad.value or "").strip(), hb.tutar_coz(aylik.value)
            kalan = int(hb.tutar_coz(kalan_tf.value) or 0)
            toplam = int(hb.tutar_coz(toplam_tf.value) or 0) or kalan
            g = int(hb.tutar_coz(gun.value) or 0)
            if not a or not tutar or tutar <= 0 or kalan <= 0 or not 1 <= g <= 31 or toplam < kalan:
                self.bildir("Ad, aylık tutar, kalan taksit ve ödeme günü (1–31) gerekli.", GIDER)
                return False
            odenen = toplam - kalan
            # sıradaki ödeme: bu ayın ödeme günü geçmediyse bu ay, geçtiyse gelecek ay
            sira = dt.date(bugun.year, bugun.month, min(g, calendar.monthrange(bugun.year, bugun.month)[1]))
            if t:
                sira = taksit_vade(t) if int(t.get("odenen") or 0) == odenen and int(t.get("odeme_gunu") or 0) == g else sira
            if sira < bugun and not t:
                y, m = (bugun.year + 1, 1) if bugun.month == 12 else (bugun.year, bugun.month + 1)
                sira = dt.date(y, m, min(g, calendar.monthrange(y, m)[1]))
            # ilk_odeme, ödenen ay kadar geriye alınır: vade = ilk_odeme + ödenen ay
            ay = sira.month - 1 - odenen
            y, m = sira.year + ay // 12, ay % 12 + 1
            ilk = dt.date(y, m, min(g, calendar.monthrange(y, m)[1]))
            kayit = {"ad": a, "kart": (kart_tf.value or "").strip() or None, "aylik_tutar": round(tutar, 2),
                     "toplam_taksit": toplam, "odenen": odenen, "odeme_gunu": g, "ilk_odeme": ilk.isoformat(),
                     "kategori": kat.value or "Diğer", "aktif": True,
                     "kasa_sahibi": kasa.value if self.yonetici else self.ben["id"]}
            if t.get("id"):
                await self._islem(self.supa.tablo_guncelle, "hb_taksitler", t["id"], kayit, basari="Taksit güncellendi ✓")
            else:
                await self._islem(self.supa.tablo_ekle, "hb_taksitler", kayit, basari="Taksit eklendi ✓ Günü gelince hatırlatılacak")

        def sil_eylemi(d):
            async def sil(e):
                self.dialog_kapat(d)
                await self._islem(self.supa.tablo_sil, "hb_taksitler", t["id"], basari="Taksit silindi")
            return buton("Sil", sil, tip="text")

        alanlar = [ad, kart_tf, aylik, ft.Row([kalan_tf, toplam_tf], spacing=8, wrap=True), gun, kat]
        if self.yonetici:
            alanlar += [yazi("Hangi kasadan ödeniyor?", 12, renk=ui.SOLUK), kasa]
        alanlar.append(kart(yazi("Önemli: Taksitle aldığınız ürünün tamamını ayrıca gider olarak girmeyin. Her ay “Ödedim” "
                                 "dediğinizde o ayın taksiti harcama olarak eklenir; böylece iki kez sayılmaz.", 11.5,
                                 renk="#b45309"), renk=ui.UYARI_ZEMIN, dolgu=10))
        self._girdi_dialog("Taksidi düzenle" if t else "Yeni taksit", alanlar, kaydet,
                           ek_eylem=sil_eylemi if t.get("id") else None)

    def taksit_ode(self, ts):
        toplam = sum(float(t["aylik_tutar"]) for t in ts)
        kasa = self._kasa_secici(ts[0]["kasa_sahibi"])
        tarih = ft.TextField(label="Ödeme tarihi", value=hb.simdi().strftime("%d.%m.%Y %H:%M"), dense=True)

        async def onay():
            zaman = hb.iso_tarih(hb.tarih_coz(tarih.value))
            sahip = kasa.value if self.yonetici else self.ben["id"]
            kayitlar = []
            for t in ts:
                n = int(t.get("odenen") or 0) + 1
                kayitlar.append({"tur": "Gider", "tutar": float(t["aylik_tutar"]), "tarih": zaman,
                                 "firma": f"{(t.get('kart') or 'Kredi kartı')} taksit",
                                 "urun": f"{t['ad']} – taksit {n}/{t['toplam_taksit']}", "kategori": t.get("kategori") or "Diğer",
                                 "kasa_sahibi": sahip, "hedef_kasa": None, "aciklama": "Kredi kartı taksidi"})
                if self.yonetici:
                    kayitlar[-1]["gizli"] = self.gizli_varsayilan
            try:
                eklenen = await self.arka(self.supa.islem_ekle, kayitlar)
                for t, k in zip(ts, eklenen or [{}] * len(ts)):
                    n = int(t.get("odenen") or 0) + 1
                    await self.arka(self.supa.tablo_guncelle, "hb_taksitler", t["id"],
                                    {"odenen": n, "aktif": n < int(t["toplam_taksit"]), "son_odeme_islem": k.get("id")})
                biten = [t["ad"] for t in ts if int(t.get("odenen") or 0) + 1 >= int(t["toplam_taksit"])]
                self.bildir(f"Ödendi ✓ {hb.tl(toplam)} kasadan düştü" + (f" • Bitti: {', '.join(biten)}" if biten else ""), GELIR)
                await self.ek_verileri_yenile()
                await self.verileri_yenile(ciz=False)
                self.ekrani_ciz()
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)
                return False

        satirlar = [ft.Row([yazi(f"{t['ad']} ({int(t.get('odenen') or 0) + 1}/{t['toplam_taksit']})", 12.5, expand=True),
                            yazi(hb.tl(t["aylik_tutar"]), 12.5, "sb")]) for t in ts]
        alanlar = [*satirlar, ft.Divider(), ft.Row([yazi("Toplam", 14, True, expand=True), yazi(hb.tl(toplam), 15, "xb")]), tarih]
        if self.yonetici:
            alanlar += [yazi("Hangi kasadan ödendi?", 12, renk=ui.SOLUK), kasa]
        self._girdi_dialog("Taksit ödemesi", alanlar, onay, "Ödedim")

    # ================================================================== gerçekten harcanabilir para
    def harcanabilir(self, pid=None):
        """Kasa − bu dönem ödenecek faturalar, taksitler ve düzenli ödemeler. pid=None: tüm kasalar."""
        bas, bit = self.donem if self.donem_ofset == 0 else hb.butce_donemi()
        bugun = hb.simdi().date()
        bak = {b["kisi"]: float(b.get("bakiye") or 0) for b in self.bakiyeler}
        kasa = sum(bak.values()) if pid is None else bak.get(pid, 0.0)

        def benim(sahip):
            return pid is None or sahip == pid

        kalemler = []
        f_top = 0.0
        for f in self.ek.get("faturalar", []):
            if f.get("odendi") or not benim(f.get("kasa_sahibi")):
                continue
            try:
                so = dt.date.fromisoformat(str(f.get("son_odeme"))[:10])
            except Exception:
                so = bugun
            if so <= bit:
                f_top += float(f.get("tutar") or 0)
        if f_top:
            kalemler.append(("Ödenmemiş faturalar", f_top, "faturalar"))
        t_top = 0.0
        for t in self.taksitler:
            if not benim(t["kasa_sahibi"]):
                continue
            for vade, tutar in taksit_takvimi(t, 3):
                if vade <= bit:
                    t_top += tutar
        if t_top:
            kalemler.append(("Bu dönemin taksitleri", t_top, "taksitler"))
        d_top = 0.0
        for d in self.ek.get("duzenli", []):
            if not d.get("aktif", True) or not benim(d.get("kasa_sahibi")):
                continue
            date_in_donem = None
            for y, a in {(bas.year, bas.month), (bit.year, bit.month)}:
                gun = dt.date(y, a, min(int(d.get("gun") or 1), calendar.monthrange(y, a)[1]))
                if bas <= gun <= bit:
                    date_in_donem = gun
            if date_in_donem and d.get("son_odenen") != date_in_donem.strftime("%Y-%m"):
                d_top += float(d.get("tutar") or 0)
        if d_top:
            kalemler.append(("Düzenli ödemeler (kira, aidat…)", d_top, "faturalar"))
        return kasa - sum(k[1] for k in kalemler), kasa, kalemler

    def harcanabilir_satiri(self, pid=None):
        try:
            serbest, kasa, kalemler = self.harcanabilir(pid)
        except Exception as e:
            print("Harcanabilir hesaplanamadı:", e)
            return None
        if not kalemler:
            return None
        return ft.Container(content=ft.Row([
            ft.Icon(ft.Icons.VERIFIED_ROUNDED, color="#5eead4", size=16),
            yazi("Gerçekten harcanabilir", 12, renk="#cbd5e1", expand=True),
            yazi(hb.tl(serbest), 14, "xb", renk="#5eead4" if serbest >= 0 else "#fca5a5"),
            ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=ui.KASA_SOLUK, size=15)], spacing=6),
            bgcolor=ui.KASA_IC, border_radius=12, padding=ft.Padding(12, 9, 10, 9),
            on_click=lambda e: self.harcanabilir_detay(pid))

    def harcanabilir_detay(self, pid=None):
        serbest, kasa, kalemler = self.harcanabilir(pid)

        def git(sayfa):
            def _(e):
                self.dialog_kapat(d)
                self.menu_ac(sayfa)
            return _

        satirlar = [ft.Row([yazi("Kasadaki para", 13, expand=True), yazi(hb.tl(kasa), 13.5, "sb")])]
        for ad, tutar, sayfa in kalemler:
            satirlar.append(ft.Container(content=ft.Row([yazi("− " + ad, 13, expand=True), yazi(hb.tl(tutar), 13.5, "sb", renk=GIDER),
                                                         ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=16, color=ui.SOLUK)]),
                                         on_click=git(sayfa)))
        satirlar += [ft.Divider(), ft.Row([yazi("Gerçekten harcanabilir", 14, True, expand=True),
                                           yazi(hb.tl(serbest), 16, "xb", renk=GELIR if serbest >= 0 else GIDER)]),
                     yazi("Bu dönemin (14'üne kadar) ödenmemiş faturaları, taksitleri ve düzenli ödemeleri düşülmüştür. "
                          "Birikim hedeflerine koyduğunuz para zaten kasadan çıktığı için ayrıca düşülmez.", 11, renk=ui.SOLUK)]
        d = ft.AlertDialog(title=yazi("Ne kadar harcayabilirim?", 17, True),
                           content=ft.Column(satirlar, tight=True, spacing=8),
                           actions=[buton("Kapat", lambda e: self.dialog_kapat(d), tip="text")])
        self.dialog_ac(d)

    # ================================================================== hane sohbeti
    async def mesajlari_yukle(self):
        try:
            m = await self.arka(self.supa.tablo, "hb_mesajlar", "select=*&order=id.desc&limit=200")
            self.mesajlar = list(reversed(m))
            self.mesaj_hazir = True
        except Exception as e:
            print("Mesajlar okunamadı:", e)
            self.mesaj_hazir = False

    @property
    def okunmamis_mesaj(self):
        return sum(1 for m in self.mesajlar if not m.get("okundu") and m.get("ekleyen") != self.ben["id"]
                   and m.get("tur") != "sistem")

    def sohbet_dugmesi(self):
        n = self.okunmamis_mesaj
        return ft.Container(content=ft.Stack([
            ft.Container(content=ft.Icon(ft.Icons.CHAT_BUBBLE_ROUNDED if n else ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED,
                                         color=ui.VURGU if n else ui.SOLUK, size=20),
                         width=40, height=40, border_radius=20, bgcolor=ui.KART, alignment=ORTA,
                         border=ui.kenar() if ui.KOYU else None, shadow=None if ui.KOYU else golge(0.4)),
            ft.Container(content=yazi(str(min(n, 99)), 10, True, renk="white"), bgcolor=GIDER, border_radius=9,
                         padding=ft.Padding(5, 1, 5, 1), right=0, top=0, visible=bool(n))], width=42, height=42),
            on_click=lambda e: self.menu_ac("sohbet"), tooltip="Hane sohbeti")

    async def _mesaj_ekle(self, kayit):
        try:
            await self.arka(self.supa.tablo_ekle, "hb_mesajlar", kayit)
        except Exception as ex:
            self.bildir(f"Gönderilemedi: {ex}", GIDER)
            return False
        await self.mesajlari_yukle()
        if self.sekme == 4 and self.alt_sayfa == "sohbet":
            self.ekrani_ciz()
        return True

    def sayfa_sohbet(self):
        diger = self.diger
        alan = ft.TextField(hint_text=f"{diger['ad'] if diger else 'Eşinize'} yazın…", expand=True, dense=True,
                            border_color="transparent", multiline=True, min_lines=1, max_lines=4, shift_enter=True,
                            value=getattr(self, "_taslak", ""))

        def taslak(e):
            self._taslak = alan.value or ""

        alan.on_change = taslak
        liste = ft.ListView(spacing=8, expand=True, auto_scroll=True, padding=ft.Padding(14, 8, 14, 8))

        async def gonder(e=None):
            metin = (alan.value or "").strip()
            if not metin:
                return
            alan.value = ""
            self._taslak = ""
            await self._mesaj_ekle({"tur": "mesaj", "metin": metin})

        alan.on_submit = gonder

        def baloncuk(m):
            benim = m.get("ekleyen") == self.ben["id"]
            zaman = hb.tarih_yerel(m.get("olusturma"))
            saat = zaman.strftime("%H:%M") if zaman.date() == hb.simdi().date() else zaman.strftime("%d.%m %H:%M")
            if m.get("tur") == "sistem":
                return ft.Row([ft.Container(content=yazi(m.get("metin") or "", 11.5, renk=ui.SOLUK), bgcolor=ui.ZEMIN2,
                                            border_radius=10, padding=ft.Padding(10, 4, 10, 4))],
                              alignment=ft.MainAxisAlignment.CENTER)
            icerik = []
            renk_zemin = ui.VURGU if benim else ui.KART
            yazi_renk = ("#04201c" if ui.KOYU else "white") if benim else ui.YAZI
            soluk = ("#0f3b35" if ui.KOYU else "#ccfbf1") if benim else ui.SOLUK
            if m.get("tur") == "istek":
                durum = m.get("durum") or "bekliyor"
                icerik += [ft.Row([ft.Icon(ft.Icons.PAYMENTS_ROUNDED, color=yazi_renk, size=18),
                                   yazi("Para isteği", 12, "sb", renk=soluk)], spacing=6),
                           yazi(hb.tl(m.get("tutar")), 22, "xb", renk=yazi_renk)]
                if m.get("metin"):
                    icerik.append(yazi(m["metin"], 13.5, renk=yazi_renk))
                etiket = {"bekliyor": "⏳ Bekliyor", "gonderildi": "✓ Gönderildi", "reddedildi": "✕ Reddedildi"}[durum]
                icerik.append(yazi(etiket, 11.5, "sb", renk=soluk))
                if durum == "bekliyor" and not benim:
                    icerik.append(ft.Row([
                        buton("Gönder", lambda e, m=m: self.page.run_task(self.istek_yanitla, m, True), ft.Icons.SEND_ROUNDED),
                        buton("Reddet", lambda e, m=m: self.page.run_task(self.istek_yanitla, m, False), tip="text")],
                        spacing=6))
                elif durum == "bekliyor" and benim:
                    icerik.append(buton("İsteği geri al", lambda e, m=m: self.page.run_task(self.mesaj_sil, m), tip="text"))
            elif m.get("tur") == "yorum":
                icerik.append(ft.Container(content=ft.Row([
                    ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, size=14, color=soluk),
                    yazi(m.get("ozet") or "Bir kayıt", 11.5, "sb", renk=soluk, expand=True, max_lines=1)], spacing=4),
                    on_click=lambda e, m=m: self.yorum_kaydini_ac(m)))
                icerik.append(yazi(m.get("metin") or "", 14, renk=yazi_renk, selectable=True))
            else:
                icerik.append(yazi(m.get("metin") or "", 14, renk=yazi_renk, selectable=True))
                if not benim and len(m.get("metin") or "") <= 60:
                    icerik.append(ft.Container(content=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART_ROUNDED, size=14, color=soluk),
                                                                yazi("Listeye ekle", 11, "sb", renk=soluk)], spacing=4, tight=True),
                                               on_click=lambda e, m=m: self.page.run_task(self.listeye_ekle, m["metin"])))
            icerik.append(yazi(saat + ("  ✓✓" if benim and m.get("okundu") else ""), 10, renk=soluk,
                               text_align=ft.TextAlign.RIGHT))
            kutu = ft.Container(content=ft.Column(icerik, spacing=4, tight=True), bgcolor=renk_zemin,
                                border=None if benim or not ui.KOYU else ui.kenar(),
                                border_radius=ft.BorderRadius(18, 18, 4 if benim else 18, 18 if benim else 4)
                                if hasattr(ft, "BorderRadius") else 18,
                                padding=ft.Padding(12, 9, 12, 7), width=290 if m.get("tur") == "istek" else None)
            return ft.Row([kutu], alignment=ft.MainAxisAlignment.END if benim else ft.MainAxisAlignment.START)

        def doldur():
            if self.mesaj_hazir is False:
                liste.controls = [kart(yazi("Sohbet için Supabase'de 'guncelleme_7.sql' dosyasını bir kez çalıştırın.", 12.5,
                                            renk=GIDER), renk=ui.UYARI_ZEMIN)]
                return
            if not self.mesajlar:
                liste.controls = [kart(ft.Column([
                    ft.Icon(ft.Icons.FORUM_ROUNDED, color=ui.VURGU, size=36),
                    yazi("Hane sohbeti", 15, True),
                    yazi("Kısa notlar yazın, para isteyin ya da bir kaydın altına “Bu neydi?” diye sorun. Mesajlar eşinizin "
                         "telefonuna bildirim olarak gider.", 12, renk=ui.SOLUK, text_align=ft.TextAlign.CENTER)],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6), dolgu=20)]
                return
            ogeler, onceki = [], None
            for m in self.mesajlar:
                g = hb.tarih_yerel(m.get("olusturma")).date()
                if g != onceki:
                    etiket = "Bugün" if g == hb.simdi().date() else ("Dün" if g == hb.simdi().date() - dt.timedelta(days=1)
                                                                     else f"{g.day} {ui.AYLAR_UZUN[g.month - 1]}")
                    ogeler.append(ft.Row([yazi(etiket, 11, "sb", renk=ui.SOLUK)], alignment=ft.MainAxisAlignment.CENTER))
                    onceki = g
                ogeler.append(baloncuk(m))
            liste.controls = ogeler

        async def okundu_yap():
            okunmamis = [m for m in self.mesajlar if not m.get("okundu") and m.get("ekleyen") != self.ben["id"]]
            if not okunmamis:
                return
            try:
                await self.arka(self.supa.tablo_guncelle_filtre, "hb_mesajlar",
                                f"okundu=eq.false&ekleyen=neq.{self.ben['id']}", {"okundu": True})
            except Exception:
                return
            for m in okunmamis:
                m["okundu"] = True

        async def ilk_yukle():
            if self.mesaj_hazir is None:
                await self.mesajlari_yukle()
                doldur()
                self.guncelle()
            await okundu_yap()

        self.page.run_task(ilk_yukle)
        doldur()
        giris = ft.Container(content=ft.Row([
            ft.IconButton(icon=ft.Icons.REQUEST_QUOTE_ROUNDED, icon_color=ui.ALTIN, tooltip="Para iste",
                          on_click=lambda e: self.para_iste()),
            ft.Container(content=alan, expand=True, bgcolor=ui.ZEMIN2, border_radius=20, padding=ft.Padding(14, 0, 6, 0)),
            ft.IconButton(icon=ft.Icons.SEND_ROUNDED, icon_color=ui.VURGU, on_click=gonder, tooltip="Gönder")], spacing=4),
            padding=ft.Padding(8, 6, 8, 8), bgcolor=ui.KART, border=ui.kenar() if ui.KOYU else None)
        return ft.Column([ft.Container(content=liste, expand=True), giris], spacing=0, expand=True)

    def para_iste(self):
        diger = self.diger
        tutar = ft.TextField(label="Tutar (₺)", keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)
        neden = ft.TextField(label="Ne için? (örn. Market, okul servisi)")

        async def gonder():
            t = hb.tutar_coz(tutar.value)
            if not t or t <= 0:
                self.bildir("Tutar girin.", GIDER)
                return False
            return await self._mesaj_ekle({"tur": "istek", "tutar": round(t, 2), "metin": (neden.value or "").strip(),
                                           "durum": "bekliyor"})

        self._girdi_dialog(f"{diger['ad'] if diger else 'Eşinizden'} para iste", [tutar, neden, yazi(
            "Eşiniz “Gönder”e dokununca kendi kasasından sizin kasanıza aktarım kendiliğinden kaydedilir.", 11.5,
            renk=ui.SOLUK)], gonder, "İste")

    async def istek_yanitla(self, m, gonder):
        if not gonder:
            try:
                await self.arka(self.supa.tablo_guncelle, "hb_mesajlar", m["id"], {"durum": "reddedildi"})
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)
                return
            await self._mesaj_ekle({"tur": "sistem", "metin": f"{self.ben['ad']} {hb.tl(m.get('tutar'))} isteğini reddetti"})
            return
        try:
            eklenen = await self.arka(self.supa.islem_ekle, [{
                "tur": "Aktarım", "tutar": float(m["tutar"]), "tarih": hb.iso_tarih(hb.simdi()),
                "kasa_sahibi": self.ben["id"], "hedef_kasa": m["ekleyen"], "kategori": "Transfer / Birikim",
                "aciklama": "Para isteği" + (f": {m['metin']}" if m.get("metin") else ""), "firma": None, "urun": None}])
            islem_id = eklenen[0].get("id") if eklenen else None
            await self.arka(self.supa.tablo_guncelle, "hb_mesajlar", m["id"], {"durum": "gonderildi", "islem_id": islem_id})
        except Exception as ex:
            self.bildir(f"Aktarım yapılamadı: {ex}", GIDER)
            return
        self.bildir(f"✓ {hb.tl(m['tutar'])} {self.ad(m['ekleyen'])} kasasına aktarıldı", GELIR)
        await self._mesaj_ekle({"tur": "sistem", "metin": f"✓ {hb.tl(m['tutar'])} {self.ad(m['ekleyen'])} kasasına gönderildi"})
        await self.verileri_yenile(ciz=False)

    async def mesaj_sil(self, m):
        try:
            await self.arka(self.supa.tablo_sil, "hb_mesajlar", m["id"])
        except Exception as ex:
            self.bildir(f"Silinemedi: {ex}", GIDER)
            return
        await self.mesajlari_yukle()
        self.ekrani_ciz()

    async def listeye_ekle(self, metin):
        await self._islem(self.supa.tablo_ekle, "hb_alisveris", [{"urun": metin.strip()[:80]}], basari="Listeye eklendi ✓")

    def yorum_yaz(self, i):
        ozet = " • ".join(x for x in [i.get("urun") or i.get("kategori") or i.get("tur"), i.get("firma"),
                                      hb.tl(i.get("tutar")), hb.tarih_goster(i.get("tarih"), False)] if x)
        alan = ft.TextField(label="Yorumunuz / sorunuz", autofocus=True, multiline=True, min_lines=1, max_lines=4)

        async def gonder():
            metin = (alan.value or "").strip()
            if not metin:
                return False
            ok = await self._mesaj_ekle({"tur": "yorum", "metin": metin, "islem_id": i.get("id"), "ozet": ozet[:120],
                                         "gizli": bool(i.get("gizli")) and self.yonetici})
            if ok:
                self.bildir("Yorum gönderildi ✓ Sohbette görünür", GELIR)
            return ok

        self._girdi_dialog("Kayda yorum yaz", [yazi(ozet, 12, "sb", renk=ui.SOLUK), alan], gonder, "Gönder")

    def yorum_kaydini_ac(self, m):
        i = next((x for x in self.islemler if x.get("id") == m.get("islem_id")), None)
        if i:
            self.islem_detay(i)
        else:
            self.bildir("Kayıt bu dönemde değil ya da silinmiş.")

    async def mesaj_canli(self, veri):
        await self.mesajlari_yukle()
        if self.sekme == 4 and self.alt_sayfa == "sohbet":
            self.ekrani_ciz()
        elif self.sekme == 0:
            self.ekrani_ciz()
