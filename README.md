# Cloudstream eklenti şablonu

Genel amaçlı bir siteden HTML ayrıştırıp Cloudstream veri modellerine dönüştüren,
siteye bağlı hiçbir değer içermeyen bir `MainAPI` şablonu. Bağımsız bir Gradle projesidir.

> Yalnızca kullanım koşulları otomatik erişime izin veren sitelerle ve izlemeye hakkınız
> olan içerikle kullanın. Şablondaki varsayılan seçiciler gerçek bir siteye değil,
> `src/test/resources/fixtures` içindeki örnek sayfalara göredir.

## Dosya ağacı

```
cinedepo/
├── settings.gradle.kts          # build.gradle.kts içeren her alt dizin = bir eklenti
├── build.gradle.kts             # AGP + Cloudstream gradle eklentisi, ortak bağımlılıklar
├── gradle.properties
├── gradlew, gradle/wrapper/     # Gradle 8.11.1 (sürümler aşağıda)
├── repo.json                    # Uygulamaya eklenen depo bildirimi
├── plugins.example.json         # makePluginsJson çıktısının biçimi (örnek)
├── site.example.json            # auto_update.py için örnek site ayarı
├── scripts/auto_update.py       # siteye uyarla + sürüm artır + gönder (tek komut)
├── scripts/site_editor.py       # aynı işin tarayıcıda açılan masaüstü arayüzü
├── .github/workflows/build.yml  # .cs3 + plugins.json üretir, `builds` dalına yayınlar
├── InternetArchive/             # archive.org'daki kamu malı filmler (JSON API, çalışan örnek)
└── CineDepo/                    # eklenti modülü; dizin adı = eklenti adı
    ├── build.gradle.kts         # sürüm + eklenti bildirimi (cloudstream { ... })
    └── src/
        ├── main/
        │   ├── AndroidManifest.xml
        │   └── kotlin/com/example/sitetemplate/
        │       ├── SiteConfig.kt            # URL, ana sayfa bölümleri, TÜM CSS seçiciler (TODO)
        │       ├── SiteParser.kt            # Saf Jsoup: Document -> veri sınıfları, URL denetimi
        │       ├── ExampleSiteProvider.kt   # MainAPI: getMainPage, search, load, loadLinks
        │       ├── ExampleEmbedExtractor.kt # Özel gömülü oynatıcı için ExtractorApi şablonu
        │       └── ExampleSitePlugin.kt     # @CloudstreamPlugin giriş noktası
        └── test/
            ├── kotlin/.../SiteParserTest.kt # JVM testi, ağ yok; kendi sabit seçicilerini kullanır
            └── resources/fixtures/*.html    # Örnek sayfalar
```

## Katmanlar

| Katman | Dosya | Görev |
|---|---|---|
| Yapılandırma | `SiteConfig` | Siteye özgü her şey: `MAIN_URL`, `HOME_SECTIONS`, `SEARCH_PATH`, seçiciler, oynatıcı JSON regex'i |
| Ayrıştırma | `SiteParser` | Ağ ve Cloudstream bağımlılığı yok; eksik alan `null` olur, başlığı/bağlantısı olmayan kart atlanır |
| Eşleme | `ExampleSiteProvider` | Sayfayı indirir (`app.get`), `SiteParser` sonucunu `newMovieSearchResponse`, `newTvSeriesLoadResponse`, `newExtractorLink` vb. ile modele çevirir |
| Bağlantı çözme | `loadLinks` | Sırayla: iframe -> `loadExtractor`, doğrudan `<video>/<source>`, satır içi JSON -> `AppUtils.tryParseJson` |

Güvenlik kuralları (`SiteParser.safeUrl`):
- Yalnızca `http`/`https`; `javascript:`, `data:`, boş ve `#` bağlantılar reddedilir.
- Liste kartları, bölümler ve `loadLinks`'e gelen `data` yalnızca `MAIN_URL` ana makinesinde
  ya da `ALLOWED_EXTRA_HOSTS` içinde olabilir. Gömülü oynatıcılar ve medya dosyaları üçüncü
  taraf olabileceğinden bu kısıt onlara uygulanmaz.
- Arama sorgusu `URLEncoder` ile kodlanır; JSON hatalı ise `tryParseJson` `null` döner.

## Yeni bir siteye uyarlama

1. `SiteConfig.kt` içindeki `TODO` alanlarını doldurun (elle ya da `scripts/auto_update.py` ile,
   aşağıya bakın). Seçicileri tarayıcıda
   Geliştirici Araçları > Öğeler ile bulun (`document.querySelectorAll("...")` ile konsolda deneyin).
