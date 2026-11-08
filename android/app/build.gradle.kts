plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.thompsonfabco.filamentkit"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.thompsonfabco.filamentkit"
        minSdk = 29
        targetSdk = 37
        // The update check compares this with the server's app/version.txt; tools/make_release.sh passes the same
        // FK_VERSION_CODE to this build and writes it to version.txt. Bump it for every app release (README).
        versionCode = System.getenv("FK_VERSION_CODE")?.takeIf { it.isNotBlank() }?.let {
            it.trim().toIntOrNull()?.takeIf { v -> v > 0 } ?: error("FK_VERSION_CODE must be a whole number above 0, got '$it'")
        } ?: 1
        versionName = "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        // Release signing comes from the environment only (tools/make_release.sh sets it up).
        val ksPath = System.getenv("FK_KEYSTORE")
        val ksPassword = System.getenv("FK_KEYSTORE_PASSWORD")
        if (!ksPath.isNullOrBlank() && !ksPassword.isNullOrBlank()) {
            create("release") {
                storeFile = file(ksPath)
                storePassword = ksPassword
                keyAlias = "filament-kit"
                keyPassword = ksPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
        unitTests.all {
            // Robolectric native graphics (Bitmap codecs) needs JDK internals on JDK 17+.
            it.jvmArgs("--add-exports=java.base/jdk.internal.access=ALL-UNNAMED")
        }
    }
}

// THIRD-PARTY.md and LICENSE live at the repository root; the APK gets copies as assets for the Licences screen.
abstract class CopyNotices : DefaultTask() {
    @get:InputFiles abstract val notices: ConfigurableFileCollection
    @get:OutputDirectory abstract val outputDir: DirectoryProperty
    @TaskAction fun copy() {
        val out = outputDir.get().asFile
        out.deleteRecursively()
        out.mkdirs()
        notices.files.forEach { it.copyTo(out.resolve(it.name)) }
    }
}

val copyNotices = tasks.register<CopyNotices>("copyNotices") {
    notices.from(rootProject.file("../THIRD-PARTY.md"), rootProject.file("../LICENSE"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(copyNotices, CopyNotices::outputDir)
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.exifinterface)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.viewmodel)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.zxing.cpp)
    implementation(libs.androidx.media3.exoplayer)
    implementation(libs.androidx.media3.exoplayer.hls)
    implementation(libs.androidx.media3.datasource.okhttp)
    implementation(libs.androidx.media3.ui)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.robolectric)
    testImplementation(libs.okhttp.tls)
    testImplementation(libs.okhttp.mockwebserver3)

    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    // Compose ui-test pulls an Espresso too old for API 37 (InputManager.getInstance is gone); pin a current one.
    androidTestImplementation(libs.androidx.test.espresso.core)
    androidTestImplementation(libs.okhttp.tls)
    androidTestImplementation(libs.okhttp.mockwebserver3)
    // Only for QrDecoderComparisonTest: ML Kit is the scanner zxing-cpp replaced, ZXing core draws the test QR
    // codes. Neither is in the APK.
    androidTestImplementation(libs.mlkit.barcode.scanning)
    androidTestImplementation(libs.zxing.core)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}
