# AMG65 Studio for macOS

SwiftUI uygulaması, Claude / Cursor / Codex kullanım panelini ve AMG65 ayarlarını aynı pencerede sunar. Grafikler, kontroller ve klavye çizimi yerel kaynaklardan üretilir; üretici uygulamasının görselleri ve fontları paketlenmez.

## Özellikler

- Yerel WebKit kullanım paneli; 127.0.0.1:47866 üzerindeki Studio köprüsünü kullanır.
- RGB efektleri, renk/parlaklık/hız, ayrı tuş renkleri.
- Tuş atamaları ve değiştirici kombinasyonları; Fn korunur.
- 240 × 135 LCD için PNG/JPEG/GIF, kırpma veya sığdırma, Mac tarih/saat eşitleme.
- 63 × 5 LED için kaydırılan metin veya görüntü/GIF, animasyon ve açılış hedefleri.
- LCD parlaklığı. Ayarların cihazdan geri okunması desteklenmez; ekran yerel tercihleri gösterir.

Mikrofon, müzik görselleştirmesi, üretici güncelleyicisi ve fabrika sıfırlama bu uygulamada yoktur. Tuş haritaları tüm tabloyu yazar. LCD/LED yükleme seçili içeriği değiştirir. Yeni donanım özelliklerinin tamamı fiziksel cihazda doğrulanmış sayılmaz; çevrimdışı testler paket doğrulamasını ve medya sınırlarını denetler.

## Derleme

macOS 14 veya daha yeni bir SDK ve Swift 5.9+ gerekir. Yerel libusb kütüphanesinin kendi minimum macOS sürümü daha yüksek olabilir; paketleme aracı bu minimumu Info.plist ve BUILD_INFO.json dosyalarına doğru biçimde yazar.

```sh
brew install libusb
python3 NativeApp/Tests/run_checks.py
python3 NativeApp/build_app.py
```

Çıktı: `NativeApp/build/AMG65 Studio.app`. ARM64 veya Intel için derleme yapılan Mac'in mimarisi kullanılır. Paket libusb'yi dinamik bağlar ve lisansını içerir. Yerel ad-hoc imza uygulanır; Apple Developer ID imzası ve notarizasyon içermez. Kök kurulum aracı arka plan köprüsünü ve uygulamayı birlikte kurar.

## USB sahipliği

Uygulama kullanım panelinde açılır ve HID aygıtını açmaz. Sürücü sayfasına geçildiğinde köprüden 45 saniyelik sahiplik alınır; köprünün bağlantıyı kapattığı görüldükten sonra per-user flock kilidi edinilir. Kira her 10 saniyede yenilenir. Pencere kapanınca veya kullanım paneline dönünce mevcut işlem tamamlanır, HID kapanır, kilit bırakılır, ardından köprüye denetim iade edilir.

Her işlem tek fiziksel aygıta sabitlenir. Yanıtın aygıtı, işlem kodu, uzunluğu ve gerektiğinde sağlama toplamı doğrulanır. USB hatası aynı bağlantıda sonraki yazmaları engeller; kullanıcı kabloyu yeniden bağlamalıdır. Hata, işlem sonucu yayımlanmadan önce iki uygulamanın ortak kullandığı `~/Library/Application Support/AMG65 Studio/state/usb-blocked.json` dosyasına atomik olarak kaydedilir. Böylece native uygulama kapansa bile köprü aynı bağlantıda tekrar yazmaz. Kayıt yalnızca yeni bir fiziksel bağlantı açıldıktan sonra kaldırılır. LCD/LED bulk arabirimi HID aygıtının USB konumuyla eşleştirilir. Birden fazla aday klavye varsa işlem başlatılmaz.

Medya 32 MB, 8192 piksel kenar ve 32 megapiksel kaynak sınırlarıyla açılır. Kare sayısı dekompresyon öncesinde LCD için 130, LED için 260 ile sınırlanır. Küçük resimler arka planda çözülür. LED açılış yüklemesi en fazla 200 kare, metin en fazla 48 karakterdir. Ağ üzerinden görsel yükleme yoktur.

## Testler

`Tests/run_checks.py`, üretim Swift kaynaklarını test giriş noktasıyla derler. HID açmadan ve mikrofon izni istemeden ACK/sağlama toplamı, RTC, tuş tablosu, LED düzeni, medya sınırları ve saklanmış parlaklık değerlerini kontrol eder. Uygulamanın gerçek UI ve USB geçiş testleri bundan ayrı yapılmalıdır.
