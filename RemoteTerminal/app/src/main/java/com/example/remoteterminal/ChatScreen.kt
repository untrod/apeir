package com.example.remoteterminal

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.core.content.ContextCompat
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.KeyboardVoice
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.derivedStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONObject
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign

data class LiveStep(val command: String, var output: String = "", var done: Boolean = false)

private val UserBubbleMaxWidth = 300.dp
private val AssistantBubbleMaxWidth = 600.dp

// 对话模式(欢迎页选择)
enum class ChatMode(val label: String, val icon: String, val desc: String, val hint: String) {
    COMMAND("指挥模式", "", "全能助手：执行任务、写作、答疑辅导、查资料，自动规划多步完成", "描述你想做什么（任务/写作/学习都行）…"),
    TERMINAL("终端模式", "", "直连设备执行命令，不经 AI，秒出结果", "输入命令…"),
    CODE("代码模式", "", "委派 Claude Code 深度理解项目、重构与修改", "描述代码任务…"),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    prefs: Prefs, db: AppDatabase, model: String,
    codeMode: Boolean = false,
    initialMode: ChatMode? = null,
    onOpenDrawer: () -> Unit, onNavigateToSettings: () -> Unit,
) {
    val context = LocalContext.current
    val messages = remember { mutableStateListOf<ChatMessage>() }
    var sessionId by remember { mutableStateOf(prefs.sessionId) }
    var input by remember { mutableStateOf("") }
    // 简洁模式(手表):只显示指挥模式,隐藏终端/代码
    val availableModes = if (prefs.simpleMode) listOf(ChatMode.COMMAND) else ChatMode.entries.toList()
    var chatMode by remember { mutableStateOf(initialMode ?: if (codeMode) ChatMode.CODE else ChatMode.COMMAND) }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    // 从 ChatWorker 读状态(不随 UI 销毁)
    val busy by ChatWorker.busy.collectAsState()
    val pendingReply by ChatWorker.pendingReply.collectAsState()
    val pendingSteps by ChatWorker.pendingSteps.collectAsState()
    val isThinking by ChatWorker.isThinking.collectAsState()
    val confirmReq by ChatWorker.confirmRequest.collectAsState()

    // 设备在线状态(轮询)
    val deviceList by ChatWorker.devices.collectAsState()
    val defaultDevice by ChatWorker.defaultDevice.collectAsState()
    LaunchedEffect(Unit) { ChatWorker.startDevicePolling() }
    // 当前目标设备的在线状态
    val targetDev = deviceList.firstOrNull { it.id == defaultDevice } ?: deviceList.firstOrNull()

    // 卫星猫状态 — derivedStateOf 避免每次重组都重新计算
    var catFlash by remember { mutableStateOf(0) }  // 0=idle 1=done 2=error
    LaunchedEffect(busy) {
        if (!busy && messages.isNotEmpty()) {
            val last = messages.lastOrNull()
            if (last?.role == "assistant") {
                catFlash = if (last.content.startsWith("出错") || last.content.startsWith("连接失败") ||
                    last.content.contains("无法连接")) 2 else 1
                kotlinx.coroutines.delay(2500)
                catFlash = 0
            }
        }
    }
    val catState by remember {
        derivedStateOf {
            when {
                confirmReq != null -> CatState.ALERT
                isThinking -> CatState.THINKING
                pendingSteps.isNotEmpty() -> CatState.WORKING
                catFlash == 2 -> CatState.ERROR
                catFlash == 1 -> CatState.DONE
                !Config.isConfigured() -> CatState.SLEEP
                else -> CatState.IDLE
            }
        }
    }

    // 语音输入(不依赖 Google,用系统 SpeechRecognizer)
    var voiceSupported by remember { mutableStateOf(false) }
    var isListening by remember { mutableStateOf(false) }
    var voiceHasSpeech by remember { mutableStateOf(false) } // 用户正在说话(区别于就绪)
    var voicePartial by remember { mutableStateOf("") }
    var voiceRms by remember { mutableStateOf(0f) }
    val voiceHelper = remember { VoiceInputHelper(context) }
    var voiceMode by remember { mutableStateOf(false) }
    var voiceFromWake by remember { mutableStateOf(false) }  // 区分唤醒触发 vs 手动点按钮
    var wakeGreeting by remember { mutableStateOf("嗯，请说") }  // 服务器返回的问候语
    val ttsHelper = remember { TTSHelper(context) }
    var ttsAvailable by remember { mutableStateOf(false) }  // 本地TTS是否可用（独立于语音识别）
    var ttsSpeaking by remember { mutableStateOf(false) }
    // 兜底录音方案: 无语音引擎时用 AudioRecorder → Agent Whisper
    val audioRecorder = remember { AudioRecorder(context) }
    var isFallbackRecording by remember { mutableStateOf(false) }
    var transcribing by remember { mutableStateOf(false) }
    var hasRecordPermission by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
    }
    // 语音唤醒监听: WakeWordService 检测到唤醒词 → 自动进入语音模式
    fun enterVoiceFromWake(greeting: String) {
        WakeWordService.pendingGreeting = null
        if (!voiceMode && !busy) {
            voiceFromWake = true
            wakeGreeting = greeting
            voiceMode = true
        }
    }
    LaunchedEffect(Unit) {
        // 冷启动:被息屏/后台唤醒拉起 App 时,消费暂存的问候语
        WakeWordService.pendingGreeting?.let { enterVoiceFromWake(it) }
        // 前台运行时:实时收唤醒事件
        WakeWordService.wakeEvents.collect { event -> enterVoiceFromWake(event.greeting) }
    }
    // 进语音模式时暂停唤醒服务,避免两个 AudioRecord 抢麦克风;退出时清理并恢复(仅当用户开了总开关)
    LaunchedEffect(voiceMode) {
        if (voiceMode) {
            try {
                context.startService(Intent(context, WakeWordService::class.java).apply { action = "stop" })
            } catch (_: Exception) {}
        } else {
            // 退出语音模式:清理所有录音/TTS 资源,不再连续听;重置唤醒标记
            voiceFromWake = false
            wakeGreeting = "嗯，请说"  // 重置问候语
            audioRecorder.cancel()
            isFallbackRecording = false
            ttsHelper.stop()
            CloudTTS.stop()
            ttsSpeaking = false
            voiceHelper.stop()
            isListening = false
            if (prefs.voiceWakeEnabled) {
                // 延迟重启:给系统时间完全释放上一个 AudioRecord 的麦克风资源
                kotlinx.coroutines.delay(600)
                try {
                    context.startService(Intent(context, WakeWordService::class.java).apply { action = "start" })
                } catch (_: Exception) {}
            }
        }
    }
    // 字号设置
    val chatFontSize = prefs.fontSize.sp

    fun doSend(text: String) {
        val t = text.trim()
        if (t.isEmpty()) return
        input = ""
        when (chatMode) {
            ChatMode.TERMINAL -> ChatWorker.sendDirect(db, sessionId, t)
            ChatMode.CODE -> ChatWorker.send(db, sessionId, "#code\n$t", model)
            else -> ChatWorker.send(db, sessionId, t, model)
        }
    }

    val initVoice = remember {
        {
            voiceHelper.init(object : VoiceInputHelper.VoiceListener {
                override fun onReady() { isListening = true; voicePartial = ""; voiceHasSpeech = false }
                override fun onSpeechStart() { voiceHasSpeech = true }
                override fun onPartial(text: String) { voicePartial = text }
                override fun onResult(text: String) {
                    isListening = false; voicePartial = ""; voiceHasSpeech = false
                    if (voiceMode && text.isNotBlank()) {
                        doSend(text)
                    } else { input = text }
                }
                override fun onSilence() { voiceHasSpeech = false }
                override fun onError(message: String) {
                    isListening = false; voicePartial = ""; voiceHasSpeech = false
                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                    // Siri 风格:出错即退出,不反复重试
                    if (voiceMode) voiceMode = false
                }
                override fun onRmsChanged(rmsDb: Float) { voiceRms = rmsDb }
            })
        }
    }

    val permLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasRecordPermission = granted
        if (granted) {
            voiceSupported = VoiceInputHelper.isSupported(context)
            if (voiceSupported) initVoice()
        }
    }

    LaunchedEffect(Unit) {
        // 手表/GSI 等非标准设备不用系统语音引擎，统一走录音+Whisper 路径
        voiceSupported = false
        // 延迟检测 TTS 是否真的初始化成功
        kotlinx.coroutines.delay(600)
        ttsAvailable = ttsHelper.isReady
    }

    // 兜底转写:录音文件上传到 Agent /transcribe,返回文字
    suspend fun uploadAudioForTranscribe(audioFile: java.io.File): String =
        withContext(Dispatchers.IO) {
            try {
                // 经 Brain 网关转发 /transcribe → Agent,避免手表需单独配 Agent IP
                val url = java.net.URL("http://${Config.HOST}:${Config.BRAIN_PORT}/transcribe")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "POST"; conn.doOutput = true
                conn.connectTimeout = 10000; conn.readTimeout = 30000
                conn.setRequestProperty("Content-Type", "audio/wav")
                // 使用手表自身客户端 token（已在服务器 clients.json 中注册）
                conn.setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
                // 防重放(公网暴露时 Brain 强制校验)
                val (ts, nonce) = antiReplay()
                conn.setRequestProperty("X-Timestamp", ts)
                conn.setRequestProperty("X-Nonce", nonce)
                audioFile.inputStream().use { input ->
                    conn.outputStream.use { output -> input.copyTo(output) }
                }
                val code = conn.responseCode
                val resp = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                conn.disconnect()
                if (code != 200) return@withContext ""
                val json = org.json.JSONObject(resp)
                if (json.optBoolean("ok", false)) json.optString("text", "")
                else { android.util.Log.e("Transcribe", json.optString("error", "")); "" }
            } catch (e: Exception) {
                android.util.Log.e("Transcribe", "Upload failed", e)
                ""
            }
        }

    // 处理一段录音:转写 → 语音模式直接发送 / 否则填入输入框(停止按钮与VAD自动停共用)
    // Siri 风格:没人说话/识别失败→自动退出,不反复听
    fun processRecording(file: java.io.File?) {
        isFallbackRecording = false
        if (file == null) { voiceMode = false; return }
        if (file.length() < 20000) {   // 太短(<~0.6s)多半是噪音/回声→没人说话,退出
            file.delete()
            voiceMode = false
            return
        }
        transcribing = true
        scope.launch(Dispatchers.IO) {
            val text = uploadAudioForTranscribe(file)
            file.delete()
            launch(Dispatchers.Main) {
                transcribing = false
                if (text.isNotBlank() && text != "(未识别到语音)") {
                    if (voiceMode) doSend(text) else input = text
                } else {
                    // 没识别到→退出语音模式,不反复听烧 token
                    voiceMode = false
                }
            }
        }
    }
    // VAD 静音自动停 → 自动转写提交(无需点按钮)
    audioRecorder.onAutoStop = { f -> processRecording(f) }

    // 语音对话模式:Siri 式 — 唤醒→即刻开麦+同时播问候→听指令→回答→退出;手动按钮→直接听指令→回答→退出
    var greetingDone by remember { mutableStateOf(false) }
    LaunchedEffect(voiceMode) {
        if (voiceMode) {
            greetingDone = false
            if (!voiceFromWake) greetingDone = true  // 手动触发:跳过问候

            // 注册 TTS 完成回调仅用于"回答播完→退出"(不用于问候→录音,那个靠定时器)
            if (ttsAvailable) {
                ttsHelper.onAllDone = {
                    ttsSpeaking = false
                    kotlinx.coroutines.MainScope().launch {
                        if (greetingDone) { kotlinx.coroutines.delay(800); voiceMode = false }
                    }
                }
            } else {
                CloudTTS.onAllDone = {
                    ttsSpeaking = false
                    kotlinx.coroutines.MainScope().launch {
                        if (greetingDone) { kotlinx.coroutines.delay(800); voiceMode = false }
                    }
                }
            }

            // 安全超时:只在"真卡死"时退出——执行中/朗读中/录音中都算活动,不退;
            // 持续 15 秒无任何活动才判定卡死;另设 180 秒硬上限兜底。
            val safetyJob = launch {
                val hardCap = System.currentTimeMillis() + 180_000
                var lastActive = System.currentTimeMillis()
                while (voiceMode) {
                    kotlinx.coroutines.delay(1000)
                    val now = System.currentTimeMillis()
                    if (busy || ttsSpeaking || isFallbackRecording || isListening || transcribing) lastActive = now
                    if (now - lastActive > 15_000 || now > hardCap) {
                        android.util.Log.w("ChatScreen", "Voice safety exit (idle/cap)")
                        voiceMode = false; break
                    }
                }
            }

            try {
                if (voiceFromWake && !busy) {
                    // —— 唤醒路径(Siri 式:即刻开麦 + 同时播问候) ——
                    // ① 立刻启动录音(不等 TTS),用户听到问候时已经在听了
                    kotlinx.coroutines.delay(100)  // 极短缓冲,让 AudioRecord 初始化
                    if (voiceMode && !isFallbackRecording) {
                        if (audioRecorder.start()) isFallbackRecording = true
                        else {
                            Toast.makeText(context, "录音启动失败,请检查麦克风权限", Toast.LENGTH_SHORT).show()
                            voiceMode = false
                        }
                    }
                    // ② 同时播问候语(后台,不阻塞录音)
                    if (voiceMode) {
                        ttsSpeaking = true
                        try {
                            if (ttsAvailable) ttsHelper.enqueue(wakeGreeting)
                            else CloudTTS.speak(wakeGreeting)
                        } catch (_: Exception) { /* TTS 失败不阻塞 */ }
                    }
                    // ③ 等待问候播完(TTS ~1s)即标记完成,用户可接着说话
                    kotlinx.coroutines.delay(1200)
                    ttsSpeaking = false; greetingDone = true
                } else if (!voiceFromWake && !busy) {
                    // —— 手动点麦克风 ——
                    kotlinx.coroutines.delay(200)
                    if (voiceMode && !isFallbackRecording) {
                        if (audioRecorder.start()) isFallbackRecording = true
                        else {
                            Toast.makeText(context, "录音启动失败,请检查麦克风权限", Toast.LENGTH_SHORT).show()
                            voiceMode = false
                        }
                    }
                }
                // ④ 订阅 AI 回答流:逐句朗读 + barge-in(朗读时说话→停 TTS→开始新录音)
                ChatWorker.speechQueue.collect { sentence ->
                    if (voiceMode) {
                        if (isListening) voiceHelper.stop()
                        if (isFallbackRecording) { audioRecorder.cancel(); isFallbackRecording = false }
                        ttsSpeaking = true
                        if (ttsAvailable) ttsHelper.enqueue(sentence)
                        else CloudTTS.speak(sentence)

                        // Barge-in 监听: TTS 朗读期间持续探测麦克风,检测到用户说话→立即打断
                        val bargeJob = launch {
                            var checkCount = 0
                            while (ttsSpeaking && voiceMode && checkCount < 40) { // 最多检查~8s(200ms×40)
                                kotlinx.coroutines.delay(200)
                                checkCount++
                                val rms = withContext(Dispatchers.IO) { audioRecorder.peekRms(200) }
                                if (rms != null && rms > 2500.0) { // 高于环境噪声阈值(比VAD阈值高,避免TTS回声误触发)
                                    android.util.Log.i("ChatScreen", "Barge-in: 检测到语音 RMS=%.0f,打断TTS".format(rms))
                                    withContext(Dispatchers.Main) {
                                        if (ttsAvailable) ttsHelper.stop()
                                        else CloudTTS.stop()
                                        ttsSpeaking = false
                                    }
                                    kotlinx.coroutines.delay(150) // 短暂缓冲,让麦克风从回声恢复
                                    // 开始新一轮录音
                                    withContext(Dispatchers.Main) {
                                        if (voiceMode && !isFallbackRecording) {
                                            if (audioRecorder.start()) isFallbackRecording = true
                                        }
                                    }
                                    break
                                }
                            }
                        }
                        // TTS 播完或被打断后,取消 barge-in 监听
                        while (ttsSpeaking && voiceMode) { kotlinx.coroutines.delay(100) }
                        bargeJob.cancel()
                        // barge-in 未触发: 等 TTS 自然播完,回到等待用户说话状态
                        if (!isFallbackRecording && voiceMode) {
                            kotlinx.coroutines.delay(300)
                            if (!isFallbackRecording && voiceMode) {
                                if (audioRecorder.start()) isFallbackRecording = true
                            }
                        }
                    }
                }
            } finally {
                safetyJob.cancel()
            }
        }
    }

    // 任务结束后自动退出语音模式(Siri 单轮:不再反复听)
    LaunchedEffect(busy) {
        if (voiceMode && !busy) {
            kotlinx.coroutines.delay(2000)
            if (!ttsSpeaking) voiceMode = false
        }
    }

    // 立即显示本地消息(不等网络),秒开不卡
    LaunchedEffect(sessionId) {
        messages.clear()
        db.messageDao().getMessages(sessionId).collect { msgs ->
            messages.clear()
            messages.addAll(msgs.map { ChatMessage(it.role, it.content, it.steps) })
        }
    }
    // 后台从服务器同步历史(手机/手表共用),不阻塞首屏
    LaunchedEffect(sessionId) {
        if (!(ChatWorker.busy.value && ChatWorker.activeSessionId.value == sessionId)) {
            syncSessionFromServer(db, sessionId)
        }
    }

    // 自动滚底
    LaunchedEffect(messages.size, pendingSteps.size) {
        if (messages.isNotEmpty() || isThinking) listState.animateScrollToItem(messages.size)
    }

    // 确认弹窗:精简 —— 先说会发生什么,命令默认折叠
    confirmReq?.let { req ->
        val isStepWarning = req.command.startsWith("已达到")
        var showCommand by remember { mutableStateOf(false) }

        ModalBottomSheet(
            onDismissRequest = { ChatWorker.handleConfirmation(db, sessionId, model, req.id, "deny") },
            containerColor = MaterialTheme.colorScheme.surface,
            dragHandle = { BottomSheetDefaults.DragHandle() },
        ) {
            Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp).padding(bottom = 28.dp)) {
                // 标题
                Row(verticalAlignment = Alignment.CenterVertically) {
                    PetCat(state = CatState.ALERT, modifier = Modifier.size(40.dp))
                    Spacer(Modifier.width(10.dp))
                    Text(
                        if (isStepWarning) "已执行多步，确认继续？" else "确认此操作",
                        style = MaterialTheme.typography.titleMedium,
                    )
                }

                Spacer(Modifier.height(10.dp))

                // 核心:将发生什么
                if (isStepWarning) {
                    val stepN = req.dangers.firstOrNull()
                        ?.let { Regex("已执行 (\\d+) 步").find(it)?.groupValues?.get(1) }
                        ?: "多"
                    Text(
                        "任务已执行 $stepN 步，继续执行可能消耗更多 Token。",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    Text(
                        "将执行以下操作：",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(4.dp))
                    req.dangers.forEach { danger ->
                        Row(modifier = Modifier.padding(vertical = 2.dp)) {
                            Text("• ", color = MaterialTheme.colorScheme.error, fontSize = 15.sp)
                            Text(danger, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }

                // 命令:折叠,想看才看
                if (!isStepWarning && req.command.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    TextButton(
                        onClick = { showCommand = !showCommand },
                        modifier = Modifier.height(30.dp),
                        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp),
                    ) {
                        Text(
                            if (showCommand) "▾ 隐藏命令" else "▸ 查看命令",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (showCommand) {
                        SelectionContainer {
                            Text(
                                req.command,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 11.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(
                                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                        RoundedCornerShape(8.dp),
                                    )
                                    .padding(10.dp),
                            )
                        }
                    }
                }

                Spacer(Modifier.height(22.dp))

                // 按钮
                Row(
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    OutlinedButton(
                        onClick = { ChatWorker.handleConfirmation(db, sessionId, model, req.id, "deny") },
                        modifier = Modifier.weight(1f),
                    ) { Text("取消") }
                    Button(
                        onClick = { ChatWorker.handleConfirmation(db, sessionId, model, req.id, "approve") },
                        modifier = Modifier.weight(1f),
                    ) { Text(if (isStepWarning) "继续" else "确认执行") }
                }
            }
        }
    }

    // 主布局
    CompositionLocalProvider(LocalTextStyle provides MaterialTheme.typography.bodyMedium.copy(fontSize = chatFontSize)) {
    Column(modifier = Modifier.fillMaxSize().padding(8.dp)) {
        // 顶栏
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            PetCat(state = catState, modifier = Modifier.size(44.dp))
            Spacer(Modifier.width(6.dp))
            Text("Nous", style = MaterialTheme.typography.titleMedium)
            // 设备在线状态芯片
            targetDev?.let { dev ->
                Spacer(Modifier.width(8.dp))
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)) {
                        Box(modifier = Modifier.size(7.dp).background(
                            if (dev.online) Color(0xFF4CAF50) else Color(0xFF9E9E9E),
                            shape = RoundedCornerShape(50)))
                        Spacer(Modifier.width(5.dp))
                        Text(dev.name, fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            if (voiceMode) {
                Text("🎙️", fontSize = 12.sp, color = MaterialTheme.colorScheme.error)
                if (ttsSpeaking) {
                    Icon(Icons.Filled.VolumeUp, "朗读中", modifier = Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                }
            }
            Spacer(Modifier.weight(1f))
            // 语音对话模式开关:Siri 风格单轮,LaunchedEffect(voiceMode) 统一处理进出
            if (hasRecordPermission) {
                IconButton(onClick = {
                    voiceMode = !voiceMode
                }, modifier = Modifier.size(36.dp)) {
                    Icon(
                        if (voiceMode) Icons.Filled.Mic else Icons.Filled.MicOff,
                        "语音对话",
                        modifier = Modifier.size(18.dp),
                        tint = when { voiceHasSpeech -> androidx.compose.ui.graphics.Color(0xFF4CAF50); voiceMode -> MaterialTheme.colorScheme.error; else -> MaterialTheme.colorScheme.onSurfaceVariant }
                    )
                }
            }
            TextButton(onClick = { sessionId = prefs.newSession(); messages.clear() }) { Text("新建") }
        }

        // 学习状态条(快速浏览)
        var dueFormulas by remember { mutableStateOf(0) }
        var dueMistakes by remember { mutableStateOf(0) }
        var todayStudyMin by remember { mutableStateOf(0) }
        LaunchedEffect(Unit) {
            // 每30秒刷新一次学习状态
            while (true) {
                withContext(Dispatchers.IO) {
                    try {
                        val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/learn/dashboard?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                        val conn = url.openConnection() as HttpURLConnection
                        conn.requestMethod = "GET"; conn.connectTimeout = 3000; conn.readTimeout = 3000
                        if (conn.responseCode == 200) {
                            val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                            val d = json.optJSONObject("dashboard") ?: JSONObject()
                            val stats = d.optJSONObject("stats") ?: JSONObject()
                            dueFormulas = d.optJSONArray("due_formulas")?.length() ?: 0
                            dueMistakes = stats.optInt("unreviewed_mistakes")
                            todayStudyMin = stats.optInt("today_study_minutes")
                        }
                        conn.disconnect()
                    } catch (_: Exception) {}
                }
                kotlinx.coroutines.delay(30000)
            }
        }
        if (dueFormulas > 0 || dueMistakes > 0) {
            Surface(color = MaterialTheme.colorScheme.primary.copy(alpha = 0.08f),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().clickable { /* 跳转到学习区 */ }) {
                Row(Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    if (dueFormulas > 0) Text("📐$dueFormulas", fontSize = 11.sp, color = MaterialTheme.colorScheme.primary)
                    if (dueMistakes > 0) Text("❌$dueMistakes", fontSize = 11.sp, color = MaterialTheme.colorScheme.error)
                    Text("⏱${todayStudyMin}min", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.weight(1f))
                    Text("学习 →", fontSize = 10.sp, color = MaterialTheme.colorScheme.primary)
                }
            }
        }

        // 消息区:空时显示欢迎页,有消息时显示列表
        if (messages.isEmpty() && !isThinking) {
            // 每日灵感
            var dailyText by remember { mutableStateOf("") }
            var dailyAuthor by remember { mutableStateOf("") }
            LaunchedEffect(Unit) {
                withContext(Dispatchers.IO) {
                    try {
                        val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/learn/daily")
                        val conn = url.openConnection() as HttpURLConnection
                        conn.requestMethod = "GET"; conn.connectTimeout = 5000; conn.readTimeout = 5000
                        if (conn.responseCode == 200) {
                            val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                            val d = json.optJSONObject("daily") ?: JSONObject()
                            dailyText = d.optString("text", "")
                            dailyAuthor = d.optString("author", "")
                        }
                        conn.disconnect()
                    } catch (_: Exception) {}
                }
            }

            WelcomePane(
                dailyText = dailyText, dailyAuthor = dailyAuthor,
                onQuick = { doSend(it) },
                modifier = Modifier.weight(1f).fillMaxWidth(),
            )
        } else {
            // 消息列表(朗读时整个区域可点打断)
            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                LazyColumn(state = listState, modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    items(messages.size, key = { it }, contentType = { messages[it].role }) { i ->
                        MessageBubble(messages[i])
                    }
                    if ((isThinking || pendingReply.isNotEmpty()) && ChatWorker.activeSessionId.value == sessionId) {
                        item { AssistantBubble(reply = pendingReply, steps = pendingSteps, isThinking = isThinking) }
                    }
                }
                // 打断层:仅在朗读时覆盖,点一下停止朗读并立即开始听(插话)
                if (ttsSpeaking) {
                    Box(modifier = Modifier.fillMaxSize().clickable {
                        ttsHelper.stop(); CloudTTS.stop(); ttsSpeaking = false
                        voiceMode = false  // Siri 风格:打断即结束本轮
                    }, contentAlignment = Alignment.BottomCenter) {
                        Surface(shape = RoundedCornerShape(16.dp),
                            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.85f),
                            modifier = Modifier.padding(bottom = 12.dp)) {
                            Text("🔊 朗读中 · 点击打断插话", fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onPrimary,
                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp))
                        }
                    }
                }
            }
        }

        // 斜杠命令补全 — 输入 / 时触发,精确匹配前缀
        val slashInput = if (input.startsWith("/")) input.trimStart('/') else ""
        val showCommands = input.startsWith("/")
        val matchedCommands = remember(input) {
            if (!showCommands) emptyList()
            else COMMANDS.filter {
                it.name.contains(slashInput, ignoreCase = true) ||
                it.description.contains(slashInput, ignoreCase = true)
            }.take(8)
        }
        if (showCommands && matchedCommands.isNotEmpty()) {
            Card(modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                shape = RoundedCornerShape(12.dp)) {
                LazyColumn {
                    items(matchedCommands) { cmd ->
                        Row(modifier = Modifier.fillMaxWidth().clickable {
                            when {
                                cmd.localAction -> {
                                    when (cmd.name) {
                                        "/clear" -> messages.clear()
                                        "/new" -> { sessionId = prefs.newSession(); messages.clear() }
                                        "/export" -> scope.launch { exportSession(context, db, sessionId, "对话导出") }
                                        "/help" -> {
                                            messages.add(ChatMessage("user", "/help"))
                                            messages.add(ChatMessage("assistant", COMMANDS.joinToString("\n") { "${it.name} — ${it.description}" }))
                                        }
                                        "/voice" -> {
                                            voiceMode = !voiceMode
                                            if (voiceMode && hasRecordPermission && !isListening) voiceHelper.start()
                                        }
                                    }
                                    input = ""
                                }
                                else -> {
                                    val st = getCommandSendText(cmd.name)
                                    input = if (st != null) st else cmd.name + " "
                                }
                            }
                        }.padding(horizontal = 12.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                            // 命令名(等宽字体) + 参数占位提示
                            Column(modifier = Modifier.width(105.dp)) {
                                Text(cmd.name, fontFamily = FontFamily.Monospace, fontSize = 13.sp,
                                    color = MaterialTheme.colorScheme.primary)
                                // 显示参数提示
                                val hint = when (cmd.name) {
                                    "/ssl", "/dns", "/whois", "/ip" -> " <domain>"
                                    "/gh", "/gitee", "/pypi" -> " <query>"
                                    "/repo", "/readme" -> " <owner> <repo>"
                                    "/clone" -> " <owner> <repo>"
                                    "/find", "/grep" -> " <pattern>"
                                    "/port" -> " <port>"
                                    "/click" -> " <x> <y>"
                                    "/open" -> " <app>"
                                    "/type" -> " <text>"
                                    "/keys" -> " <shortcut>"
                                    "/qr" -> " <content>"
                                    "/pwd" -> " [length]"
                                    "/short" -> " <url>"
                                    "/read", "/write", "/review", "/hash" -> " <file>"
                                    "/blame" -> " <file:line>"
                                    "/trending" -> " [language]"
                                    "/python" -> " <code>"
                                    else -> ""
                                }
                                if (hint.isNotEmpty()) {
                                    Text(hint, fontSize = 10.sp, fontFamily = FontFamily.Monospace,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f))
                                }
                            }
                            Spacer(Modifier.width(8.dp))
                            Text(cmd.description, fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
        }

        // 输入栏(iPhone 圆角胶囊风)
        Spacer(Modifier.height(8.dp))
        Surface(
            shape = RoundedCornerShape(24.dp),
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp)) {
                // 主输入行
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // 语音按钮:优先检查录音/转写状态（语音模式强制用 AudioRecorder）
                    if (isFallbackRecording) {
                        // 录音中 → 红色停止按钮(手动停;也会自动静音停)
                        IconButton(onClick = {
                            isFallbackRecording = false
                            processRecording(audioRecorder.stop())
                        }, modifier = Modifier.size(36.dp)) {
                            Icon(Icons.Filled.Stop, "停止录音",
                                modifier = Modifier.size(20.dp),
                                tint = MaterialTheme.colorScheme.error)
                        }
                    } else if (transcribing) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                    } else if (!hasRecordPermission) {
                        IconButton(onClick = { permLauncher.launch(Manifest.permission.RECORD_AUDIO) },
                            modifier = Modifier.size(36.dp)) {
                            Icon(Icons.Filled.KeyboardVoice, "授权录音",
                                modifier = Modifier.size(20.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    } else if (voiceSupported) {
                        // 有原生语音引擎 → 可选用 SpeechRecognizer（非语音模式下快速填文字）
                        IconButton(onClick = {
                            if (isListening) {
                                voiceHelper.stop()
                                if (voicePartial.isNotBlank()) { input = voicePartial }
                                isListening = false; voicePartial = ""
                            } else {
                                voiceHelper.start()
                            }
                        }, enabled = !busy, modifier = Modifier.size(36.dp)) {
                            if (isListening) {
                                Icon(Icons.Filled.KeyboardVoice, "停止",
                                    modifier = Modifier.size(20.dp),
                                    tint = MaterialTheme.colorScheme.error)
                            } else {
                                Icon(Icons.Filled.KeyboardVoice, "语音",
                                    modifier = Modifier.size(20.dp),
                                    tint = if (busy) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.primary)
                            }
                        }
                    } else {
                        // 无语音引擎 → 用录音 + Whisper 转文字
                        IconButton(onClick = {
                            if (audioRecorder.start()) isFallbackRecording = true
                            else Toast.makeText(context, "录音启动失败", Toast.LENGTH_SHORT).show()
                        }, enabled = !busy, modifier = Modifier.size(36.dp)) {
                            Icon(Icons.Filled.KeyboardVoice, "开始录音",
                                modifier = Modifier.size(20.dp),
                                tint = MaterialTheme.colorScheme.primary)
                        }
                    }
                    // 文本框(无边框,融入胶囊背景)
                    androidx.compose.foundation.text.BasicTextField(
                        value = input,
                        onValueChange = { input = it },
                        modifier = Modifier.weight(1f).padding(horizontal = 8.dp, vertical = 8.dp),
                        textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface),
                        singleLine = true,
                        decorationBox = { inner ->
                            Box {
                                if (input.isEmpty()) Text(chatMode.hint,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                    style = MaterialTheme.typography.bodyMedium)
                                inner()
                            }
                        },
                    )
                    // 发送/终止按钮(圆形):忙时变红色终止按钮,点击结束当前任务
                    if (busy) {
                        IconButton(
                            onClick = { ttsHelper.stop(); CloudTTS.stop(); ChatWorker.stop() },
                            modifier = Modifier.size(36.dp).background(
                                MaterialTheme.colorScheme.error, shape = RoundedCornerShape(50)),
                        ) {
                            Icon(Icons.Filled.Stop, "终止", modifier = Modifier.size(18.dp),
                                tint = MaterialTheme.colorScheme.onError)
                        }
                    } else {
                        IconButton(
                            onClick = { doSend(input) },
                            modifier = Modifier.size(36.dp).background(
                                if (input.isNotBlank()) MaterialTheme.colorScheme.primary else Color.Transparent,
                                shape = RoundedCornerShape(50)),
                        ) {
                            Icon(Icons.Filled.ArrowUpward, "发送", modifier = Modifier.size(18.dp),
                                tint = if (input.isNotBlank()) MaterialTheme.colorScheme.onPrimary
                                       else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                // 单一全能模式:不再列出模式标签,模型按内容自动判断
            }
        }
    } // end CompositionLocalProvider
    }
}

// 欢迎页(极简:NOUS + 每日文字;备考/进度在「学习」页)
@Composable
fun WelcomePane(dailyText: String, dailyAuthor: String, onQuick: (String) -> Unit, modifier: Modifier = Modifier) {
    val cs = MaterialTheme.colorScheme
    val ctx = LocalContext.current
    // 后台拉简报只为调度今日通知(到点提醒),不在首页渲染,保持主页简洁
    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            try {
                val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/learn/brief?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"; conn.connectTimeout = 6000; conn.readTimeout = 8000
                if (conn.responseCode == 200) {
                    val j = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    j.optJSONObject("brief")?.optJSONArray("timeline")?.let { tl ->
                        val items = (0 until tl.length()).mapNotNull { i ->
                            val t = tl.getJSONObject(i)
                            val time = t.optString("time")
                            if (time.contains(":")) Triple(time, "学习提醒", t.optString("text")) else null
                        }
                        if (items.isNotEmpty()) ReminderScheduler.scheduleToday(ctx, items)
                    }
                }
                conn.disconnect()
            } catch (_: Exception) {}
        }
    }

    Column(
        modifier = modifier.padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("NOUS", style = MaterialTheme.typography.headlineMedium,
            fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = cs.onBackground)
        if (dailyText.isNotBlank()) {
            Spacer(Modifier.height(16.dp))
            Text(dailyText, fontSize = 14.sp, color = cs.onBackground, textAlign = TextAlign.Center)
            if (dailyAuthor.isNotBlank())
                Text("— $dailyAuthor", fontSize = 11.sp, color = cs.onSurfaceVariant)
        }
    }
}

// 助手实时气泡
@Composable
fun AssistantBubble(reply: String, steps: List<LiveStep>, isThinking: Boolean) {
    var expanded by remember { mutableStateOf(false) }
    val cs = MaterialTheme.colorScheme
    val bg = if (isThinking) cs.primary.copy(alpha = 0.10f) else cs.surfaceVariant
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Surface(modifier = Modifier.widthIn(max = AssistantBubbleMaxWidth),
            shape = RoundedCornerShape(20.dp, 20.dp, 20.dp, 6.dp), color = bg) {
            Column(modifier = Modifier.padding(14.dp)) {
                if (reply.isNotEmpty()) MarkdownText(reply)
                else if (isThinking) Text("正在思考…", style = MaterialTheme.typography.bodyMedium, color = cs.onSurfaceVariant)
                if (steps.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    val doneCount = steps.count { it.done }
                    Text("执行 $doneCount/${steps.size}", style = MaterialTheme.typography.labelSmall, color = cs.onSurfaceVariant)
                    Spacer(Modifier.height(4.dp))
                    (if (expanded) steps else steps.takeLast(3)).forEach { step ->
                        Row(modifier = Modifier.padding(vertical = 2.dp)) {
                            Text(if (step.done) "✓" else "○", fontSize = 11.sp,
                                color = if (step.done) cs.primary else cs.onSurfaceVariant, modifier = Modifier.width(16.dp))
                            Text(step.command, style = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = cs.onSurfaceVariant),
                                modifier = Modifier.weight(1f))
                        }
                    }
                    if (steps.size > 3) TextButton(onClick = { expanded = !expanded }, modifier = Modifier.height(26.dp)) {
                        Text(if (expanded) "收起" else "展开全部 ${steps.size} 步", fontSize = 11.sp)
                    }
                }
            }
        }
    }
}

// 用户气泡
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun UserBubble(text: String) {
    val context = LocalContext.current; val cs = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        Surface(modifier = Modifier.widthIn(max = UserBubbleMaxWidth).combinedClickable(onClick = {}, onLongClick = {
            (context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as ClipboardManager)
                .setPrimaryClip(ClipData.newPlainText("消息", text))
            Toast.makeText(context, "已复制", Toast.LENGTH_SHORT).show()
        }), shape = RoundedCornerShape(20.dp, 20.dp, 6.dp, 20.dp), color = cs.primary) {
            SelectionContainer {
                Text(text, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                    style = MaterialTheme.typography.bodyMedium, color = cs.onPrimary)
            }
        }
    }
}

// 历史助手气泡
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun AssistantHistoryBubble(msg: ChatMessage) {
    val context = LocalContext.current; var expanded by remember { mutableStateOf(false) }
    val stepLines = msg.steps.split("\n").filter { it.isNotBlank() }; val cs = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Surface(modifier = Modifier.widthIn(max = AssistantBubbleMaxWidth).combinedClickable(onClick = {}, onLongClick = {
            val text = if (msg.steps.isNotBlank()) "${msg.content}\n---\n${msg.steps}" else msg.content
            (context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as ClipboardManager)
                .setPrimaryClip(ClipData.newPlainText("消息", text))
            Toast.makeText(context, "已复制", Toast.LENGTH_SHORT).show()
        }), shape = RoundedCornerShape(20.dp, 20.dp, 20.dp, 6.dp), color = cs.surfaceVariant) {
            Column(modifier = Modifier.padding(14.dp)) {
                MarkdownText(msg.content)
                if (stepLines.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text("已执行 ${stepLines.size} 条命令", style = MaterialTheme.typography.labelSmall, color = cs.onSurfaceVariant)
                    Spacer(Modifier.height(4.dp))
                    (if (expanded) stepLines else stepLines.takeLast(2)).forEach { line ->
                        Text("✓ ${line.removePrefix("$ ")}", style = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = cs.onSurfaceVariant),
                            modifier = Modifier.padding(vertical = 1.dp))
                    }
                    if (stepLines.size > 2) TextButton(onClick = { expanded = !expanded }, modifier = Modifier.height(26.dp)) {
                        Text(if (expanded) "收起" else "展开全部 ${stepLines.size} 条", fontSize = 11.sp)
                    }
                }
            }
        }
    }
}

@Composable
fun MessageBubble(msg: ChatMessage) {
    if (msg.role == "user") UserBubble(msg.content) else AssistantHistoryBubble(msg)
}
