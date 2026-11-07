# AMG65 Studio for macOS

**0.3.0** SwiftUI uygulaması, Claude / Cursor / Codex kullanımını, gerçek iş durumu sinyallerini ve AMG65 ayarlarını aynı pencerede sunar. Studio’nun kendi UsageEngine yardımcısı sağlayıcılardan veri alır; CodexBar uygulaması, CLI’ı, ayarları veya cache’i gerekli değildir. Grafikler, kontroller ve klavye çizimi yerel kaynaklardan üretilir; üretici uygulamasının görselleri ve fontları paketlenmez.

## Özellikler

- Yerel WebKit kullanım paneli; 127.0.0.1:47866 üzerindeki Studio köprüsünü kullanır.
- Üç sağlayıcının ayrı kota pencereleri, kalan yüzdeleri, sıfırlanma ve ölçüm zamanları; bilinmeyen ve eski veri açıkça ayrılır.
- Gerçek hook/Codex metadata sinyallerinden çalışan, onay/bilgi bekleyen, tamamlanan veya hata veren işler; üç sağlayıcı menüde birlikte görünür, LED dikkat gerektiren sinyale öncelik verir.
- RGB efektleri, renk/parlaklık/hız, ayrı tuş renkleri.
- Tuş atamaları ve değiştirici kombinasyonları; Fn korunur.
- 240 × 135 LCD için PNG/JPEG/GIF, kırpma veya sığdırma, Mac tarih/saat eşitleme.
- 63 × 5 LED için kaydırılan metin veya görüntü/GIF, animasyon ve açılış hedefleri.
- LCD parlaklığı. Ayarların cihazdan geri okunması desteklenmez; ekran yerel tercihleri gösterir.

Mikrofon, müzik görselleştirmesi, üretici güncelleyicisi ve fabrika sıfırlama bu uygulamada yoktur. Tuş haritaları tüm tabloyu yazar. LCD/LED yükleme seçili içeriği değiştirir. Yeni donanım özelliklerinin tamamı fiziksel cihazda doğrulanmış sayılmaz; çevrimdışı testler paket doğrulamasını ve medya sınırlarını denetler.

## Derleme

macOS 14 veya daha yeni hedef ve modern ikon derlemesi için tam Xcode 26+ gerekir. Native paket Swift 5.9 araç biçimini, bağımsız UsageEngine derlemesi Swift 6 modunu kullanır. Yerel libusb kütüphanesinin kendi minimum macOS sürümü daha yüksek olabilir; paketleme aracı bu minimumu Info.plist ve BUILD_INFO.json dosyalarına doğru biçimde yazar.

```sh
brew install libusb
python3 tools/prepare_claude_auth.py
python3 UsageEngine/build.py --test
python3 UsageEngine/build.py
python3 NativeApp/Tests/run_checks.py
python3 NativeApp/build_app.py
```

Çıktılar: `NativeApp/build/AMG65 Studio.app`, `bin/amg65-usage` ve `bin/claude-auth`. ARM64 veya Intel için derleme yapılan Mac'in mimarisi kullanılır. Native paket libusb'yi dinamik bağlar ve lisansını içerir; UsageEngine yalnızca macOS SDK kütüphanelerini kullanır. Studio uygulamasına yerel ad-hoc imza uygulanır; Apple Developer ID imzası ve notarizasyon içermez. İndirilen Claude yardımcısının üretici imzası ayrıca doğrulanır. Kök `./build.sh`, HID dahil tam derlemeyi yapar; kurulum aracı arka plan köprüsünü, yardımcıları ve uygulamayı birlikte kurar. Yalnızca `.app` derlemek arka plan köprüsünü kurmaz. Tam derleme, sabit resmi Claude yardımcısını ilk kez hazırlarken yaklaşık 280 MB ağ indirmesi gerektirebilir.

## Kullanım motoru ve oturumlar

