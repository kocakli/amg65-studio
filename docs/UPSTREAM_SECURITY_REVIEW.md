# AMG65 macOS referans sürücüsü: güvenlik ve güvenilirlik incelemesi

İnceleme tarihi: **7 Kasım 2026**. İncelenen depo: **SameedZ/aula-leobog-amg65-macos-driver**, sabit commit **`5d66a58711089abf682509dab21e2d8ed6911536`**. Bu rapordaki bulgular bu sürüme aittir; geliştirilen yeni sürücüde giderildiği ayrıca doğrulanmadıkça bir düzeltme iddiası içermez.

**Sonuç:** Kaynakta doğrulanmış bir uzaktan kod çalıştırma veya veri sızdırma yolu bulunmadı. Ancak mikrofonun kapalı modda başlayabilmesi, hatalı USB yanıtlarının başarılı sayılması ve başarısız işlemlerden sonra gönderimin sürmesi giderilmesi gereken somut sorunlar. Görsel/metin işleme sınırları ve çoklu cihaz eşleştirmesi de güçlendirilmeli. Bu sonuç uygulamanın, bağımlılıklarının veya yayımlanmış bir DMG'nin zararlı yazılımdan arınmış olduğuna dair sertifika değildir.

## Kapsam ve yöntem

- 15 Swift dosyası, SwiftPM bildirimi, libusb modül tanımı, beş Python yardımcı aracı, üç kabuk betiği ve belgeler incelendi.
- 32 yerel metin dosyası, GitHub'ın sabit commit ağacındaki Git blob kimlikleriyle karşılaştırıldı. İndirme işleminin eklediği tek son satır sonu çıkarıldığında **32/32 eşleşti**; açıklanamayan fark yok. İki GIF önizleme dosyası indirilmedi ve incelenmedi. Satır numaraları etkilenmedi.
- Python dosyaları AST ile, kabuk betikleri yalnızca `bash -n` ile kontrol edildi. Uygulama, resmi Windows sürücüsü, build/package betikleri, USB aktarımı ve mikrofon çalıştırılmadı.
- Seçili gerçek kaynak metotları geçici test dosyalarına alınarak HID, mikrofon, zamanlayıcı ve kuyruklar zararsız test nesneleriyle değiştirildi. Aşağıdaki kontrol akışı sonuçları bu çevrimdışı testlerden elde edildi. Gerçek ImageIO ayrıştırıcısına saldırı dosyası verilmedi; bellek tüketimi hesaplandı, büyük bellek ayrılmadı.
- Release ikilisi, DMG imzası/notarizasyon bileti, işletim sistemi sürücüleri, cihaz firmware'i ve kurulu üçüncü taraf kütüphaneler denetlenmedi. Kaynakta libusb/Python paketlerinin kesin sürümleri bulunmadığından CVE'siz oldukları iddia edilmez.

Tehdit modeli yerel bir masaüstü uygulamasıdır. Dosyayı seçen/sürükleyen kullanıcı, aynı kullanıcı hesabındaki süreçler ve bağlı USB cihazları başlıca giriş noktalarıdır. Ağ dinleyicisi, uygulama içi HTTP istemcisi, shell başlatma veya kimlik bilgisi toplama yolu incelenen çalışma zamanı kaynaklarında görülmedi. Bir dosyanın internetten gelmesi, dosya açılmadan uzaktan erişim sağlandığı anlamına gelmez.

## Bulgular

| Kimlik | Düzey | Tür | Durum |
|---|---|---|---|
| F1 | Orta | Mikrofon yaşam döngüsü / gizlilik | Gerçek metot + test nesnesiyle doğrulandı |
| F2 | Orta | USB ACK / veri bütünlüğü | Gerçek metot + sahte yanıtlarla doğrulandı |
| F3 | Orta | Sınırsız görsel/metin işleme | Statik akış ve bellek hesabı |
| F4 | Orta | Hata sonrası gönderim / cihaz erişilebilirliği | Python akışı doğrulandı; Swift akışı statik |
| F5 | Orta | Fiziksel cihaz eşleştirmesi ve süreçler arası sahiplik | Statik; çoklu donanım testi yapılmadı |
| F6 | Düşük | Geçersiz yerel ayar / takvim dönüşümü | Sayısal sınır testleri doğrulandı |
| F7 | Düşük | Kısa USB raporunda CLI çökmesi | Gerçek Python fonksiyonuyla doğrulandı |