2. Hedef sitenin bir liste, film ve dizi sayfasını `src/test/resources/fixtures/` altına
   kaydedin, `SiteParserTest` beklentilerini güncelleyin.
3. Oynatıcı başka bir ana makinedeyse ve Cloudstream onu tanımıyorsa
   `ExampleEmbedExtractor`'ı uyarlayın (`mainUrl` = oynatıcının adresi).
4. `CineDepo/build.gradle.kts` içinde `description`, `authors`, `language`,
   `tvTypes`, `iconUrl` alanlarını düzenleyin. Her yayında `version` değerini artırın.
5. Kök `build.gradle.kts` içindeki `setRepo(...)` yedeğini ve `repo.json` içindeki
   depo adresini kendi deponuza göre güncelleyin (şu an `mtndlgc/cinedepo`).

Yeni eklenti eklemek için `CineDepo` dizinini kopyalayıp adını ve paketini
değiştirmeniz yeterli; `settings.gradle.kts` onu kendiliğinden ekler.

## Internet Archive eklentisi

`InternetArchive/`, archive.org'daki kamu malı (telif süresi dolmuş) filmleri gösteren, gerçek
içerikle çalışan bir eklentidir. HTML seçicileri yerine Internet Archive'ın açık JSON API'sini
kullanır, bu yüzden `SiteConfig` ve site düzenleyiciyle ilgisi yoktur.

- Ana sayfa satırları: Uzun Metraj Filmler (`feature_films`), Kara Filmler (`Film_Noir`),
  Bilim Kurgu ve Korku (`SciFi_Horror`), Komedi (`comedy_films`), Sessiz Filmler (`silent_films`),
  Klasik Çizgi Filmler (`classic_cartoons`), Klasik TV (`classic_tv`). Liste
  `ArchiveApi.COLLECTIONS` içindedir.
- Arama bu koleksiyonlarda başlık ve konuya göre yapılır; sonuçlar indirme sayısına göre sıralanır.
- Video: Android oynatıcısının sorunsuz oynattığı biçimler (h.264, MPEG4, 512Kb MPEG4) en iyiden
  başlayarak sunulur; MPEG2, Ogg ve Matroska atlanır. `.srt` / `.vtt` altyazılar eklenir.

Bu koleksiyonlar Internet Archive'ın kamu malı film koleksiyonlarıdır, ama öğeleri kullanıcılar
yükler ve Archive her öğenin hak durumunu tek tek doğrulamaz. Bir öğenin durumundan şüphelenirsen
archive.org'daki sayfasına bak.

## Masaüstü arayüzü (`scripts/site_editor.py`)

Site adresini ve seçicileri komut satırı yerine bir pencereden düzenlemek için:

macOS / Linux:

```bash
git clone https://github.com/mtndlgc/cinedepo && cd cinedepo
python3 scripts/site_editor.py
```

Windows (PowerShell; eski PowerShell `&&` tanımadığı için komutlar ayrı satırda):

```powershell
git clone https://github.com/mtndlgc/cinedepo
cd cinedepo
py scripts\site_editor.py
```

`py` bulunamazsa `python scripts\site_editor.py` deneyin. Python yoksa python.org'dan kurun ve
kurulumda "Add python.exe to PATH" kutusunu işaretleyin. Git yoksa git-scm.com'dan kurun.

Tarayıcıda `http://127.0.0.1:8765` açılır (açılmazsa adresi kendin aç; kapatmak için terminalde
`Ctrl+C`). Gereken tek şey Python 3; Windows, macOS ve Linux'ta aynı çalışır, ek paket gerekmez.

Sayfa `SiteConfig.kt`'deki mevcut değerleri gösterir: site adresi, uygulamadaki ad, dil, arama
yolu, ana sayfa satırları, ek alan adları ve 25 CSS seçicisinin hepsi, Türkçe açıklamalarıyla.

| Düğme | Ne yapar |
|---|---|
| **Önizle** | Değişiklikleri renkli fark olarak gösterir, dosyaya yazmaz |
| **Kaydet** | Dosyaları yazar ve sürümü artırır, commit atmaz |
| **Kaydet ve GitHub'a gönder** | Yazar, commit'ler, gönderir; GitHub Actions derlemeyi başlatır (~2 dk) |

- "Sürümü artır" işaretliyse sürüm 1 artar. Önce Kaydet sonra Gönder'e basınca sürüm yalnızca bir
  kez artar.
