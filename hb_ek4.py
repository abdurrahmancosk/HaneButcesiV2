"""
Hane Bütçesi v2 – kredi kartı taksitleri, "gerçekten harcanabilir para", hane sohbeti
(para isteği, kayda yorum, kısa notlar).
"""
import asyncio
import calendar
import datetime as dt
import os

import flet as ft

import hb_akil as ak
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

        ogeler = [ust, ft.Row([
            buton("Ekstreden ekle", lambda e: self.ekstre_yukle(), ft.Icons.DOCUMENT_SCANNER_ROUNDED, expand=True),
            buton("Elle ekle", lambda e: self.taksit_duzenle(), ft.Icons.ADD_CARD_ROUNDED, tip="outlined", expand=True)],
            spacing=8),
            yazi("Ekstreden ekle: bankanın PDF hesap özetini ya da ekran görüntüsünü verin; taksitler kendiliğinden bulunur, "
                 "var olanlar güncellenir.", 11, renk=ui.SOLUK)]
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
        if getattr(self, "_bekleyen_ekstre", None):
            ogeler.insert(1, ft.Container(content=ft.Row([
                ft.Icon(ft.Icons.MARK_EMAIL_UNREAD_ROUNDED, color="white"),
                yazi("E-postada yeni kart ekstresi var: taksitleri güncelle", 13, "sb", renk="white", expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color="white")], spacing=10), bgcolor="#4f46e5", border_radius=16,
                padding=12, on_click=lambda e: self.ekstre_mail_sor()))
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


    # ================================================================== kart ekstresinden taksit
    def ekstre_yukle(self):
        def git(f):
            async def _(e):
                self.dialog_kapat(d)
                await f()
            return _

        async def pdf():
            veri = await self.dosya_sec("pdf")
            if veri:
                await self.ekstre_isle(veri, "pdf")

        async def foto():
            veri = await self.dosya_sec("resim")
            if veri:
                await self.ekstre_isle(veri, "resim")

        async def kamera():
            await self.kamera_ekrani(mod="ekstre")

        secenekler = [buton("PDF ekstre seç", git(pdf), ft.Icons.PICTURE_AS_PDF_ROUNDED),
                      buton("Ekran görüntüsü / fotoğraf", git(foto), ft.Icons.PHOTO_LIBRARY_ROUNDED, tip="outlined")]
        if self.mobil:
            secenekler.append(buton("Kamerayla çek", git(kamera), ft.Icons.PHOTO_CAMERA_ROUNDED, tip="outlined"))
        d = ft.AlertDialog(title=yazi("Kart ekstresinden taksit ekle", 17, True), content=ft.Column([
            yazi("Bankanın e-posta ile gönderdiği PDF hesap özetini seçin. PDF şifreliyse şifresi sorulur (çoğu bankada "
                 "T.C. kimlik no'nun son 6 hanesi veya doğum tarihi). Uygulamadan da ekran görüntüsü alabilirsiniz.", 12,
                 renk=ui.SOLUK), *secenekler], tight=True, spacing=10),
            actions=[buton("Vazgeç", lambda e: self.dialog_kapat(d), tip="text")])
        self.dialog_ac(d)

    def _pdf_sifre_sor(self, veri, yanlis=False):
        alan = ft.TextField(label="PDF şifresi", password=True, can_reveal_password=True, autofocus=True,
                            keyboard_type=ft.KeyboardType.NUMBER)

        async def tamam():
            if not (alan.value or "").strip():
                return False
            self.page.run_task(self.ekstre_isle, veri, "pdf", alan.value.strip())

        self._girdi_dialog("Ekstre şifreli", [
            *([yazi("Şifre tutmadı, tekrar deneyin.", 12, "sb", renk=GIDER)] if yanlis else []),
            yazi("Bankanın PDF şifresini girin (genelde T.C. kimlik no'nun son 6 hanesi ya da doğum tarihi GGAAYYYY). "
                 "Şifre kaydedilmez, yalnızca bu dosyayı açmak için kullanılır.", 11.5, renk=ui.SOLUK), alan], tamam, "Aç")

    async def ekstre_isle(self, veri: bytes, tip: str, sifre: str | None = None):
        if not self.gemini_anahtari:
            self.bildir("Ekstre okumak için Menü > Ayarlar'da Gemini anahtarı gerekli.", GIDER)
            return
        mime = "application/pdf"
        if tip == "pdf":
            try:
                veri = await self.arka(ak.pdf_sifresini_coz, veri, sifre)
            except ak.PdfSifreli as e:
                if e.desteklenmiyor:
                    self.bildir("Bu PDF'in şifreleme türü telefonda açılamıyor. Ekstreyi PDF görüntüleyicide açıp ekran "
                                "görüntüsü alın ve “Ekran görüntüsü / fotoğraf” ile yükleyin.", GIDER)
                    return
                self._pdf_sifre_sor(veri, yanlis=e.yanlis)
                return
        else:
            veri, mime = await self.arka(hb.gorseli_hazirla, veri)
        self.bildir("💳 Ekstre okunuyor, taksitler aranıyor…")
        try:
            sonuc = await self.arka(ak.ekstre_analiz_et, veri, mime, self.gemini_anahtari, self.kategoriler)
        except Exception as ex:
            self.bildir(f"Ekstre okunamadı: {ex}", GIDER)
            return
        self.ekstre_onay(sonuc)

    def _taksit_eslestir(self, t, kartadi):
        en_iyi, puan = None, 0.0
        for x in self.ek.get("taksitler", []):
            if int(x["toplam_taksit"]) != int(t["toplam_taksit"]) or abs(float(x["aylik_tutar"]) - t["aylik_tutar"]) > 1.0:
                continue
            p = ak._benzerlik(x["ad"], t["ad"]) + (0.3 if kartadi and (x.get("kart") or "").lower() == kartadi.lower() else 0)
            if p > puan:
                en_iyi, puan = x, p
        return en_iyi if puan >= 0.35 else None

    def ekstre_onay(self, s):
        bugun = hb.simdi().date()
        kartadi = s.get("kart") or s.get("banka") or ""
        kart_tf = ft.TextField(label="Kart adı", value=kartadi, dense=True)
        son = s.get("son_odeme")
        son_tf = ft.TextField(label="Son ödeme tarihi (GG.AA.YYYY)", value=son.strftime("%d.%m.%Y") if son else "", dense=True)
        kasa = self._kasa_secici()
        satirlar, secimler = [], []
        for t in s["taksitler"]:
            var = self._taksit_eslestir(t, kartadi)
            odenen_yeni = t["taksit_no"] - 1
            if var and int(var.get("odenen") or 0) >= t["taksit_no"]:
                durum, renk, varsayilan = "Kayıtlı ve bu taksit ödenmiş", ui.SOLUK, False
            elif var:
                durum, renk, varsayilan = (f"Kayıtlı: {int(var.get('odenen') or 0) + 1}/{var['toplam_taksit']} → "
                                           f"{t['taksit_no']}/{t['toplam_taksit']} olarak güncellenecek"), "#d97706", True
            else:
                durum, renk, varsayilan = "Yeni taksit", GELIR, True
            cb = ft.Checkbox(value=varsayilan)
            kat = acilir("Kategori", self.kategoriler, t["kategori"], dense=True)
            secimler.append((cb, kat, t, var, odenen_yeni))
            satirlar.append(ft.Container(content=ft.Column([
                ft.Row([cb, ft.Column([yazi(t["ad"], 13.5, "sb"),
                                       yazi(f"{t['taksit_no']}/{t['toplam_taksit']}. taksit • aylık {hb.tl(t['aylik_tutar'])} • "
                                            f"kalan {hb.tl(t['aylik_tutar'] * (t['toplam_taksit'] - odenen_yeni))}", 11,
                                            renk=ui.SOLUK),
                                       yazi(durum, 11, "sb", renk=renk)], spacing=1, expand=True)], spacing=4,
                       vertical_alignment=ft.CrossAxisAlignment.START),
                kat], spacing=4), bgcolor=ui.ZEMIN2, border_radius=14, padding=10))
        ozet = [yazi(" • ".join(x for x in [s.get("banka"), f"dönem borcu {hb.tl(s['donem_borcu'])}" if s.get("donem_borcu") else "",
                                            f"asgari {hb.tl(s['asgari'])}" if s.get("asgari") else ""] if x), 12, renk=ui.SOLUK)]
        if s.get("diger"):
            ozet.append(kart(yazi(f"Ekstrede taksitsiz {len(s['diger'])} harcama da var "
                                  f"({hb.tl(sum(h['tutar'] for h in s['diger']))}); bunlar eklenmedi.", 11.5, renk="#b45309"),
                             renk=ui.UYARI_ZEMIN, dolgu=10))
        if not s["taksitler"]:
            ozet.append(kart(yazi("Bu ekstrede taksitli işlem bulunamadı. Doğru belge mi? Gerekirse ekran görüntüsüyle tekrar "
                                  "deneyin ya da taksidi elle ekleyin.", 12, renk=GIDER), renk=ui.UYARI_ZEMIN))

        async def kaydet():
            so = hb.tarih_coz(son_tf.value).date() if (son_tf.value or "").strip() else None
            if not so:
                self.bildir("Son ödeme tarihini girin.", GIDER)
                return False
            sahip = kasa.value if self.yonetici else self.ben["id"]
            yeni = guncel = 0
            try:
                for cb, kat, t, var, odenen in secimler:
                    if not cb.value:
                        continue
                    ay = so.month - 1 - odenen
                    y, m = so.year + ay // 12, ay % 12 + 1
                    ilk = dt.date(y, m, min(so.day, calendar.monthrange(y, m)[1]))
                    kayit = {"ad": t["ad"], "kart": (kart_tf.value or "").strip() or None, "aylik_tutar": t["aylik_tutar"],
                             "toplam_taksit": t["toplam_taksit"], "odenen": odenen, "odeme_gunu": so.day,
                             "ilk_odeme": ilk.isoformat(), "kategori": kat.value or "Diğer", "aktif": True}
                    if var:
                        kayit.pop("ad")
                        await self.arka(self.supa.tablo_guncelle, "hb_taksitler", var["id"], kayit)
                        guncel += 1
                    else:
                        kayit["kasa_sahibi"] = sahip
                        await self.arka(self.supa.tablo_ekle, "hb_taksitler", kayit)
                        yeni += 1
            except Exception as ex:
                self.bildir(f"Kaydedilemedi: {ex}", GIDER)
                return False
            self.bildir(f"✓ {yeni} yeni taksit eklendi" + (f", {guncel} taksit güncellendi" if guncel else "")
                        + f" • son ödeme {so.day} {ui.AYLAR_UZUN[so.month - 1]}", GELIR)
            await self.ek_verileri_yenile()
            self.alt_sayfa = "taksitler"
            self.sekmeye_git(4)

        alanlar = [*ozet, ft.Row([ft.Container(content=kart_tf, expand=True), ft.Container(content=son_tf, expand=True)],
                                 spacing=8), *satirlar]
        if self.yonetici and s["taksitler"]:
            alanlar += [yazi("Hangi kasadan ödeniyor?", 12, renk=ui.SOLUK), kasa]
        if s["taksitler"]:
            alanlar.append(yazi("Bu ayki taksitler henüz ödenmemiş sayılır; ödeyince Taksitler'de “Ödedim” deyin.", 11,
                                renk=ui.SOLUK))
        self._girdi_dialog("Ekstrede bulunan taksitler", alanlar, kaydet, "Taksitleri kaydet" if s["taksitler"] else "Kapat")

    # ================================================================== aşağı çekip yenile
    def yenileme_bagla(self, kok):
        """Ekrandaki ilk kaydırılabilir listeye 'aşağı çek → yenile' bağlar."""
        def bul(c, derin=0):
            if c is None or derin > 5:
                return None
            if type(c).__name__ == "ListView":
                return c
            for ad in ("content", "controls"):
                v = getattr(c, ad, None)
                for x in (v if isinstance(v, list) else [v] if v is not None else []):
                    if isinstance(x, ft.Control):
                        r = bul(x, derin + 1)
                        if r is not None:
                            return r
            return None

        lv = bul(kok)
        if lv is None or getattr(lv, "_cek_bagli", False):
            return
        durum = {"cekme": 0.0}

        def kaydirma(e):
            tur = str(getattr(e, "event_type", None) or getattr(e, "type", "") or "").lower()
            px = float(getattr(e, "pixels", 0) or 0)
            ov = float(getattr(e, "overscroll", 0) or 0)
            if "start" in tur or "end" in tur:
                durum["cekme"] = 0.0
                return
            if "over" in tur and ov < 0:
                durum["cekme"] += ov
            if durum["cekme"] < -70 or px < -80:
                durum["cekme"] = 0.0
                self.page.run_task(self.cekip_yenile)

        lv.on_scroll = kaydirma
        try:
            lv._cek_bagli = True
        except Exception:
            pass

    async def cekip_yenile(self, e=None):
        import time as _t
        if getattr(self, "_cek_yenileniyor", False) or _t.time() - getattr(self, "_cek_son", 0) < 3:
            return
        self._cek_yenileniyor = True
        self._cek_son = _t.time()
        bar = getattr(self, "yenile_bar", None)
        if bar is not None:
            bar.visible = True
            self.guncelle()
        try:
            await asyncio.gather(self.verileri_yenile(ciz=False), self.mesajlari_yukle(), return_exceptions=True)
            if self.mail_otomatik(0.5):
                self.page.run_task(self.mail_kontrol, True)
            self.page.run_task(self.kurumlari_sorgula, 2, True)
            if self.cevrimdisi:
                self.bildir("📴 İnternet yok – son kaydedilen veriler gösteriliyor", GIDER)
            else:
                self.bildir("✓ Güncellendi", GELIR)
        finally:
            self._cek_yenileniyor = False
            if bar is not None:
                bar.visible = False
            self.ekrani_ciz()

    # ================================================================== e-postadan fatura takibi
    def mail_ayari(self):
        return self._yerel_ayar().get("mail") or {}

    def _mail_gorulen(self):
        g = self._yerel_oku("mail_gorulen")
        return set(g or [])

    def mail_karti(self):
        a = self.mail_ayari()
        adres = ft.TextField(label="Gmail adresi", value=a.get("adres", ""), dense=True,
                             keyboard_type=ft.KeyboardType.EMAIL)
        sifre = ft.TextField(label="Uygulama şifresi (16 harf)", value="", password=True, can_reveal_password=True, dense=True,
                             hint_text="•••• •••• •••• ••••" if a.get("sifre") else "abcd efgh ijkl mnop")
        durum = yazi(self._mail_durum_metni(), 11.5, renk=ui.SOLUK)

        async def kaydet(e):
            ad = (adres.value or "").strip()
            sf = (sifre.value or "").replace(" ", "") or a.get("sifre", "")
            if not ad or len(sf) < 16:
                self.bildir("Gmail adresi ve 16 harfli uygulama şifresi gerekli.", GIDER)
                return
            self.bildir("Bağlantı deneniyor…")
            try:
                await self.arka(ak.mail_baglanti_dene, ad, sf)
            except Exception as ex:
                m = str(ex)
                self.bildir("Bağlanamadı: " + ("adres ya da uygulama şifresi hatalı" if "AUTHENTICATIONFAILED" in m.upper()
                                               or "invalid credentials" in m.lower() else m), GIDER)
                return
            self._yerel_ayar_yaz(mail={"adres": ad, "sifre": sf, "son_kontrol": None})
            sifre.value = ""
            self.bildir("✓ Gmail bağlandı. Son 45 günün faturaları aranıyor…", GELIR)
            await self.mail_kontrol(sessiz=False, gun=45)

        def kaldir(e):
            self._yerel_ayar_yaz(mail=None)
            self.bildir("Gmail bağlantısı kaldırıldı (şifre bu cihazdan silindi)")
            self.ekrani_ciz()

        adimlar = ft.Column([
            yazi("Kurulum (bir kez):", 12, "sb"),
            yazi("1) Google hesabınızda 2 adımlı doğrulama açık olmalı.", 11.5, renk=ui.SOLUK),
            yazi("2) myaccount.google.com/apppasswords adresinde “Hane Bütçesi” adıyla uygulama şifresi oluşturun.", 11.5,
                 renk=ui.SOLUK),
            yazi("3) Çıkan 16 harfli şifreyi buraya yazıp “Bağla”ya dokunun.", 11.5, renk=ui.SOLUK),
            ft.TextButton("Uygulama şifresi sayfasını aç", url="https://myaccount.google.com/apppasswords")
            if ui._param_var(ft.TextButton, "url") else yazi("myaccount.google.com/apppasswords", 11.5, renk=ui.VURGU)],
            spacing=2)
        bagli = bool(a.get("sifre"))
        return kart(ft.Column([
            ft.Row([simge_kutusu(ft.Icons.MARK_EMAIL_READ_ROUNDED, "#ea4335", 18, 36),
                    ft.Column([yazi("E-postadan fatura takibi", 14, True),
                               yazi("Bağlı: " + a.get("adres", "") if bagli else "Bağlı değil", 11.5,
                                    renk=GELIR if bagli else ui.SOLUK)], spacing=0, expand=True)], spacing=10),
            yazi("Gmail'e gelen su, doğalgaz, elektrik, internet, telefon faturaları okunur ve kendiliğinden eklenir. Şifre "
                 "yalnızca bu cihazda saklanır; Hatice'nin telefonuna ve buluta gitmez. Mailler okunmamış olarak kalır.", 11.5,
                 renk=ui.SOLUK),
            *([] if bagli else [adimlar]), adres, sifre, durum,
            ft.Row([buton("Bağla" if not bagli else "Güncelle", kaydet, ft.Icons.LINK_ROUNDED, tip="tonal"),
                    *([buton("Şimdi kontrol et", lambda e: self.page.run_task(self.mail_kontrol, False),
                             ft.Icons.REFRESH_ROUNDED, tip="text"),
                       buton("Kaldır", kaldir, tip="text")] if bagli else [])], wrap=True, spacing=4)], spacing=8),
            shadow=golge(0.5))

    def _mail_durum_metni(self):
        a = self.mail_ayari()
        if not a.get("son_kontrol"):
            return "Henüz kontrol edilmedi."
        return f"Son kontrol: {hb.tarih_goster(a['son_kontrol'])}" + (f" • {a['son_sonuc']}" if a.get("son_sonuc") else "")

    async def mail_kontrol(self, sessiz=True, gun=21):
        a = self.mail_ayari()
        if not a.get("sifre") or getattr(self, "_mail_calisiyor", False):
            return
        if not self.gemini_anahtari:
            if not sessiz:
                self.bildir("Faturaları okumak için Menü > Ayarlar'da Gemini anahtarı gerekli.", GIDER)
            return
        self._mail_calisiyor = True
        await self._mail_denetimi()
        gorulen = self._mail_gorulen()
        eklenen, ekstreler, hatalar = [], [], 0
        eslesen_alisveris = bekleyen_alisveris = 0
        try:
            if not sessiz:
                self.bildir("📧 E-postadaki faturalar kontrol ediliyor…")
            try:
                mailler = await self.arka(ak.mail_faturalari_getir, a["adres"], a["sifre"], gun, gorulen)
            except Exception as ex:
                m = str(ex)
                sonuc = ("Gmail girişi reddedildi: uygulama şifresini yenileyin" if "AUTHENTICATIONFAILED" in m.upper()
                         else f"E-postaya ulaşılamadı ({m[:60]})")
                self._yerel_ayar_yaz(mail=dict(a, son_kontrol=hb.iso_tarih(hb.simdi()), son_sonuc=sonuc))
                if not sessiz:
                    self.bildir(sonuc, GIDER)
                return
            turler = self.fatura_turleri()
            for mail in sorted(mailler, key=lambda x: x["tarih"]):
                try:
                    f = await self.arka(ak.mail_fatura_coz, mail, self.gemini_anahtari, turler)
                except Exception as ex:
                    print("Mail okunamadı:", ex)
                    hatalar += 1
                    continue  # görülmedi say: sonra tekrar denensin
                gorulen.add(mail["id"])
                cesit = f.get("cesit")
                if cesit == "ekstre" and mail.get("pdfler"):
                    ekstreler.append(mail)
                elif cesit == "alisveris":
                    if await self._alisveris_faturasi(f, mail):
                        eslesen_alisveris += 1
                    else:
                        bekleyen_alisveris += 1
                elif cesit == "abonelik":
                    k = await self._mail_faturasi_kaydet(f, mail)
                    if k:
                        eklenen.append(k)
            self._yerel_yaz("mail_gorulen", list(gorulen)[-800:])
            if eklenen:
                await self.ek_verileri_yenile()
                await self.faturalari_esle(sessiz=True)
            if ekstreler:
                self._bekleyen_ekstre = ekstreler[-1]
            sonuc = (f"{len(eklenen)} yeni fatura" if eklenen else "yeni fatura yok") + \
                    (f", {len(ekstreler)} kart ekstresi" if ekstreler else "") + \
                    (f", {eslesen_alisveris} alışveriş faturası harcamasına eklendi" if eslesen_alisveris else "") + \
                    (f", {bekleyen_alisveris} alışveriş faturası onay bekliyor" if bekleyen_alisveris else "") + \
                    (f", {hatalar} mail okunamadı" if hatalar else "")
            if bekleyen_alisveris and sessiz:
                self.bildir(f"🧾 E-postada {bekleyen_alisveris} alışveriş faturası var: Faturalar sayfasından bakın")
            self._yerel_ayar_yaz(mail=dict(self.mail_ayari() or a, son_kontrol=hb.iso_tarih(hb.simdi()), son_sonuc=sonuc))
            if eklenen:
                odenen = sum(1 for k in eklenen if k.get("odendi"))
                self.bildir(f"📧 E-postadan {len(eklenen)} fatura eklendi" + (f" ({odenen} tanesi ödenmiş olarak)" if odenen else ""),
                            GELIR)
            elif not sessiz:
                self.bildir(f"📧 E-posta kontrol edildi: {sonuc}")
            if ekstreler and not sessiz:
                self.ekstre_mail_sor()
            self.ekrani_ciz()
        finally:
            self._mail_calisiyor = False

    async def _mail_faturasi_kaydet(self, f, mail):
        # aynı fatura elle eklenmişse tekrar ekleme
        for x in self.ek.get("faturalar", []):
            if x.get("tur") == f["tur"] and abs(float(x.get("tutar") or 0) - f["tutar"]) < 0.01 and \
                    (str(x.get("son_odeme") or "")[:10] == (f.get("son_odeme") or "") or (x.get("donem") and x.get("donem") == f.get("donem"))):
                return None
        abone = None
        for ab in self.ek.get("abonelikler", []):
            if f.get("abone_no") and ab.get("abone_no") and hb.urun_anahtari(ab["abone_no"]) == hb.urun_anahtari(f["abone_no"]):
                abone = ab
                break
        if abone is None:
            abone = next((ab for ab in self.ek.get("abonelikler", []) if ab.get("tur") == f["tur"] and not ab.get("abone_no")), None)
        gorsel = None
        if f.get("pdf"):
            try:
                gorsel = await self.arka(self.supa.fis_yukle, f["pdf"], "pdf", "application/pdf")
            except Exception:
                gorsel = None
        varsayilan_kat = {"Kredi kartı": "Kredi Kartı, Kredi Ödemesi & Borç"}
        kayit = {"tur": f["tur"], "kurum": f.get("kurum"), "abone_no": f.get("abone_no"), "donem": f.get("donem"),
                 "fatura_tarihi": f.get("fatura_tarihi"), "son_odeme": f.get("son_odeme"), "tuketim": f.get("tuketim"),
                 "birim": f.get("birim"), "birim_fiyat": f.get("birim_fiyat"), "tutar": f["tutar"], "gorsel": gorsel,
                 "kasa_sahibi": (abone or {}).get("kasa_sahibi") or self.ben["id"], "mail_id": "gmail:" + str(mail["id"]),
                 "kategori": varsayilan_kat.get(f["tur"], "Kira & Aidat & Faturalar")}
        onceki = next((x for x in sorted(self.ek["faturalar"], key=lambda x: x.get("fatura_tarihi") or x.get("son_odeme") or "",
                                         reverse=True) if x["tur"] == kayit["tur"]), None)
        try:
            kayit["analiz"] = ak.fatura_karsilastir(kayit, onceki)
        except Exception:
            pass
        odeme = await self.fatura_odemesini_bul(kayit)
        if odeme:
            kayit.update(odendi=True, odeme_islem_id=odeme["id"])
        elif f.get("son_odeme"):
            try:
                if (hb.simdi().date() - dt.date.fromisoformat(f["son_odeme"])).days > 20:
                    kayit["odendi"] = True  # eski fatura; ödemesi kayıtlarda yoksa da ödenmiş varsayılır
                    kayit["analiz"] = ((kayit.get("analiz") or "") + "\nE-postadan bulunan eski fatura: ödenmiş sayıldı "
                                       "(kasadan düşülmedi).").strip()
            except Exception:
                pass
        try:
            sonuc = await self.arka(self.supa.fatura_mailden_ekle, kayit)
        except hb.ApiHatasi as ex:
            print("Mail faturası eklenemedi:", ex)
            return None
        if not sonuc:
            return None  # başka cihaz eklemiş
        self.ek.setdefault("faturalar", []).insert(0, sonuc[0] if isinstance(sonuc[0], dict) else kayit)
        if f.get("abone_no") and not any(hb.urun_anahtari(ab.get("abone_no") or "") == hb.urun_anahtari(f["abone_no"])
                                         for ab in self.ek.get("abonelikler", [])):
            try:
                gun = dt.date.fromisoformat(f["fatura_tarihi"]).day if f.get("fatura_tarihi") else mail["tarih"].day
                yeni = {"tur": f["tur"], "kurum": f.get("kurum"), "abone_no": f["abone_no"], "beklenen_gun": gun,
                        "kasa_sahibi": kayit["kasa_sahibi"], "not_": "E-postadan otomatik eklendi"}
                await self.arka(self.supa.tablo_ekle, "hb_abonelikler", yeni)
                self.ek.setdefault("abonelikler", []).append(yeni)
            except Exception as ex:
                print("Abonelik eklenemedi:", ex)
        return kayit

    def ekstre_mail_sor(self):
        mail = getattr(self, "_bekleyen_ekstre", None)
        if not mail:
            return

        async def isle(e):
            self.dialog_kapat(d)
            self._bekleyen_ekstre = None
            self.planla_ac("taksitler")
            await self.ekstre_isle(mail["pdfler"][0][1], "pdf")

        d = ft.AlertDialog(title=yazi("E-postada kart ekstresi var", 17, True),
                           content=yazi(f"{mail.get('konu') or 'Hesap özeti'} ({mail['tarih']:%d.%m.%Y}). Taksitleri bu ekstreden "
                                        "güncelleyelim mi?", 13),
                           actions=[buton("Sonra", lambda e: self.dialog_kapat(d), tip="text"),
                                    buton("Taksitleri güncelle", isle, ft.Icons.CREDIT_CARD_ROUNDED)])
        self.dialog_ac(d)

    def mail_otomatik(self, en_az_saat):
        a = self.mail_ayari()
        if not a.get("sifre"):
            return False
        son = a.get("son_kontrol")
        return not son or (hb.simdi() - hb.tarih_yerel(son)).total_seconds() > en_az_saat * 3600

    # ================================================================== abonelikler
    def abonelik_faturasi(self, ab):
        for f in self.ek.get("faturalar", []):
            if ab.get("abone_no") and f.get("abone_no") and hb.urun_anahtari(f["abone_no"]) == hb.urun_anahtari(ab["abone_no"]):
                return f
            if not ab.get("abone_no") and f.get("tur") == ab.get("tur"):
                return f
        return None

    def abonelik_hatirlatmalari(self):
        bugun = hb.simdi().date()
        sonuc = []
        for ab in self.ek.get("abonelikler", []):
            if not ab.get("aktif", True) or not ab.get("beklenen_gun"):
                continue
            if not self.yonetici and ab.get("kasa_sahibi") != self.ben["id"]:
                continue
            if bugun.day < int(ab["beklenen_gun"]) + 5:
                continue
            f = self.abonelik_faturasi(ab)
            tarih = None
            if f:
                try:
                    tarih = dt.date.fromisoformat(str(f.get("fatura_tarihi") or f.get("olusturma") or "")[:10])
                except Exception:
                    tarih = None
            if tarih and (bugun - tarih).days < 25:
                continue
            sonuc.append({"seviye": "yakin", "metin": f"📭 {ab['tur']} faturası bu ay henüz gelmedi"
                                                          + (f" ({ab['kurum']})" if ab.get("kurum") else ""),
                          "sayfa": "abonelikler"})
        return sonuc

    def sayfa_abonelikler(self):
        ogeler = [kart(yazi("Su, doğalgaz, elektrik, internet, telefon gibi aboneliklerinizi buradan izleyin. E-postadan gelen "
                            "faturalar abone numarasıyla eşleşir; beklenen günden 5 gün sonra fatura gelmemişse uyarılırsınız.",
                            12, renk=ui.SOLUK)),
                  ft.Row([buton("Abonelik ekle", lambda e: self.abonelik_duzenle(), ft.Icons.ADD_ROUNDED, expand=True),
                          buton("E-postayı kontrol et", lambda e: self.page.run_task(self.mail_kontrol, False),
                                ft.Icons.MARK_EMAIL_UNREAD_ROUNDED, tip="outlined", expand=True)], spacing=8)]
        if not self.mail_ayari().get("sifre"):
            ogeler.append(kart(yazi("E-posta bağlı değil: Menü > Ayarlar > “E-postadan fatura takibi”nden Gmail'inizi bağlayın.",
                                    12, renk="#b45309"), renk=ui.UYARI_ZEMIN, dolgu=12))
        from hb_ek import FATURA_SIMGE, _ikon
        for ab in self.ek.get("abonelikler", []):
            if not self.yonetici and ab.get("kasa_sahibi") != self.ben["id"]:
                continue
            simge, renk = FATURA_SIMGE.get(ab["tur"], FATURA_SIMGE["Diğer"])
            f = self.abonelik_faturasi(ab)
            alt = [x for x in [ab.get("kurum"), f"Abone no {ab['abone_no']}" if ab.get("abone_no") else None,
                               f"Her ayın ~{ab['beklenen_gun']}'i" if ab.get("beklenen_gun") else None] if x]
            son = (f"Son fatura: {hb.tl(f['tutar'])}" + (f" • {f['donem']}" if f.get("donem") else "")
                   + (" • ödendi" if f.get("odendi") else " • ödenmedi")) if f else "Henüz fatura yok"
            if ab.get("baglanti"):
                son = (ab.get("son_bilgi") or "Henüz sorgulanmadı") + (
                    f" • {hb.tarih_goster(ab['son_sorgu'])}" if ab.get("son_sorgu") else "") + " • " + son
            ogeler.append(ft.Container(content=ft.Row([
                simge_kutusu(_ikon(simge), renk, 18, 38),
                ft.Column([yazi(ab["tur"], 14, True), yazi(" • ".join(alt), 11, renk=ui.SOLUK),
                           yazi(son, 11.5, "sb", renk=ui.YAZI if f else ui.SOLUK)], spacing=1, expand=True),
                ft.IconButton(icon=ft.Icons.TRAVEL_EXPLORE_ROUNDED, tooltip="Kurumdan şimdi sorgula", icon_color=ui.VURGU,
                              on_click=lambda e, ab=ab: self.page.run_task(self._tek_sorgu, ab))
                if ab.get("baglanti") else ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=ui.SOLUK)], spacing=10),
                bgcolor=ui.KART, border_radius=18, padding=12, border=ui.kenar() if ui.KOYU else None,
                shadow=None if ui.KOYU else golge(0.4), opacity=1 if ab.get("aktif", True) else 0.5,
                on_click=lambda e, ab=ab: self.abonelik_duzenle(ab)))
        if not self.ek.get("abonelikler"):
            ogeler.append(kart(yazi("Henüz abonelik yok. E-postadan fatura geldikçe kendiliğinden eklenir ya da elle ekleyin.",
                                    12.5, renk=ui.SOLUK)))
        return self._liste(ogeler)

    def abonelik_duzenle(self, ab=None):
        ab = ab or {}
        tur = acilir("Tür", self.fatura_turleri(), ab.get("tur") or "Elektrik")
        kurum = ft.TextField(label="Kurum (örn. Palen, ESKİ, Türk Telekom)", value=ab.get("kurum") or "", dense=True)
        no = ft.TextField(label="Abone / tesisat / müşteri no", value=ab.get("abone_no") or "", dense=True)
        gun = ft.TextField(label="Fatura genelde ayın kaçında gelir?", value=str(ab.get("beklenen_gun") or ""), dense=True,
                           keyboard_type=ft.KeyboardType.NUMBER)
        aktif = ft.Switch(label="Aktif", value=ab.get("aktif", True))
        kasa = self._kasa_secici(ab.get("kasa_sahibi"))
        import hb_kurum
        secenek = ["Yok"] + [v[0] for v in hb_kurum.KURUMLAR.values()]
        bag_ad = hb_kurum.KURUMLAR.get(ab.get("baglanti") or "", ("Yok",))[0]
        if not ab.get("id") and not ab.get("baglanti") and (ab.get("tur") == "Su" or "eski" in (ab.get("kurum") or "").lower()):
            bag_ad = hb_kurum.KURUMLAR["eski"][0]
        baglanti = acilir("Kurumdan otomatik borç sorgusu", secenek, bag_ad)
        musteri = ft.TextField(label="Müşteri no", value=ab.get("musteri_no") or "", dense=True,
                               keyboard_type=ft.KeyboardType.NUMBER, visible=bag_ad != "Yok")
        bag_bilgi = yazi("ESKİ'nin borç sorgulama sayfasından tesisat no (yukarıdaki abone no) + müşteri no ile günde iki kez "
                         "otomatik sorgulanır; borç çıkınca fatura eklenir, borç yoksa ödenmemiş görünen faturalar kapanır.",
                         11, renk=ui.SOLUK, visible=bag_ad != "Yok")

        def bag_degisti(e):
            musteri.visible = bag_bilgi.visible = baglanti.value != "Yok"
            if baglanti.value != "Yok":
                tur.value = "Su"
                if not (kurum.value or "").strip():
                    kurum.value = "ESKİ"
                no.label = "Tesisat no"
            self.guncelle()

        baglanti.on_change = bag_degisti

        async def kaydet():
            g = int(hb.tutar_coz(gun.value) or 0) or None
            bag = next((k for k, v in hb_kurum.KURUMLAR.items() if v[0] == baglanti.value), None)
            if bag and (not (no.value or "").strip().isdigit() or not (musteri.value or "").strip().isdigit()):
                self.bildir("Otomatik sorgu için tesisat no ve müşteri no (yalnız rakam) gerekli.", GIDER)
                return False
            kayit = {"tur": tur.value, "kurum": (kurum.value or "").strip() or None, "abone_no": (no.value or "").strip() or None,
                     "beklenen_gun": g if g and 1 <= g <= 31 else None, "aktif": bool(aktif.value),
                     "kasa_sahibi": kasa.value if self.yonetici else self.ben["id"]}
            if bag or ab.get("baglanti"):
                kayit.update(baglanti=bag, musteri_no=(musteri.value or "").strip() or None)
            try:
                if ab.get("id"):
                    await self.arka(self.supa.tablo_guncelle, "hb_abonelikler", ab["id"], kayit)
                    hedef = dict(ab, **kayit)
                else:
                    r = await self.arka(self.supa.tablo_ekle, "hb_abonelikler", kayit)
                    hedef = r[0] if r else dict(kayit)
            except hb.ApiHatasi as ex:
                self.bildir("Kaydedilemedi: " + ("Supabase'de guncelleme_9.sql çalıştırılmamış" if "baglanti" in ex.mesaj
                                                 or "musteri_no" in ex.mesaj else str(ex)), GIDER)
                return False
            self.bildir("Kaydedildi ✓", GELIR)
            await self.ek_verileri_yenile()
            self.ekrani_ciz()
            if bag:
                await self.kurum_sorgula(hedef, sessiz=False)
                self.ekrani_ciz()

        def sil(d):
            async def s(e):
                self.dialog_kapat(d)
                await self._islem(self.supa.tablo_sil, "hb_abonelikler", ab["id"], basari="Silindi")
            return buton("Sil", s, tip="text")

        self._girdi_dialog("Aboneliği düzenle" if ab.get("id") else "Yeni abonelik",
                           [tur, kurum, no, baglanti, musteri, bag_bilgi, gun, aktif] + ([yazi("Kimin kasasından ödenir?", 12, renk=ui.SOLUK), kasa]
                                                            if self.yonetici else []), kaydet,
                           ek_eylem=sil if ab.get("id") else None)

    # ================================================================== fatura ↔ ödeme eşleştirme
    _FATURA_IZLERI = {"Elektrik": ["elektrik", "enerji", "edaş", "edas", "aras", "ck ", "enerjisa"],
                      "Su": ["su ", "su fat", "aski", "eski", "iski", "suski", "belediye"],
                      "Doğalgaz": ["doğalgaz", "dogalgaz", "gaz", "palen", "igdaş", "başkentgaz", "aksa"],
                      "İnternet": ["internet", "türk telekom", "turk telekom", "superonline", "turknet", "ttnet", "fiber"],
                      "Telefon": ["telefon", "turkcell", "vodafone", "türk telekom", "fatura"],
                      "Aidat": ["aidat", "yönetim", "site"], "Kira": ["kira"]}

    async def fatura_odemesini_bul(self, f, kullanilan=None):
        """Faturanın tutarına ve tarihine uyan, daha önce kaydedilmiş bir ödeme (gider) arar."""
        try:
            tutar = float(f.get("tutar") or 0)
        except Exception:
            return None
        if tutar <= 0:
            return None
        bugun = hb.simdi().date()

        def gun(x):
            try:
                return dt.date.fromisoformat(str(x)[:10]) if x else None
            except Exception:
                return None

        so = gun(f.get("son_odeme"))
        ft_ = gun(f.get("fatura_tarihi"))
        bas = (ft_ or (so - dt.timedelta(days=20) if so else bugun - dt.timedelta(days=60))) - dt.timedelta(days=5)
        bit = (so or bas + dt.timedelta(days=30)) + dt.timedelta(days=40)
        pay = max(1.0, tutar * 0.01)
        q = hb.urllib.parse.quote
        b1 = hb.iso_tarih(dt.datetime(bas.year, bas.month, bas.day, tzinfo=hb.TZ))
        b2 = hb.iso_tarih(dt.datetime(bit.year, bit.month, bit.day, tzinfo=hb.TZ))
        sorgu = (f"select=id,tutar,tarih,urun,firma,kategori,aciklama&tur=eq.Gider&tutar=gte.{tutar - pay:.2f}"
                 f"&tutar=lte.{tutar + pay:.2f}&tarih=gte.{q(b1)}&tarih=lt.{q(b2)}&order=tarih&limit=30")
        try:
            adaylar = await self.arka(self.supa.tablo, "hb_islemler", sorgu)
        except Exception:
            return None
        kullanilan = kullanilan if kullanilan is not None else {x.get("odeme_islem_id") for x in self.ek.get("faturalar", [])
                                                               if x.get("odeme_islem_id")}
        izler = [i for i in self._FATURA_IZLERI.get(f.get("tur"), [])] + \
                ([hb.urun_anahtari(f["kurum"]).split(" ")[0]] if f.get("kurum") else []) + [hb.urun_anahtari(f.get("tur") or "")]
        en_iyi, puan = None, -1
        for a in adaylar:
            if a.get("id") in kullanilan or abs(float(a.get("tutar") or 0) - tutar) > pay:
                continue
            if not bas <= hb.tarih_yerel(a["tarih"]).date() < bit:
                continue
            metin = " " + hb.urun_anahtari(" ".join(str(a.get(k) or "") for k in ("urun", "firma", "aciklama", "kategori"))) + " "
            p = 0
            if any(iz and iz.strip() and iz.strip() in metin for iz in izler):
                p += 3
            if "fatura" in metin or "aidat" in metin:
                p += 2
            p -= abs(float(a["tutar"]) - tutar)  # kuruş farkı az olan önce
            if so:
                p -= abs((hb.tarih_yerel(a["tarih"]).date() - so).days) / 30
            if p > puan:
                en_iyi, puan = a, p
        # metin ipucu yoksa yalnızca birebir tutar kabul edilir
        if en_iyi and (puan >= 1 or abs(float(en_iyi["tutar"]) - tutar) < 0.01):
            return en_iyi
        return None

    async def faturalari_esle(self, sessiz=True):
        """Ödenmemiş görünen faturaları eski kayıtlardaki ödemelerle eşleştirir."""
        if getattr(self, "_eslestiriyor", False):
            return 0
        self._eslestiriyor = True
        n = eski = 0
        try:
            kullanilan = {x.get("odeme_islem_id") for x in self.ek.get("faturalar", []) if x.get("odeme_islem_id")}
            bugun = hb.simdi().date()
            for f in list(self.ek.get("faturalar", [])):
                if f.get("odendi") or not f.get("id"):
                    continue
                if not self.yonetici and f.get("kasa_sahibi") != self.ben["id"]:
                    continue
                odeme = await self.fatura_odemesini_bul(f, kullanilan)
                if odeme:
                    kullanilan.add(odeme["id"])
                    await self.arka(self.supa.tablo_guncelle, "hb_faturalar", f["id"],
                                    {"odendi": True, "odeme_islem_id": odeme["id"]})
                    f.update(odendi=True, odeme_islem_id=odeme["id"])
                    n += 1
                elif f.get("mail_id") and f.get("son_odeme"):
                    try:
                        so = dt.date.fromisoformat(str(f["son_odeme"])[:10])
                    except Exception:
                        continue
                    if (bugun - so).days > 20:  # e-postadan bulunan eski fatura: ödenmiş say, kasaya dokunma
                        await self.arka(self.supa.tablo_guncelle, "hb_faturalar", f["id"], {"odendi": True})
                        f["odendi"] = True
                        eski += 1
        except Exception as ex:
            print("Fatura eşleştirme:", ex)
        finally:
            self._eslestiriyor = False
        if n or eski:
            await self.ek_verileri_yenile()
            if not sessiz or n or eski:
                self.bildir("✓ " + ", ".join(x for x in [f"{n} fatura eski kayıtlardaki ödemeyle eşleşti" if n else "",
                                                         f"{eski} eski fatura ödenmiş sayıldı" if eski else ""] if x), GELIR)
            self.ekrani_ciz()
        elif not sessiz:
            self.bildir("Eşleşen ödeme bulunamadı.")
        return n + eski


    # ================================================================== e-postadaki alışveriş faturaları
    def _mail_alisveris(self):
        return self._yerel_oku("mail_alisveris") or []

    async def _alisveris_faturasi(self, f, mail):
        """Satın alma faturası: kayıtlı harcamayla eşleşirse PDF'i ona eklenir; yoksa onaya bırakılır.
        Dönüş: True = harcamayla eşleşti."""
        tutar = float(f.get("tutar") or 0)
        gun = hb.tarih_kesin(f.get("fatura_tarihi")) or mail["tarih"].date()
        pay = max(1.0, tutar * 0.01)
        q = hb.urllib.parse.quote
        b1 = hb.iso_tarih(dt.datetime.combine(gun - dt.timedelta(days=10), dt.time(), hb.TZ))
        b2 = hb.iso_tarih(dt.datetime.combine(gun + dt.timedelta(days=10), dt.time(), hb.TZ))
        try:
            adaylar = await self.arka(self.supa.tablo, "hb_islemler",
                                      f"select=id,tutar,tarih,urun,firma,fis_gorsel,aciklama&tur=eq.Gider"
                                      f"&tutar=gte.{tutar - pay:.2f}&tutar=lte.{tutar + pay:.2f}"
                                      f"&tarih=gte.{q(b1)}&tarih=lt.{q(b2)}&limit=20")
        except Exception:
            adaylar = []
        adaylar = [a for a in adaylar if abs(float(a.get("tutar") or 0) - tutar) <= pay]
        if adaylar:
            a = min(adaylar, key=lambda a: (abs(float(a["tutar"]) - tutar), abs((hb.tarih_yerel(a["tarih"]).date() - gun).days)))
            guncelle = {}
            if not a.get("fis_gorsel") and f.get("pdf"):
                try:
                    guncelle["fis_gorsel"] = await self.arka(self.supa.fis_yukle, f["pdf"], "pdf", "application/pdf")
                except Exception:
                    pass
            if not a.get("firma") and f.get("kurum"):
                guncelle["firma"] = f["kurum"]
            if guncelle:
                try:
                    await self.arka(self.supa.islem_guncelle, a["id"], guncelle)
                except Exception as ex:
                    print("Alışveriş faturası harcamaya eklenemedi:", ex)
            return True
        # onaya bırak (PDF yerelde saklanır)
        liste = [x for x in self._mail_alisveris() if x.get("id") != mail["id"]]
        yol = None
        if f.get("pdf") and len(f["pdf"]) < 3_000_000:
            yol = os.path.join(hb.veri_klasoru(), f"mail_{mail['id']}.pdf")
            try:
                with open(yol, "wb") as fp:
                    fp.write(f["pdf"])
            except Exception:
                yol = None
        liste.append({"id": mail["id"], "kurum": f.get("kurum") or mail.get("kimden"), "tutar": tutar,
                      "tarih": gun.isoformat(), "urunler": f.get("urunler"), "konu": mail.get("konu"), "pdf": yol})
        self._yerel_yaz("mail_alisveris", liste[-30:])
        return False

    def alisveris_faturalari_karti(self):
        liste = self._mail_alisveris()
        if not liste:
            return None
        satirlar = []
        for x in liste[-8:][::-1]:
            satirlar.append(ft.Container(content=ft.Column([
                ft.Row([ft.Column([yazi(x.get("kurum") or "Satıcı", 13, "sb"),
                                   yazi(" • ".join(y for y in [x.get("urunler"), hb.tarih_kesin(x.get("tarih")).strftime("%d.%m.%Y")
                                                               if hb.tarih_kesin(x.get("tarih")) else None] if y), 11,
                                        renk=ui.SOLUK, max_lines=2)], spacing=0, expand=True),
                        yazi(hb.tl(x["tutar"]), 13.5, "xb")], spacing=8),
                ft.Row([buton("Harcama olarak ekle", lambda e, x=x: self.alisveris_faturasi_ekle(x), ft.Icons.ADD_ROUNDED,
                              tip="text"),
                        buton("Yoksay", lambda e, x=x: self.alisveris_faturasi_kaldir(x), tip="text")],
                       alignment=ft.MainAxisAlignment.END, spacing=0)], spacing=2),
                bgcolor=ui.ZEMIN2, border_radius=14, padding=ft.Padding(12, 8, 6, 2)))
        return kart(ft.Column([
            ft.Row([ft.Icon(ft.Icons.SHOPPING_BAG_ROUNDED, color="#0891b2"),
                    yazi(f"E-postadaki alışveriş faturaları ({len(liste)})", 14, True, expand=True)]),
            yazi("Bunlar ödenecek fatura değil; satın aldığınız ürünlerin e-faturaları. Kayıtlı bir harcamayla eşleşmedikleri "
                 "için size soruluyor: harcama olarak eklemediyseniz ekleyin, eklediyseniz yoksayın.", 11.5, renk=ui.SOLUK),
            *satirlar], spacing=8), shadow=golge(0.5))

    def alisveris_faturasi_kaldir(self, x):
        self._yerel_yaz("mail_alisveris", [y for y in self._mail_alisveris() if y.get("id") != x.get("id")])
        if x.get("pdf"):
            try:
                os.remove(x["pdf"])
            except Exception:
                pass
        self.ekrani_ciz()

    def alisveris_faturasi_ekle(self, x):
        kat = acilir("Kategori", self.kategoriler, "Diğer")
        urun = ft.TextField(label="Ürün / açıklama", value=x.get("urunler") or "", dense=True)
        kasa = self._kasa_secici()

        async def kaydet():
            gorsel = None
            if x.get("pdf"):
                try:
                    with open(x["pdf"], "rb") as fp:
                        gorsel = await self.arka(self.supa.fis_yukle, fp.read(), "pdf", "application/pdf")
                except Exception:
                    gorsel = None
            gun = hb.tarih_kesin(x.get("tarih")) or hb.simdi().date()
            kayit = {"tur": "Gider", "tutar": float(x["tutar"]), "tarih": hb.iso_tarih(dt.datetime.combine(gun, dt.time(12), hb.TZ)),
                     "firma": x.get("kurum"), "urun": (urun.value or "").strip() or None, "kategori": kat.value or "Diğer",
                     "kasa_sahibi": kasa.value if self.yonetici else self.ben["id"], "hedef_kasa": None,
                     "fis_gorsel": gorsel, "aciklama": "E-postadaki e-faturadan"}
            if self.yonetici:
                kayit["gizli"] = self.gizli_varsayilan
            if await self.kayit_ekle([kayit]):
                self.bildir("Harcama eklendi ✓", GELIR)
            self.alisveris_faturasi_kaldir(x)
            await self.verileri_yenile(ciz=False)
            self.ekrani_ciz()

        self._girdi_dialog(f"{x.get('kurum') or 'Alışveriş'} – {hb.tl(x['tutar'])}", [urun, kat] + (
            [yazi("Hangi kasadan ödendi?", 12, renk=ui.SOLUK), kasa] if self.yonetici else []), kaydet, "Ekle")

    async def _mail_denetimi(self):
        """v2.8.1 öncesi e-postadan eklenen, abone numarası olmayan 'faturalar' (alışveriş e-faturası olabilir) silinir ve
        yeni sınıflandırmayla yeniden değerlendirilmek üzere tekrar taranır (bir kez)."""
        if self._yerel_ayar().get("mail_denetim_282"):
            return
        gorulen = self._mail_gorulen()
        silinen = 0
        for f in list(self.ek.get("faturalar", [])):
            if not f.get("mail_id") or f.get("abone_no") or not f.get("id"):
                continue
            try:
                await self.arka(self.supa.tablo_sil, "hb_faturalar", f["id"])
                gorulen.discard(str(f["mail_id"]).replace("gmail:", ""))
                silinen += 1
            except Exception as ex:
                print("Denetim: fatura silinemedi:", ex)
                return
        self._yerel_yaz("mail_gorulen", list(gorulen))
        self._yerel_ayar_yaz(mail_denetim_282=True)
        if silinen:
            await self.ek_verileri_yenile()
            self.bildir(f"🔎 E-postadan yanlışlıkla fatura sayılan {silinen} kayıt kaldırıldı; yeniden değerlendirilecek")

    # ================================================================== kurum sayfasından borç sorgusu (ESKİ)
    def _bagli_abonelikler(self):
        return [ab for ab in self.ek.get("abonelikler", []) if ab.get("baglanti") and ab.get("aktif", True)
                and (self.yonetici or ab.get("kasa_sahibi") == self.ben["id"])]

    async def kurum_sorgula(self, ab, sessiz=True):
        import hb_kurum
        try:
            r = await self.arka(hb_kurum.borc_sorgula, ab["baglanti"], ab.get("abone_no") or "", ab.get("musteri_no"))
        except Exception as ex:
            mesaj = str(ex)
            try:
                await self.arka(self.supa.tablo_guncelle, "hb_abonelikler", ab["id"],
                                {"son_sorgu": hb.iso_tarih(hb.simdi()), "son_bilgi": f"Sorgulanamadı: {mesaj[:120]}"})
            except Exception:
                pass
            if not sessiz:
                self.bildir(f"{ab.get('kurum') or ab['tur']}: sorgulanamadı – {mesaj}", GIDER)
            return None
        kurum = hb_kurum.KURUMLAR.get(ab["baglanti"], (ab.get("kurum") or "Kurum",))[0]
        yeni = 0
        if not r["borc_yok"]:
            kalemler = r["kalemler"] or [{"tutar": r["toplam"], "son_odeme": None, "donem": None}]
            for k in kalemler:
                anahtar = f"{ab['baglanti']}:{ab.get('abone_no')}:{k.get('donem') or k.get('son_odeme') or hb.simdi().strftime('%Y-%m')}:{k['tutar']:.2f}"
                kayit = {"tur": ab.get("tur") or "Su", "kurum": ab.get("kurum") or kurum.split(" –")[0],
                         "abone_no": ab.get("abone_no"), "donem": k.get("donem"), "son_odeme": k.get("son_odeme"),
                         "tutar": k["tutar"], "kasa_sahibi": ab.get("kasa_sahibi") or self.ben["id"], "mail_id": anahtar,
                         "kategori": "Kira & Aidat & Faturalar",
                         "analiz": f"{kurum} borç sorgusundan otomatik eklendi ({hb.tarih_goster(r['zaman'])})."}
                try:
                    if await self.arka(self.supa.fatura_mailden_ekle, kayit):
                        yeni += 1
                except Exception as ex:
                    print("Kurum faturası eklenemedi:", ex)
        bilgi = (f"Borç yok ✓" if r["borc_yok"] else f"Borç: {hb.tl(r['toplam'])}"
                 + (f" (gecikme {hb.tl(r['gecikme'])})" if r.get("gecikme") else ""))
        try:
            await self.arka(self.supa.tablo_guncelle, "hb_abonelikler", ab["id"],
                            {"son_sorgu": r["zaman"], "son_borc": r["toplam"], "son_bilgi": bilgi})
        except Exception:
            pass
        ab.update(son_sorgu=r["zaman"], son_borc=r["toplam"], son_bilgi=bilgi)
        # kurumda borç yoksa, uygulamada "ödenmedi" duran o aboneliğin faturaları ödenmiştir
        bekleyen = [f for f in self.ek.get("faturalar", []) if not f.get("odendi") and f.get("id")
                    and ((ab.get("abone_no") and f.get("abone_no") == ab.get("abone_no"))
                         or (not f.get("abone_no") and f.get("tur") == ab.get("tur")))]
        kapanan = 0
        if r["borc_yok"] and bekleyen:
            for f in bekleyen:
                odeme = await self.fatura_odemesini_bul(f)
                alanlar = {"odendi": True}
                if odeme:
                    alanlar["odeme_islem_id"] = odeme["id"]
                else:
                    alanlar["analiz"] = ((f.get("analiz") or "") + f"\n{kurum} sorgusunda borç görünmüyor: ödenmiş sayıldı "
                                         "(kasadan düşülmedi; ödemeyi kaydetmediyseniz harcama olarak ekleyin).").strip()
                try:
                    await self.arka(self.supa.tablo_guncelle, "hb_faturalar", f["id"], alanlar)
                    kapanan += 1
                except Exception as ex:
                    print("Fatura kapatılamadı:", ex)
        if yeni or kapanan:
            await self.ek_verileri_yenile()
            self.bildir(f"💧 {kurum}: " + ", ".join(x for x in [f"{yeni} yeni borç faturası eklendi" if yeni else "",
                                                                f"{kapanan} fatura ödenmiş görünüyor" if kapanan else ""] if x),
                        GIDER if yeni else GELIR)
        elif not sessiz:
            self.bildir(f"💧 {kurum}: {bilgi}", GELIR if r["borc_yok"] else GIDER)
        return r

    async def _tek_sorgu(self, ab):
        self.bildir(f"🔎 {ab.get('kurum') or ab['tur']} sorgulanıyor…")
        await self.kurum_sorgula(ab, sessiz=False)
        self.ekrani_ciz()

    async def kurumlari_sorgula(self, en_az_saat=12, sessiz=True):
        for ab in self._bagli_abonelikler():
            son = ab.get("son_sorgu")
            if son and (hb.simdi() - hb.tarih_yerel(son)).total_seconds() < en_az_saat * 3600:
                continue
            await self.kurum_sorgula(ab, sessiz)
        if self.sekme == 4 and self.alt_sayfa in ("abonelikler", "faturalar"):
            self.ekrani_ciz()
