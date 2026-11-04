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
├── .github/workflows/build.yml  # .cs3 + plugins.json üretir, `builds` dalına yayınlar
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
            ├── kotlin/.../SiteParserTest.kt # JVM testi, ağ yok
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

1. `SiteConfig.kt` içindeki `TODO` alanlarını doldurun. Seçicileri tarayıcıda
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
