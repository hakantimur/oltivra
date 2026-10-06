import java.util.Base64
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing: android/key.properties (never committed) with storeFile, storePassword, keyAlias, keyPassword.
val keystoreProperties = Properties().apply {
    val file = rootProject.file("key.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

// `--dart-define` values (Flutter passes them base64-encoded in the `dart-defines` property).
val dartDefines: Map<String, String> = (project.findProperty("dart-defines") as String?)
    ?.split(",")
    ?.mapNotNull { encoded ->
        val pair = String(Base64.getDecoder().decode(encoded)).split("=", limit = 2)
        if (pair.size == 2) pair[0] to pair[1] else null
    }
    ?.toMap()
    ?: emptyMap()

android {
    namespace = "com.noriloop.oltivra"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    buildFeatures {
        // Firebase config resources (google_app_id, ...) below.
        resValues = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Must match the Play Console package name.
        applicationId = "com.noriloop.oltivra"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // Real AdMob app ID: `-PadmobAppId=ca-app-pub-...~...` or `admobAppId=` in android/gradle.properties.
        manifestPlaceholders["admobAppId"] =
            (project.findProperty("admobAppId") as String?) ?: "ca-app-pub-3940256099942544~3347511713"
        // Firebase Analytics reads its config from Android resources at process start (Dart-side
        // `Firebase.initializeApp` comes too late for it), so real builds get the same values the Dart side uses.
        // The default app then starts natively with identical options, which `Firebase.initializeApp` accepts.
        val firebaseAppId = dartDefines["FIREBASE_APP_ID"]
        if (dartDefines["USE_EMULATORS"] == "false" && firebaseAppId != null) {
            resValue("string", "google_app_id", firebaseAppId)
            resValue("string", "google_api_key", dartDefines["FIREBASE_API_KEY"] ?: "")
            resValue("string", "gcm_defaultSenderId", dartDefines["FIREBASE_SENDER_ID"] ?: "")
            resValue("string", "project_id", dartDefines["FIREBASE_PROJECT_ID"] ?: "")
        }
    }

    signingConfigs {
        if (keystoreProperties.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            // Upload key from key.properties; falls back to debug keys so `flutter run --release` works locally.
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
