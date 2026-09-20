package com.example.remoteterminal

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.content.Intent
import androidx.core.content.ContextCompat
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : ComponentActivity() {
    companion object {
        // App 是否在前台:唤醒服务据此决定是否需要"拉起"界面(前台则无需,直接走 wakeEvents)
        @Volatile var isForeground = false
    }

    override fun onResume() { super.onResume(); isForeground = true }
    override fun onPause() { super.onPause(); isForeground = false }

    // 录音权限请求:在 onCreate 之前注册(Activity Result API 要求)
    private val audioPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            startWakeService()
        }
    }

    private fun startWakeService() {
        val wakeIntent = Intent(this, WakeWordService::class.java).apply { action = "start" }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(wakeIntent)
        } else {
            startService(wakeIntent)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 被语音唤醒拉起时(息屏/锁屏):点亮屏幕并显示在锁屏之上
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true); setTurnScreenOn(true)
        }
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        Config.load(this)         // 从 SharedPreferences 加载配置
        TunnelManager.init(this)  // 初始化 WireGuard backend
        I18n.init(this)           // 初始化多语言
        // Android 12+ 保活:启动前台服务防止进程被杀
        if (Config.isConfigured() && !KeepAliveService.isRunning) {
            startForegroundService(Intent(this, KeepAliveService::class.java))
        }
        // 语音唤醒:仅在用户开启总开关时才后台监听(默认关 → 不监听、不消耗)
        // 先检查录音权限,未授权则请求后再启动
        if (Config.isConfigured() && Prefs(this).voiceWakeEnabled) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED) {
                startWakeService()
            } else {
                audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
            }
        }
        setContent { AppRoot() }
        // WG 异步后台连接,不阻塞 UI 渲染
        lifecycleScope.launch(Dispatchers.IO) {
            autoConnectWg()
        }
    }

    private fun autoConnectWg() {
        val f = TunnelManager.loadFields(this)
        if (f.privateKey.isBlank() || f.peerPublicKey.isBlank()) return
        val intent = TunnelManager.prepareVpn(this)
        if (intent != null) {
            startActivityForResult(intent, 1001)
        } else {
            // Android 12+ 不允许后台启动前台服务,用 lifecycleScope 等 RESUME 后再连
            lifecycleScope.launch {
                lifecycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.RESUMED) {
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                        TunnelManager.connect(this@MainActivity)
                    }
                    return@repeatOnLifecycle // 只执行一次
                }
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 1001 && resultCode == android.app.Activity.RESULT_OK) {
            lifecycleScope.launch {
                lifecycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.RESUMED) {
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                        TunnelManager.connect(this@MainActivity)
                    }
                    return@repeatOnLifecycle
                }
            }
        }
    }
}

data class ChatMessage(val role: String, val content: String, val steps: String = "")

// Prefs
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    var model: String
        get() = sp.getString("model", Config.DEFAULT_MODEL) ?: Config.DEFAULT_MODEL
        set(v) { sp.edit().putString("model", v).apply() }
    var sessionId: String
        get() {
            var id = sp.getString("session_id", null)
            if (id == null) { id = java.util.UUID.randomUUID().toString(); sp.edit().putString("session_id", id).apply() }
            return id
        }
        set(v) { sp.edit().putString("session_id", v).apply() }
    fun newSession(): String { val id = java.util.UUID.randomUUID().toString(); sessionId = id; return id }
    // 深色模式:-1=跟随系统, 0=浅色, 1=深色
    var darkModePref: Int
        get() = sp.getInt("dark_mode_pref", -1)
        set(v) { sp.edit().putInt("dark_mode_pref", v).apply() }
    var fontSize: Int
        get() = sp.getInt("font_size", 15)
        set(v) { sp.edit().putInt("font_size", v).apply() }
    // 简洁模式(手表):只保留指挥模式,隐藏终端/代码,聚焦学习对话
    var simpleMode: Boolean
        get() = sp.getBoolean("simple_mode", false)
        set(v) { sp.edit().putBoolean("simple_mode", v).apply() }
    // 语音唤醒总开关(默认关:不开就完全不监听、不消耗)
    var voiceWakeEnabled: Boolean
        get() = sp.getBoolean("voice_wake_enabled", false)
        set(v) { sp.edit().putBoolean("voice_wake_enabled", v).apply() }
}

