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
├── gradlew, gradle/wrapper/     # Gradle 8.11.1
├── repo.json                    # Uygulamaya eklenen depo bildirimi
├── plugins.example.json         # makePluginsJson çıktısının biçimi (örnek)
└── ExampleSiteProvider/
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
            ├── kotlin/.../SiteParserTest.kt # JVM testi, ağ yok
            └── resources/fixtures/*.html    # Örnek sayfalar

.github/workflows/build.yml         # .cs3 + plugins.json üretir, `builds` dalına yayınlar
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

1. `SiteConfig.kt` içindeki `TODO` alanlarını doldurun. Seçicileri tarayıcıda
   Geliştirici Araçları > Öğeler ile bulun (`document.querySelectorAll("...")` ile konsolda deneyin).
2. Hedef sitenin bir liste, film ve dizi sayfasını `src/test/resources/fixtures/` altına
   kaydedin, `SiteParserTest` beklentilerini güncelleyin.
3. Oynatıcı başka bir ana makinedeyse ve Cloudstream onu tanımıyorsa
   `ExampleEmbedExtractor`'ı uyarlayın (`mainUrl` = oynatıcının adresi).
4. `ExampleSiteProvider/build.gradle.kts` içinde `description`, `authors`, `language`,
   `tvTypes`, `iconUrl` alanlarını düzenleyin. Her yayında `version` değerini artırın.
5. Kök `build.gradle.kts` içindeki `setRepo(...)` yedeğini ve `repo.json` içindeki
   depo adresini kendi deponuza göre güncelleyin (şu an `mtndlgc/cinedepo`).

Yeni eklenti eklemek için `ExampleSiteProvider` dizinini kopyalayıp adını ve paketini
değiştirmeniz yeterli; `settings.gradle.kts` onu kendiliğinden ekler.

## Derleme

Gerekenler: JDK 17, Android SDK (`ANDROID_HOME` veya `local.properties` içinde `sdk.dir`),
JitPack erişimi.

```bash
cd cinedepo
./gradlew testDebugUnitTest            # ayrıştırıcı testleri
./gradlew make makePluginsJson         # ExampleSiteProvider/build/ExampleSiteProvider.cs3 + build/plugins.json
./gradlew ExampleSiteProvider:deployWithAdb   # USB ile bağlı cihaza (geliştirici modu) yükler
```

Not: Cloudstream eklenti dosyalarının uzantısı `.cs3`'tür.

## GitHub Actions

`.github/workflows/build.yml`:
1. main/master dalına gönderimde, PR açıldığında (veya elle) çalışır.
2. JDK 17 + Android SDK kurar, birim testlerini ve `make makePluginsJson` görevini çalıştırır.
3. `.cs3` dosyalarını, `plugins.json`'ı ve depo adına göre doldurulmuş `repo.json`'ı
   iş çıktısı olarak yükler.
4. `main`/`master` gönderimlerinde bunları `builds` dalına (ilk seferde yetim dal olarak
   oluşturur) tek commit halinde zorla gönderir. PR'larda yalnız derler.

Depo ayarlarında **Settings > Actions > General > Workflow permissions** "Read and write"
olmalıdır. Ardından uygulamada **Ayarlar > Eklentiler > Depo ekle** ile şu adresi girin:

```
https://raw.githubusercontent.com/<kullanıcı>/<depo>/builds/repo.json
```
