package com.example.remoteterminal

import android.app.*
import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import java.io.ByteArrayOutputStream

/**
 * 语音唤醒服务 — 后台持续监听"嘿 Nous"唤醒词。
 */
class WakeWordService : Service() {

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var audioRecord: AudioRecord? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var enabled = false

    companion object {
        private const val TAG = "WakeWord"
        private const val NOTIFICATION_ID = 200
        private const val CHANNEL_ID = "nous_wakeword"
        private const val SAMPLE_RATE = 16000
        private const val BUFFER_SIZE = SAMPLE_RATE / 2  // 0.25s buffer
        // 阈值:环境噪声 RMS≈500~1300,偶尔 1760,设为 2000 抓语音
        private const val VAD_THRESHOLD = 2000.0
        private const val HANGOVER_MS = 300L           // 静音多久算一句结束(缩短,更快响应)
        private const val MIN_SEG_BYTES = SAMPLE_RATE * 2 * 2 / 10   // ≥0.2s 才送转写
        private const val MAX_SEG_BYTES = SAMPLE_RATE * 2 * 3        // 上限3s(whisper需要足够上下文,太短会幻觉)
        private const val COOLDOWN_MS = 2000L          // 唤醒冷却(缩短,减少等)
        private const val MERGE_WINDOW_MS = 300L       // 说完后等多久合并邻近句(纯"Nous"无需长等;"在吗Nous"靠服务器前缀兜)

        data class WakeEvent(val source: String, val greeting: String)
        val wakeEvents = MutableSharedFlow<WakeEvent>(extraBufferCapacity = 1)
        // 息屏/后台唤醒:Activity 还没起来时,暂存问候语供 ChatScreen 冷启动消费
        @Volatile var pendingGreeting: String? = null
        private const val LAUNCH_CHANNEL_ID = "nous_wake_launch"
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("待命中…"))
        Log.d(TAG, "Service created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.d(TAG, "onStartCommand action=${intent?.action}")
        when (intent?.action) {
            "start" -> startListening()
            "stop" -> stopListening()
            "toggle" -> if (enabled) stopListening() else startListening()
            else -> startListening()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startListening() {
        if (enabled) return
        Log.d(TAG, "startListening...")
        doStartListening()
    }

    private fun doStartListening(retries: Int = 0) {
        if (enabled) return
        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val bufSize = maxOf(minBuf, BUFFER_SIZE)
        Log.d(TAG, "AudioRecord minBuf=$minBuf bufSize=$bufSize retry=$retries")

        try {
            audioRecord = AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufSize)
        } catch (e: Exception) {
            Log.e(TAG, "AudioRecord create failed: ${e.message}")
            if (retries < 3) {
                updateNotification("⚠ 麦克风暂不可用,${(retries+1)*500}ms后重试…")
                scope.launch { kotlinx.coroutines.delay((retries + 1) * 500L); doStartListening(retries + 1) }
            } else {
                updateNotification("⚠ 麦克风不可用: ${e.message}")
            }
            return
        }

        if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "AudioRecord not initialized, state=${audioRecord?.state}")
            audioRecord?.release(); audioRecord = null
            if (retries < 3) {
                updateNotification("⚠ 录音初始化失败,${(retries+1)*500}ms后重试…")
                scope.launch { kotlinx.coroutines.delay((retries + 1) * 500L); doStartListening(retries + 1) }
            } else {
                updateNotification("⚠ 录音初始化失败(已重试3次)")
            }
            return
        }

        try {
            audioRecord?.startRecording()
            Log.d(TAG, "AudioRecord started, recordingState=${audioRecord?.recordingState}")
        } catch (e: Exception) {
            Log.e(TAG, "startRecording failed: ${e.message}")
            audioRecord?.release(); audioRecord = null
            if (retries < 3) {
                scope.launch { kotlinx.coroutines.delay((retries + 1) * 500L); doStartListening(retries + 1) }
            } else {
                updateNotification("⚠ 录音启动失败")
            }
            return
        }

        enabled = true
        acquireWakeLock()
        updateNotification("🔊 待命中…(说「Nous」唤醒)")
        Log.d(TAG, "Listening started, VAD threshold=$VAD_THRESHOLD")

