import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")  // Room 注解处理器
}

val localProps = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) {
        file.inputStream().use { load(it) }
    }
}

fun localProp(name: String): String =
    (localProps.getProperty(name) ?: "").replace("\\", "\\\\").replace("\"", "\\\"")

android {
    namespace = "com.example.remoteterminal"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.remoteterminal"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        buildConfigField("String", "NOUS_SERVER_URL", "\"${localProp("NOUS_SERVER_URL")}\"")
        buildConfigField("String", "NOUS_BRAIN_HOST", "\"${localProp("NOUS_BRAIN_HOST")}\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    // Compose BOM 统一管理 Compose 各库版本,下面引 Compose 库时不用写版本号
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")  // 更多图标(语音/编辑/删除等)
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    // Dispatchers.IO 等协程能力
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // WireGuard 隧道 —— 内嵌 VPN,不再需要外部 WireGuard App
    implementation("com.wireguard.android:tunnel:1.0.20230706")

    // Room 数据库 —— 手机端聊天记录本地持久化
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

}