### F1 — İzin yanıtı geldiğinde Music modu yeniden kontrol edilmiyor

[LiveStrip.swift:135–146](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LiveStrip.swift#L135-L146) Music seçildiğinde asenkron mikrofon izni ister. Kullanıcı cevap beklerken Off veya Clock seçerse mevcut motor durdurulur, ancak önceki izin callback'i daha sonra `granted` ile gelince motor koşulsuz başlatılır. Off sırasında yeniden durduracak bir zamanlayıcı da yoktur.

**Doğrulama:** Music → Off → bekleyen izin callback'ine `true` sırası, gerçek `modeChanged()` metodunu kullanan çevrimdışı testte `mode_off=true microphone_stub_running=true` üretti. Gerçek mikrofon açılmadı. Bu işletim sistemi iznini atlama değildir: kullanıcı önce izni vermelidir. Risk, kullanıcının seçtiği kapalı durum ile gerçek ses toplama durumunun ayrılmasıdır. İncelenen ses kodu FFT bantları hesaplıyor; kayıt dosyası veya ağ aktarımı görülmedi.

**Düzeltme:** Callback'te hem güncel modun Music olduğunu hem isteğin güncel nesle ait olduğunu doğrulayın; mod değişiminde bekleyen isteği mantıksal olarak iptal edin. Uygulama kapanışı/uyku ve gerektiğinde pencere yaşam döngüsünde motoru durdurun. Ses motorunun başlatılamaması ayrıca görünür hata olmalı.

### F2 — Yanlış opcode ve eksik checksum kabul edilebiliyor

[KeyboardHID.swift:253–267](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/KeyboardHID.swift#L253-L267) başarıyı esas olarak yanıtın dördüncü baytına bağlıyor. Beklenen komut kimliği doğrulanmıyor. Veri içeren bir işlemin END yanıtı altı bayttan kısaysa checksum kontrolü başarısız olmak yerine **atlanıyor**. Bulk ACK kontrolü de yalnızca aynı durum baytını kullanıyor: [satır 175–184](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/KeyboardHID.swift#L175-L184), [211–215](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/KeyboardHID.swift#L211-L215).

**Doğrulama:** Gerçek Swift `send()` metodu, BEGIN için `99 99 00 01` yanıtını başarılı saydı. Veri + END işleminde END'e verilen `04 02 00 01` yanıtı checksum taşımamasına rağmen sonuç `ok=true` oldu. Bu sahte periferik, yanlış kuyruktaki veya gecikmiş yanıtın yanlış başarı bildirimine neden olabileceğini gösterir; checksum kriptografik doğrulama değildir.

**Düzeltme:** İşlem ve paket başına beklenen yanıt türü/uzunluğu/opcode/durum şeması kullanın. Checksum bekleniyorsa uzunluğunu zorunlu tutun. İstisnaları yalnızca donanımda doğrulanmış paket türüne sınırlandırın; örneğin zaman ayarı checksum taşımayabilir. Gelen yanıtı kaynak cihaz ve mevcut işlemle ilişkilendirin. ACK alındığını, kalıcı ayarın cihazdan geri okunup doğrulandığı anlamında sunmayın.

### F3 — Upload sınırları yükleme sırasında kaynak tüketimini sınırlamıyor

[LCD.swift:57–68](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LCD.swift#L57-L68) ve [LEDStrip.swift:47–53](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LEDStrip.swift#L47-L53) tüm görsel karelerini çözüp bellekte tutuyor. 130/260 kare sınırları ancak upload tamponu oluşturulurken uygulanıyor. Kaynak dosya boyutu, piksel boyutu ve toplam çözülmüş bellek bütçesi kontrolü yok; çağrılar UI olaylarından eşzamanlı geliyor.

Metin de [LEDStrip.swift:67–79](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LEDStrip.swift#L67-L79) içinde her kaydırma adımı için yeni bir 315 piksellik kareye genişletiliyor; [136 ve 152–153](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LEDStrip.swift#L135-L153) her değişimde bunu tekrarlıyor. Örneğin 100.000 ASCII karakter, 400.063 kare ve yalnız ham RGB için **378.059.535 bayt** gerektirir; dizi/nesne ek yükü buna dahil değildir. Bu hesap yapıldı, büyük tahsis denenmedi.

**Etki:** Kullanıcının açtığı büyük/kötü niyetli bir dosya veya yapıştırdığı uzun metin uygulamayı dondurabilir veya bellek baskısıyla kapatabilir. ImageIO'da kod yürütme açığı bulunduğu iddia edilmez.

**Düzeltme:** Kare, dosya boyutu, kaynak piksel boyutu ve toplam bellek bütçelerini **decode öncesinde** uygulayın; thumbnail decode kullanın. UI dışında, iptal edilebilir iş yürütün. Metin uzunluğunu sınırlandırın/debounce edin veya kareleri akış halinde üretin. Python yardımcılarında da tüm GIF'i listeye almadan önce sınır uygulayın: [amg65_lcd.py:71–77](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/tools/amg65_lcd.py#L71-L77), [amg65_strip.py:79–80](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/tools/amg65_strip.py#L79-L80).

### F4 — İşlem başarısızlığından sonra cihaz durumu belirsizken yazım sürebiliyor

Swift paket dizisi ilk hatada duruyor; bu olumlu. Ancak [LiveStrip.swift:149–158](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LiveStrip.swift#L149-L158) tamamlanma callback'inde hatadan bağımsız olarak `inFlight` bayrağını temizliyor. Sonraki 100 ms tikinde yeni kare başlatılabiliyor; kopuk işlem için kilitleme/backoff veya yeniden bağlantı şartı yok. Off seçimi de cihazda stream sonlandırma işlemi yapmıyor: [135–138](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LiveStrip.swift#L135-L138).

Python [amg65.py:287–295](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/tools/amg65.py#L287-L295) daha doğrudan: list comprehension bütün paketleri gönderiyor, sonucu sonunda topluyor. Çevrimdışı gerçek `run()` testinde hiçbir ACK yokken **3/3 yazım** yapıldı; ilk başarısızlıktan sonra durmadı.

**Etki:** Kopma/yoğunluk sırasında protokol sırası bozulabilir, kısmi ayar/animasyon kalabilir veya USB kontrol kanalı yanıt vermez hale gelebilir. Kalıcı firmware hasarı gösterilmedi. Bulk işlemi de başarısız ACK için 100 × 600 ms bekleyebilir; iptal ve kapanış koordinasyonu görünmüyor.

**Düzeltme:** İlk belirsiz yazım/ACK hatasında kuyruğu durdurun; aynı fiziksel bağlantıya kör tekrar yapmayın. Hata durumunu UI'ye bildirin. Güvenli durumda stream'i açıkça kapatın; yeni bağlantı kimliğiyle oturumu yeniden kurun. Python akışını erken dönen döngüye çevirin. Bulk upload için iptal, son tarih ve kontrollü kapanış ekleyin.

### F5 — İki USB kanalı aynı fiziksel cihazla eşleştirilmiyor

[KeyboardHID.swift:72–87](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/KeyboardHID.swift#L72-L87) son eklenen uygun cihazı tek alana yazar; [118–132](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/KeyboardHID.swift#L118-L132) her paket için bu alanı tekrar seçer. Bulk kanal ise [LCD.swift:94–99](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/LCD.swift#L94-L99) içinde ilk VID/PID eşleşmesini bağımsız açar. İki AMG65 bağlıysa header birine, görüntü bloğu diğerine gidebilir. İşlem ortasında takılan yeni cihaz sonraki paketlerin hedefini de değiştirebilir.

Wired ve dongle callback'leri tek, kaynak etiketsiz ve boyutu sınırsız ACK kuyruğuna yazar: [78–106](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/KeyboardHID.swift#L78-L106). Seri `ioQueue` bir uygulama içindeki işleri sıralıyor; ayrı uygulama/CLI süreçleri arasında özel sahiplik kilidi bulunmuyor.

**Etki ve sınır:** Bu esas olarak yanlış cihaza yazma/erişilebilirlik riskidir; iki cihaz, hotplug veya rakip yerel süreç gerekir. VID/PID taklit eden kötü amaçlı USB zaten güçlü fiziksel erişime sahiptir; bu bulgudan uzaktan saldırı sonucu çıkarılmaz. Çoklu donanımla denenmedi.

**Düzeltme:** Kontrol ve bulk arabirimlerini aynı USB location/registry kimliğine bağlayın; işlem boyunca cihazı sabitleyin. Birden fazla eşleşmede seçim isteyin veya aktarımı reddedin. Yanıtları cihaz bazında ayırın/boyut sınırı koyun, kaldırma olayında bekleyen işlemi iptal edin. GUI ve CLI arasında aynı kullanıcıya ait sabit bir donanım yazıcı kilidi kullanın.

### F6 — Yerel ayar ve takvim değerleri dar sayısal tipe denetlenmeden çevriliyor

[CustomLight.swift:25](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/CustomLight.swift#L25) `UserDefaults` içindeki tamsayıyı doğrudan `UInt8` yapıyor. Negatif veya 255 üzeri değer uygulama başlatılırken dönüşüm hatasına neden olabilir. Bu tercihi yazabilen aynı kullanıcı hesabı veya bozulmuş tercih dosyası gerekir; ayrıcalık yükseltme değildir.

[Protocol.swift:63–68](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Sources/AMG65/Protocol.swift#L63-L68) `Calendar.current` yılına `% 2000` uygulayıp `UInt8` yapıyor. Çevrimdışı Foundation testi, 2026-11-07 için Budist takvim yılının 2569, dönüştürülecek değerin 569 olduğunu ve `UInt8(exactly:)` tarafından temsil edilemediğini doğruladı. Bu kullanıcı takvimiyle saat eşitlemenin çökme ihtimalidir; uygulamayı kasten çökertmedik veya Mac takvimini değiştirmedik.

**Düzeltme:** Parlaklık gibi tercihlerde geçerli iş alanını (örneğin 1…5) doğrulayıp varsayılana dönün. Cihaz takvimini açıkça Gregorian olarak kodlayın; iki haneli yıl için `% 100` ve desteklenen tarih aralığı kontrolü kullanın. Hafta günü eşleştirmesini cihaz protokolüne göre ayrıca test edin.

### F7 — Python CLI kısa giriş raporunu kontrol etmeden indeksliyor

[amg65.py:114–124](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/tools/amg65.py#L114-L124) yalnız boş yanıtı ayıklıyor; sonra `[3]`, gerektiğinde `[4]` ve `[5]` indekslerine doğrudan erişiyor. Tek baytlık sahte ACK ile gerçek `send()` fonksiyonu **IndexError** üretti. Yerel hatalı/kötü niyetli periferik gerekir; Python bellek güvenliği açığı veya kod çalıştırma gösterilmedi.

**Düzeltme:** Rapor türüne göre asgari uzunluk, opcode ve durum doğrulaması yapın; bozuk yanıtı kontrollü hata olarak dönün ve işlemi durdurun. `drain()` döngülerine de rapor sayısı/zaman bütçesi koyun; sürekli rapor gönderen periferik drain'i sınırsız tutmamalı.

## Dağıtım, bağımlılıklar ve izinler

**İmza/notarizasyon:** [build_app.sh:57](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/build_app.sh#L57) varsayılan olarak ad-hoc imza oluşturuyor. [package_dmg.sh:33–39](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/package_dmg.sh#L33-L39) Developer ID'yi, [54–58](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/package_dmg.sh#L54-L58) notarizasyonu isteğe bağlı yapıyor. Betik bunların eksikliğini dürüstçe bildiriyor; bu tek başına istismar değildir. Genel dağıtımda sürümün imza/notarizasyon durumunu açıkça belirtin, sertifika kimliğini ve paketi doğrulayın. Aynı release yanında yayımlanan SHA-256 dosyası bütünlük kontrolüne yarar; bağımsız yayıncı doğrulaması yerine geçmez. Bu inceleme gerçek bir release paketinin imzalı olup olmadığını belirlemedi.

**Hardened Runtime + mikrofon:** Paketleme yolu `--options runtime` kullanıyor fakat `--entitlements` vermiyor; kaynak ağacında entitlement dosyası yok. `NSMicrophoneUsageDescription` mevcut olması tek başına Hardened Runtime ses girişini açmaz. Music korunacaksa yalnız gereken `com.apple.security.device.audio-input` iznini ekleyin ve imzalı build'i test edin; korumaları topluca devre dışı bırakmayın. [Apple Audio Input Entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.audio-input).

**Bağımlılık kökeni:** [Package.swift:8–16](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/Package.swift#L8-L16) uzaktan Swift paketleri çekmiyor; yerel Homebrew libusb'ye bağlanıyor. [build_app.sh:24–29](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/build_app.sh#L24-L29) derleme makinesindeki dylib'i sürüm/hash kaydı olmadan kopyalıyor. Python araçları hidapi/PyUSB/Pillow import ediyor; incelenen ağaçta kilitlenmiş sürüm bildirimi yok. Tekrarlanabilir release için kesin sürümler, hash'ler, SBOM/üçüncü taraf bildirimleri ve bağımlılık taraması eklenmeli. `/opt/homebrew` yolları ayrıca Apple Silicon yerleşimini varsayıyor. Bir CVE eşleşmesi bu raporda doğrulanmadı.

**Kaynaklar ve varlıklar:** İncelenen [README:112](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/README.md#L112) o commit'te açık kaynak lisansı olmadığını belirtiyor. Kullanıcı bu çalışma için kaynak kodunun kendisine ait olduğunu ve kullanım/geliştirme yetkisini açıkça bildirmiştir; rapor bunu bir engel olarak değerlendirmiyor. Buna karşılık build betiğinin kopyaladığı resmi üretici skin/font/icon/örnek GIF kaynakları ayrı girdilerdir: [build_app.sh:18–22](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/build_app.sh#L18-L22), [31–33](https://github.com/SameedZ/aula-leobog-amg65-macos-driver/blob/5d66a58711089abf682509dab21e2d8ed6911536/MacApp/build_app.sh#L31-L33). Yeni ürünün dağıtımından üretici varlıkları çıkarılmalıdır; kullanıcıya ait kod beyanı bu ayrı varlıkları inceleme kapsamına sokmaz.

## Olumlu kontroller ve sınırlar

- Kod kernel extension kurmuyor; kullanıcı alanında IOKit/libusb kullanıyor. Kaynakta yönetici yetkisi talebi veya `sudo` akışı yok.
- Kontrol kanalları VID/PID ve vendor usage page ile filtreleniyor; genel klavye tuş akışı kaydedilmiyor. Bu filtre cihaz kimliğinin kriptografik kanıtı değildir.
- GUI içindeki yazımlar seri kuyrukta; live mod `inFlight` ile sınırsız kare birikmesini önlüyor. Bulk yazımı hem libusb dönüş kodunu hem gönderilen bayt sayısını denetliyor.
- Birçok protokol tablosunda slot/payload sınırları var; LCD/strip upload tamponları kare sayısını sınırlandırıyor. F3'teki eksik, bu sınırların decode'dan **sonra** uygulanmasıdır.
- UI/belgeler okunamayan cihaz ayarlarının son uygulanan yerel kopyasını kullandığını ve bazı modların denenmediğini açıklıyor. ACK/checksum, gerçek görsel sonuç veya kalıcı readback ile aynı şey değildir.
- Build betikleri değişkenleri tırnaklıyor, `set -euo pipefail` kullanıyor ve DMG hazırlığı için `mktemp` kullanıyor. Statik taramada build sırasında uzaktan indirip çalıştırma görülmedi.

## Tekrarlanabilir doğrulama özeti

Yerel çalışma ağacında `python3 work/security-repro/run_offline.py` yalnız seçilmiş metotları test nesneleriyle çalıştırır. Donanım ve mikrofon modülleri testlere dahil edilmez; kaynak uygulama/build betikleri çalıştırılmaz. Kanıt çıktıları `work/security-repro/results.json` ve `static-results.json` içinde tutuldu; bunlar ürünün çalışma zamanı bileşeni değildir.

```text
mode_off=true microphone_stub_running=true
wrong_opcode_accepted=true
missing_checksum_accepted=true
buddhist_year=2569 encoded_year=569 fits_UInt8=false
negative_preference_fits_UInt8=false
writes_after_first_missing_ack=3
one_byte_reply=IndexError
source_files_verified=32 (tek ek son satır sonu normalize edildi)
python_AST_parses=5; shell_syntax_passes=3
```

Yayımlanacak yeni build için ayrı kabul ölçütleri: eski izin callback'inin Off durumunu değiştirmemesi; yanlış/eksik ACK'nin reddedilmesi; ilk belirsiz USB hatasından sonra yeni yazım yapılmaması; iki cihazın karıştırılmaması; sınırlı ve iptal edilebilir görsel decode; takvim/tercih sınır testleri; imza ve gerekli izinlerin paketten doğrulanması. Gerçek cihazda tarih/ekran okuması ve kontrollü uzun süreli bağlantı testi bu kaynak incelemesinin yerine geçmediği ek doğrulamalardır.
