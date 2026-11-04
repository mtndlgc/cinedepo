import com.android.build.gradle.BaseExtension
import com.lagradost.cloudstream3.gradle.CloudstreamExtension
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.jetbrains.kotlin.gradle.tasks.KotlinJvmCompile

buildscript {
    repositories {
        google()
        mavenCentral()
        // The Cloudstream gradle plugin and the Cloudstream stubs are served from JitPack.
        maven("https://jitpack.io")
    }
    dependencies {
        classpath("com.android.tools.build:gradle:8.7.3")
        // Builds .cs3 files and plugins.json (tasks: make, makePluginsJson, deployWithAdb).
        classpath("com.github.recloudstream:gradle:-SNAPSHOT")
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.10") // must read the metadata version of the cloudstream stubs
    }
}

allprojects {
    repositories {
        google()
        mavenCentral()
        maven("https://jitpack.io")
    }
}

fun Project.cloudstream(configuration: CloudstreamExtension.() -> Unit) =
    extensions.getByName<CloudstreamExtension>("cloudstream").configuration()

fun Project.android(configuration: BaseExtension.() -> Unit) =
    extensions.getByName<BaseExtension>("android").configuration()

subprojects {
    apply(plugin = "com.android.library")
    apply(plugin = "kotlin-android")
    apply(plugin = "com.lagradost.cloudstream3.gradle")

    cloudstream {
        // In GitHub Actions GITHUB_REPOSITORY is "owner/repo". The plugin uses it to
        // build the download URLs written into plugins.json (…/builds/<Name>.cs3).
        // TODO: replace the fallback with your own repository.
        setRepo(System.getenv("GITHUB_REPOSITORY") ?: "https://github.com/mtndlgc/cinedepo")
    }

    android {
        namespace = "com.example.${project.name.lowercase()}"

        defaultConfig {
            minSdk = 21
            compileSdkVersion(35)
            targetSdk = 35
        }

        compileOptions {
            sourceCompatibility = JavaVersion.VERSION_11
            targetCompatibility = JavaVersion.VERSION_11
        }
    }

    tasks.withType<KotlinJvmCompile>().configureEach {
        compilerOptions {
            jvmTarget.set(JvmTarget.JVM_11)
            freeCompilerArgs.addAll(
                "-Xno-call-assertions",
                "-Xno-param-assertions",
                "-Xno-receiver-assertions",
            )
        }
    }

    dependencies {
        val cloudstream by configurations
        val implementation by configurations
        val testImplementation by configurations

        // Stubs of the Cloudstream app (MainAPI, ExtractorLink, AppUtils, ...).
        // Provided by the app at runtime, so it is not bundled into the .cs3.
        cloudstream("com.lagradost:cloudstream3:pre-release")

        implementation(kotlin("stdlib"))
        implementation("com.github.Blatzar:NiceHttp:0.4.11") // `app.get(...)`
        implementation("org.jsoup:jsoup:1.18.3")
        // JSON (@JsonProperty, AppUtils.parseJson/tryParseJson). Keep at 2.13.1:
        // newer Jackson versions break on older Android versions.
        implementation("com.fasterxml.jackson.module:jackson-module-kotlin:2.13.1")

        testImplementation("junit:junit:4.13.2")
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