Native menü ve WebKit paneli kota için yalnızca yerel HTTP durumunu okur. Python köprüsü kendi Swift yardımcısını ayrı süreçte çalıştırır; sağlayıcı HTTPS beklemesi USB yazıcısını durdurmaz. Otomatik yenileme beş dakikada birdir; Yenile düğmesi aynı sınırlı işi ister. Ölçüm 15 dakikayı veya pencerenin sıfırlanma zamanını geçtiğinde eski işaretlenir. Eksik değer `--` kalır; kotalar toplanmaz veya farklı pencereler ortalanmaz.

- **Codex:** `CODEX_HOME/auth.json`; varsayılan `~/.codex/auth.json` abonelik oturumu.
- **Claude:** `CLAUDE_CONFIG_DIR` / `CLAUDE_SECURESTORAGE_CONFIG_DIR` içindeki `.credentials.json`. Varsayılan profilde geçerli Claude Code Keychain kaydı etkileşimsiz fallback olabilir; özel profil varsayılan hesaba düşmez.
- **Cursor:** uygulamanın `state.vscdb` erişim token’ı; etkin WAL salt okunur takip edilir. Gerekirse `Cursor Safe Storage` anahtarı etkileşimsiz çözümleme için kullanılır. Tarayıcı cookie’leri taranmaz.

Profil değişkenleri köprü/yardımcı sürecin ortamında bulunmalıdır; LaunchAgent shell profilini kendiliğinden yüklemez. Açıkça verilen profil yolları mutlak olmalıdır. Otomatik kullanım motoru yeni giriş ekranı açmaz, sağlayıcının refresh token’ını yenilemez ve kimlik bilgisi depolarına yazmaz. Süresi dolan oturumu ilgili sağlayıcı uygulaması/CLI’ında veya aşağıdaki açık **Hesaplar** işlemiyle yenileyin. Keychain erişim gerektiriyorsa arka plan işi `keychain_locked` gösterir; izin penceresi çıkarmaz.

İstekler üç tam HTTPS sağlayıcı host’uyla sınırlıdır; yönlendirme ve kalıcı cookie deposu yoktur. Kimlik bilgileri Swift süreç belleğinde kalır. Özel kota cache’inde yalnızca normalize edilmiş ölçüm ve opak hesap ayırıcısı tutulur; hesap parmak izi HTTP/UI/LED yanıtından çıkarılır. Geçici ağ hatasında önceki ölçüm ancak aynı hesap doğrulanabiliyorsa eski olarak korunur; hesap değişimi veya kimlik doğrulama hatası önceki kotayı temizler. Kaynak uyarlamaları ve lisans için [`UsageEngine/NOTICE.md`](../UsageEngine/NOTICE.md), ayrıntılı sınırlar için [güvenlik değerlendirmesi](../docs/STUDIO_SECURITY.md) bulunur.

## Menüden hesap bağlama

Doğrulanmış kullanım verisi bulunan hesaplarda yeşil **Bağlı** etiketi ve ikincil **Hesap değiştir** düğmesi görünür. Uygulama yeniden açıldığında da kullanım verisi bağlantı durumunu belirler. Giriş tamamlanınca kullanım doğrulanır; geçici ağ hatası yeniden giriş istemez, süresi dolan veya reddedilen oturum ise yeniden giriş gerektirir.

**Hesaplar → Giriş yap** resmi sağlayıcı akışını başlatır. Codex cihaz kodu ve sağlayıcı web sayfasını kullanır. Claude için Studio’ya özel, doğrulanmış güncel resmi yardımcıda `auth login --claudeai` çalıştırılır; eski global CLI’ın `/login` ajan oturumu başlatılmaz. Doğrulanmış sağlayıcı bağlantısı giriş tıklamasından sonra tarayıcıda açılır; yeniden açma düğmesi de bulunur. Cihaz kodu gösterilir ve kullanıcı isterse kopyalanır. Claude kod isterse yalnızca tek kullanımlık yetkilendirme kodu güvenli alana yapıştırılır; Studio parola veya API anahtarı istemez. Girilen kod ve ham CLI çıktısı kaydedilmez veya durum API’sine konulmaz.