// 模型供应商
data class ModelProvider(val name: String, val models: List<String>, val defaultModel: String, val apiUrl: String)
val MODEL_PROVIDERS = listOf(
    ModelProvider("DeepSeek", listOf("deepseek-chat", "deepseek-reasoner"), "deepseek-chat", "https://api.deepseek.com/chat/completions"),
    ModelProvider("OpenAI", listOf("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o4-mini"), "gpt-4o", "https://api.openai.com/v1/chat/completions"),
    ModelProvider("Claude", listOf("claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5"), "claude-sonnet-4-6", "https://api.anthropic.com/v1/messages"),
    ModelProvider("Google", listOf("gemini-2.5-pro", "gemini-2.5-flash"), "gemini-2.5-pro", "https://generativelanguage.googleapis.com/v1beta/models/"),
    ModelProvider("智谱GLM", listOf("glm-4-plus", "glm-4-flash"), "glm-4-plus", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
    ModelProvider("Moonshot", listOf("moonshot-v1-8k", "moonshot-v1-32k"), "moonshot-v1-8k", "https://api.moonshot.cn/v1/chat/completions"),
)

// Drawer tabs
enum class DrawerTab { NEW_CHAT, CODE, STUDY, DOCS, DEVICES, RECENTS, SETTINGS }

@Composable
fun AppRoot() {
    val context = LocalContext.current
    val prefs = remember { Prefs(context) }
    val db = remember { AppDatabase.getInstance(context) }
    var model by remember { mutableStateOf(prefs.model) }

    // 深色模式:跟随系统(-1)/浅(0)/深(1)
    val systemDark = androidx.compose.foundation.isSystemInDarkTheme()
    var darkPref by remember { mutableStateOf(prefs.darkModePref) }
    val darkMode = when (darkPref) { 0 -> false; 1 -> true; else -> systemDark }

    var currentTab by remember { mutableStateOf(DrawerTab.NEW_CHAT) }
    var chatKey by remember { mutableStateOf(0) }   // 每次"新建/切换会话"+1,强制 ChatScreen 重建
    var initialChatMode by remember { mutableStateOf<ChatMode?>(null) }  // 进入聊天时的初始模式(如学习提问)
    var railExpanded by remember { mutableStateOf(false) }  // 左侧导航栏:收起=只图标,展开=图标+名称
    val scope = rememberCoroutineScope()

    // 请求通知权限(Android 13+),用于学习提醒
    val notifLauncher = rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    fun openChat(newSession: Boolean, tab: DrawerTab) {
        if (newSession) prefs.newSession()
        initialChatMode = null  // 普通进入聊天清除学习模式预设
        currentTab = tab
        chatKey++
        railExpanded = false
    }

    RemoteTerminalTheme(darkTheme = darkMode) {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
          // 菜单宽度动画:收起 56dp(只图标)→ 展开 180dp(图标+文字),内容被向右挤窄。
          // 用弹簧(无回弹)→ 跟手、收尾自然;配合内容固定测量缓存,推拉顺滑。
          val railWidth by animateDpAsState(
              targetValue = if (railExpanded) 180.dp else 56.dp,
              animationSpec = androidx.compose.animation.core.spring(
                  dampingRatio = 1f,
                  stiffness = androidx.compose.animation.core.Spring.StiffnessMediumLow,
              ),
              label = "railWidth",
          )
          Box(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxSize()) {
                // 左侧导航栏:宽度随展开延伸,内容随之让位
                NousRail(
                    expanded = railExpanded,
                    width = railWidth,
                    current = currentTab,
                    onToggle = { railExpanded = !railExpanded },
                    onNew = { openChat(true, DrawerTab.NEW_CHAT) },
                    onSelect = { tab -> currentTab = tab; railExpanded = false },
                )
                Box(modifier = Modifier.weight(1f).fillMaxHeight()) {
                    when (currentTab) {
                    DrawerTab.NEW_CHAT, DrawerTab.CODE -> key(chatKey) {
                        ChatScreen(
                            prefs = prefs, db = db, model = model,
                            codeMode = currentTab == DrawerTab.CODE,
                            initialMode = initialChatMode,
                            onOpenDrawer = { railExpanded = !railExpanded },
                            onNavigateToSettings = { currentTab = DrawerTab.SETTINGS },
                        )
                    }
                    DrawerTab.STUDY -> {
                        var studySub by remember { mutableStateOf(0) } // 0=面板 1=课表 2=规划 3=导图
                        var pendingMessage by remember { mutableStateOf("") }
                        val goChat: (String) -> Unit = { msg ->
                            pendingMessage = msg
                            currentTab = DrawerTab.NEW_CHAT
                            chatKey++
                        }
                        when (studySub) {
                            1 -> TimetableView(onBack = { studySub = 0 })
                            2 -> StudyPlanScreen(onBack = { studySub = 0 }, onOpenChat = goChat)
                            3 -> MindMapScreen(onBack = { studySub = 0 }, onOpenChat = goChat)
                            else -> StudyDashboard(
                                prefs = prefs,
                                onNavigateBack = { currentTab = DrawerTab.NEW_CHAT },
                                onOpenChat = goChat,
                                onOpenTimetable = { studySub = 1 },
                                onOpenPlan = { studySub = 2 },
                                onOpenMindMap = { studySub = 3 },
                            )
                        }
                        // 从学习区跳转到聊天时带上预填消息
                        LaunchedEffect(chatKey, pendingMessage) {
                            if (pendingMessage.isNotBlank() && currentTab == DrawerTab.NEW_CHAT) {
                                // 消息通过 ChatScreen 的 initialMode 传入
                                pendingMessage = ""
                            }
                        }
                    }
                    DrawerTab.DOCS -> DocsScreen(onBack = { currentTab = DrawerTab.NEW_CHAT })
                    DrawerTab.DEVICES -> DevicesScreen(onBack = { currentTab = DrawerTab.NEW_CHAT })
                    DrawerTab.RECENTS -> SessionsScreen(
                        prefs = prefs, db = db,
                        onSelectSession = { currentTab = DrawerTab.NEW_CHAT; chatKey++ },
                        onBack = { currentTab = DrawerTab.NEW_CHAT },
                    )
                    DrawerTab.SETTINGS -> SettingsScreenFull(
                        prefs = prefs, model = model, darkPref = darkPref,
                        onModelChange = { model = it; prefs.model = it },
                        onDarkPrefChange = { darkPref = it; prefs.darkModePref = it },
                        onBack = { currentTab = DrawerTab.NEW_CHAT },
                    )
                    }   // end when
                    // 菜单展开时,点内容区即可关闭(只覆盖内容,无涟漪)
                    if (railExpanded) {
                        Box(Modifier.fillMaxSize().clickable(
                            indication = null,
                            interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                        ) { railExpanded = false })
                    }
                }       // end Box(content)
            }           // end Row
          }             // end Box(root)
        }               // end Surface
    }                   // end RemoteTerminalTheme
}                       // end AppRoot

// 左侧常驻导航栏(Linux 风:收起=图标,点菜单键向右展开显示名称)
@Composable
fun NousRail(
    expanded: Boolean,
    width: androidx.compose.ui.unit.Dp,
    current: DrawerTab,
    onToggle: () -> Unit,
    onNew: () -> Unit,
    onSelect: (DrawerTab) -> Unit,
) {
    val cs = MaterialTheme.colorScheme
    data class NavItem(val tab: DrawerTab?, val icon: ImageVector, val label: String, val action: () -> Unit)
    val items = listOf(
        NavItem(DrawerTab.NEW_CHAT, Icons.Filled.Add, "新对话", onNew),
        NavItem(DrawerTab.STUDY, Icons.Filled.School, "学习") { onSelect(DrawerTab.STUDY) },
        NavItem(DrawerTab.DOCS, Icons.Filled.Folder, "资料") { onSelect(DrawerTab.DOCS) },
        NavItem(DrawerTab.DEVICES, Icons.Filled.Devices, "设备") { onSelect(DrawerTab.DEVICES) },
        NavItem(DrawerTab.RECENTS, Icons.Filled.History, "最近") { onSelect(DrawerTab.RECENTS) },
        NavItem(DrawerTab.SETTINGS, Icons.Filled.Settings, "设置") { onSelect(DrawerTab.SETTINGS) },
    )
    Column(
        modifier = Modifier.width(width).fillMaxHeight()
            .background(cs.surface)
            .padding(vertical = 8.dp),
        horizontalAlignment = Alignment.Start,   // 始终左对齐 → 图标位置固定不跳
    ) {
        // 顶部菜单键:展开/收起(固定左侧,与下方图标同一列)
        IconButton(onClick = onToggle) {
            Icon(Icons.Filled.Menu, "菜单", tint = cs.onSurface)
        }
        Spacer(Modifier.height(8.dp))
        items.forEach { it2 ->
            val selected = it2.tab != null && it2.tab == current
            val fg = if (selected) cs.primary else cs.onSurfaceVariant
            val bg = if (selected) cs.primary.copy(alpha = 0.12f) else androidx.compose.ui.graphics.Color.Transparent
            Row(
                modifier = Modifier.fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 3.dp)
                    .clip(RoundedCornerShape(12.dp)).background(bg)
                    .clickable(onClick = it2.action)
                    .padding(vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Start,  // 图标恒定靠左,不居中
            ) {
                Spacer(Modifier.width(8.dp))
                Icon(it2.icon, it2.label, tint = fg, modifier = Modifier.size(22.dp))
                if (width > 110.dp) {
                    Spacer(Modifier.width(14.dp))
                    Text(it2.label, style = MaterialTheme.typography.bodyLarge, color = fg, maxLines = 1, softWrap = false)
                }
            }
        }
    }
}

