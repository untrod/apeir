package com.example.remoteterminal

import android.media.AudioAttributes
import android.media.MediaPlayer
import android.util.Log
import kotlinx.coroutines.*
import java.io.File
import java.net.HttpURLConnection
import java.net.URLEncoder

/**
 * 云端 TTS——调 Brain /tts 端点(Edge TTS,免费)生成 MP3 并播放。
 * 用于无本地 TTS 引擎的设备(手表等)。
 */
object CloudTTS {
    private const val TAG = "CloudTTS"
    private var player: MediaPlayer? = null
    private var currentJob: Job? = null
    @Volatile var isSpeaking = false; private set
    var onAllDone: (() -> Unit)? = null

    /** 朗读一句(打断之前)。只适合短文本,长文本会被截断。 */
    fun speak(text: String) {
        stop()
        val t = text.trim().take(300)
        if (t.isBlank()) return
        currentJob = CoroutineScope(Dispatchers.IO).launch {
            try {
                val audio = fetchTtsAudio(t)
                if (audio != null) {
                    playAudio(audio)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Cloud TTS failed", e)
                isSpeaking = false
                onAllDone?.invoke()
            }
        }
    }

    fun stop() {
        currentJob?.cancel()
        currentJob = null
        try { player?.stop() } catch (_: Exception) {}
        try { player?.release() } catch (_: Exception) {}
        player = null
        isSpeaking = false
    }

    private suspend fun fetchTtsAudio(text: String): File? = withContext(Dispatchers.IO) {
        try {
            // 经 Brain 网关转发 /tts → Agent,避免手表需单独配 Agent IP
            val url = java.net.URL("http://${Config.HOST}:${Config.BRAIN_PORT}/tts")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"; conn.doOutput = true
            conn.connectTimeout = 8000; conn.readTimeout = 15000
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
            // 防重放(公网暴露时 Brain 强制校验)
            val (ts, nonce) = antiReplay()
            conn.setRequestProperty("X-Timestamp", ts)
            conn.setRequestProperty("X-Nonce", nonce)
            val body = "{\"text\":\"${text.replace("\"","\\\"")}\"}"
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            if (conn.responseCode != 200) { conn.disconnect(); return@withContext null }
            val tmp = File.createTempFile("nous_tts_", ".mp3")
            conn.inputStream.use { input -> tmp.outputStream().use { output -> input.copyTo(output) } }
            conn.disconnect()
            if (tmp.length() > 0) tmp else null
        } catch (e: Exception) {
            Log.e(TAG, "Fetch TTS failed", e)
            null
        }
    }

    private fun playAudio(file: File) {
        try {
            player?.release()
            player = MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .setUsage(AudioAttributes.USAGE_ASSISTANT).build())
                setDataSource(file.absolutePath)
                setOnPreparedListener {
                    isSpeaking = true
                    start()
                }
                setOnCompletionListener {
                    isSpeaking = false
                    release(); player = null
                    file.delete()
                    onAllDone?.invoke()
                }
                setOnErrorListener { _, _, _ ->
                    isSpeaking = false
                    release(); player = null
                    file.delete()
                    onAllDone?.invoke()
                    true
                }
                prepareAsync()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Play audio failed", e)
            isSpeaking = false
            player?.release(); player = null
            file.delete()
            onAllDone?.invoke()
        }
    }
}