Cursor düğmesi Cursor uygulamasını açar; orada giriş yaptıktan sonra kullanımı yenileyin. Claude giriş yardımcısı ajan, proje güveni veya MCP onayı başlatmadan doğrudan kimlik doğrulama komutunu çalıştırır. Eski `/login` yoluna geri dönüş yapılmaz; yardımcı yoksa veya doğrulanamazsa giriş kullanılamaz olarak gösterilir. Giriş en fazla beş dakika açık kalır. **İptal** yalnızca Studio’nun başlattığı giriş sürecini durdurur. Tarayıcıya geçerken menünün kapanması girişi iptal etmez; menü yeniden açıldığında durum izlenebilir. Kimlik bilgilerini oluşturan/yazan resmi CLI veya sağlayıcı uygulamasıdır; otomatik quota motorundan ayrı bir kullanıcı eylemidir.

Resmi Claude yardımcısı tam derleme sırasında [`tools/prepare_claude_auth.py`](../tools/prepare_claude_auth.py) ile sabit sürüm/kaynak/checksum üzerinden hazırlanır; ayrıca çalıştırılabilir. İndirme ve imza doğrulamasından sonra `bin/claude-auth` konumuna yerleştirilir ve Studio’nun özel kurulumuna kopyalanır. Global `claude` komutu, PATH, mevcut CLI kurulumu ve proje yapılandırmaları değiştirilmez. Mevcut Claude Code 2.0.35 etkinlik hook desteği ayrı kalır; kimlik doğrulama yardımcısının sürümüyle karıştırılmamalıdır.

## Tuşların aydınlatma rengini seçme

**Aydınlatma → Tek renk** bölümündeki paletten bir renk seçin veya HEX kodunu girip Enter ile seçimi onaylayın. RGB kaydırıcıları özel tonları ayarlar; ayrı macOS renk paneline gerek yoktur. Bir renk seçmek çok renkli tercihini kapatır. Düz arka plan için **Sabit renge geç**, ardından **Klavyeye uygula** seçilir. Animasyonlarda seçilen rengin kullanımı efektin firmware davranışına bağlıdır.

Tuş renkleri bölümünde aynı kontroller fırçayı seçer; renk seçimi silgiyi kapatır. Tuşa tıklamak veya tüm tuşları doldurmak taslağı düzenler; **Renkleri uygula** ayarları cihaza gönderir. Renk seçmek tek başına USB yazımı başlatmaz.

## Gerçek iş durumları

İş durumu kotadan veya işlemci kullanımından tahmin edilmez. Pasif host hook’ları ve Codex’in sınırlı son oturum metadata’sı kullanılır. Prompt, cevap, komut, dosya yolu veya araç çıktısı menüye/LED’e taşınmaz; yalnızca sabit durum/özet, zaman ve opak oturum kimliği tutulur. Kayıt hatası agent işine izin vermez, onu reddetmez veya değiştirmez. Etkinlik göstergesini kapatmak için paneldeki **İş durumlarını LED’de göster** seçeneğini kullanın.

Doğrulanan host kapsamı Codex **0.166** kararlı hook’ları ve Claude Code **2.0.35** güvenli olay alt kümesidir. Claude 2.0.35’e açık `PermissionRequest` hook’u eklenmez; typed `notification_type` de bulunmadığı için bu sürümde onay bekleme gözlemi kullanılamaz. Cursor entegrasyonu yalnızca pasif olayları kullanır ve güvenilir bir onay bekleme olayı sağlamaz. Desteklenmeyen olaylar veya sinyal yokluğu **bilinmeyen** kalır; bunlar “iş tamamlandı” sayılmaz. Hook yapılandırması kurulu sürümün doğrulanmış olay kümesini gerektirir; decoder’da bulunan her olayın bütün host sürümlerinde kurulabileceği varsayılmaz.

Yeni sinyal gelmezse sırada 30 sn, çalışıyor 120 sn, onay/bilgi bekleme 300 sn, tamamlandı 45 sn ve hata 90 sn sonra durum bilinmeyene döner. LED’in sabit ASCII kodları `QUEUE`, `RUN`, `ASK`, `INPUT`, `DONE`, `ERROR`’dur. Çalışan/sıradaki işler kota görünümüyle dönüşür; eşit önemdeki sağlayıcılar sırayla görünür. Uzun süre sinyal üretmeyen gerçek bir iş de bu nedenle bilinmeyen olabilir.