// 展开菜单浮层(覆盖在内容上,不挤压内容)
@Composable
fun NousRailExpanded(current: DrawerTab, onNew: () -> Unit, onSelect: (DrawerTab) -> Unit) {
    val cs = MaterialTheme.colorScheme
    data class NavItem(val tab: DrawerTab?, val icon: ImageVector, val label: String, val action: () -> Unit)
    val items = listOf(
        NavItem(DrawerTab.NEW_CHAT, Icons.Filled.Add, "新对话", onNew),
        NavItem(DrawerTab.STUDY, Icons.Filled.School, "学习") { onSelect(DrawerTab.STUDY) },
        NavItem(DrawerTab.DOCS, Icons.Filled.Folder, "资料") { onSelect(DrawerTab.DOCS) },
        NavItem(DrawerTab.DEVICES, Icons.Filled.Devices, "设备") { onSelect(DrawerTab.DEVICES) },
        NavItem(DrawerTab.RECENTS, Icons.Filled.History, "最近") { onSelect(DrawerTab.RECENTS) },
        NavItem(DrawerTab.SETTINGS, Icons.Filled.Settings, "设置") { onSelect(DrawerTab.SETTINGS) },
    )
    Column(
        modifier = Modifier.width(180.dp).fillMaxHeight().background(cs.surface)
            .clickable(enabled = false) {}  // 吃掉点击,避免点面板关闭
            .padding(vertical = 8.dp),
    ) {
        Spacer(Modifier.height(8.dp))
        Text("Nous", style = MaterialTheme.typography.titleMedium, color = cs.onSurface,
            modifier = Modifier.padding(start = 20.dp, bottom = 8.dp))
        items.forEach { it2 ->
            val selected = it2.tab != null && it2.tab == current
            val fg = if (selected) cs.primary else cs.onSurface
            val bg = if (selected) cs.primary.copy(alpha = 0.12f) else androidx.compose.ui.graphics.Color.Transparent
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 3.dp)
                    .clip(RoundedCornerShape(12.dp)).background(bg)
                    .clickable(onClick = it2.action).padding(horizontal = 12.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(it2.icon, it2.label, tint = fg, modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(14.dp))
                Text(it2.label, style = MaterialTheme.typography.bodyLarge, color = fg)
            }
        }
    }
}

// 抽屉:主导航项(Apple 风:圆角胶囊,选中淡色底)
@Composable
fun DrawerNavItem(label: String, icon: ImageVector, selected: Boolean, onClick: () -> Unit) {
    val bg = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f) else androidx.compose.ui.graphics.Color.Transparent
    val fg = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 3.dp)
            .clip(RoundedCornerShape(12.dp)).background(bg).clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = label, tint = fg, modifier = Modifier.size(22.dp))
        Spacer(Modifier.width(14.dp))
        Text(label, style = MaterialTheme.typography.bodyLarge, color = fg)
    }
}

