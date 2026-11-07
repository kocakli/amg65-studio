# AMG65 için Claude maskotu: kaynak araştırması ve uygulama tasarımı

**Tarih:** 7 Kasım 2026. **Hedef:** Claude çalışırken klavyenin gerçek 63 × 5 LED alanında ileri geri yürüyen, yanıt beklerken duran küçük bir karakter. Bu raporun örnekleri sentetiktir; kişisel hesap, dosya veya konuşma verisi içermez.

Seçilen yaklaşım, blok biçimli yengeç karakterinden esinlenen **özgün 11 × 5 piksel yorumudur**. Büyük bir GIF küçültülmez; başka bir projenin sprite’ı veya kodu taşınmaz. Hareket yalnız gerçek ve süresi dolmamış Claude etkinliğinin sunumudur. Sağlayıcının çalıştığını varsayan bağımsız bir “evcil hayvan” döngüsü oluşturulmaz.

## 1. İncelenen birincil kaynaklar

| Kaynak | Kendi yazarının gösterdiği yaklaşım | AMG65’e aktarılabilecek fikir |
| --- | --- | --- |
| [b-barri / clawd-touchbar](https://github.com/b-barri/clawd-touchbar) | Touch Bar üzerinde Claude Code hook olaylarına tepki veren; çalışma, soru, tamamlanma gibi pozlar kullanan maskot. Repo AGPL-3.0 olarak etiketli. | Küçük klavye ekranında durumun karakterle anlatılması; yanıt gereken anda yürüyüşün durması. Kod ve çizimler alınmaz. |
| [CodeChrisB / MyClawd](https://github.com/CodeChrisB/MyClawd) | Animasyon setlerini giriş, döngü ve çıkış bölümlerine ayırıyor; ortak başlangıç/bitiş pozuyla sıçramasız geçiş hedefliyor. Proje kendini açıkça Anthropic’ten bağımsız bir fan çalışması olarak tanımlıyor. | RUN’dan beklemeye geçerken nötr bir duruş kullanmak; iki yürüme pozunun gövde hizasını korumak. GIF/set/toolkit kopyalanmaz. |
| [zhanbodev / clawd-buddy](https://github.com/zhanbodev/clawd-buddy) | Terminal ve masaüstü Claude görünümünde çalışma türüne göre pozlar; okuma, arama, yazma gibi hareketler ve daha geniş sahneler. | Karakterin görünüşünü olayın anlamına bağlamak. Geniş sahne, konuşma balonu ve oyunlar beş satırlık LED’e uygun değildir. |
| [Adafruit / John Park: Sprite Sheet Animation](https://learn.adafruit.com/pixel-art-matrix-display/sprite-sheet-animation) | Az sayıdaki sprite karesinin sırayla gösterilmesini ve yürüyüş pozlarından ayrı olarak karakterin ekranda yatay taşınmasını anlatıyor. | Bacak pozu ile x konumunu ayrı hesaplamak. AMG65’e özel iki poz ve hareket alanı tasarlamak. |

Buradaki “Clawd” adı topluluk projelerinin kullandığı addır. Bu kaynaklar, AMG65 çiziminin Anthropic tarafından sağlandığını, onaylandığını veya resmî marka varlığı olduğunu kanıtlamaz. Üründe açık ad **Claude maskotu**, teknik açıklamada **Studio’nun düşük çözünürlüklü yorumu** olmalıdır. Codex veya Cursor için benzer bir resmî karakter varmış gibi yeni maskotlar uydurulmaz.

### Örneklerdeki durum eşlemeleri aynen alınmamalı

Touch Bar projesinin README’si başarılı araç dönüşünü kısa kutlamaya, belirli bir `Stop`/araç olayı dizisini hataya eşliyor. Bu, o projenin davranışıdır. Tek araç çağrısının bitmesi tüm işin bittiği anlamına gelmez; eksik olay da hata kanıtı değildir. Studio kendi doğrulanmış olay sınıflandırmasını korur. Kaynak yalnız görsel etkileşim fikri için kullanılır. [clawd-touchbar durum tablosu](https://github.com/b-barri/clawd-touchbar#what-it-does)

Clawd Buddy’nin araç adına göre poz seçmesi daha geniş bir ekranda anlamlıdır. Studio’nun LED’i dosya adını, komutu, yanıtı veya model tarafından yazılmış açıklamayı göstermez. Mevcut izinli durum sözcükleri ve zaman damgaları yeterlidir. Kaynak projenin araç/dosya açıklamalarını gösterme yaklaşımı burada uygulanmaz. [Clawd Buddy özellikleri](https://github.com/zhanbodev/clawd-buddy#what-it-does)

## 2. Neden 11 × 5 ve iki yürüme pozu?

AMG65’in yüksekliği yalnız beş pikseldir. Yüz ayrıntısı, gövde ve ayakların her biri aynı satır bütçesini paylaşır. Büyük bir karakteri otomatik küçültmek göz boşluklarını veya ayakları birleştirebilir. Özgün bitmap, aynı gövdeyi koruyup yalnız alt satırdaki ayak pozunu değiştirebilir. İki pozun yeterli hareket hissi vermesi **tasarım hipotezidir**; fiziksel okunurluk testi gerekir.

Adafruit’in kaynak örneği az kareli sprite animasyonunu ve yatay konum değiştirmeyi ayrı işlemler olarak ele alır. “İki poz + 11 × 5” sayıları o kaynaktan alınmış donanım standardı değildir; bu panel için seçilen daha dar bir çözüm bütçesidir. [Adafruit animasyon temelleri ve yatay hareket](https://learn.adafruit.com/pixel-art-matrix-display/sprite-sheet-animation)

Önerilen çizim kuralları:

- Gövdenin silueti, göz boşlukları ve tabanı iki pozda aynı yerde kalsın; yalnız ayakların basış şekli değişsin.
- Her poz tam **11 sütun × 5 satır** olsun; bitmap taşıma sırasında yeniden ölçeklenmesin.
- Siyah göz/arka plan boşluğu korunsun; dış kenara glow veya yumuşatma eklenmesin.
- Sola dönerken bitmap yatay aynalanabilir; ayakların yönü konum değişimiyle tutarlı olsun.
- Claude rengi ve `A` etiketi birlikte kullanılsın. Kimlik yalnız turuncuya bağlı kalmasın.

Web/native turuncusu için Anthropic’in resmî paleti `#D97757`’dir. Mevcut fiziksel LED adayı `(254, 92, 24)` ayrı bir ayardır; aynı görünümü verdiği ölçülmüş değildir. [Anthropic marka yönergesi](https://github.com/anthropics/skills/blob/main/skills/brand-guidelines/SKILL.md) Ayrıntılı renk/gamma gerekçesi [LED tasarım araştırmasındadır](LED_DESIGN_RESEARCH.md).

## 3. Kesin yerleşim ve yürüyüş alanı

| Bölüm | Mantıksal sütunlar | Görev |
| --- | --- | --- |
| Maskot sahnesi | x=0–24 | 11 × 5 sprite ve bekleme işareti. |
| Boşluk | x=25 | Sahne ile kimliği ayırır. |
| Claude kimliği | x=26–28 | `A` harfi; panel açıklamasında A=Claude. |
| Boşluk | x=29–31 | Durum yazısından ayırır. |
| Durum sözcüğü | x=32–51 | RUN, ASK, INPUT, DONE vb.; `INPUT` mevcut fontta 20 px. |
| Ayrılmış boş alan | x=52–55 | Metin ve sağ bölümü ayırır. |
| Sağ bölümün boş kenarı | x=56 | Görsel sınır. |
| Üç kota göstergesi | x=57 / 59 / 61 | Claude, Codex, Cursor sırası korunur. |

```text
0.......................24 25 26..28 29..31 32................51 52..55 | 56..62
        MASKOT             .    A      .      DURUM SÖZCÜĞÜ       .    | KOTALAR
```

Uygulanan yürüyüşte sprite’ın sol kenarı **x=1 ile x=13** arasında gidip gelir: `1 → 3 → 5 → 7 → 9 → 11 → 13 → 11 → 9 → 7 → 5 → 3`, ardından çevrim yeniden başlar. 11 sütunluk sprite en sağda x=23’e kadar uzanır; sahnenin x=0 ve x=24 kenarları boş kalır. On iki görsel adımdan oluşan çevrimde ilerleme, gerçekten üretilen animasyon karesi başına **2 pikseldir**. Eski saat tikleri hızlandırılmış şekilde arka arkaya oynatılmaz. Bacak pozu iki kare arasında değişir; bakış yönü yürüyüş yönüne uyar.

ASK veya INPUT durumuna geçince maskot sabit x=3 konumuna alınır. Böylece 11 sütunluk gövde x=3–13’te kalır; x=18–22’deki `!` veya `?` ile çakışmaz. Durum metni de ekranda kalır. Sadece rengi değiştirmek yeterli bir işaret değildir. [W3C: renge ek şekil/metin kullanımı](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)

Bu düzen maskot açıldığında uzun `CLAUDE` adını bir harfe indirir. Bunun bedeli açıkça kabul edilmelidir: sahne daha canlı, kimlik daha kısadır. Maskot kapalıyken mevcut tam sağlayıcı adı + durum ikonu görünümü korunur. Diğer sağlayıcıların görünümü değişmez.

## 4. Durum sözleşmesi: hareket bilgi uydurmamalı

| Gözlenen durum | Sunum kararı | Kaçınılacak yorum |
| --- | --- | --- |
| Claude RUN; kaynak geçerli, süresi dolmamış | İleri geri yürüyüş ve iki ayak pozu | Yürüyüş hızından ilerleme yüzdesi çıkarmak. |
| Claude ASK | Sabit maskot + `!` + ASK | Maskotun kendiliğinden onay vermesi veya diyaloğun kesin açık olduğunu iddia etmek. |
| Claude INPUT | Sabit maskot + `?` + INPUT | Eksik veri yüzünden “bilgi bekliyor” durumu tahmin etmek. |
| QUEUE | Mevcut kuyruk etiketi/işareti; yürüyüş çalışma kanıtı olarak kullanılmaz | Kuyrukta olan işi çalışıyor göstermek. |
| DONE | İki pozlu kol sallama ve DONE etiketi; ileri geri yürüyüş yok | Tek araç dönüşünü tüm işin başarısı saymak. |
| ERROR | Sabit hata işareti ve ERROR etiketi | Hata sırasında neşeli yürüyüşe devam etmek. |
| Etkinlik yok, eski veya süresi dolmuş | Etkinlik seçimi sona erer; kota görünümü geri gelir | Sürekli yürüyen “canlı” maskotla faaliyet varmış izlenimi vermek. |

Kaynak önceliği, çoklu sağlayıcı seçimi ve TTL bu özellik için değiştirilmez. Uzun fakat sessiz bir işlem mevcut süre sınırından sonra bilinmeyen olabilir. Bu sınırlama, maskotu eğlenceli tutmak için kaldırılmamalıdır. Desteklenmeyen onay olayları tahmin edilmez; yeni hook, süreç izleme, ekran okuma veya ek ağ isteği gerekmez. Güncel kurallar [ACTIVITY.md](ACTIVITY.md) içinde tutulur.

Maskot yalnız seçilmiş Claude etkinlik sahnesini değiştirir. Daha öncelikli bir Codex/Cursor uyarısı varsa Claude karakteri ekranı sahiplenmez. `activity_enabled` kapalıysa maskot seçimi tek başına etkinlik gösterimini başlatmaz. Kayıtlı `claude_mascot` tercihi, kullanıcı etkinlik görünümünü yeniden açana kadar saklanabilir.

## 5. Ayar ve efektlerle birlikte çalışma

Yeni ayar `claude_mascot: boolean`, varsayılan **false**. Ekran bölümünde **Claude maskotu** anahtarı ve “Claude çalışırken yürür; onay veya bilgi beklerken durur.” açıklaması bulunur. Türkçe, İngilizce, İspanyolca, Basitleştirilmiş Çince ve Japonca desteklenir. Eksik/eski ayar nesnesinde kapalı davranış korunur; `"true"` metni veya `1` sayısı boolean yerine kabul edilmez.

Yazı efekti ile maskot hareketi farklı katmanlardır. Maskot sahnesi ve sağdaki kota göstergeleri Matrix/Kayan yazı işleminin içinde sürüklenmemelidir. Maskot sahnesinin tamamı dekoratif metin efektinden ayrıdır; durum sözcüğü de kendi ayrılmış alanında sabit kalır. ASK/INPUT/ERROR için mevcut sabit uyarı kuralı geçerlidir. Kullanıcının seçimi henüz gönderilmediyse durum sorgusu veya dil değişimi bu taslağı geri almamalıdır; yalnız eşleşen tamamlanmış ayar yanıtı kaydı kesinleştirmelidir.

Global animasyon üst sınırı mevcut **2 fps** olarak kalır. Gerçek tempo tamamlanan kare aktarımına bağlıdır; önceki yerel ölçümde kare başına yaklaşık 0,86 saniye görülmesi bu üst sınıra her zaman erişilemediğini gösterir. 500 ms aralıklı sentetik GIF yalnız tasarım önizlemesidir; fiziksel yürüyüş hızı kanıtı değildir. Daha fazla sprite karesi bu taşıma hızını artırmayı gerektirmez; aynı sprite pozları farklı konumlarda kullanılabilir. USB ACK, checksum ve hata sonrası durma kuralları aynen korunur. Bu sınır fiziksel titreşim güvenliği veya renk doğruluğu garantisi değildir. Hareket dikkat dağıtıyorsa maskot anahtarı kapatılabilir. [W3C: hareketi durdurma denetimi](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html)

## 6. Sonraki fikirler ve uygulanabilirlik

| Fikir | Uygulanabilirlik | Kazanç / maliyet | Durum |
| --- | --- | --- | --- |
| 11 × 5 yürüyen özgün maskot | Mevcut LED sahnesine doğrudan uygun | Basit, iki poz; kimlik için A açıklaması gerekir | Bu çalışma kapsamı. |
| Çoklu etkin oturum sırası | Mevcut öncelik ve eşit öncelikte dönüşümle geliştirilebilir | Adil gösterim; aynı sağlayıcıda birden çok işi tek karakterin temsil ettiği açık olmalı | Gelecek önerisi; yeni olay çıkarımı yok. |
| Sahne düzenleyici | Önce tamamen çevrimdışı 63 × 5 tuval | Piksel hizası, renk ve hareket yolu kullanıcı tarafından seçilebilir; sınırlı boyut/kare hızı ve doğrulama gerekir | Gelecek önerisi. |
| 32 × 32 portre | Ayrı TFT alanı için tasarım varlığı olabilir | Gözler, kollar ve daha çok poz için alan verir; TFT gerçek çözünürlük/format/aktarım bütçesi ayrıca doğrulanmalı | Yalnız gelecek seçeneği; bu işte TFT yüklemesi uygulanmaz. |
| Tam şehir/sahne, oyun veya konuşma balonu | 63 × 5’te kota/durum alanını tüketir | Büyük ekranda eğlenceli, bu LED’de anlamı zor okunur | Bu panel için seçilmedi. |

MyClawd’ın ortak giriş/çıkış pozu fikri gelecekte kısa bir “durdu ve baktı” geçişine uyarlanabilir. Clawd Buddy’nin büyük sahneleri ise ayrı TFT portresi veya masaüstü önizleme için araştırma yönü olabilir. Bu fikirler mevcut projelerin varlıklarını kopyalamayı veya bu sürümde yeni ekran yükleme işlemi yapmayı gerektirmez. [MyClawd](https://github.com/CodeChrisB/MyClawd), [Clawd Buddy](https://github.com/zhanbodev/clawd-buddy)

## 7. Doğrulama ve sonuçların sınırı

**Uygulama durumu:** Renderer’da özgün 11 × 5 sprite, yukarıdaki 12 adımlı RUN yürüyüşü, sabit QUEUE/ASK/INPUT/ERROR ve iki pozlu DONE kol hareketi uygulandı. Son piksel kalıplarının kaynağı [renderer.py](../renderer.py) dosyasıdır; dış projelerin çizimleri kullanılmadı. Bu rapor, yeni hareketin cihaz üzerinde görsel doğrulamasını tamamlanmış saymaz.

**Çevrimdışı kabul:** Her sprite 11 × 5; her kare 315 RGB piksel; kanallar 0–254. Sprite hiçbir adımda x=24’ü aşmaz. Sol uç, sağ uç, dönüş ve iki ayak pozu sınanır. ASK/INPUT kareleri zaman değişse de sabit kalır. Sağ kota göstergeleri ve ayırıcı sütun korunur. Özellik kapalıyken eski görünümle eşitlik; Codex/Cursor karelerinde değişmeme; süresi dolmuş olayda hayalî yürüyüş üretmeme kontrol edilir.

**Ayar kabulü:** Eksik alan false; true/false kaydetme ve yeniden yükleme; beş dilde açıklama; taslak, odak ve bekleyen işlem sırasında seçimi koruma. Bu rapor yazılırken web tarafındaki altı yerelleştirme testi ve JS sözdizimi kontrolü geçti. Gerçek form yardımcıları çevrimdışı çalıştırılarak üç ekran modu × beş yazı efekti × iki maskot tercihi için **30 ayar gönderim birleşimi**, eksik/hatalı boolean ve taslak/onay koruması doğrulandı. Bunlar renderer veya USB donanım testinin yerine geçmez.

**Cihazda ayrı doğrulama:** Normal oturma mesafesinde maskotun karakter olarak seçilmesi; iki ayağın yürüyüş hissi vermesi; turuncunun göz boşluklarını kapatmaması; bir RUN→ASK→RUN dizisinde durma/hareketin anlaşılması. Deneme gerçek hesap yerine sentetik karelerle yapılabilir; canlı etkinlik eşlemesi ayrıca yalnız mevcut izinli olaylarla kontrol edilir. Gözlenen USB onayı, hareketin hoş veya okunur olduğunun tek başına kanıtı değildir.

Araştırma sırasında dış projeler **kurulmadı**, kod veya sprite varlıkları kopyalanmadı, kullanıcı sırları okunmadı ve donanıma yazılmadı. Uygulama, bağımsız çizim ve mevcut Studio olay sözleşmesi üzerinde ilerler; fiziksel görünümün son onayı gerçek cihaz gözlemine aittir.

## Kurulu sürüm doğrulaması

Bu çalışma sonunda sürüm16 kuruldu; 163 Python testi, 185 native kontrol ve 12 native yerelleştirme testi geçti. Kullanıcıya ait kurulumda `claude_mascot` tercihi açıldı. Olay seçimi ve USB aktarımı mevcut köprüde devam ediyor. Yürüyüş GIF’i ve altı durum görseli gerçek renderer fonksiyonlarından üretilmiş sentetik önizlemelerdir; yeni bir çalışan Claude olayı oluşturulmadı. Maskotun tetiklenmesi gerçek Claude etkinlik sinyaline bağlıdır. Gösterilecek araç seçicisinde Otomatik/Claude/Codex/Cursor odağı bulunur; odaklı mod seçilen aracın durum ve çalışma adımlarını gösterir.