## USB sahipliği

Uygulama kullanım panelinde açılır ve HID aygıtını açmaz. Sürücü sayfasına geçildiğinde köprüden 45 saniyelik sahiplik alınır; köprünün bağlantıyı kapattığı görüldükten sonra per-user flock kilidi edinilir. Kira her 10 saniyede yenilenir. Pencere kapanınca veya kullanım paneline dönünce mevcut işlem tamamlanır, HID kapanır, kilit bırakılır, ardından köprüye denetim iade edilir. Pencereyi kapatmak uygulamayı sonlandırmaz; menü çubuğunda çalışmayı sürdürür.

Her işlem tek fiziksel aygıta sabitlenir. Yanıtın aygıtı, işlem kodu, uzunluğu ve gerektiğinde sağlama toplamı doğrulanır. USB hatası aynı bağlantıda sonraki yazmaları engeller; kullanıcı kabloyu yeniden bağlamalıdır. Hata, işlem sonucu yayımlanmadan önce iki uygulamanın ortak kullandığı `~/Library/Application Support/AMG65 Studio/state/usb-blocked.json` dosyasına atomik olarak kaydedilir. Böylece native uygulama kapansa bile köprü aynı bağlantıda tekrar yazmaz. Kayıt yalnızca yeni bir fiziksel bağlantı açıldıktan sonra kaldırılır. LCD/LED bulk arabirimi HID aygıtının USB konumuyla eşleştirilir. Birden fazla aday klavye varsa işlem başlatılmaz.

Medya 32 MB, 8192 piksel kenar ve 32 megapiksel kaynak sınırlarıyla açılır. Kare sayısı dekompresyon öncesinde LCD için 130, LED için 260 ile sınırlanır. Küçük resimler arka planda çözülür. LED açılış yüklemesi en fazla 200 kare, metin en fazla 48 karakterdir. Ağ üzerinden görsel yükleme yoktur.

## Testler

`Tests/run_checks.py`, üretim Swift kaynaklarını test giriş noktasıyla derler. HID açmadan ve mikrofon izni istemeden ACK/sağlama toplamı, RTC, tuş tablosu, LED düzeni, medya sınırları, saklanmış parlaklık, kota ve etkinlik sunumunu kontrol eder. 7 Kasım 2026 geliştirme oturumunda **78 native**, **122 UsageEngine** ve **105 Python** kontrol/testinin geçtiği gözlendi; bunlar ara sayılardır, sonraki değişiklikleri otomatik olarak kapsamaz. Son kaynak için üç komut yeniden çalıştırılmalıdır:

```sh
python3 -B -m unittest discover -s tests -v
python3 NativeApp/Tests/run_checks.py
python3 UsageEngine/build.py --test
```

UsageEngine kontrolleri sentetik kimlik bilgileri ve sahte HTTP kullanır; gerçek provider hesabı, Keychain sırrı veya USB açılmaz. macOS `LAContext` doğrulaması bazı sandbox ortamlarının dışına erişim gerektirebilir. Uygulamanın gerçek UI, sağlayıcı bağlantısı ve USB geçiş testleri bunlardan ayrıdır.

## Dil ve uygulama ikonu

Yan çubuktaki dil menüsü Türkçe, English, Español, 简体中文 ve 日本語 sunar. Önceki Türkçe varsayılanı korunur; **Sistem dili** ayrıca seçilebilir. Desteklenmeyen sistem dilleri İngilizceye döner. Seçim `studioLanguage` kullanıcı tercihiyle saklanır. Değişiklik uygulamayı veya USB oturumunu yeniden başlatmaz; hazırlanan ayarlar ve metin korunur. Kullanım paneline dil `#native&lang=<kod>` üzerinden iletilir; açık WebKit sayfasında yalnızca fragment değiştirilir.