// 抽屉:最近对话项
@Composable
fun DrawerRecentItem(title: String, subtitle: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)
            .padding(start = 24.dp, end = 16.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.AutoMirrored.Filled.Chat, null, modifier = Modifier.size(16.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(12.dp))
        Column {
            Text(title.take(28), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface, maxLines = 1)
            Text(subtitle, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

// 可折叠分组
@Composable
fun CollapsibleSection(title: String, initiallyExpanded: Boolean = false, content: @Composable () -> Unit) {
    var expanded by remember { mutableStateOf(initiallyExpanded) }
    Column {
        Row(
            modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(title, style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.weight(1f))
            Icon(
                if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                contentDescription = if (expanded) "收起" else "展开",
                modifier = Modifier.size(20.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        AnimatedVisibility(
            visible = expanded,
            enter = expandVertically(),
            exit = shrinkVertically(),
        ) {
            Column(modifier = Modifier.padding(bottom = 8.dp)) { content() }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

// 完整设置页(分组折叠)
@Composable
fun SettingsScreenFull(
    prefs: Prefs, model: String, darkPref: Int,
    onModelChange: (String) -> Unit, onDarkPrefChange: (Int) -> Unit, onBack: () -> Unit,
) {
    val ctx = LocalContext.current
    val muted = MaterialTheme.colorScheme.onSurfaceVariant

    // 外观
    var fontSize by remember { mutableStateOf(prefs.fontSize) }

    // 语言
    var language by remember { mutableStateOf(I18n.current()) }

    // API Keys
    var apiKeys by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var selectedProvider by remember { mutableStateOf("DeepSeek") }
    LaunchedEffect(Unit) {
        val sp = ctx.getSharedPreferences("api_keys", Context.MODE_PRIVATE)
        apiKeys = MODEL_PROVIDERS.associate { it.name to (sp.getString(it.name, "") ?: "") }
    }
    fun saveApiKey(provider: String, key: String) {
        ctx.getSharedPreferences("api_keys", Context.MODE_PRIVATE).edit().putString(provider, key).apply()
        apiKeys = apiKeys + (provider to key)
    }

    // 用量
    var usageJson by remember { mutableStateOf("") }
    var usageLoading by remember { mutableStateOf(false) }

    // 高级设置
    var safetyMode by remember { mutableStateOf(Config.SAFETY_MODE) }
    var maxSteps by remember { mutableStateOf(Config.BRAIN_MAX_STEPS.toString()) }
    var stepWarning by remember { mutableStateOf(Config.BRAIN_STEP_WARNING.toString()) }
    var idleLimit by remember { mutableStateOf(Config.BRAIN_IDLE_LIMIT.toString()) }
    var cmdTimeout by remember { mutableStateOf(Config.COMMAND_TIMEOUT.toString()) }
    var rateLimit by remember { mutableStateOf(Config.RATE_LIMIT_PER_MINUTE.toString()) }
    var advancedMsg by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        // 从 Brain 拉取高级配置
        try {
            kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                val url = java.net.URL("http://${Config.HOST}:${Config.BRAIN_PORT}/config?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "GET"; conn.connectTimeout = 8000; conn.readTimeout = 8000
                if (conn.responseCode == 200) {
                    val text = conn.inputStream.bufferedReader().use { it.readText() }
                    val cfg = JSONObject(text).optJSONObject("config") ?: JSONObject()
                    val map = mutableMapOf<String, Any>()
                    cfg.keys().forEach { map[it] = cfg.get(it) }
                    Config.loadAdvancedFromConfig(map)
                }
                conn.disconnect()
            }
        } catch (_: Exception) {}
        safetyMode = Config.SAFETY_MODE
        maxSteps = Config.BRAIN_MAX_STEPS.toString()
        stepWarning = Config.BRAIN_STEP_WARNING.toString()
        idleLimit = Config.BRAIN_IDLE_LIMIT.toString()
        cmdTimeout = Config.COMMAND_TIMEOUT.toString()
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("设置", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onBack) { Text("完成") }
        }

        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(0.dp)) {
            // 外观
            item {
                CollapsibleSection(I18n.t("appearance"), initiallyExpanded = true) {
                    Spacer(Modifier.height(4.dp))
                    Text(I18n.t("theme"), style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(I18n.t("follow_system") to -1, I18n.t("light") to 0, I18n.t("dark") to 1).forEach { (lbl, v) ->
                            FilterChip(selected = darkPref == v, onClick = { onDarkPrefChange(v) }, label = { Text(lbl) })
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Text("${I18n.t("font_size")}: ${fontSize}sp", color = muted)
                    Slider(value = fontSize.toFloat(), onValueChange = { fontSize = it.toInt(); prefs.fontSize = fontSize },
                        valueRange = 12f..20f, steps = 7)
                    Spacer(Modifier.height(8.dp))
                    // 简洁模式(手表):只留指挥模式
                    var simpleMode by remember { mutableStateOf(prefs.simpleMode) }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("简洁模式（手表）", style = MaterialTheme.typography.bodyMedium)
                            Text("只保留指挥模式，隐藏终端/代码，适合小屏", fontSize = 11.sp, color = muted)
                        }
                        Switch(checked = simpleMode, onCheckedChange = { simpleMode = it; prefs.simpleMode = it })
                    }
                    Spacer(Modifier.height(8.dp))
                    // 语音唤醒总开关
                    var voiceWake by remember { mutableStateOf(prefs.voiceWakeEnabled) }
                    val audioPermLauncher = rememberLauncherForActivityResult(
                        ActivityResultContracts.RequestPermission()
                    ) { granted ->
                        if (granted) {
                            voiceWake = true; prefs.voiceWakeEnabled = true
                            ctx.startService(Intent(ctx, WakeWordService::class.java).apply { action = "start" })
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("语音唤醒（说 Nous）", style = MaterialTheme.typography.bodyMedium)
                            Text("开启后像 Siri:听到「Nous」即唤醒。关闭则完全不监听、不消耗", fontSize = 11.sp, color = muted)
                        }
                        Switch(checked = voiceWake, onCheckedChange = { enable ->
                            if (enable) {
                                // 开启前检查录音权限,未授权则先请求
                                if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO)
                                    == PackageManager.PERMISSION_GRANTED) {
                                    voiceWake = true; prefs.voiceWakeEnabled = true
                                    ctx.startService(Intent(ctx, WakeWordService::class.java).apply { action = "start" })
                                } else {
                                    prefs.voiceWakeEnabled = true  // 先存意愿,权限授予后生效
                                    audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                }
                            } else {
                                voiceWake = false; prefs.voiceWakeEnabled = false
                                ctx.startService(Intent(ctx, WakeWordService::class.java).apply { action = "stop" })
                            }
                        })
                    }
                }
            }

            // 通用
            item {
                CollapsibleSection(I18n.t("general")) {
                    Spacer(Modifier.height(4.dp))
                    Text(I18n.t("language"), style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(I18n.t("chinese") to "zh", I18n.t("english") to "en").forEach { (lbl, v) ->
                            FilterChip(selected = language == v, onClick = {
                                language = v
                                I18n.setLanguage(ctx, v)
                            }, label = { Text(lbl) })
                        }
                    }
                }
            }

            // 连接配置
            item {
                CollapsibleSection(I18n.t("connection")) {
                    ConnectionSettingsSection(prefs)
                }
            }

            // WireGuard 隧道
            item {
                CollapsibleSection(I18n.t("wireguard")) {
                    WireGuardSettingsSection()
                }
            }

            // 设备身份
            item {
                CollapsibleSection("设备身份") {
                    var clientName by remember { mutableStateOf("") }
                    var clientId by remember { mutableStateOf("") }
                    var tokenSuffix by remember { mutableStateOf("") }
                    var whoamiLoading by remember { mutableStateOf(true) }
                    var whoamiError by remember { mutableStateOf("") }
                    LaunchedEffect(Unit) {
                        withContext(Dispatchers.IO) {
                            try {
                                val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/whoami?token=${
                                    java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                                val conn = url.openConnection() as HttpURLConnection
                                conn.requestMethod = "GET"; conn.connectTimeout = 8000; conn.readTimeout = 8000
                                if (conn.responseCode == 200) {
                                    val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                                    clientName = json.optString("name", "")
                                    clientId = json.optString("client_id", "")
                                    tokenSuffix = json.optString("token_suffix", "")
                                } else { whoamiError = "HTTP ${conn.responseCode}" }
                                conn.disconnect()
                            } catch (e: Exception) { whoamiError = e.message ?: "" }
                        }
                        whoamiLoading = false
                    }
                    Spacer(Modifier.height(4.dp))
                    if (whoamiLoading) Text("加载中...", style = MaterialTheme.typography.bodySmall)
                    else if (whoamiError.isNotBlank()) Text(whoamiError, color = MaterialTheme.colorScheme.error)
                    else if (clientId.isNotEmpty()) {
                        if (clientName.isNotEmpty()) Text("名称: $clientName", style = MaterialTheme.typography.bodyMedium)
                        Text("设备ID: $clientId", style = MaterialTheme.typography.bodySmall)
                        if (tokenSuffix.isNotEmpty()) Text("Token: ***$tokenSuffix", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            // API 配置
            item {
                CollapsibleSection(I18n.t("api_config")) {
                    var showProviderPicker by remember { mutableStateOf(false) }
                    var showModelPicker by remember { mutableStateOf(false) }
                    var showOtherKeys by remember { mutableStateOf(false) }

                    Spacer(Modifier.height(4.dp))
                    // 提供商
                    OutlinedButton(onClick = { showProviderPicker = true }, modifier = Modifier.fillMaxWidth()) {
                        Text("${I18n.t("provider")}: $selectedProvider")
                    }
                    DropdownMenu(expanded = showProviderPicker, onDismissRequest = { showProviderPicker = false }) {
                        MODEL_PROVIDERS.forEach { p ->
                            DropdownMenuItem(text = { Text(p.name) }, onClick = {
                                selectedProvider = p.name; showProviderPicker = false; onModelChange(p.defaultModel)
                            })
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                    // 模型
                    val provider = MODEL_PROVIDERS.find { it.name == selectedProvider } ?: MODEL_PROVIDERS[0]
                    OutlinedButton(onClick = { showModelPicker = true }, modifier = Modifier.fillMaxWidth()) {
                        Text("${I18n.t("model")}: $model")
                    }
                    DropdownMenu(expanded = showModelPicker, onDismissRequest = { showModelPicker = false }) {
                        provider.models.forEach { m ->
                            DropdownMenuItem(text = { Text(m) }, onClick = { onModelChange(m); showModelPicker = false })
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    // API Key
                    val currentKey = apiKeys[selectedProvider] ?: ""
                    var showKey by remember { mutableStateOf(false) }
                    OutlinedTextField(
                        value = currentKey, onValueChange = { saveApiKey(selectedProvider, it) },
                        label = { Text(I18n.t("api_key")) },
                        visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                        trailingIcon = {
                            IconButton(onClick = { showKey = !showKey }) {
                                Icon(if (showKey) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, if (showKey) "隐藏" else "显示")
                            }
                        },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                    )
                    Spacer(Modifier.height(6.dp))
                    // API URL(切换提供商时自动填该商的默认地址)
                    var apiUrl by remember(selectedProvider) { mutableStateOf(provider.apiUrl) }
                    OutlinedTextField(
                        value = apiUrl, onValueChange = { apiUrl = it },
                        label = { Text(I18n.t("api_url")) },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                    )
                    Spacer(Modifier.height(8.dp))
                    // 应用此模型到大脑:把 URL/Key/Model 推到 brain,一键切换 DeepSeek/Claude/智谱
                    var applyMsg by remember { mutableStateOf("") }
                    Button(onClick = {
                        applyMsg = "切换中..."
                        Config.pushToBrain(mapOf(
                            "LLM_API_URL" to apiUrl.trim(),
                            "LLM_API_KEY" to (apiKeys[selectedProvider] ?: "").trim(),
                            "LLM_MODEL" to model,
                        )) { ok, msg ->
                            applyMsg = if (ok) "已切换到 $selectedProvider · $model" else "切换失败: $msg"
                        }
                    }, modifier = Modifier.fillMaxWidth()) { Text("应用此模型到大脑") }
                    if (applyMsg.isNotBlank()) {
                        Text(applyMsg, style = MaterialTheme.typography.bodySmall,
                            color = if (applyMsg.contains("已切换")) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(top = 4.dp))
                    }
                    Spacer(Modifier.height(8.dp))
                    // 其他 Key
                    TextButton(onClick = { showOtherKeys = !showOtherKeys }) {
                        Text(I18n.t(if (showOtherKeys) "collapse_other" else "expand_other"))
                    }
                    if (showOtherKeys) {
                        MODEL_PROVIDERS.filter { it.name != selectedProvider }.forEach { p ->
                            val k = apiKeys[p.name] ?: ""
                            var showK by remember { mutableStateOf(false) }
                            OutlinedTextField(
                                value = k, onValueChange = { saveApiKey(p.name, it) },
                                label = { Text("${p.name} API Key") },
                                visualTransformation = if (showK) VisualTransformation.None else PasswordVisualTransformation(),
                                trailingIcon = {
                                    IconButton(onClick = { showK = !showK }) {
                                        Icon(if (showK) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, "show")
                                    }
                                },
                                modifier = Modifier.fillMaxWidth().padding(top = 4.dp), singleLine = true,
                            )
                        }
                    }
                }
            }

            // API 用量
            item {
                CollapsibleSection(I18n.t("api_usage")) {
                    Spacer(Modifier.height(4.dp))
                    var showUsage by remember { mutableStateOf(false) }
                    var usageTotalCalls by remember { mutableStateOf(0) }
                    var usageTotalTokens by remember { mutableStateOf(0L) }
                    var usageToday by remember { mutableStateOf(0L) }
                    var usageMonth by remember { mutableStateOf(0L) }
                    var usageErr by remember { mutableStateOf("") }

                    Button(onClick = {
                        usageLoading = true; usageErr = ""
                        Config.fetchUsage { ok, resp ->
                            usageLoading = false
                            if (ok) {
                                try {
                                    val json = JSONObject(resp).optJSONObject("usage") ?: JSONObject()
                                    usageTotalCalls = json.optInt("total_calls", 0)
                                    usageTotalTokens = json.optLong("total_tokens", 0)
                                    val daily = json.optJSONObject("daily") ?: JSONObject()
                                    val monthly = json.optJSONObject("monthly") ?: JSONObject()
                                    val today = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.getDefault()).format(java.util.Date())
                                    val month = java.text.SimpleDateFormat("yyyy-MM", java.util.Locale.getDefault()).format(java.util.Date())
                                    usageToday = daily.optLong(today, 0)
                                    usageMonth = monthly.optLong(month, 0)
                                    showUsage = true
                                } catch (_: Exception) { usageErr = "解析失败" }
                            } else { usageErr = resp }
                        }
                    }, enabled = !usageLoading) {
                        Text(if (usageLoading) I18n.t("loading") else I18n.t("test"))
                    }

                    if (usageErr.isNotBlank()) {
                        Text(usageErr, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }

                    if (showUsage) {
                        Spacer(Modifier.height(8.dp))
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                            StatCard(I18n.t("total_calls"), usageTotalCalls.toString(), Modifier.weight(1f))
                            StatCard(I18n.t("total_tokens"), formatNumber(usageTotalTokens), Modifier.weight(1f))
                        }
                        Spacer(Modifier.height(6.dp))
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                            StatCard(I18n.t("today_tokens"), formatNumber(usageToday), Modifier.weight(1f))
                            StatCard(I18n.t("month_tokens"), formatNumber(usageMonth), Modifier.weight(1f))
                        }
                    }
                }
            }

            // 高级设置
            item {
                var showAdvanced by remember { mutableStateOf(false) }
                CollapsibleSection(I18n.t("advanced")) {
                    Spacer(Modifier.height(4.dp))

                    // 安全模式
                    Text(I18n.t("safety_mode"), style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.height(4.dp))
                    var showSafetyPicker by remember { mutableStateOf(false) }
                    val safetyLabels = mapOf("normal" to I18n.t("safety_normal"), "strict" to I18n.t("safety_strict"), "off" to I18n.t("safety_off"))
                    OutlinedButton(onClick = { showSafetyPicker = true }, modifier = Modifier.fillMaxWidth()) {
                        Text(safetyLabels[safetyMode] ?: safetyMode)
                    }
                    DropdownMenu(expanded = showSafetyPicker, onDismissRequest = { showSafetyPicker = false }) {
                        listOf("normal", "strict", "off").forEach { m ->
                            DropdownMenuItem(text = { Text(safetyLabels[m] ?: m) }, onClick = { safetyMode = m; showSafetyPicker = false })
                        }
                    }
                    Spacer(Modifier.height(10.dp))

                    // 步数设置
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(value = maxSteps, onValueChange = { maxSteps = it },
                            label = { Text(I18n.t("max_steps")) }, modifier = Modifier.weight(1f), singleLine = true)
                        OutlinedTextField(value = stepWarning, onValueChange = { stepWarning = it },
                            label = { Text(I18n.t("step_warning")) }, modifier = Modifier.weight(1f), singleLine = true)
                    }
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(value = idleLimit, onValueChange = { idleLimit = it },
                            label = { Text(I18n.t("idle_limit")) }, modifier = Modifier.weight(1f), singleLine = true)
                        OutlinedTextField(value = cmdTimeout, onValueChange = { cmdTimeout = it },
                            label = { Text(I18n.t("command_timeout")) }, modifier = Modifier.weight(1f), singleLine = true)
                    }
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(value = rateLimit, onValueChange = { rateLimit = it },
                        label = { Text(I18n.t("rate_limit")) }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(Modifier.height(12.dp))

                    // 同步按钮
                    val scope = rememberCoroutineScope()
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            val configMap = mapOf<String, Any>(
                                "SAFETY_MODE" to safetyMode,
                                "BRAIN_MAX_STEPS" to (maxSteps.toIntOrNull() ?: 9999),
                                "BRAIN_STEP_WARNING" to (stepWarning.toIntOrNull() ?: 3000),
                                "BRAIN_IDLE_LIMIT" to (idleLimit.toIntOrNull() ?: 3),
                                "COMMAND_TIMEOUT" to (cmdTimeout.toIntOrNull() ?: 30),
                                "RATE_LIMIT_PER_MINUTE" to (rateLimit.toIntOrNull() ?: 30),
                            )
                            advancedMsg = "同步中..."
                            Config.pushToBrain(configMap) { ok, msg ->
                                advancedMsg = if (ok) "高级设置已同步" else msg
                            }
                        }) { Text("同步到电脑") }
                        if (advancedMsg.isNotBlank()) {
                            Text(advancedMsg, style = MaterialTheme.typography.bodySmall,
                                color = if (advancedMsg.contains("已同步")) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                                modifier = Modifier.align(Alignment.CenterVertically))
                        }
                    }
                }
            }

            // 数据管理
            item {
                CollapsibleSection(I18n.t("data_manage")) {
                    var showClearAll by remember { mutableStateOf(false) }
                    var clearDone by remember { mutableStateOf("") }
                    val scope = rememberCoroutineScope()
                    val db = remember { AppDatabase.getInstance(ctx) }

                    Spacer(Modifier.height(4.dp))
                    OutlinedButton(onClick = { showClearAll = true },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                        modifier = Modifier.fillMaxWidth()) {
                        Text(I18n.t("clear_all_sessions"))
                    }
                    if (clearDone.isNotBlank()) {
                        Text(clearDone, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                    }

                    if (showClearAll) {
                        AlertDialog(
                            onDismissRequest = { showClearAll = false },
                            title = { Text(I18n.t("clear_confirm_title")) },
                            text = { Text(I18n.t("clear_confirm_msg")) },
                            confirmButton = {
                                Button(onClick = {
                                    scope.launch {
                                        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                                            deleteAllSessionsRemote(ctx)
                                        }
                                        db.messageDao().deleteAll()
                                        clearDone = "已清除"
                                        showClearAll = false
                                    }
                                }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)) {
                                    Text(I18n.t("clear_all_sessions"))
                                }
                            },
                            dismissButton = { TextButton(onClick = { showClearAll = false }) { Text(I18n.t("cancel")) } },
                        )
                    }
                }
            }

            item { Spacer(Modifier.height(40.dp)) }
        }
    }
}

// 用量统计卡片
@Composable
fun StatCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier.padding(4.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(modifier = Modifier.padding(12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(value, style = MaterialTheme.typography.titleMedium)
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

fun formatNumber(n: Long): String = when {
    n >= 1_000_000 -> "${n / 1_000_000}.${(n % 1_000_000) / 100_000}M"
    n >= 1_000 -> "${n / 1_000}.${(n % 1_000) / 100}K"
    else -> n.toString()
}

// 连接配置
@Composable
fun ConnectionSettingsSection(prefs: Prefs) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val cs = MaterialTheme.colorScheme

    var host by remember { mutableStateOf(Config.HOST) }
    var brainPort by remember { mutableStateOf(Config.BRAIN_PORT.toString()) }
    var authToken by remember { mutableStateOf(Config.AUTH_TOKEN) }
    var relayAddress by remember { mutableStateOf(Config.RELAY_ADDRESS) }
    var terminalViaBrain by remember { mutableStateOf(Config.TERMINAL_VIA_BRAIN) }
    var directAgentHost by remember { mutableStateOf(Config.DIRECT_AGENT_HOST) }
    var agentPort by remember { mutableStateOf(Config.AGENT_PORT.toString()) }

    var showToken by remember { mutableStateOf(false) }
    var testResult by remember { mutableStateOf("") }
    var syncResult by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    fun saveAll() {
        Config.save(ctx, host, brainPort.toIntOrNull() ?: 8770,
            authToken, relayAddress, terminalViaBrain, directAgentHost, agentPort.toIntOrNull() ?: 8765,
            Config.LLM_API_KEY, Config.LLM_API_URL, Config.DEFAULT_MODEL)
    }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // Brain 服务器地址
        OutlinedTextField(value = host, onValueChange = { host = it },
            label = { Text("Brain 服务器地址") }, placeholder = { Text("https://runtime-host:8770") },
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = brainPort, onValueChange = { brainPort = it },
            label = { Text("Brain 端口") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        // 鉴权令牌
        OutlinedTextField(value = authToken, onValueChange = { authToken = it },
            label = { Text("鉴权令牌 (Token)") },
            visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { showToken = !showToken }) {
                    Icon(if (showToken) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, if (showToken) "隐藏" else "显示")
                }
            }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        // 中继地址
        OutlinedTextField(value = relayAddress, onValueChange = { relayAddress = it },
            label = { Text("中继服务器公网地址") }, placeholder = { Text("公网 IP 或域名") },
            modifier = Modifier.fillMaxWidth(), singleLine = true)

        HorizontalDivider(color = cs.outlineVariant, modifier = Modifier.padding(vertical = 4.dp))
        Text("终端模式", style = MaterialTheme.typography.labelMedium, color = cs.onSurfaceVariant)

        // 终端模式路由开关
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("终端命令走 Brain 路由", modifier = Modifier.weight(1f))
            Switch(checked = terminalViaBrain, onCheckedChange = { terminalViaBrain = it })
        }
        Text(if (terminalViaBrain) "命令经 Brain 转发到目标设备(有审计)" else "直连 Agent 执行(低延迟,需配地址)",
            style = MaterialTheme.typography.bodySmall, color = cs.onSurfaceVariant)

        if (!terminalViaBrain) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value = directAgentHost, onValueChange = { directAgentHost = it },
                    label = { Text("Agent 地址") }, placeholder = { Text("设备隧道地址") },
                    modifier = Modifier.weight(2f), singleLine = true)
                OutlinedTextField(value = agentPort, onValueChange = { agentPort = it },
                    label = { Text("Agent 端口") },
                    modifier = Modifier.weight(1f), singleLine = true)
            }
        }

        if (testResult.isNotBlank())
            Text(testResult, style = MaterialTheme.typography.bodySmall,
                color = if (testResult.contains("成功") || testResult.contains("通")) cs.primary else cs.error)
        if (syncResult.isNotBlank())
            Text(syncResult, style = MaterialTheme.typography.bodySmall,
                color = if (syncResult.contains("已同步")) cs.primary else cs.error)

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { saveAll(); testResult = ""; syncResult = I18n.t("saved_local") }) { Text(I18n.t("save")) }
            OutlinedButton(onClick = {
                saveAll()
                scope.launch {
                    busy = true; testResult = I18n.t("testing")
                    val err = withContext(Dispatchers.IO) {
                        try { val sock = java.net.Socket(); sock.connect(java.net.InetSocketAddress(Config.HOST, Config.BRAIN_PORT), 5000); sock.close(); null }
                        catch (e: Exception) { e.message }
                    }
                    testResult = if (err == null) I18n.t("conn_success") else "${I18n.t("conn_fail")}: $err"
                    busy = false
                }
            }, enabled = !busy) { Text(I18n.t("test_conn")) }
            OutlinedButton(onClick = {
                saveAll()
                busy = true; syncResult = I18n.t("syncing")
                Config.pushToBrain(mapOf("RELAY_PRIMARY" to Config.RELAY_ADDRESS, "LLM_API_KEY" to Config.LLM_API_KEY, "LLM_API_URL" to Config.LLM_API_URL, "LLM_MODEL" to Config.DEFAULT_MODEL)) { ok, msg ->
                    syncResult = if (ok) I18n.t("sync_success") else "${I18n.t("sync_fail")}: $msg"; busy = false
                }
            }, enabled = !busy) { Text(I18n.t("sync_to_pc")) }
        }
    }
}

// WireGuard 设置
@Composable
fun WireGuardSettingsSection() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val cs = MaterialTheme.colorScheme

    val saved = remember { TunnelManager.loadFields(ctx) }
    var privateKey by remember { mutableStateOf(saved.privateKey) }
    var address by remember { mutableStateOf(saved.address) }
    var dns by remember { mutableStateOf(saved.dns) }
    var peerPublicKey by remember { mutableStateOf(saved.peerPublicKey) }
    var endpoint by remember { mutableStateOf(saved.endpoint) }
    var allowedIPs by remember { mutableStateOf(saved.allowedIPs) }
    var keepalive by remember { mutableStateOf(saved.keepalive) }

    var tunnelStatus by remember { mutableStateOf(TunnelManager.state.name) }
    var testResult by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    fun saveAll() {
        TunnelManager.saveFields(ctx, TunnelManager.WgFields(privateKey, address, dns, peerPublicKey, endpoint, allowedIPs, keepalive))
    }

    val vpnLauncher = rememberLauncherForActivityResult(contract = ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == android.app.Activity.RESULT_OK) {
            scope.launch { busy = true; saveAll(); val err = TunnelManager.connect(ctx); tunnelStatus = if (err == null) "UP" else err; busy = false }
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            val stColor = when (tunnelStatus) { "UP" -> cs.primary; "DOWN" -> cs.error; else -> cs.onSurfaceVariant }
            val stText = when (tunnelStatus) { "UP" -> I18n.t("connected"); "DOWN" -> I18n.t("disconnected"); else -> tunnelStatus }
            Text(stText, color = stColor, style = MaterialTheme.typography.titleSmall)
        }
        if (testResult.isNotBlank())
            Text(testResult, style = MaterialTheme.typography.bodySmall, color = if (testResult.startsWith("通")) cs.primary else cs.error)

        OutlinedTextField(value = privateKey, onValueChange = { privateKey = it },
            label = { Text(I18n.t("wg_private_key")) }, modifier = Modifier.fillMaxWidth(), singleLine = true, visualTransformation = PasswordVisualTransformation())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(value = address, onValueChange = { address = it }, label = { Text(I18n.t("wg_address")) }, modifier = Modifier.weight(1f), singleLine = true)
            OutlinedTextField(value = dns, onValueChange = { dns = it }, label = { Text(I18n.t("wg_dns")) }, modifier = Modifier.weight(1f), singleLine = true)
        }
        OutlinedTextField(value = peerPublicKey, onValueChange = { peerPublicKey = it },
            label = { Text(I18n.t("wg_public_key")) }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(value = endpoint, onValueChange = { endpoint = it }, label = { Text(I18n.t("wg_endpoint")) }, modifier = Modifier.weight(2f), singleLine = true)
            OutlinedTextField(value = keepalive, onValueChange = { keepalive = it }, label = { Text(I18n.t("wg_keepalive")) }, modifier = Modifier.weight(1f), singleLine = true)
        }
        OutlinedTextField(value = allowedIPs, onValueChange = { allowedIPs = it }, label = { Text(I18n.t("wg_allowed_ips")) }, modifier = Modifier.fillMaxWidth(), singleLine = true)

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                saveAll()
                if (privateKey.isBlank() || peerPublicKey.isBlank()) { tunnelStatus = I18n.t("wg_need_keys"); return@Button }
                val intent = TunnelManager.prepareVpn(ctx)
                if (intent != null) vpnLauncher.launch(intent)
                else scope.launch { busy = true; val err = TunnelManager.connect(ctx); tunnelStatus = if (err == null) "UP" else err; busy = false }
            }, enabled = !busy && tunnelStatus != "UP") { Text(I18n.t("connect")) }
            OutlinedButton(onClick = {
                scope.launch { busy = true; TunnelManager.disconnect(); tunnelStatus = "DOWN"; busy = false }
            }, enabled = !busy && tunnelStatus == "UP") { Text(I18n.t("disconnect")) }
            OutlinedButton(onClick = {
                scope.launch {
                    busy = true; testResult = I18n.t("testing")
                    val err = TunnelManager.testConnection()
                    testResult = if (err == null) I18n.t("wg_conn_test_ok") else "${I18n.t("wg_conn_test_fail")}: $err"
                    busy = false
                }
            }, enabled = !busy) { Text(I18n.t("test")) }
        }
    }
}