- "Seçicileri canlı sayfada dene" işaretliyse önizleme, listedeki seçicileri sitenin gerçek
  sayfasında dener (`pip install beautifulsoup4` gerekir).
- Hatalı girişte (boş seçici, geçersiz adres ya da dil kodu, `%s` olmayan arama yolu) hiçbir şey
  yazılmaz; hata altta gösterilir.
- Gönderim, bilgisayarındaki git kimliğini kullanır. `git push` terminalde çalışıyorsa buradan da
  çalışır.
- Eklentinin kendi iki dosyası dışında commit'lenmemiş bir değişiklik varsa gönderim durur; bu,
  ilgisiz dosyaların yanlışlıkla commit'lenmesini engeller.

Güvenlik: sunucu yalnızca `127.0.0.1` adresini dinler, ağdaki başka cihazlar erişemez. Her
çalıştırmada rastgele bir anahtar üretilir ve her istek bu anahtarı taşımak zorundadır; böylece
tarayıcıda açık olan başka bir site arayüze istek gönderemez.

## Otomatik güncelleme (`scripts/auto_update.py`)

Siteye uyarlama, sürüm artırma ve gönderme tek komuttur. Yalnızca Python 3 standart
kitaplığı gerekir.

```bash
cp site.example.json site.json          # düzenleyin: url, name, lang, home_sections, selectors
python3 scripts/auto_update.py --config site.json --dry-run   # yalnız farkı göster
python3 scripts/auto_update.py --config site.json             # yaz, commit'le, gönder
```

Ya da yalnızca bazı alanları komut satırından değiştirin:

```bash
python3 scripts/auto_update.py --selector LIST_ITEM="div.film-card" --selector ITEM_TITLE="h2"
python3 scripts/auto_update.py --url https://site.example --home "/filmler/%d|Filmler"
```

