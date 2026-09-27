plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// app 網址由 GitHub Actions 傳入（https://<用戶名>.github.io/<repo>/）
val appUrl = (project.findProperty("appUrl") as String?) ?: "https://example.github.io/stock-app/"
val run = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

android {
    namespace = "hk.longtou.app"
    compileSdk = 34
    defaultConfig {
        applicationId = "hk.longtou.app"
        minSdk = 24
        targetSdk = 34
        versionCode = run
        versionName = "1.0.$run"
        buildConfigField("String", "APP_URL", "\"$appUrl\"")
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