// 数据类 / 网络函数(逻辑不变)

/**
 * 快速 TCP 探测:3 秒内能否连上大脑。发消息前调用,断了立即提示,不等 15 秒超时。
 * 在 IO 线程执行。返回 null=通,否则返回错误提示文案。
 */
suspend fun quickPing(): String? = withContext(Dispatchers.IO) {
    try {
        val sock = java.net.Socket()
        sock.connect(java.net.InetSocketAddress(Config.HOST, Config.BRAIN_PORT), Config.PING_TIMEOUT_MS)
        sock.close()
        null // 通
    } catch (e: Exception) {
        "无法连接服务器(${e.message?.take(60)})。\n请检查:\n1) 手表 WireGuard 是否已连接\n2) 服务器 Brain 是否正常运行"
    }
}

data class ChatResult(
    val ok: Boolean, val status: String, val reply: String, val steps: String,
    val error: String, val confirmationId: String, val dangerCommand: String, val dangers: List<String>,
)
data class StreamStep(val command: String, val output: String)

/** 生成防重放参数:当前时间戳(秒) + 随机 nonce。Brain 强制校验。 */
fun antiReplay(): Pair<String, String> {
    val ts = (System.currentTimeMillis() / 1000).toString()
    val nonce = java.util.UUID.randomUUID().toString().replace("-", "")
    return ts to nonce
}

