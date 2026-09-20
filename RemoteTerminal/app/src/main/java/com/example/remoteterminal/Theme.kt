package com.example.remoteterminal

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color


// iOS / Apple 风配色。浅色 = 分组背景灰 + 纯白卡片;深色 = 纯黑 + 深灰卡片。
// 关键:所有界面颜色都从 MaterialTheme.colorScheme 取,深色模式才能真正生效。


private val iOSBlue = Color(0xFF007AFF)
private val iOSBlueDark = Color(0xFF0A84FF)

private val LightColors = lightColorScheme(
    primary = iOSBlue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE5F0FF),
    onPrimaryContainer = Color(0xFF003063),
    secondary = Color(0xFF5856D6),          // iOS 紫
    background = Color(0xFFF2F2F7),          // iOS 分组背景
    onBackground = Color(0xFF1C1C1E),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF1C1C1E),
    surfaceVariant = Color(0xFFE9E9EB),      // 助手气泡灰
    onSurfaceVariant = Color(0xFF6C6C70),    // 次级文字
    outline = Color(0xFFD1D1D6),
    outlineVariant = Color(0xFFE5E5EA),
    error = Color(0xFFFF3B30),
)

private val DarkColors = darkColorScheme(
    primary = iOSBlueDark,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF0A3A66),
    onPrimaryContainer = Color(0xFFCDE2FF),
    secondary = Color(0xFF5E5CE6),
    background = Color(0xFF000000),          // iOS 纯黑
    onBackground = Color(0xFFFFFFFF),
    surface = Color(0xFF1C1C1E),             // 卡片/抽屉
    onSurface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFF2C2C2E),      // 助手气泡深灰
    onSurfaceVariant = Color(0xFFAEAEB2),
    outline = Color(0xFF38383A),
    outlineVariant = Color(0xFF2C2C2E),
    error = Color(0xFFFF453A),
)

@Composable
fun RemoteTerminalTheme(darkTheme: Boolean, content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content,
    )
}
