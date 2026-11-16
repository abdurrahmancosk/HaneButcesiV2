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

## Sürüm 2.4 – kasa geçmişi, altın/döviz, market fiyatları ve daha fazlası
**Önce bir kez:** Supabase > SQL Editor'da `guncelleme_5.sql` dosyasının içeriğini yapıştırıp **Run** deyin.

- **Kasa hareketleri:** Özet'teki kasa kartına (yönetici: kişi kasalarına da) dokunun. Para girişleri / Aktarımlar / Giderler / Tümü, ay ay toplamlarla bütün geçmiş.
- **Tüm zamanlar:** Özet'te dönem çubuğunun altındaki “Tüm zamanlar” ile ilk kayıttan bugüne gelir/gider/kategoriler.
- **Mükerrer fiş uyarısı:** Okunan fiş aynı gün, aynı market ve aynı saat (±10 dk) ya da aynı toplamla zaten eklenmişse kırmızı uyarı çıkar; “Yine de ekle” ile kaydedilebilir.
- **Altın & döviz (Menü):** “Mevcut varlığımı ekle” kasayı etkilemez; “Yeni aldım” kasadan gider olarak düşer; “Sattım” kasaya gelir ekler. Güncel değer ve kâr/zarar finans.truncgil.com fiyatlarıyla.
- **Güncel market fiyatları:** Menü > Ayarlar'da ev konumunu kaydedin. Fiyat takibi sayfasından ürün arayın; Alışveriş listesinde “Listeyi en ucuza tamamla”. Kaynak marketfiyati.org.tr (TÜBİTAK); resmi API değildir, değişirse çalışmayabilir.
- **Harçlık bütçesi:** Menü > Bütçe limitleri > Kişi bütçeleri (yalnız Abdurrahman belirler). Hatice kalan tutarı Özet'te görür; %80 ve aşımda ikinize bildirim.
- **Okul harçlığı otomatiği:** Menü > Ayarlar (Abdurrahman). Hafta içi okul günlerinde, MEB tatilleri hariç otomatik gider.
- **Haftalık özet bildirimi:** Pazar akşamı.
- **İnternetsiz kayıt:** İnternet yokken elle girilen kayıtlar telefonda bekler, bağlantı gelince gönderilir. Son veriler önbellekten gösterilir.
- **Görseller:** Halka grafik (dokununca o kategorinin işlemleri), harcama takvimi, kişi renkleri (Abdurrahman mavi, Hatice pembe), Menü > Yıl özeti.

## Sürüm 2.5 – aktüel kataloglar ve Erzurum altın fiyatı
**Önce bir kez:** Supabase > SQL Editor'da `guncelleme_6.sql` içeriğini çalıştırın.

- **Aktüel fırsatlar (otomatik):** Uygulama günde bir kez BİM, A101, ŞOK, Migros ve CarrefourSA'nın güncel aktüel kataloglarını yapay zekayla internette arar (Gemini + Google Arama, Gemini anahtarınızla). Sonuçlar iki telefonda ortaktır.
  - Fiyat takibi sayfasında “Bu haftanın aktüel fırsatları” (market seçimi, arama, “Şimdi tara”).
  - Alışveriş listesindeki ürün aktüeldeyse satırda yeşil etiket çıkar ve ikinize bir kez bildirim gider.
  - “Listeyi en ucuza tamamla” sonucunda aktüeldekiler ayrıca gösterilir.
- **Altın fiyatı:** Artık Harem Altın (Erzurum Kuyumcular Odası uygulamasının da baz aldığı kaynak) kullanılır; ulaşılamazsa truncgil'e döner.
  - **Erzurum fiyatıyla eşitle:** Oda uygulamasındaki gram ve çeyrek alış/satış fiyatını bir kez girin; uygulama farkı öğrenir ve fiyatlar değiştikçe değeri Erzurum fiyatına göre hesaplar.

## Sürüm 2.6 – yeni “Gece” görünümü
- Açık ve koyu tema; varsayılan **cihazın teması** (telefon koyu moddaysa uygulama da koyu). Menü > Ayarlar > Tema: Cihaz / Açık / Koyu.
- Yeni alt menü: Özet · İşlemler · **+** · Planla · Menü. Ortadaki altın **+** düğmesi fiş tarama, galeri, PDF, gider, gelir, aktarım ve fatura yüklemeyi tek yerde toplar (eski Ekle ve Fiş sekmeleri birleşti).
- **Planla** sekmesi: yaklaşan ödemeler, bütçe ve harçlık durumu, alışveriş listesi (aktüel etiketleriyle), birikim hedefleri, açık borç/alacak.
- Inter yazı tipi, lacivert kasa kartı, kuruşları soluk gösteren büyük rakamlar, sade kartlar.