fun saveToDbStatic(db: AppDatabase, sessionId: String, role: String, content: String, steps: String) {
    kotlinx.coroutines.runBlocking {
        db.messageDao().insert(LocalMessage(sessionId = sessionId, role = role, content = content, steps = steps))
    }
}

suspend fun sendChat(
    sessionId: String, message: String, model: String,
    confirmationId: String = "", confirmationAction: String = "",
): ChatResult = withContext(Dispatchers.IO) {
    var conn: HttpURLConnection? = null
    try {
        val bodyJson = JSONObject().put("session_id", sessionId).put("model", model)
        if (confirmationId.isNotEmpty())
            bodyJson.put("confirmation", JSONObject().put("id", confirmationId).put("action", confirmationAction))
        else bodyJson.put("message", message)
        val body = bodyJson.toString()
        val (ts, nonce) = antiReplay()
        conn = (URL(Config.CHAT_URL).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; connectTimeout = 15000; readTimeout = Config.TIMEOUT_MS; doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
            setRequestProperty("X-Timestamp", ts)
            setRequestProperty("X-Nonce", nonce)
        }
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        if (code == 401) return@withContext ChatResult(false, "", "", "", "鉴权失败", "", "", emptyList())
        if (code !in 200..299) return@withContext ChatResult(false, "", "", "", "HTTP $code", "", "", emptyList())
        val json = JSONObject(text)
        if (!json.optBoolean("ok", false))
            return@withContext ChatResult(false, "", "", "", json.optString("error"), "", "", emptyList())
        val status = json.optString("status", "done")
        if (status == "awaiting_confirmation") {
            val dl = mutableListOf<String>(); val da = json.optJSONArray("dangers")
            if (da != null) for (i in 0 until da.length()) dl.add(da.getString(i))
            return@withContext ChatResult(true, "awaiting_confirmation", "", "", "", json.optString("confirmation_id", ""), json.optString("command", ""), dl)
        }
        val stepsArr = json.optJSONArray("steps")
        val stepsText = buildString {
            if (stepsArr != null) for (i in 0 until stepsArr.length())
                append("$ ${stepsArr.getJSONObject(i).optString("command")}\n")
        }.trim()
        ChatResult(true, "done", json.optString("reply", ""), stepsText, "", "", "", emptyList())
    } catch (e: Exception) { ChatResult(false, "", "", "", "连接失败:${e.message}", "", "", emptyList()) }
    finally { conn?.disconnect() }
}

