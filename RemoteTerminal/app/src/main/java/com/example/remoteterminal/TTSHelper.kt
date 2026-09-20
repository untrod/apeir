package com.example.remoteterminal

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale

/**
 * 文字转语音(TTS)辅助类。
 * 把 AI 回复朗读出来,适合手表/免提/驾车场景。
 * 支持中文优先,回退英文。
 */
class TTSHelper(context: Context) {
    private var tts: TextToSpeech? = null
    private var initialized = false
    private val utteranceId = "nous_tts"
    var isSpeaking = false
        private set
    /** TTS 引擎是否初始化成功（可用于判断设备是否有 TTS 能力）*/
    val isReady: Boolean get() = initialized
    // 队列里还没读完的句子数。归 0 才算"全部读完"。
    @Volatile private var pending = 0
    // 全部读完(队列清空)回调。语音模式用它决定何时重新监听。
    var onAllDone: (() -> Unit)? = null
    var onDone: (() -> Unit)? = null  // 兼容旧调用

    init {
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val result = tts?.setLanguage(Locale.CHINESE)
                if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                    tts?.setLanguage(Locale.US) // 回退英文
                }
                initialized = true
            }
        }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(uttId: String?) { isSpeaking = true }
            override fun onDone(uttId: String?) {
                if (pending > 0) pending--
                if (pending <= 0) { isSpeaking = false; onAllDone?.invoke(); onDone?.invoke() }
            }
            override fun onError(uttId: String?) { if (pending > 0) pending--; if (pending <= 0) isSpeaking = false }
            @Deprecated("")
            override fun onError(uttId: String?, errorCode: Int) { if (pending > 0) pending--; if (pending <= 0) isSpeaking = false }
        })
    }

    private var uttCounter = 0

    /** 清洗 markdown,让 TTS 读起来更自然。 */
    private fun clean(text: String): String = text
        .replace(Regex("```[\\s\\S]*?```"), "，代码省略，")
        .replace(Regex("\\*\\*(.+?)\\*\\*"), "$1")
        .replace(Regex("`(.+?)`"), "$1")
        .replace(Regex("[*#\\[\\]>|]"), "")
        .replace(Regex("\\n+"), "。")
        .trim()

    /** 整段朗读(打断之前的)。会截断过长文本(前 500 字)。 */
    fun speak(text: String) {
        if (!initialized || tts == null) return
        val c = clean(text).take(500)
        if (c.isBlank()) return
        // 先 speak 再设 pending,避免 speak 静默失败导致 pending 永久 >0
        if (tts?.speak(c, TextToSpeech.QUEUE_FLUSH, null, "${utteranceId}_${uttCounter++}") == TextToSpeech.SUCCESS) {
            pending = 1
        }
    }

    /** 追加朗读一句(排队,不打断前一句)。用于流式逐句朗读。 */
    fun enqueue(sentence: String) {
        if (!initialized || tts == null) return
        val c = clean(sentence)
        if (c.isBlank()) return
        // 先 speak 再设 pending,避免 speaks 竞态导致 pending 泄漏
        if (tts?.speak(c, TextToSpeech.QUEUE_ADD, null, "${utteranceId}_${uttCounter++}") == TextToSpeech.SUCCESS) {
            pending++
            isSpeaking = true
        }
    }

    /** 停止朗读(清空队列) */
    fun stop() {
        pending = 0
        tts?.stop()
        isSpeaking = false
    }

    /** 释放资源 */
    fun shutdown() {
        tts?.stop()
        tts?.shutdown()
        tts = null
    }

    companion object {
        fun isAvailable(): Boolean = true // TTS 几乎所有 Android 设备都支持
    }
}
