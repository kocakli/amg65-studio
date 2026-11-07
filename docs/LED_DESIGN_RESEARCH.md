# AMG65 63 × 5 LED: kota ve agent durumu tasarım araştırması

Araştırma tarihi: **7 Kasım 2026**. Kapsam, klavyenin 315 piksellik RGB LED şerididir. Örnek yüzdeler **sentetiktir**; gerçek hesap, sohbet, dosya veya görev bilgisi içermez.

Öneri: varsayılan görünümde üç sağlayıcının kalan kotası aynı anda, sabit konumlarda gösterilsin. Dikkat isteyen gerçek bir olay geldiğinde tam sağlayıcı adı, kısa durum sözcüğü ve ayrıca bir şekil kullanılsın. Claude arayüzde resmi turuncuyla, fiziksel LED’de ayrıca doğrulanacak daha doygun bir turuncu paletle temsil edilsin. Beş satırlık panelde şıklık; az hareket, düzenli boşluk ve tutarlı hizadan gelmeli.

## 1. Kanıt ve sınırlar

| Bilgi | Dayanak / doğrulama durumu |
| --- | --- |
| 63 × 5 mantıksal piksel, 56 × 5 ana bölüm ve fiziksel olarak ayrı 7 × 5 sağ bölüm | Açık protokol uygulaması ve Studio kaynak kodu. Upstream yazar, 315 noktayı tek tek görüntüleyerek bellek eşlemesini doğruladığını bildiriyor. Bu raporda yeni bir fiziksel ölçüm yapılmadı. |
| Bellekte dört 14 × 5 blok, ardından sağdaki 7 × 5 blok | Upstream `RAW_ORDER`; mantıksal satır sırası doğrudan USB sırası değildir. |
| Kanal üst sınırı 254; 315 RGB piksel = 945 bayt, protokol çerçevesi 960 bayt | Upstream `MAX_CHANNEL` ve `to_raw_bytes`; mevcut Studio taşıması aynı sınırı korur. |
| Marka turuncusu `#D97757` | Anthropic’in kendi marka yönergesi; fiziksel AMG65 renk ölçümü değildir. |
| `(254, 92, 24)` LED turuncusu, ikonlar, sayfa süreleri | Bu çalışma sırasında seçilen **tasarım adayları**. Piksel yerleşimi hesaplanabilir; algılanan renk ve okunabilirlik cihaz üzerinde ayrıca sınanmalıdır. |