Uygulamanın kontrolleri, menüleri, efekt adları ve durum/hata açıklamaları yerel JSON kataloglarından görüntülenirken çevrilir. Eski işlem sonuçları da yeni dile geçer. Klavyenin fiziksel tuş yazıları, dosya adları ve kullanıcının LED metni değiştirilmez. macOS'un kendi dosya seçicisi, servisleri ve işletim sistemi hata açıklamaları sistem dilini kullanabilir. LED'in 3 × 5 yazı tipi A–Z, rakamlar ve temel noktalama ile sınırlıdır; arayüzün Çince/Japonca desteği bu donanım fontuna yeni glif eklemez.

Çevirilerin düzenlenebilir kaynakları `Resources/localization_source.tsv` ve `Resources/localization_technical.tsv` içindedir. Çalışma zamanı kataloglarını üretmek için:

```sh
python3 NativeApp/Tools/build_localizations.py
python3 NativeApp/Tests/run_checks.py
```

Paketleme, Icon Composer ile hazırlanmış `Resources/AppIcon.icon` kaynağını Apple `actool` ile derler; modern `Assets.car` ikon katmanı ve uyumlu ICNS birlikte üretilir. Tam Xcode 26+ gerekir. Orijinal `Resources/AppIcon.png` yan çubukta kullanılır. Menü çubuğu için ayrı, tek renkli bir şablon simgesi kullanılır. Paket yerel çevirileri içerir; dil desteği için ağa bağlanmaz.


## Menü çubuğunda çalışma

AMG65 Studio menü çubuğunda tek renkli bir klavye simgesiyle kalır. **Kullanım hakları, Gösterim, Aydınlatma, Tuş atamaları, LCD ekran, LED animasyonu, Cihaz ayarları ve Hesaplar** aynı paneldedir. Kullanım bölümü dört sağlayıcı sekmesinde de sabit 460 × 410 pt boyutundadır; diğer bölümler 460 × 600 pt kullanır. Tuş eşleme ve tuş başına renk çizimi 760 × 600 pt genişliğe açılır. Donanım bölümleri ortak USB sahipliğini alır; Hesaplar ve Gösterim bölümü USB oturumu açmaz. Ana pencere isteğe bağlıdır.

Kullanım bölümünde Genel bakış, Codex, Claude ve Cursor sekmeleri bulunur. Genel bakış üç sağlayıcıyı sade satırlarda gösterir; sağlayıcı sekmeleri birbirinden bağımsız kota pencerelerini ve yenilenme zamanlarını açar. Sekmelerin altındaki küçük göstergeler ilgili sağlayıcının seçili penceresini yansıtır, farklı kotalar toplanmaz. Bilinmeyen değerler sıfır sayılmaz; eski veya erişilemeyen ölçümler açıkça işaretlenir. Sayılar yalnızca yerel `GET /api/status` yanıtından okunur; native menü sağlayıcılara doğrudan bağlanmaz.

Panel açıkken yerel kota/durum 15 saniyede bir, yalnızca Hesaplar bölümündeyken giriş durumu iki saniyede bir okunur. İstekler 5 saniyelik istek / 8 saniyelik kaynak zaman aşımı ve 256 KiB yanıt sınırı kullanır; yönlendirmeler takip edilmez. Dişli menüsündeki dil seçimi iki arayüzde ortaktır; çıkış da bu menüdedir. **Studio’yu aç** ana pencereyi getirir. Yenileme düğmesi kullanıcının isteğiyle yerel `/api/refresh` yoluna başvurur ve Studio UsageEngine’den yeni ölçüm ister; otomatik yerel okumalar sağlayıcılara ayrı istek göndermez. Saat düğmesi mevcut köprüye eşitleme isteği gönderir; native sürücü USB denetimini elinde tutuyorsa bu düğme kullanılamaz. Gösterim taslakları poll veya dil değişiminde silinmez; yalnızca eşleşen uygulama onayı alındığında ve kullanıcı yeniden düzenlememişse normalize edilir.

