// 顶层构建文件:只声明用到的插件版本,具体配置在 app/build.gradle.kts
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.1.10" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.10" apply false
    id("com.google.devtools.ksp") version "2.1.10-1.0.31" apply false
}