Protokol dayanağı: [aumbro AMG65 projesi](https://github.com/aumbro/leobog_amg65_rgb), incelenen [matrix.py sabit sürümü](https://github.com/aumbro/leobog_amg65_rgb/blob/2bd9ed8e9a2c0f8778562f68449d7869a86476a5/amg65/matrix.py). Bu topluluk tersine mühendislik çalışması, üreticinin yayımladığı bir donanım garantisi değildir. Renk dayanağı: [Anthropic resmi marka yönergesi](https://github.com/anthropics/skills/blob/main/skills/brand-guidelines/SKILL.md).

## 2. Gerçek piksel bütçesi ve font

Beş piksel yüksekliğinde tek metin satırı vardır. Başlık, yüzde ve alt açıklama üst üste yerleştirilemez. Adafruit’in standart GFX yazısının belgelenen yüksekliği bu alana sığmaz; ölçekleyerek küçültmek yerine beş satıra özel bitmap gerekir. [Adafruit metin çizimi](https://learn.adafruit.com/adafruit-gfx-graphics-library/graphics-primitives)

Adafruit’in TomThumb kaynağında birçok büyük harf/rakam için genişlik 3, yükseklik 5 ve ilerleme 4 pikseldir. Ancak tüm karakterler aynı boyutta değildir; örneğin bazı küçük harfler alt satıra taşar. Bu nedenle yalnız seçilen büyük harf/rakam kümesi ölçülmelidir; fontun tamamı körlemesine alınmamalıdır. [Adafruit TomThumb glyph tablosu](https://github.com/adafruit/Adafruit-GFX-Library/blob/master/Fonts/TomThumb.h)

Studio’nun araştırma başındaki fontu çoğunlukla 3 × 5, aralık 1 pikseldir; `N` 4, `M/W` 5 piksel genişliğindedir. Aynı boydaki harf varsayımı yerine gerçek genişlik toplamı kullanılmalıdır:

```text
metin_genişliği = toplam(glyph_genişliği + 1) - 1
```

Mevcut `FONT` tablosuyla çevrimdışı hesap:

| Örnek | Genişlik | Sonuç |
| --- | ---: | --- |
| `A100` | 15 px | 18 px kota hücresine sığar. |
| `A100%` | 19 px | 18 px hücreye sığmaz; üçlü görünümde `%` eklenmesin. |
| `CLAUDE` / `CURSOR` | 23 px | Tam ad için ayrılmış 23 px alana sığar. |
| `CODEX` | 19 px | Aynı başlangıç çizgisi korunur. |
| `RUN` / `ASK` | 12 / 11 px | Kısa durumlar rahat sığar. |
| `INPUT` / `DONE` | 20 / 16 px | `INPUT` durum alanının üst sınırını belirler. |
| `ERROR` / `QUEUE` | 19 / 19 px | 20 px durum alanına sığar. |

En az bir karanlık sütun harfleri ayırsın. Sayılar sağa hizalansın; `9 → 10 → 100` geçişinde sağlayıcı kimliği yer değiştirmesin. Antialiasing, ince gölge, ekran fontunu küçültme ve dekoratif çerçeve bu bütçede bilgiye ayrılan pikselleri tüketir. Bunların kaldırılması tasarım önerisidir; karşılaştırmalı fiziksel okuma testi henüz yapılmadı.

## 3. Düzen seçeneklerinin karşılaştırması

| Seçenek | Güçlü taraf | Bedeli | Karar |
| --- | --- | --- | --- |
| Üç sabit kota hücresi | Üç sağlayıcı tek bakışta; sayı karşılaştırması kolay | Tek harf kısaltmaları öğrenilmeli | Varsayılan. |
| Sağlayıcı başına tam ad + yüzde sayfası | Kimlik açık, alan ferah | Diğer sağlayıcıyı görmek için beklenir | Kullanıcının seçtiği ayrıntı modu. |
| Sürekli kayan ad ve kota | Uzun metin taşınabilir | Bilgi parçalanır; okuma anına bağlıdır, daha çok kare değişir | Kota ve alarmda kullanılmasın. |
| Yalnız üç renkli çubuk | Az piksel ve düşük görsel yoğunluk | Kesin oran yok; renk/konum açıklaması gerekir | Metnin yanında ikincil gösterge. |
| Beş piksele indirgenmiş marka logoları | Dekoratif kimlik hissi | Benzer şekiller; resmi logoyu tanıma garantisi yok | Ana kimlik yerine kullanılmasın. |

Renklere ek olarak metin veya şekil verilmesi W3C’nin renk kullanım ilkesiyle uyumludur. Burada bu ilke fiziksel arayüz tasarımına uyarlanıyor; klavye için WCAG uygunluk sertifikası iddia edilmiyor. [W3C: Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)

### Seçilen uygulama planı

Aşağıdaki koordinatlar bu araştırma sırasında renderer için kararlaştırılan plandır. Fiziksel renk/okuma doğrulaması tamamlanmış ürün ölçümü değildir. Kodun güncel uygulanma durumu [renderer.py](../renderer.py) ve [renderer testlerinden](../tests/test_renderer.py) izlenmelidir.

**Üçlü kota:** `A = Claude`, `X = Codex`, `C = Cursor`. Bu eşleme uygulamadaki açıklamada sürekli görünür olsun. Sentetik örnek: `A85   X42   C100`.

| Bölüm | Mantıksal x konumu |
| --- | --- |
| Sağlayıcı harfi | 0 / 19 / 38 |
| Sayısal alanın sağ sınırı | 16 / 35 / 54, sağ sınır hariç |
| Eski veri işareti için ayrılmış piksel | 17 / 36 / 55 |
| Sağ bölümün boş kenarı | 56 |
| Üç kota göstergesi | 57 / 59 / 61 |

`--` veri bilinmiyor demektir; `0` kotanın gerçekten sıfır olduğunu belirtir. Kaynak eskiyse karartmaya ek şekil işareti korunsun. Yalnız sönük renk, düşük parlaklıkta güvenilir bir açıklama değildir. Sağdaki çubuklar beş basamakla yaklaşık kota gösterir; tam yüzde olarak yorumlanmamalıdır. Mevcut `ceil(yüzde / 20)` hesabında sıfırdan büyük oran en az bir basamak yakar.

**Agent durumu:**

```text
x: 0....4  7.....................29  32................51  52..55 | 56..62
   5×5 ikon  TAM SAĞLAYICI ADI          RUN / ASK / INPUT     boş | 3 kota
```

Tam sağlayıcı adı kendi renginde, durum sözcüğü sabit ve okunur kalır. `CLAUDE` ve `CURSOR` 7–29, `INPUT` 32–51 aralığını tam kullanır. İkon 0–4’te bağımsızdır; yazı ve sağ göstergelerle çakışmaz. Ayrıntı kotasında ad x=1’den başlar, yüzde sağ sınır 51’e hizalanır; gösterge x=58–60 olur.

## 4. Durum dili ve öncelik

LED, bir izin isteğine yanıt vermez; yalnız gözlenen olayı gösterir. Renk tek başına durum taşımasın:

| Olay | LED etiketi | Şekil önerisi | Davranış |
| --- | --- | --- | --- |
| Onay isteği | `ASK` | Sabit `!` | Öncelikli dikkat sayfası. |
| Kullanıcı girdisi isteği | `INPUT` | Sabit `?` | `ASK` ile aynı öncelik. |
| Hata olayı | `ERROR` | Kırmızı çapraz | Dikkat isteklerinden sonra. |
| Çalışma olayı | `RUN` | Oynat/çalışma simgesi | Metin sabit; küçük ikon hareketi isteğe bağlı. |
| Kuyruk olayı | `QUEUE` | Kum saati / bekleme şekli | Çalışmadan sonra; kota görünümünü sürekli engellemez. |
| Tamamlanma olayı | `DONE` | Onay işareti | Kısa bildirim; daha öncelikli olayları kesmez. |
| Veri yok / süresi dolmuş | Etkinlik sayfası yok | Başarı simgesi yok | Kota görünümüne dönülür. |

Önerilen sıra: **ASK = INPUT > ERROR > RUN > QUEUE > DONE**. Eşit öncelikteki sağlayıcılar 4 saniyelik duraklarla dönüşebilir. RUN/QUEUE için mevcut 10 saniyelik çevrimin 6 saniyesini etkinliğe, 4 saniyesini üçlü kotaya ayırma yaklaşımı korunabilir. Bunlar okunabilirlik denemesi için başlangıç ayarlarıdır; bir standarttan türetilmiş zorunlu süreler değildir. `DONE` için 4 saniyelik tek gösterim veya kullanıcı ayarlı kısa süre tercih edilebilir; olayın önbellekte 45 saniye yaşaması, metnin 45 saniye kesintisiz ekranda kalmasını gerektirmez.

Kaynak sözleşmesi önemlidir: süre sınırı geçen RUN, DONE’a dönüşmez; bilinmeyene döner. ASK son gözlenen istektir, hâlâ açık bir onay penceresinin kanıtı değildir. Cursor’ın doğrulanmış olay sözleşmesinde bekleyen onay olayı yoksa ASK tahmin edilmez. Kurulu eski Claude hostunda desteklenmeyen olay da üretilmez. Güncel gözlem sınırları ve TTL değerleri [ACTIVITY.md](ACTIVITY.md) içinde tutulur; LED tasarımı bu sınırları aşmamalıdır.

## 5. Renk, gamma ve parlaklık

Anthropic’in kendi paletinde birincil vurgu turuncusu **`#D97757`**, yani `(217, 119, 87)`’dir. Studio’nun web/native kimliğinde bunun kullanılması kaynakla desteklenir. Bu değerler fiziksel LED’in renk ölçümü değildir. [Anthropic marka renkleri](https://github.com/anthropics/skills/blob/main/skills/brand-guidelines/SKILL.md)

Adafruit, LED’de kırmızıya yüksek miktarda yeşil eklenince amaçlanan turuncunun sarı algılanabildiğini ve insan parlaklık algısının doğrusal olmadığını anlatır. Ekran rengi ile doğrudan LED kanal sayıları arasındaki farkın gerçek bir gerekçesi vardır. Ancak bu açıklama AMG65’in sürücü aktarım eğrisini ölçmez. [Adafruit: gamma sorunu](https://learn.adafruit.com/led-tricks-gamma-correction/the-issue)

| Kullanım | Değer / yaklaşım | Statü |
| --- | --- | --- |
| Claude web/native | `#D97757` | Resmi marka referansı. |
| Claude fiziksel LED | `(254, 92, 24)` | Daha doygun turuncu adayı; cihaz üzerinde doğrulanmalı. |
| Codex fiziksel LED | Mevcut mint `(123, 220, 176)` başlangıç adayı | Studio’nun ayırt etme paleti; resmi OpenAI renk standardı iddiası yok. |
| Cursor fiziksel LED | Mevcut mavi `(134, 190, 248)` başlangıç adayı | Studio paleti; resmi Cursor marka rengi iddiası yok. |
| ASK/INPUT / ERROR | Amber + `!/?` / kırmızı + çapraz | Renk, sözcük ve şekil birlikte. |
| Bilinmeyen | Nötr gri + `--` | Sıfır veya başarı görünümüyle karıştırılmaz. |

Ölçüm olmadan bütün renklere sabit bir gamma üssü uygulamayın. Donanım zaten dönüştürüyor olabilir; ikinci dönüşüm düşük seviyeleri aşırı karartabilir. Önce ayrı LED paleti, sonra aynı parlaklık çarpanıyla tutarlı üretim kullanılabilir. Örneğin `(254,92,24)` ve 0,4 çarpanı yuvarlandığında `(102,37,10)` gönderilir. Bu sadece sayısal hesap, algısal renk eşitliği değildir.

Karşılaştırma üç sağlayıcının eşit sayısal parlaklıkta eşit parlak göründüğünü varsaymamalıdır. Düşük seviyede kanal yuvarlaması ve difüzör etkisi tonu değiştirebilir. 0,2 / 0,4 / 0,7 gibi birkaç sabit seviye, gündüz ve loş ortamda gözlenmeli; sonunda kullanılan LED paleti ile parlaklık kaydedilmelidir. Bunlar test noktalarıdır, zorunlu kullanıcı ayarları değildir.

## 6. Hareket, sayfa bekleme ve USB yükü

Kota ve alarm metinleri kaymasın. Uzun kişisel metinde kaydırma ayrı, kullanıcının seçtiği bir özellik olabilir. Kısa metin 56 sütunda ortalansın; sağ küçük bölüm dekoratif taşma alanı yapılmasın. Araştırma başındaki `render_text` içinde tanımsız `*` karakterinin `?` çizimine düşmesi gerçek bir önizleme kusuruydu; bunun yerine açıkça tanımlanmış bir metin simgesi planlandı.

RUN için planlanan 2 Hz, dört fazlı küçük ikon hareketi **iki kare değişimi/saniye** demektir; metnin yanıp sönmesi anlamına gelmemelidir. ASK/INPUT simgeleri statik kalsın. Bütün şeridi terslemek, kırmızı flaş ve yüzde yazısını söndürmek kullanılmasın. Statik/azaltılmış hareket seçeneği bir sonraki kullanılabilirlik geliştirmesi olarak değerlendirilsin. W3C, sürekli hareketi durdurma denetimini ve flaşlardan kaçınmayı ayrı konular olarak ele alır; yalnız düşük Hz sayısı fiziksel güvenlik veya erişilebilirlik kanıtı değildir. [W3C hareket denetimi](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html), [W3C flaş eşiği açıklaması](https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html)

Studio’nun mevcut akışı aynı piksel dizisini yeniden göndermez. Tek bir hareketli nokta bile kareyi değiştirir; canlı kare aktarımı 19 raporluk işlem gerektirir. Bu nedenle hareket, statik sayfadan daha fazla USB işlemi üretir. Upstream’in kendi cihazındaki hızlı akış deneyleri bu kurulum için güvenilir hız garantisi değildir. Görsel iyileştirme adına ACK doğrulaması, checksum veya hata sonrası durma davranışı gevşetilmemelidir. Kaynak: [AMG65 aktarım uygulaması](https://github.com/aumbro/leobog_amg65_rgb/blob/2bd9ed8e9a2c0f8778562f68449d7869a86476a5/amg65/matrix.py), Studio [AMG65HID.swift](../AMG65HID.swift) ve [app.py](../app.py).

## 7. Bitmap önizleme ve doğrulama planı

Önizleme mantıksal 63 × 5 pikselden, tamsayı ölçeğinde üretilsin. Sağ fiziksel bölüm aralığı görünür olsun; uygulamada bunun “önizleme” olduğu belirtilsin. Bulanıklaştırma/glow okunurluk hatasını gizlememeli. Renkleri eşit griye çeviren ikinci kontrol, kimlik ve durumun renksiz anlaşılmasını sınar. Bilgisayar önizlemesi fiziksel LED renk kalibrasyonu yerine geçmez.

Aşağıdaki **sentetik** `CLAUDE INPUT` taslağı, ölçülen font ve seçilen yerleşimden çevrimdışı üretildi. Sol `?` örnek şekildir; son renderer simgesi farklı olabilir. `#` yanan, `:` sönük gösterge, `.` kapalı pikseldir. `|` yalnız iki fiziksel bölümü anlatır, piksel değildir. Sağdaki seviyeler sentetik %85 / %42 / %100 için 5 / 3 / 5 basamaktır.

```text
.###....##.#....#..#.#.##..###..###.#..#.##..#.#.###.... | .#.:.#.
...#...#...#...#.#.#.#.#.#.#.....#..##.#.#.#.#.#..#..... | .#.:.#.
..##...#...#...###.#.#.#.#.##....#..#.##.##..#.#..#..... | .#.#.#.
.......#...#...#.#.#.#.#.#.#.....#..#..#.#...#.#..#..... | .#.#.#.
..#.....##.###.#.#.###.##..###..###.#..#.#...###..#..... | .#.#.#.
```

Uygulama kabul ölçütleri:

1. **Geometri:** 315 RGB piksel; her kanal 0–254; x=56 siyah; hiçbir metin ayrılmış alanı aşmaz. `100`, `0`, `--`, bütün sağlayıcılar ve altı durum denenir. Kaynak sırası değişse de fiziksel sıra değişmez.
2. **Doğruluk:** Bilinmeyen, sıfır ve eski veri birbirinden ayrılır. Süresi dolmuş veya desteklenmeyen etkinlik başarıya dönüştürülmez. ASK/INPUT önceliği ve eşit öncelikte adil dönüşüm kontrol edilir. Özel görev metni kareyi etkilemez.
3. **Sayısal hizalama:** `9/10/99/100` ardışık örnekleri sabit sağlayıcı konumunda karşılaştırılır. Yüzde işareti üçlü hücreye sığdırılmaya çalışılmaz. Sağa hizalama geniş `N` gibi glyphlere dayalı gerçek genişlikle hesaplanır.
4. **Fiziksel okunabilirlik:** Normal oturma mesafesi ölçülüp kaydedilir; ışık seviyesi ve LED parlaklığı not edilir. Kullanıcı karışık sıradaki sentetik kartlarda sağlayıcıyı, oranı ve durumu okur. Özellikle `0/8`, `1/7`, `ASK/INPUT`, `DONE/ERROR` karışmaları kaydedilir. Belirlenen 4 saniyelik bekleme yetersizse artırılır.
5. **Renk:** Resmi web turuncusu ve LED adayı ayrı gösterilir; fiziksel görünüm kullanıcı tarafından seçilir. Fotoğraf yalnız belge olur: otomatik pozlama/beyaz ayarı renk ölçümü sayılmaz. Kalibre cihaz olmadan “tam marka eşleşmesi” denmez.
6. **Hareket/taşıma:** Önce statik, sonra yalnız küçük ikon hareketiyle kontrollü deneme yapılır. ACK hatası, yanlış renk/nokta veya gözle görünür rahatsızlıkta durulur. Hata sonrası yeniden gönderim eklenmez; kararlılık önizleme testiyle kanıtlanmış sayılmaz.

Bu rapor hazırlanırken renderer ve testler okundu, glyph genişlikleri ve yukarıdaki sentetik piksel yerleşimi çevrimdışı hesaplandı. **Donanıma yeni kare gönderilmedi; fiziksel renk, izleme mesafesi, hareket ve uzun süreli kararlılık yeniden ölçülmedi.** Rapor tasarım gerekçesini ve uygulanabilir doğrulama adımlarını verir; bu son ölçümleri tamamlanmış gibi sunmaz.

## Ek: kullanıcı seçimiyle yazı efektleri

Kullanıcının ek isteğiyle Ekran ayarlarına **Sade, Tarama, Nefes ve Matrix** seçenekleri eklenir (`text_effect`: `none`, `scan`, `breathe`, `matrix`). Varsayılan **Sade** kalır. Efektler kota ve kişisel metin görünümüne uygulanır; onay ve bilgi isteği metinleri/simgeleri sabit kalır. Matrix adı bir stil seçeneğidir; rastgele karakterler gerçek yüzde veya durumun yerine geçmemelidir.

Hareket kullanıcı tarafından açılır; global kare üretimi üst sınırı **2 fps** olarak korunur. Bu, yeni bir USB hız modu veya iki flaş/saniye güvenlik iddiası değildir. ACK bekleme, checksum, kare aktarım aralığı ve hata sonrası durma kuralları değiştirilmez. Son görünümün okunabilirliği ve fiziksel rengi yukarıdaki cihaz testlerine tabidir; özellikle Nefes efektinin en sönük fazında rakamların seçilebilir kalması kontrol edilmelidir.

## Uygulama ve önizleme

Bu araştırmadaki hizalı kota düzeni, soldaki durum ikonları ve ayrı LED turuncusu renderer’a uygulandı. Sade, Tarama, Nefes ve Matrix seçenekleri hem native menüye hem web ekran ayarlarına eklendi. Etkinlik sayfaları bu dekoratif işlemeden geçmez. Matrix için çalışan yerel köprüde yazı/gösterge piksellerinin korunduğu ve değişen karelerin USB onayı aldığı gözlendi; algılanan fiziksel renk veya uzun süreli kararlılık ölçümü yapılmış değildir.

[15 sentetik görünümün toplu çizimi](images/led-layouts.svg), gerçek renderer fonksiyonlarından üretilebilir. `python3 tools/preview_led.py --help` ile çevrimdışı etkileşimli HTML veya isteğe bağlı PNG çıktısı hazırlanır. Örnek veriler gerçek hesap kotası değildir.