`--menu-bar` başlangıç parametresi ana pencereyi göstermeden menü çubuğu modunu açar. Kök kurulum aracı oturum açılışındaki başlangıcı ayarlar. Pencere kapatıldığında USB köprüye iade edilir, uygulama çalışmayı sürdürür. Menüdeki çıkış düğmesi uygulamayı kapatır; SIGTERM de aynı güvenli kapanış yolunu izler. Devam eden bir cihaz aktarımının tamamlanması beklenebilir.


Popup tasarımını gerçek SwiftUI bileşenlerinden, kullanıcı kotaları yerine açıkça test verileriyle çevrimdışı görüntülemek için `python3 NativeApp/Tests/render_menu.py /tmp/amg65-menu-preview` kullanılabilir. Bu derleme `STUDIO_UI_PREVIEW` koşulunu kullanır; ağ döngüsü devre dışıdır ve hiçbir pencere açılmaz. Test görselleri gerçek kullanım değerleri olarak paylaşılmamalıdır.

## LED yazı efektleri

**Gösterim → Yazı efekti** bölümünde Sade, Tarama, Nefes, Matrix ve Kayan yazı seçenekleri bulunur. Tarama aydınlık bir sütun geçişi; Nefes hafif parlaklık değişimi oluşturur. Matrix harf gruplarını yukarıdan aşağı akıtır ve aralarda metnin okunması için duraklar. Kayan yazı, kısa metinler dahil yazıyı sürekli yatay kaydırır. Kota görünümü, sağlayıcı ayrıntısı ve kişisel metinde seçilen efekt uygulanır. `RUN`, `QUEUE` ve `DONE` durumlarının yazıları da efekti kullanır; soldaki durum ikonu sabit kalır. Onay (`ASK`), bilgi (`INPUT`) ve hata (`ERROR`) uyarıları bütünüyle sabit kalır. Efekt seçimi taslaktır; **Uygula** ile kaydedilir. Varsayılan Sade’dir.

**Gösterim → Araç maskotları** varsayılan olarak kapalıdır. Açıp **Uygula** ile kaydettiğinizde desteklenen gerçek etkinlik sinyallerinde özgün piksel maskotlar kullanılır: Claude yengeci, Codex robotu ve Cursor imleci. Seçilen araç veya Otomatik görünümde gözlenen duruma göre hareket eder; onay veya bilgi beklerken dururlar. Etkinlik sinyali olmadan çalışma durumu üretilmez. Maskot sahnelerine ayrıca Matrix, Kayan yazı veya diğer dekoratif yazı efektleri uygulanmaz; maskotun hareketi ve durum işaretleri korunur. Eski `claude_mascot` tercihi genel `mascot_enabled` ayarına taşınır; yeni alan varsa önceliklidir. Native uygulama yalnız yeni alanı gönderir.

**Gösterim → Gösterilecek araç** seçeneğinde Otomatik, Claude, Codex veya Cursor seçilir. Belirli bir araç seçildiğinde desteklenen gerçek durumları ve çalışma adımları gösterilir; çalışan iş kota sayfasıyla dönüşmez. Etkinlik olmadığında seçilen aracın kotası görünür. Otomatik, önceki görünüm ve dönüş davranışını korur. Genel görünüm ve özel metin kontrolleri yalnız Otomatik seçiliyken görünür; saklanan metin ve görünüm taslağı araç değiştirirken silinmez. Seçim **Uygula** ile kaydedilir.

Köprü `fault_reconnect` bildirdiğinde menü başlığı **LED aktarımı durdu** ve **USB kablosunu çıkarıp yeniden takın.** uyarılarını gösterir. Kullanım kotaları ve ayar taslakları korunur; uyarı 410 pt kullanım panelinin yüksekliğini veya sekme hizasını değiştirmez. Çevrimdışı köprü, native sürücü denetimi, kapalı LED gösterimi ve eksik USB bağlantısı ayrı durumlar olarak gösterilir. Bilinmeyen yeni durum kodları sağlıklı aktarım sayılmaz; keyfi köprü hata metni arayüze aktarılmaz.
