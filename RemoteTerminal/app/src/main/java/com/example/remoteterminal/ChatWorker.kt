package com.example.remoteterminal

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * 聊天工作者:在独立的 CoroutineScope 里执行网络请求,不随 UI 切页面/进后台被取消。
 *
 * 根因:Compose 的 rememberCoroutineScope 绑定在 Composable 生命周期,
 * ChatScreen 销毁(切到设置页/后台)时协程被取消 → 正在进行的请求中断 → 助手回复丢失。
 *
 * 修法:这个单例持有自己的 scope(SupervisorJob,不会因子任务失败全停),
 * 请求完成后结果写入 DB;UI 回来时从 DB 加载,不丢数据。
 */
object ChatWorker {
    // 独立 scope:不随任何 Composable 销毁
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    // 当前任务 Job(用于用户主动终止)
    private var currentJob: Job? = null

    // 当前是否有任务在跑(UI 读这个显示"处理中")
    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    // 当前任务的会话 ID(让 UI 知道是哪个会话在忙)
    private val _activeSessionId = MutableStateFlow("")
    val activeSessionId: StateFlow<String> = _activeSessionId

    // 实时状态(思考中/步骤),UI 读这些渲染 pending 气泡
    private val _pendingReply = MutableStateFlow("")
    val pendingReply: StateFlow<String> = _pendingReply

    private val _pendingSteps = MutableStateFlow<List<LiveStep>>(emptyList())
    val pendingSteps: StateFlow<List<LiveStep>> = _pendingSteps

    private val _isThinking = MutableStateFlow(false)
    val isThinking: StateFlow<Boolean> = _isThinking

    // 流式回复:逐 token 累积的正文(UI 打字机显示)
    private val _streamingReply = MutableStateFlow("")
    val streamingReply: StateFlow<String> = _streamingReply

    // 待朗读的句子队列(语音模式按句即读)。replay=0 只发给当前订阅者。
    private val _speechQueue = kotlinx.coroutines.flow.MutableSharedFlow<String>(extraBufferCapacity = 32)
    val speechQueue: kotlinx.coroutines.flow.SharedFlow<String> = _speechQueue
    // 内部:累积未成句的尾巴
    private var speechBuffer = StringBuilder()

    /** 把流式增量切句,完整句子推入朗读队列,残句留着。 */
    private fun feedSpeech(delta: String, flushAll: Boolean = false) {
        speechBuffer.append(delta)
        // 按中英文句末标点切句
        val text = speechBuffer.toString()
        val marks = charArrayOf('。', '！', '？', '\n', '.', '!', '?', '；', ';')
        var lastCut = 0
        var i = 0
        while (i < text.length) {
            if (text[i] in marks) {
                val sentence = text.substring(lastCut, i + 1).trim()
                if (sentence.length >= 2) _speechQueue.tryEmit(sentence)
                lastCut = i + 1
            }
            i++
        }
        speechBuffer = StringBuilder(text.substring(lastCut))
        if (flushAll && speechBuffer.isNotBlank()) {
            _speechQueue.tryEmit(speechBuffer.toString().trim())
            speechBuffer = StringBuilder()
        }
    }

    // 确认请求(弹窗)
    data class ConfirmRequest(val id: String, val command: String, val dangers: List<String>)
    private val _confirmRequest = MutableStateFlow<ConfirmRequest?>(null)
    val confirmRequest: StateFlow<ConfirmRequest?> = _confirmRequest

    fun clearConfirmRequest() { _confirmRequest.value = null }