        scope.launch {
            listenLoop()
        }
    }

    private fun stopListening() {
        Log.d(TAG, "stopListening")
        enabled = false
        try { audioRecord?.stop() } catch (_: Exception) {}
        try { audioRecord?.release() } catch (_: Exception) {}
        audioRecord = null
        releaseWakeLock()
        updateNotification("待命中…")
    }

    private var checking = false

    private suspend fun listenLoop() {
        val buffer = ShortArray(BUFFER_SIZE)
        val seg = ByteArrayOutputStream()
        var speaking = false
        var silenceStart = 0L
        var utteranceEnded = false  // 说完后在合并窗口内等可能的后续("在吗"+"Nous")
        var utteranceEndTime = 0L
        var loopCount = 0
        Log.d(TAG, "listenLoop started (HANGOVER=${HANGOVER_MS}ms MERGE=${MERGE_WINDOW_MS}ms)")

        while (enabled) {
            val readSize = try {
                audioRecord?.read(buffer, 0, BUFFER_SIZE) ?: -1
            } catch (e: Exception) {
                Log.e(TAG, "AudioRecord.read error: ${e.message}"); -1
            }
            if (readSize <= 0) {
                if (readSize == AudioRecord.ERROR_INVALID_OPERATION || readSize == AudioRecord.ERROR_DEAD_OBJECT) break
                continue
            }

            var sum = 0.0
            for (i in 0 until readSize) { val s = buffer[i].toDouble(); sum += s * s }
            val rms = kotlin.math.sqrt(sum / readSize)
            val now = System.currentTimeMillis()

            if (rms > VAD_THRESHOLD) {
                if (!speaking) {
                    if (utteranceEnded) {
                        Log.d(TAG, ">>> VAD merge: continuing after brief pause")
                    } else {
                        Log.i(TAG, ">>> VAD speech start RMS=%.0f".format(rms))
                    }
                }
                speaking = true; utteranceEnded = false; silenceStart = 0L
                appendPcm(seg, buffer, readSize)
                // 滑动窗口:超出上限时丢弃前半,保留最后 MAX_SEG_BYTES
                if (seg.size() > MAX_SEG_BYTES) {
                    val raw = seg.toByteArray()
                    seg.reset()
                    seg.write(raw, raw.size - MAX_SEG_BYTES, MAX_SEG_BYTES)
                }
            } else if (speaking) {
                appendPcm(seg, buffer, readSize)   // 带上尾音,别切字
                if (silenceStart == 0L) silenceStart = now
                else if (now - silenceStart > HANGOVER_MS) {
                    // 说完 → 进入合并窗口,等可能的后半句("在吗"→"Nous")
                    speaking = false; utteranceEnded = true; utteranceEndTime = now; silenceStart = 0L
                }
            } else if (utteranceEnded) {
                // 合并窗口内继续追加(保留停顿,让 whisper vad_filter 自己过滤)
                appendPcm(seg, buffer, readSize)
                if (now - utteranceEndTime > MERGE_WINDOW_MS) {
                    // 合并窗口到期,真正处理
                    utteranceEnded = false
                    var bytes = seg.toByteArray(); seg.reset()
                    // 超长不整段丢,裁掉前面、保留最后 MAX_SEG_BYTES(唤醒词在末尾)
                    if (bytes.size > MAX_SEG_BYTES) bytes = bytes.copyOfRange(bytes.size - MAX_SEG_BYTES, bytes.size)
                    if (bytes.size >= MIN_SEG_BYTES) checkWake(bytes)
                }
            }
        }
        Log.d(TAG, "listenLoop exited")
    }

    /** 息屏/后台被唤醒:点亮屏幕 + 用全屏 intent 通知把 App 拉到前台。 */
    private fun launchForWake(greeting: String) {
        // App 已在前台:ChatScreen 会通过 wakeEvents 直接处理,无需拉起(避免重启 Activity 打断问候朗读)
        if (MainActivity.isForeground) return
        try {
            // 1) 点亮屏幕(短暂)
            try {
                val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                @Suppress("DEPRECATION")
                val wl = pm.newWakeLock(
                    PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP or PowerManager.ON_AFTER_RELEASE,
                    "Nous:wakeScreen")
                wl.acquire(8000)
            } catch (_: Exception) {}
            // 2) 构造拉起 MainActivity 的 intent
            val launch = Intent(this, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
                putExtra("from_wake", true)
            }
            // 直接尝试启动(前台服务+点屏后通常可行)
            try { startActivity(launch) } catch (_: Exception) {}
            // 3) 全屏 intent 通知兜底(锁屏/息屏下由系统拉起 Activity,和来电一样)
            val pi = PendingIntent.getActivity(this, 2, launch,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val n = NotificationCompat.Builder(this, LAUNCH_CHANNEL_ID)
                .setContentTitle("Nous").setContentText(greeting)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setFullScreenIntent(pi, true)
                .setAutoCancel(true)
                .setTimeoutAfter(8000)
                .build()
            getSystemService(NotificationManager::class.java).notify(201, n)
        } catch (e: Exception) {
            Log.e(TAG, "launchForWake failed: ${e.message}")
        }
    }

    private fun appendPcm(out: ByteArrayOutputStream, buf: ShortArray, n: Int) {
        for (i in 0 until n) { val v = buf[i].toInt(); out.write(v and 0xFF); out.write((v shr 8) and 0xFF) }
    }

    private var lastWakeEmit = 0L

    // 真·唤醒词:把这段语音送服务器转写,只有听到"Nous/诺"等才唤醒,否则忽略(杜绝环境噪声误触发)
    private fun checkWake(pcm: ByteArray) {
        if (checking) return
        if (System.currentTimeMillis() - lastWakeEmit < COOLDOWN_MS) return
        checking = true
        scope.launch {
            try {
                val result = ChatWorker.transcribeWake(pcm, SAMPLE_RATE)
                Log.d(TAG, "wake check → isWake=${result.isWake} greeting=${result.greeting}")
                if (result.isWake) {
                    lastWakeEmit = System.currentTimeMillis()
                    Log.i(TAG, "WAKE MATCHED (server) greeting=${result.greeting}")
                    updateNotification("✅ 已唤醒")
                    pendingGreeting = result.greeting          // 冷启动兜底
                    wakeEvents.emit(WakeEvent("voice_wake", result.greeting))  // 前台直接收
                    launchForWake(result.greeting)             // 息屏/后台:点亮+拉起 App
                    delay(2500); updateNotification("🔊 待命中…")
                }
            } catch (e: Exception) {
                Log.e(TAG, "checkWake error: ${e.message}")
            } finally {
                checking = false
            }
        }
    }

    // 注:唤醒词匹配在服务端 /transcribe?hint=wake 完成(可随时调整,无需重建 App)。
    // 保留此函数供将来可能的本地快速初筛使用。
    @Suppress("unused")
    private fun isWakeWord(text: String): Boolean {
        if (text.isBlank()) return false
        val t = text.lowercase().replace(Regex("[\\s,，。.!！?？、~'’\"-]"), "")
        if (t.length > 12) return false
        val kws = listOf(
            "nous", "nu's", "no's", "knous", "noose", "news", "newce",
            "诺斯", "努斯", "纽斯", "闹斯", "拿斯", "那斯", "糯斯", "诺丝", "努丝", "诺司", "努司",
            "诺", "努", "纽", "糯", "喏", "懦",
            "你好诺", "小诺", "嘿诺", "黑诺", "嗨诺", "嘿nous", "嗨nous", "你好nous")
        return kws.any { t.contains(it) }
    }

    override fun onDestroy() {
        stopListening()
        scope.cancel()
        super.onDestroy()
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Nous:WakeWord")
        wakeLock?.acquire(10 * 60 * 1000L)
    }

    private fun releaseWakeLock() {
        try { wakeLock?.release() } catch (_: Exception) {}
        wakeLock = null
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(
                CHANNEL_ID, "Nous 语音唤醒", NotificationManager.IMPORTANCE_LOW))
            // 全屏拉起用高优先级频道(息屏/锁屏下才能像来电一样唤起界面)
            nm.createNotificationChannel(NotificationChannel(
                LAUNCH_CHANNEL_ID, "Nous 唤醒拉起", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "听到唤醒词时点亮并打开 Nous"
                    setShowBadge(false)
                })
        }
    }

    private fun buildNotification(status: String): Notification {
        val pi = PendingIntent.getActivity(this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val toggleIntent = Intent(this, WakeWordService::class.java).apply { action = "toggle" }
        val togglePi = PendingIntent.getService(this, 1, toggleIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Nous 语音唤醒")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .setContentIntent(pi)
            .addAction(android.R.drawable.ic_media_pause, "暂停", togglePi)
            .build()
    }

    private fun updateNotification(status: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIFICATION_ID, buildNotification(status))
    }
}