suspend fun sendChatStream(
    sessionId: String, message: String, model: String, token: String,
    onStep: (command: String, output: String, stepNum: Int) -> Unit = { _, _, _ -> },
    onConfirmation: (confirmationId: String, command: String, dangers: List<String>) -> Unit = { _, _, _ -> },
    onReplyDelta: (text: String) -> Unit = {},
    onDone: (reply: String, steps: List<StreamStep>) -> Unit = { _, _ -> },
    onError: (error: String) -> Unit = {},
) = withContext(Dispatchers.IO) {
    var conn: HttpURLConnection? = null
    try {
        val (ts, nonce) = antiReplay()
        val url = "${Config.CHAT_URL}/stream?session_id=$sessionId&message=${java.net.URLEncoder.encode(message, "UTF-8")}&model=${java.net.URLEncoder.encode(model, "UTF-8")}&token=${java.net.URLEncoder.encode(token, "UTF-8")}&ts=$ts&nonce=$nonce"
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"; connectTimeout = 10000; readTimeout = 130000  // 等大脑调模型(可能多步,最长~120s),略大于服务端 LLM_TIMEOUT
            setRequestProperty("Accept", "text/event-stream")
        }
        if (conn.responseCode != 200) { onError("SSE HTTP ${conn.responseCode}"); return@withContext }
        val reader = BufferedReader(InputStreamReader(conn.inputStream, Charsets.UTF_8))
        var ev = ""; var dt = ""; val steps = mutableListOf<StreamStep>()
        reader.forEachLine { line ->
            when {
                line.startsWith("event: ") -> ev = line.removePrefix("event: ").trim()
                line.startsWith("data: ") -> dt = line.removePrefix("data: ").trim()
                line.isEmpty() && dt.isNotEmpty() -> {
                    try {
                        val json = JSONObject(dt)
                        when (ev) {
                            "thinking" -> onStep("思考中...", "", json.optInt("step", 0))
                            "reply_delta" -> onReplyDelta(json.optString("text"))
                            "step_start" -> onStep(json.optString("command"), "...", json.optInt("step_num", 0))
                            "step_done" -> {
                                val c = json.optString("command"); val o = json.optString("output")
                                steps.add(StreamStep(c, o)); onStep(c, o, steps.size)
                            }
                            "confirmation_required" -> {
                                val dl = mutableListOf<String>(); val da = json.optJSONArray("dangers")
                                if (da != null) for (i in 0 until da.length()) dl.add(da.getString(i))
                                onConfirmation(json.optString("confirmation_id"), json.optString("command"), dl)
                            }
                            "done" -> {
                                val reply = json.optString("reply")
                                val sa = json.optJSONArray("steps")
                                if (sa != null) for (i in 0 until sa.length()) {
                                    val s = sa.getJSONObject(i)
                                    if (steps.none { it.command == s.optString("command") }) steps.add(StreamStep(s.optString("command"), s.optString("output")))
                                }
                                onDone(reply, steps)
                            }
                            "error" -> onError(json.optString("message"))
                        }
                    } catch (_: Exception) {}
                    ev = ""; dt = ""
                }
            }
        }
        reader.close()
    } catch (e: Exception) { onError("SSE: ${e.message}") }
    finally { conn?.disconnect() }
}