    /**
     * 发送消息。在独立 scope 里跑,切页面/后台不会中断。
     * 完成后自动存 DB。
     */
    fun send(
        db: AppDatabase,
        sessionId: String,
        text: String,
        model: String,
    ) {
        if (_busy.value) return  // 防重复点
        _busy.value = true
        _activeSessionId.value = sessionId
        _isThinking.value = true
        _pendingReply.value = ""
        _pendingSteps.value = emptyList()

        currentJob = scope.launch {
          try {
            // 先存用户消息到 DB
            withContext(Dispatchers.IO) {
                db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "user", content = text, steps = ""))
            }

            // 快速探测连通性
            val pingErr = quickPing()
            if (pingErr != null) {
                _isThinking.value = false
                _busy.value = false
                withContext(Dispatchers.IO) {
                    db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = pingErr, steps = ""))
                }
                return@launch
            }

            // 重置流式状态
            _streamingReply.value = ""; speechBuffer = StringBuilder()

            // SSE 流式请求(主路径)
            sendChatStream(
                sessionId = sessionId, message = text, model = model, token = Config.AUTH_TOKEN,
                onStep = { cmd, out, _ ->
                    if (cmd == "思考中...") {
                        _isThinking.value = true; _pendingReply.value = "思考中..."
                    } else {
                        _isThinking.value = false
                        val cur = _pendingSteps.value.toMutableList()
                        val idx = cur.indexOfFirst { it.command == cmd && !it.done }
                        if (idx >= 0) cur[idx] = cur[idx].copy(output = out, done = true)
                        else cur.add(LiveStep(cmd, out, true))
                        _pendingSteps.value = cur
                        if (_pendingReply.value.let { it == "思考中..." || it.isEmpty() }) _pendingReply.value = "正在执行..."
                    }
                },
                onConfirmation = { cid, cmd, dangers ->
                    _confirmRequest.value = ConfirmRequest(cid, cmd, dangers)
                },
                onReplyDelta = { delta ->
                    // 逐 token 累积 → 打字机显示 + 喂朗读
                    _isThinking.value = false
                    _streamingReply.value = _streamingReply.value + delta
                    _pendingReply.value = _streamingReply.value
                    feedSpeech(delta)
                },
                onDone = { reply, steps ->
                    _isThinking.value = false
                    feedSpeech("", flushAll = true)  // 把残句也读出来
                    _streamingReply.value = ""
                    _pendingReply.value = ""; _pendingSteps.value = emptyList()
                    val stepsText = steps.joinToString("\n") { it.command }
                    // 存到 DB(即使 UI 已切走,数据也不丢)
                    scope.launch(Dispatchers.IO) {
                        db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = reply, steps = stepsText))
                    }
                    _busy.value = false
                },
                onError = { _ ->
                    // SSE 失败,回退到非流式
                    _isThinking.value = false; _pendingReply.value = ""; _pendingSteps.value = emptyList()
                    scope.launch {
                        val r = sendChat(sessionId, text, model)
                        if (r.ok) {
                            feedSpeech(r.reply, flushAll = true)  // 非流式回退也要朗读(语音模式)
                            scope.launch(Dispatchers.IO) {
                                db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = r.reply, steps = r.steps))
                            }
                        } else {
                            scope.launch(Dispatchers.IO) {
                                db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = "出错:${r.error}", steps = ""))
                            }
                        }
                        _busy.value = false
                    }
                },
            )
            // 不再做超时强制解锁:任务多久都不打断,只有用户点终止(stop)才结束。
          } catch (e: kotlinx.coroutines.CancellationException) {
              throw e  // 用户主动终止,正常传播
          } catch (e: Throwable) {
              // 息屏/切后台/网络异常:绝不让 UI 永久卡住或崩溃
              _isThinking.value = false; _pendingReply.value = ""; _pendingSteps.value = emptyList()
              _busy.value = false
          }
        }
    }

    /** 用户主动终止当前任务。取消进行中的请求并解锁。 */
    fun stop() {
        currentJob?.cancel()
        currentJob = null
        _isThinking.value = false
        _pendingReply.value = ""
        _pendingSteps.value = emptyList()
        _busy.value = false
    }

    /**
     * 终端模式:跳过 LLM,直接发命令到 Agent /exec。
     * 秒出结果,适合快速敲命令。
     */
    fun sendDirect(
        db: AppDatabase,
        sessionId: String,
        command: String,
    ) {
        if (_busy.value) return
        _busy.value = true
        _activeSessionId.value = sessionId
        _isThinking.value = false
        _pendingReply.value = "执行中..."; _pendingSteps.value = emptyList()
        scope.launch {
            withContext(Dispatchers.IO) {
                db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "user", content = "$ $command", steps = ""))
            }
            try {
                val result = withContext(Dispatchers.IO) { directExec(command) }
                _pendingReply.value = ""; _pendingSteps.value = emptyList()
                withContext(Dispatchers.IO) {
                    db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = result, steps = "$ $command"))
                }
            } catch (e: Exception) {
                withContext(Dispatchers.IO) {
                    db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = "执行失败: ${e.message}", steps = ""))
                }
            }
            _busy.value = false
        }
    }

    // 终端执行:走 brain 代理或直连 agent(取决于 Config.TERMINAL_VIA_BRAIN)
    private suspend fun directExec(command: String): String = withContext(Dispatchers.IO) {
        val url = java.net.URL(Config.EXEC_URL)
        val conn = url.openConnection() as java.net.HttpURLConnection
        conn.requestMethod = "POST"; conn.doOutput = true
        conn.connectTimeout = 10000; conn.readTimeout = Config.TIMEOUT_MS
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        conn.setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
        // 防重放(brain 代理时强制;直连 agent 时 agent 不校验但带着无害)
        val (ts, nonce) = antiReplay()
        conn.setRequestProperty("X-Timestamp", ts)
        conn.setRequestProperty("X-Nonce", nonce)
        val body = org.json.JSONObject().put("command", command).toString()
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        val code = conn.responseCode
        val resp = (if (code in 200..299) conn.inputStream else conn.errorStream)
            ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        conn.disconnect()
        if (code != 200) return@withContext "HTTP $code: $resp"
        val json = org.json.JSONObject(resp)
        val out = buildString {
            val stdout = json.optString("stdout", "")
            val stderr = json.optString("stderr", "")
            if (stdout.isNotBlank()) append(stdout)
            if (stderr.isNotBlank()) {
                if (isNotEmpty()) append("\n")
                append("[stderr]\n$stderr")
            }
            if (isEmpty()) append("(无输出) returncode=${json.optInt("returncode")}")
        }
        out
    }

    /** 处理确认回复(同意/拒绝) */
    fun handleConfirmation(db: AppDatabase, sessionId: String, model: String, confirmId: String, action: String) {
        _confirmRequest.value = null
        _busy.value = true
        scope.launch {
            val r = sendChat(sessionId, "", model, confirmId, action)
            if (r.status == "awaiting_confirmation") {
                _confirmRequest.value = ConfirmRequest(r.confirmationId, r.dangerCommand, r.dangers)
            } else if (r.ok) {
                scope.launch(Dispatchers.IO) {
                    db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = r.reply, steps = r.steps))
                }
            } else {
                scope.launch(Dispatchers.IO) {
                    db.messageDao().insert(LocalMessage(sessionId = sessionId, role = "assistant", content = "出错:${r.error}", steps = ""))
                }
            }
            _pendingReply.value = ""; _pendingSteps.value = emptyList(); _isThinking.value = false
            _busy.value = false
        }
    }

    // 设备在线状态
    data class DeviceInfo(
        val id: String, val name: String, val os: String, val type: String,
        val online: Boolean, val lastSeen: Long, val capabilities: List<String>,
    )
    private val _devices = MutableStateFlow<List<DeviceInfo>>(emptyList())
    val devices: StateFlow<List<DeviceInfo>> = _devices
    private val _defaultDevice = MutableStateFlow("")
    val defaultDevice: StateFlow<String> = _defaultDevice

    private var devicepollStarted = false
    /** 启动设备状态轮询(每 20s 拉一次 /devices)。幂等,只启动一次。 */
    fun startDevicePolling() {
        if (devicepollStarted) return
        devicepollStarted = true
        scope.launch {
            while (true) {
                fetchDeviceStatusOnce()
                delay(20_000)
            }
        }
    }

    /** 拉一次设备状态。 */
    fun fetchDeviceStatusOnce() {
        if (!Config.isConfigured()) return
        scope.launch(Dispatchers.IO) {
            try {
                val url = java.net.URL("http://${Config.HOST}:${Config.BRAIN_PORT}/devices?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "GET"; conn.connectTimeout = 6000; conn.readTimeout = 6000
                if (conn.responseCode != 200) { conn.disconnect(); return@launch }
                val text = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                conn.disconnect()
                val json = org.json.JSONObject(text)
                _defaultDevice.value = json.optString("default_device", "")
                val arr = json.optJSONArray("devices") ?: return@launch
                val list = mutableListOf<DeviceInfo>()
                for (i in 0 until arr.length()) {
                    val d = arr.getJSONObject(i)
                    val caps = mutableListOf<String>()
                    d.optJSONArray("capabilities")?.let { for (j in 0 until it.length()) caps.add(it.getString(j)) }
                    list.add(DeviceInfo(
                        id = d.optString("device_id"), name = d.optString("name"),
                        os = d.optString("os"), type = d.optString("type"),
                        online = d.optBoolean("online", false),
                        lastSeen = d.optLong("last_seen", 0), capabilities = caps,
                    ))
                }
                _devices.value = list
            } catch (_: Exception) { /* 拉不到就保持上次状态 */ }
        }
    }

    // 语音唤醒辅助: PCM → Brain /transcribe
    /**
     * 将原始 PCM 音频发送到 Brain 转写。
     * [pcmBytes] 16-bit mono PCM
     * [sampleRate] 采样率(通常 16000)
     * 返回转写文本，失败返回空串。
     */
    suspend fun transcribeAudio(pcmBytes: ByteArray, sampleRate: Int = 16000, hint: String = ""): String =
        transcribeRaw(pcmBytes, sampleRate, hint)?.optString("text", "") ?: ""

    /** 唤醒判定结果:服务器端做唤醒词匹配,返回是否命中 + 问候语(以后调唤醒词只改服务器,不用重建 App)。 */
    data class WakeResult(val isWake: Boolean, val greeting: String)

    suspend fun transcribeWake(pcmBytes: ByteArray, sampleRate: Int = 16000): WakeResult {
        val r = transcribeRaw(pcmBytes, sampleRate, "wake") ?: return WakeResult(false, "")
        val text = r.optString("text", "")
        val isWake = r.optBoolean("wake", false)
        val greeting = r.optString("greeting", "嗯，请说")  // 兜底:服务器不返回时用默认
        android.util.Log.i("WakeWord", "服务器转写=「$text」 wake=$isWake greeting=$greeting")
        return WakeResult(isWake, greeting)
    }

    private suspend fun transcribeRaw(pcmBytes: ByteArray, sampleRate: Int, hint: String): org.json.JSONObject? {
        return withContext(Dispatchers.IO) {
            try {
                val dataSize = pcmBytes.size
                val wavBuf = java.nio.ByteBuffer.allocate(44 + dataSize).apply {
                    order(java.nio.ByteOrder.LITTLE_ENDIAN)
                    put("RIFF".toByteArray()); putInt(36 + dataSize); put("WAVE".toByteArray())
                    put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1)
                    putInt(sampleRate); putInt(sampleRate * 2); putShort(2); putShort(16)
                    put("data".toByteArray()); putInt(dataSize); put(pcmBytes)
                }
                val hintQ = if (hint.isNotEmpty()) "&hint=$hint" else ""
                val url = java.net.URL("http://${Config.HOST}:${Config.BRAIN_PORT}/transcribe?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}$hintQ")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "POST"; conn.doOutput = true
                conn.connectTimeout = 10000; conn.readTimeout = 15000
                conn.setRequestProperty("Content-Type", "audio/wav")
                conn.outputStream.use { it.write(wavBuf.array()) }
                if (conn.responseCode != 200) { conn.disconnect(); return@withContext null }
                val body = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                conn.disconnect()
                org.json.JSONObject(body)
            } catch (e: Exception) {
                null
            }
        }
    }
}