Script şunları yapar:
1. `SiteConfig.kt` içindeki `MAIN_URL`, `NAME`, `LANG`, `SEARCH_PATH`, `HOME_SECTIONS`,
   `ALLOWED_EXTRA_HOSTS` ve `Selectors` altındaki her sabiti günceller. Seçici anahtarı
   `LIST_ITEM` ya da `listItem` yazılabilir; bilinmeyen anahtarda mevcut alanları listeleyip durur.
   Değerler Kotlin dizgesi olarak kaçırılır (`"`, `\`, `$`).
2. `build.gradle.kts` içinde `version` değerini 1 artırır, `iconUrl` alan adını ve `language`
   değerini eşitler. Hiçbir şey değişmiyorsa sürümü artırmaz.
3. Yalnızca bu iki dosyayı commit'ler ve bulunduğunuz dala gönderir. Çalışma alanında başka
   commit'lenmemiş değişiklik varsa durur (`--allow-dirty` ile geçilebilir); git hatasında durur.

Diğer seçenekler: `--check` (seçicileri canlı sayfada dener, `pip install beautifulsoup4`
gerekir; JavaScript ile oluşan sayfalarda sonuç vermez), `--no-bump`, `--no-commit`,
`--no-push`, `--plugin <dizin>` (birden çok eklenti varsa).

`site.json` kendi sitenize ait olduğu için depoya eklemeyin; `.gitignore` onu dışarıda tutar.

Birim testleri `SiteConfig`'e değil, testin içindeki sabit seçicilere bağlıdır. Böylece
seçicileri gerçek siteye göre değiştirmek CI'yı kırmaz. Gerçek sitenin sayfalarını da test
etmek isterseniz onları `fixtures/` altına kaydedip yeni bir test yazın.

### Uygulamanın güncellemeyi alması

Gönderimden sonra GitHub Actions derlemesi 1,5-2 dakika sürer ve yeni `.cs3` ile
`plugins.json`'ı `builds` dalına koyar. Cloudstream, `plugins.json` içindeki `version`
değeri kuruluyla karşılaştırarak güncellemeyi fark eder. Uygulama depoları açılışta denetler.
Eklenti ayarlarında otomatik güncelleme açıksa güncellemeyi kendisi kurar; değilse Eklentiler
ekranında eklentinin yanında güncelleme seçeneği görünür. (Ayarın adı ve varsayılanı uygulama
sürümüne göre değişebilir.)

Beklemeden denemek için: `./gradlew make` ile yerelde `.cs3` üretin, ya da cihaz USB'ye bağlıysa
`./gradlew CineDepo:deployWithAdb` ile doğrudan yükleyin.

## Sürümler

Derleme bu sürümlerle doğrulandı (GitHub Actions, `ubuntu-latest`):

| Bileşen | Sürüm | Nerede |
|---|---|---|
| Gradle | 8.11.1 | `gradle/wrapper/gradle-wrapper.properties` |
| Android Gradle Plugin | 8.7.3 | `build.gradle.kts` |
| Kotlin | 2.4.10 | `build.gradle.kts` |
| Java / JVM hedefi | JDK 17 ile derleme, hedef JVM 11 | `build.gradle.kts`, `build.yml` |
| Android SDK | `compileSdk`/`targetSdk` 35, `minSdk` 21 | `build.gradle.kts` |
| Cloudstream | `com.lagradost:cloudstream3:pre-release` + `recloudstream/gradle:-SNAPSHOT` (JitPack) | `build.gradle.kts` |
| NiceHttp | 0.4.11 | `build.gradle.kts` |
| Jsoup | 1.18.3 | `build.gradle.kts` |
| Jackson (`jackson-module-kotlin`) | 2.13.1 | `build.gradle.kts` |

Dikkat edilecekler:
- **Kotlin, Cloudstream kütüphanesinden eski olamaz.** `cloudstream3:pre-release` sabit bir sürüm
  değildir; şu anki hâli Kotlin 2.4 meta verisi ve JVM 11 bayt kodu taşır. Kotlin 2.1 / JVM 1.8 ile
  `Module was compiled with an incompatible version of Kotlin. The binary version of its metadata
  is 2.4.0` hatası ve onun ardından onlarca `Unresolved reference` görülür. Cloudstream ileride
  daha yeni bir Kotlin'e geçerse `kotlin-gradle-plugin` sürümünü ona göre yükseltin.
- **Jackson 2.13.1'de kalmalı.** Daha yeni sürümler eski Android sürümlerinde çalışmıyor.
- Kotlin 2.4, Gradle 8.11 için "Deprecated Gradle Version" uyarısı verir; derlemeyi durdurmaz.

## Derleme

Gerekenler: JDK 17, Android SDK (`ANDROID_HOME` ya da `local.properties` içinde `sdk.dir`),
JitPack erişimi.

```bash
git clone https://github.com/mtndlgc/cinedepo && cd cinedepo
./gradlew testDebugUnitTest                   # ayrıştırıcı testleri
./gradlew make makePluginsJson                # CineDepo/build/CineDepo.cs3 + build/plugins.json
./gradlew CineDepo:deployWithAdb              # USB ile bağlı cihaza (geliştirici modu) yükler
```

Not: Cloudstream eklenti dosyalarının uzantısı `.cs3`'tür.

## GitHub Actions

`.github/workflows/build.yml`:
1. `main`/`master` dalına gönderimde, PR açıldığında ya da elle çalışır; yalnız `.md` değiştiyse çalışmaz.
2. JDK 17 kurar. Android SDK için ayrı adım yoktur: `ubuntu-latest` SDK'yı `ANDROID_HOME` ile
   hazır getirir, eksik platformu AGP kendisi indirir. (`android-actions/setup-android@v3`
   artık bulunmayan `tools` paketini kurmaya çalışıp hata verdiği için kaldırıldı.)
3. Birim testlerini, ardından `make makePluginsJson` görevini çalıştırır.
4. `.cs3` dosyalarını, `plugins.json`'ı ve depo adına göre doldurulmuş `repo.json`'ı iş çıktısı
   olarak yükler.
5. `main`/`master` gönderimlerinde bunları `builds` dalına (ilk seferde yetim dal olarak oluşturur)
   tek commit hâlinde zorla gönderir. PR'larda yalnız derler.

Kullanılan action'lar: `actions/checkout@v5`, `actions/setup-java@v5`,
`gradle/actions/setup-gradle@v5`, `actions/upload-artifact@v5`.

Gerekli ayarlar:
- **Settings > Actions > General > Workflow permissions**: "Read and write".
- Depo **public** olmalı. Uygulama dosyaları `raw.githubusercontent.com` üzerinden kimlik
  doğrulaması olmadan indirir; özel depoda adresler 404 döner.

Uygulamada **Ayarlar > Eklentiler > Depo ekle** ile şu adresi girin:

```
https://raw.githubusercontent.com/mtndlgc/cinedepo/builds/repo.json
```

Uygulamanın güncellemeyi görmesi için her yayında eklentinin `version` değerini artırın.
