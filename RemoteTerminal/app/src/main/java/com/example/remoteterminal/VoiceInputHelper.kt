package com.example.remoteterminal

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log

/**
 * 语音输入辅助类 — 用 Android 原生 SpeechRecognizer，不依赖 Google。
 * 国产手机(小米/华为/OPPO/vivo)自带语音引擎都能用。
 * 支持持续监听、静音检测、错误回退到 Intent 模式。
 */
class VoiceInputHelper(private val context: Context) {
    private var recognizer: SpeechRecognizer? = null
    private var listener: VoiceListener? = null
    var isListening = false
        private set

    interface VoiceListener {
        fun onReady()                              // 麦克风就绪，可以说话
        fun onSpeechStart()                        // 检测到用户开始说话（onBeginningOfSpeech）{}
        fun onPartial(text: String)                // 实时部分结果
        fun onResult(text: String)                 // 最终结果
        fun onSilence()                            // 检测到静音
        fun onError(message: String)               // 出错
        fun onRmsChanged(rmsDb: Float)             // 音量变化(0-10)，做波形动画
    }

    /** 创建 SpeechRecognizer，优先用系统默认(不指定 Google) */
    fun init(listener: VoiceListener) {
        this.listener = listener
        try {
            // isRecognitionAvailable 检测设备是否有语音服务
            if (!SpeechRecognizer.isRecognitionAvailable(context)) {
                listener.onError("此设备不支持语音识别")
                return
            }
            recognizer = SpeechRecognizer.createSpeechRecognizer(context)
            recognizer?.setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    isListening = true
                    listener.onReady()
                }

                override fun onBeginningOfSpeech() {
                    listener.onSpeechStart()
                }

                override fun onRmsChanged(rmsdB: Float) {
                    listener.onRmsChanged(rmsdB)
                }

                override fun onBufferReceived(buffer: ByteArray?) {}

                override fun onEndOfSpeech() {
                    listener.onSilence()
                }

                override fun onError(error: Int) {
                    isListening = false
                    val msg = when (error) {
                        SpeechRecognizer.ERROR_AUDIO -> "麦克风错误"
                        SpeechRecognizer.ERROR_CLIENT -> "客户端错误"
                        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "没有录音权限"
                        SpeechRecognizer.ERROR_NETWORK -> "网络不可用(离线模式可能需要下载语言包)"
                        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "语音服务超时"
                        SpeechRecognizer.ERROR_NO_MATCH -> "未识别到语音"
                        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "语音服务忙碌"
                        SpeechRecognizer.ERROR_SERVER -> "语音服务错误"
                        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "说话超时"
                        else -> "语音错误 ($error)"
                    }
                    listener.onError(msg)
                }

                override fun onResults(results: Bundle?) {
                    isListening = false
                    val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    if (!matches.isNullOrEmpty()) {
                        listener.onResult(matches[0])
                    }
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    if (!matches.isNullOrEmpty()) {
                        listener.onPartial(matches[0])
                    }
                }

                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
        } catch (e: Exception) {
            listener.onError("语音引擎初始化失败: ${e.message}")
        }
    }

    /** 开始监听(中文优先，连续模式) */
    fun start() {
        if (recognizer == null) {
            listener?.onError("语音引擎未初始化")
            return
        }
        try {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                // 中文优先，回退英文
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "zh-CN;en-US")
                // 开启部分结果(实时显示)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                // 最长静音后自动结束(3秒)
                putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 3000)
                putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1500)
            }
            recognizer?.startListening(intent)
        } catch (e: Exception) {
            listener?.onError("启动语音失败: ${e.message}")
        }
    }

    /** 停止监听 */
    fun stop() {
        try {
            recognizer?.stopListening()
        } catch (_: Exception) {}
        isListening = false
    }

    /** 取消(不返回结果) */
    fun cancel() {
        try {
            recognizer?.cancel()
        } catch (_: Exception) {}
        isListening = false
    }

    /** 释放资源 */
    fun destroy() {
        try {
            recognizer?.cancel()
            recognizer?.destroy()
        } catch (_: Exception) {}
        recognizer = null
        isListening = false
    }

    companion object {
        private const val TAG = "VoiceInput"

        /** 快速检测是否支持语音 */
        fun isSupported(context: Context): Boolean {
            return SpeechRecognizer.isRecognitionAvailable(context)
        }
    }
}