## Sürüm 2.7 – taksitler, gerçekten harcanabilir para, hane sohbeti
**Önce bir kez:** Supabase > SQL Editor'da `guncelleme_7.sql` içeriğini çalıştırın.

- **Taksitler** (Planla ve Menü): ne alındı, kart, aylık tutar, kalan taksit, ayın kaçında ödendiği, kategori, kasa. Ödeme gününden bir gün önce ve o gün ikinize bildirim. Aynı karttaki taksitler tek “kart ödemesi” olarak görünür; “Ödedim” her birini kendi kategorisiyle harcamalara ekler ve kasadan düşer. Kalan taksit borcu ve 6 aylık yük grafiği.
- **Gerçekten harcanabilir:** Kasa kartında; kasadan bu dönemin ödenmemiş faturaları, taksitleri ve düzenli ödemeleri düşülür. Dokununca dökümü açılır.
- **Hane sohbeti** (Özet'teki konuşma balonu veya Menü): mesajlar, para isteği (eşiniz “Gönder” deyince aktarım kendiliğinden kaydedilir), bir kaydın detayından “Yorum yaz”, gelen kısa mesajı tek dokunuşla alışveriş listesine ekleme. Her mesaj diğer telefona bildirim olarak gider; gizli kayıtlara yazılan yorumları Hatice görmez.

## Sürüm 2.7.1
- **Kart ekstresinden taksit:** Taksitler > “Ekstreden ekle” (PDF, ekran görüntüsü ya da kamera). Şifreli PDF'te şifre sorulur (kaydedilmez). Bulunan taksitler listelenir; kayıtlı olanlar güncellenir, yeniler eklenir. Fiş ya da fatura olarak yüklenen ekstre PDF'leri de otomatik olarak buraya yönlendirilir.
- **Fatura türü ekleme:** Fatura ekranında türün yanındaki **+** ile yeni tür (Okul servisi, Kasko…). “Kredi kartı” ve “Sigorta” hazır. Ödenince hangi harcama kategorisine yazılacağı seçilebilir. Kayıtlı faturalarda **Düzenle**.
- **Aşağı çekip yenile:** Özet, İşlemler, Planla ve menü sayfalarında ekranı aşağı çekin (ya da Özet'teki “Canlı” etiketine dokunun).
- **Daha hızlı okuma:** Fiş/fatura/ekstre okurken yapay zekanın uzun “düşünme” adımı kapatıldı.

## Sürüm 2.8 – e-postadan otomatik fatura takibi, abonelikler
**Önce bir kez:** Supabase > SQL Editor'da `guncelleme_8.sql` içeriğini çalıştırın.

Gmail bağlama (bir kez, her cihazda ayrı):
1. Google hesabında 2 adımlı doğrulama açık olmalı (myaccount.google.com > Güvenlik).
2. https://myaccount.google.com/apppasswords → uygulama adı “Hane Bütçesi” → Oluştur → 16 harfli şifreyi kopyalayın.
3. Uygulamada Menü > Ayarlar > “E-postadan fatura takibi”: Gmail adresi + uygulama şifresi → **Bağla**.

- Bağlanınca son 45 günün faturaları aranır; sonra uygulama her açıldığında (4 saatte bir) ve aşağı çekince (30 dakikada bir) kontrol eder.
- Fatura e-postaları (PDF ek ya da mail metni) okunur, fatura olarak eklenir, ikinize bildirim gider. Reklam/dekont/kargo mailleri atlanır. Aynı fatura iki kez eklenmez.
- Abone numarası olan her yeni kurum **Abonelikler**e kendiliğinden eklenir; beklenen günden 5 gün sonra fatura gelmezse uyarılır.
- E-postayla gelen kart ekstresi fark edilir: Taksitler sayfasında “taksitleri güncelle” önerisi çıkar.
- Uygulama şifresi yalnızca o cihazda saklanır (buluta/Hatice'ye gitmez). Mailler okunmamış olarak kalır. İstediğiniz an Ayarlar'dan “Kaldır” ya da Google hesabınızdan şifreyi silerek erişimi kapatabilirsiniz.

## Sürüm 2.9 – ESKİ su borcu otomatik sorgu
**Önce bir kez:** Supabase > SQL Editor'da `guncelleme_9.sql` içeriğini çalıştırın.

Menü > Abonelikler > (Su aboneliğine dokunun ya da “Abonelik ekle”) → Kurum: ESKİ, “Kurumdan otomatik borç sorgusu”: **ESKİ – Erzurum Su**, abone no alanına **tesisat no**, **müşteri no** → Kaydet.
- Kaydedince hemen, sonra günde iki kez (ve aşağı çekince en çok 2 saatte bir) ESKİ'nin borç sorgulama sayfası okunur.
- Borç varsa her dönem için su faturası eklenir (son ödeme tarihiyle) ve hatırlatılır; aynı borç iki kez eklenmez.
- Borç yoksa uygulamada “ödenmedi” görünen su faturaları kapanır (ödemesi kayıtlarda bulunursa ona bağlanır; bulunamazsa ödenmiş sayılır, kasadan düşülmez).
- Abonelik kartındaki 🔎 düğmesiyle istediğiniz an sorgulanır. Resmi bir servis değildir; ESKİ sayfası değişirse “Sorgulanamadı” yazar.

## Sürüm 2.10
- **PBY'den aidat & yakıt:** Faturalar sayfası ya da **+** menüsü > “Aidat & yakıt (PBY)”. PBY uygulamasında bu ayın borç ekranının ekran görüntüsünü seçin: yakıt → “Yakıt” faturası, aidat + elektrik → “Aidat” faturası, ikisinin de son ödeme tarihi yakıtınki. Aynı ay iki kez eklenmez.
- **Günlük harcama sınırı:** Özet'te “Bugün harcayabileceğin”: kasadan bu dönemin ödenmemiş faturaları, taksitleri ve düzenli ödemeleri düşülür, kalan gün sayısına bölünür. %90'da ve aşılınca uyarır.
- **Akıllı bütçe (Menü):** son 6 ayın fişlerinden hangi ürünü ne sıklıkla/ne kadara aldığınız, yakında bitecekler (tek dokunuşla listeye), bu dönemin gidişatı ve ortalamalar, ortalamaları bütçe limiti yapma, yapay zeka önerileri.
- Düzeltmeler: elle eklemede `suffix_text` hatası; Flet 1.x'te değişen parametreler için genel uyumluluk katmanı; açılır listelerde seçim olayının çalışmaması (ESKİ aboneliğinin kaydedilememesi); pencere kapatılırken üstteki bildirimin pencere yerine kapanması; fiş detayında “Yorum yaz” hatası.

## Sürüm 2.11 – kalıcı APK imzası, yeni kredi kartı ekstresi, yanıp sönen uyarılar
**Bir kez – APK güncelleme sorunu (önemli):**
1. Klasördeki **Imza_Kur.bat** dosyasını çalıştırın. Tarayıcıda GitHub'ın “New repository secret” sayfası açılır; her adımda gereken metin panoya kopyalanır, siz Ctrl+V yapıp “Add secret”e basarsınız. İki secret eklenir: `ANDROID_KEYSTORE_BASE64` ve `ANDROID_KEYSTORE_PASSWORD`. (Bilgisayarda GitHub CLI `gh` giriş yapılmışsa bunu kendisi yapar.)
2. Sonra **GitHub_Yukle.bat** ile derletin. GitHub > Releases'te “Kalici imza” yazıyorsa tamam.
3. Telefonlarda bekleyen çevrimdışı kayıt olmadığından emin olun, eski uygulamayı **son bir kez** silin, yeni APK'yi kurun. Kayıtlarınız bulutta olduğu için kaybolmaz; yalnızca telefonda tutulanlar yeniden yapılır: giriş, PIN/parmak izi, tema, Gmail uygulama şifresi ve (yaptıysanız) Erzurum altın fiyatı eşitlemesi.
4. Bundan sonraki her sürüm silmeden “Güncelle” ile kurulur.
- `imza` klasörü imza anahtarıdır: silmeyin, paylaşmayın. GitHub'a yüklenmez.

**İsteğe bağlı:** Supabase > SQL Editor'da `guncelleme_10.sql` (gelecek ay tahminleri için ayrı ayrı “fatura yükledi” bildirimi gitmez).

- **Kredi kartı (Menü / Planla):** Ekstre yükleyince harcama kalemleri gösterilmez; yalnızca **bu ayın ödenecek toplamı** son ödeme tarihine kaydedilir, **kalan taksitlerin ay ay toplamı** gelecek aylara “tahmini ekstre” olarak yazılır (kartla yeni harcama yapılmayacağı varsayımıyla). O ayın gerçek ekstresi yüklenince tahmin gerçek tutarla değişir; aynı ekstre iki kez eklenmez.
- **İadeler** artık harcama sayılmaz (eksi tutarlar, “İADE/İptal” kayıtları); iade edilen taksitli alışverişin kalan taksitleri gelecek aylara yazılmaz. Kart borcu ödemeleri de karışmaz.
- Kart sayfasında sıradaki ödeme, “Ödedim” (eksik ödenirse kalan gelecek ayın tahminine eklenir), 8 aylık yük grafiği ve ödenmiş ekstreler. Elle eklenen taksitler varsa ayrıca görünür; ekstre yüklerken bunlar kapatılabilir (iki kez sayılmasın).
- **Yanıp sönen uyarı:** Son ödeme günü gelen ya da geçen fatura, kart ekstresi, taksit ve düzenli ödemeler Özet'te, Faturalar'da, Planla'da ve kart sayfasında yanıp söner.

## Sürüm 2.12.2 – Hatice gelirler ve gizlenenler dışında her şeyi görür (toplam kasa ve günlük sınır dahil)
**Önce bir kez (zorunlu):** Supabase > SQL Editor'da `guncelleme_13.sql` içeriğini çalıştırın. `guncelleme_11.sql` ve `guncelleme_12.sql`'in içeriği de bu dosyada; onları çalıştırdıysanız da çalıştırmadıysanız da yalnızca bu yeterli. Çalıştırılmazsa Hatice yine yalnızca kendi kasasını görür.

- **Hatice görmez:** gelirler (kendi kasasına kendi girdikleri hariç) ve “Hatice'den gizle” işaretli kayıtlar (fiş görselleri ve hedeflere katkıları dahil).
- **Hatice görür:** Özet'te **TOPLAM KASA** ve iki kasanın bakiyesi, “gerçekten harcanabilir” tutar ve **hanenin günlük harcama sınırı** (sizinkiyle aynı rakam); harcamalar ve aktarımlar (İşlemler'de kimin kasası olduğu yazar, kasaya göre süzülebilir), ödenen/ödenecek tüm faturalar ve kart ekstreleri, düzenli ödemeler, taksitler, birikim hedefleri, borç/alacaklar, altın & döviz, abonelikler. Hatırlatmalarda başkasına ait olanın başında sahibinin adı yazar. Takvim, kategoriler, bütçe limitleri, yıl özeti ve akıllı bütçe hanenin harcamasıyla hesaplanır; harçlık bütçesi yalnızca kendisinindir.
- **Gizli harcamalar ve günlük sınır:** Gizlediğiniz harcamalar Hatice'nin listesinde görünmez, ama günlük sınır iki telefonda aynı çıksın diye bugünkü toplama yalnızca rakam olarak eklenir; o gün gizli harcama varsa Hatice'nin kartında tutar yerine “sınırın %… kullanıldı” yazar.
- **Değiştirme yetkisi:** Hatice yalnızca kendi eklediği kayıtları ve kendi kasasına ait olanları öder/düzenler/siler; sizinkileri yalnızca görür (dokununca “yalnızca görüntüleyebilirsiniz” der). Sizin kasanızın hareket sayfasını açamaz, kendi kasasınınkini açar.
- **Hızlı gizle (yalnız sizde):** bir kayda ya da fişe dokunun → **Gizle** / **Göster**. Fişte tüm satırlar birlikte gizlenir. Önceden Hatice sizin kasanızı hiç görmediği için gizlemediğiniz eski harcamalar bu güncellemeyle ona görünür hale gelir; görmesini istemediklerinizi SQL'i çalıştırmadan önce bu düğmeyle gizleyin (ya da SQL dosyasının sonundaki isteğe bağlı satırla eskilerin hepsini birden).

## Sürüm 2.12.3 – e-posta yalnızca 16 Kasım 2026 ve sonrası
- Gmail'den fatura / alışveriş faturası taraması artık yalnızca **16.11.2026 ve sonraki** e-postalara bakar; daha eski postalar hiç okunmaz, böylece önceden girilmiş faturalar ikinci kez eklenmez.

## Sürüm 2.13.0 – gerçekçi harcama temposu
- Fatura, kart ekstresi, kira/aidat, taksit, birikim/yatırım ödemeleri ve tek seferlik büyük alışverişler (tipik bir alışverişin 8 katından ve 1.500 ₺'den büyük olanlar, fiş tek alışveriş sayılır) artık “günlük tempo”ya katılmaz.
- Dönem sonu tahmini = ödenen sabitler + bu dönem kalan bilinen ödemeler (fatura, ekstre, taksit, düzenli) + büyük alışverişler + tipik günlük harcama × kalan gün.
- Grafikte günlük harcamalar çubuk, toplu ödeme günleri turuncu noktayla gösterilir; geçen dönemin aynı gününe göre karşılaştırma eklenir. Günlük harcama sınırı da aynı toplu ödemeleri saymaz.

## Sürüm 2.13.1 – altın/döviz alışını düzenleme
- Menü > Altın & döviz > Detay'da her alışın yanında ✏️ var: miktar, birim alış fiyatı (bilmiyorsanız ödediğiniz toplamı yazın, birim fiyat hesaplanır), tarih ve not düzeltilebilir. Alım kasadan düşülmüşse bağlı gider kaydı da yeni tutara göre düzeltilir.

## Sürüm 2.14.0 – takvimden tarih, saatten saat; açılır birim listesi
- Tüm tarih alanlarının yanında 📅 düğmesi var: takvimden gün seçilir, işlem tarihlerinde ardından saat de sorulur (okul harçlığı saati 🕘 ile). Elle yazmak yine serbest.
- Miktar artık sayı + açılır birim listesi (adet, kg, gr, lt, ml, paket, kutu, şişe, demet, metre, m³, kWh…). Listenin en altındaki “+ Yeni birim…” ile kalıcı birim eklenir (sizin eklediğiniz birimler iki telefonda da görünür; Hatice'nin eklediği kendi telefonunda kalır). Fatura tüketim birimi de aynı listeden seçilir.

## Sürüm 2.15.0 – kaydırma düzeltmesi, en başa/en sona, ek ders tahmini
- Liste aşağı kaydırılmışken arka plan yenilemesi (20 sn / 2 dk'da bir, ya da eşinizin eklediği kayıt) artık sizi en üste atmıyor: veri değişmediyse ekran hiç yeniden çizilmez; değiştiyse kaldığınız yere geri dönülür. Arama kutusuna yazarken de ekran değişmez.
- Harcamalar listesinin sağ altında “en başa” ve “en sona” düğmeleri var.
- Kasa hareketleri (kendi kasanız) ve Planla ekranında **Tahmini ek ders** kartı (yalnızca yönetici görür): ayın pansiyon nöbet (belleticilik) sayısını + / − ile girin (ayda en fazla 8); o ayın net ek dersi ve gelecek ayın 5–8'inde yatacağı gösterilir.
  - Hesap Ekim 2026 puantajındaki haftalık programla yapılır: Pzt 8 (3 nöbet + 2 yer.geç.gör. + 3 gündüz), Çar 2, Per 2, Cum 4 (2 yer.geç.gör. + 2 gündüz) = haftada 16 saat; her belleticilik 8 saat; ara tatilde günde 3 saat; resmî bayram günü de ödenir; yaz/yarıyıl tatilinde 0. Hafta bütünlüğü esas (perşembesi o ayda olan haftalar – Ekim 2026 = 28 Eylül–1 Kasım).
  - Ücret: brüt saat 220,57 ₺ (ozkansoft EDUHEP, 2026 Temmuz–Aralık, kadrolu, lisans); gelir vergisi %20 − 5.615,10 ₺ asgari ücret istisnası; damga vergisi 33.030 ₺ üstüne. Ekim 2026 için tahmin 28.201,64 ₺ – bordroyla kuruşu kuruşuna aynı.
  - Geçmiş aylarda yatan gerçek tutar ve tahminden fark kartta görünür. ⚙ ile gün gün program, vergi dilimi, istisnalar, saat ücreti ve “diğer ek ders” saatleri değiştirilebilir; Ocak 2027'de istisna tutarlarını güncelleyin. “Yattı – gelir olarak ekle” formu doldurur. Ayarlar bu telefonda saklanır.
