# Hane Bütçesi v2 – Kurulum (ilk deneme)

Uygulama; **Flet** (Android + Windows), **Supabase** (giriş, veritabanı, anlık senkron, fiş görselleri) ve **Gemini** (fiş okuma) ile çalışır. Mevcut Supabase projenizi kullanır; eski `islemler` tablonuza dokunmaz, yeni tablolar `hb_` ile başlar.

## 1) Veritabanını kurun (tek seferlik)
Dashboard → **SQL Editor → New query** → `supabase_kurulum.sql` dosyasının tamamını yapıştırın → **Run**.
Bu betik: tabloları, “Hatice yalnızca kendi kasasını görür” güvenlik kurallarını, kasa bakiyesi fonksiyonunu, anlık senkronu, `hb-fisler` fiş deposunu ve mevcut kategorilerinizle 80 ürün→kategori eşlemenizi kurar. Tekrar çalıştırmak güvenlidir.

## 2) İlk giriş: şifreleri uygulamada belirleyin
Uygulamayı açınca giriş ekranında **“Abdurrahman için şifre belirle”** / **“Hatice için şifre belirle”** düğmeleri çıkar. Her kişi kendi şifresini bir kez belirler; sonra kullanıcı adı + şifre ile girilir. Şifre sonradan **Ayarlar → Şifremi değiştir** ile değiştirilebilir.

## 3) Bilgisayarda hemen deneyin
```
cd HaneButcesiV2
pip install -r requirements.txt
python main.py
```
Abdurrahman ile girin → **Ayarlar** → Gemini API anahtarını kaydedin (tek sefer; iki telefon da kullanır).
İkinci bir pencerede `python main.py` açıp Hatice ile girerek anlık senkronu görebilirsiniz.

## 4) Telefona APK
1. GitHub'da boş bir depo açın (örn. `HaneButcesiV2`).
2. `GitHub_Yukle.bat` dosyasına çift tıklayın, ilk seferde depo adresini yapıştırın.
3. GitHub → **Actions** derlemeyi bitirince **Releases → latest → HaneButcesi_v2.apk** dosyasını iki telefona kurun.
   (Paket adı farklı olduğu için eski uygulamanızla yan yana kurulabilir.)
4. Aynı Releases sayfasında bilgisayar için **HaneButcesi.exe** de bulunur; kurulum gerektirmez, çift tıklayıp açılır.
   (İlk açılış 10-20 sn sürebilir. Windows SmartScreen uyarısında *Ek bilgi → Yine de çalıştır* deyin.)

## Nasıl çalışır?
- **Bütçe dönemi:** ayın 15'i – sonraki ayın 14'ü. Bugün 15 ve sonrasıysa bu ayın 15'inden, 14 ve öncesiyse geçen ayın 15'inden başlar. Oklarla önceki/sonraki dönemlere geçilir.
- **Kasalar:** Abdurrahman *Toplam Kasa* + *Abdurrahman* + *Hatice* kasalarını görür; Hatice yalnızca kendi kasasını ve kendi işlemlerini görür (sunucu tarafında RLS ile zorunlu).
- **Kim ekledi:** her kayıtta ekleyenin adı sunucu tarafından yazılır (taklit edilemez).
- **Aktarım:** bir kasadan diğerine para verme; toplam kasa değişmez.
- **Fiş:** fotoğraf/PDF seçilir → görsel buluta yüklenir → Gemini ürünleri, fiyatları, kategorileri çıkarır → siz düzeltip kaydedersiniz. Değiştirdiğiniz kategoriler öğrenilir, bir dahakine otomatik uygulanır.
- **Anlık senkron:** biri kayıt eklediğinde diğer telefon ~1 sn içinde güncellenir ve “🔔 Hatice: …” bildirimi görünür.

## Sürüm 2.2 – yeni özellikler
Supabase'de bir kez **`guncelleme_3.sql`** çalıştırın (yeni tablolar). Sonra `GitHub_Yukle.bat`.

- **Kamera:** Fiş ve faturayı uygulama içinden çekin; uzun fişleri birkaç parça halinde çekince tek görsele birleştirilir. Flaş, galeriden seçme.
- **Faturalar:** Fatura fotoğrafı/PDF'i yüklenince tür, kurum, tüketim, tutar, son ödeme tarihi okunur. Önceki faturayla karşılaştırılıp “zam mı, kullanım mı” söylenir. Son ödemeden 1 gün önce ve gününde uyarı (uygulama açıkken / açılışta). “Ödendi” deyince kasadan düşer.
- **Düzenli ödemeler:** Kira, aidat vb.; günü gelince hatırlatır, “Öde” deyince kasadan düşer, zam gelince tutar güncellenir.
- **Bütçe limitleri**, **birikim hedefleri**, **borç/alacak**, **ortak alışveriş listesi** (fiş kaydedilince eşleşen ürünler otomatik işaretlenir).
- **Fiyat takibi:** Fişte her ürünün altında son fiyat/en ucuz market; Menü > Fiyat takibi.
- **Hızlı ekleme:** Özet ekranında “bimden 3 ekmek 45 lira” yazın (klavyenin mikrofonuyla sesli de olur).
- **Akıllı rapor:** Önceki dönemle kategori karşılaştırması, yapay zeka yorumu ve tasarruf önerileri, Excel/PDF indirme.
- **Asistan:** “Bu ay sigaraya ne kadar verdik?” gibi sorular.
- **Karanlık tema** ve **PIN kilidi** (Menü > Ayarlar).

## Sürüm 2.3 – bildirimler, sesli ekleme, parmak izi
Supabase'de bir kez **`guncelleme_4.sql`** çalıştırın, sonra `GitHub_Yukle.bat`.

- **Uygulama içi bildirimler (zil simgesi):** Eşinizin eklediği gider/gelir, fiş, fatura ve alışveriş listesi maddeleri ile her sabah 09:00'da fatura/düzenli ödeme hatırlatmaları. Her bildirim **bir kez** üretilir; okununca/temizlenince bir daha gelmez. Hatice, sizin gizli işaretlediğiniz ya da sizin kasanıza ait kayıtlar için bildirim almaz.
- **Uygulama kapalıyken telefona bildirim (OneSignal, ücretsiz):**
  1. https://onesignal.com → ücretsiz hesap → *New App* → ad: Hane Bütçesi → platform: **Google Android (FCM)**.
  2. OneSignal sizden Firebase dosyası ister: https://console.firebase.google.com → *Proje oluştur* → ⚙️ *Proje ayarları* → *Hizmet hesapları* → **Yeni özel anahtar oluştur** → inen JSON dosyasını OneSignal'e yükleyin.
  3. OneSignal → *Settings → Keys & IDs*: **App ID**'yi kopyalayın, **Add Key** ile bir **App API Key** oluşturup kopyalayın.
  4. Uygulamada Abdurrahman ile: **Menü → Ayarlar → Telefon bildirimleri** → ikisini yapıştırıp *Kaydet*.
  5. Uygulamayı iki telefonda da kapatıp açın, bildirim iznini verin.
- **Sesli ekleme:** Özet'teki hızlı ekleme kutusunda 🎙️ → "Migros'tan iki süt seksen lira" deyin → tekrar dokunun → onaylayın. Asistan ekranında da sesli soru sorabilirsiniz. (Telefonda; ilk kullanımda mikrofon izni ister.)
- **Parmak izi:** Menü → Ayarlar → *Parmak izi / yüz tanıma ile kilit*. PIN ile birlikte de kullanılabilir.
