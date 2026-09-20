package com.example.remoteterminal

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.ContextCompat
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * 音频录制——用 AudioRecord 采集 16kHz mono PCM，写入标准 WAV。
 * Whisper 要求的格式：16kHz, mono, 16-bit PCM。
 */
class AudioRecorder(private val context: Context) {
    companion object {
        private const val TAG = "AudioRecorder"
        private const val SAMPLE_RATE = 16000
        private const val CHANNELS = AudioFormat.CHANNEL_IN_MONO
        private const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
        // VAD 自动停:说完静音这么久就结束(阈值需>环境噪声,手表实测≈1068)
        private const val VAD_THRESHOLD = 2000.0     // RMS:高于此算说话(手表环境噪声≈500~1300)
        private const val SILENCE_MS = 1600L         // 说过话后静音多久判定说完(放长,句中停顿不误切)
        private const val MIN_RECORD_MS = 800L       // 至少录这么久才允许自动停
        private const val MAX_RECORD_MS = 20000L     // 最长录音(防一直不停)
        private const val NO_SPEECH_MS = 6000L       // 开始后一直没人说话就停(给足开口时间)
    }

    private var recorder: AudioRecord? = null
    private var outputFile: File? = null
    private var recordingThread: Thread? = null
    @Volatile var isRecording = false
        private set
    /** 静音自动停回调:返回转好的 WAV 文件(可能为 null)。在主线程调用。 */
    var onAutoStop: ((File?) -> Unit)? = null
    private val finalized = AtomicBoolean(false)
    private val mainHandler = Handler(Looper.getMainLooper())

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    fun start(): Boolean {
        if (isRecording) return true
        if (!hasPermission()) return false
        try {
            val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNELS, ENCODING)
            val bufSize = maxOf(minBuf, SAMPLE_RATE * 2) // 至少 1 秒缓冲区
            recorder = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE, CHANNELS, ENCODING, bufSize
            )
            if (recorder!!.state != AudioRecord.STATE_INITIALIZED) {
                recorder!!.release(); recorder = null
                return false
            }
            outputFile = File.createTempFile("nous_voice_", ".pcm", context.cacheDir)
            finalized.set(false)
            recorder!!.startRecording()
            isRecording = true
            recordingThread = thread(name = "audio-capture") {
                val buf = ByteArray(bufSize)
                val startTime = System.currentTimeMillis()
                var hasSpoken = false
                var lastVoice = startTime
                var autoStop = false
                RandomAccessFile(outputFile, "rw").use { raf ->
                    while (isRecording) {
                        val n = recorder?.read(buf, 0, buf.size) ?: -1
                        if (n > 0) raf.write(buf, 0, n)
                        if (n <= 0) break
                        val now = System.currentTimeMillis()
                        val rms = rmsOf(buf, n)
                        if (rms > VAD_THRESHOLD) { hasSpoken = true; lastVoice = now }
                        // 说过话 + 静音够久 + 录够最短时长 → 自动停
                        if (hasSpoken && now - lastVoice > SILENCE_MS && now - startTime > MIN_RECORD_MS) {
                            autoStop = true; break
                        }
                        if (!hasSpoken && now - startTime > NO_SPEECH_MS) { autoStop = true; break }
                        if (now - startTime > MAX_RECORD_MS) { autoStop = true; break }
                    }
                }
                if (autoStop && finalized.compareAndSet(false, true)) {
                    isRecording = false
                    val f = doFinalize()
                    mainHandler.post { onAutoStop?.invoke(f) }
                }
            }
            Log.d(TAG, "Recording started: ${outputFile!!.absolutePath}")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Start recording failed", e)
            return false
        }
    }

    /** 手动停止(点按钮)。若已被 VAD 自动停,返回 null。 */
    fun stop(): File? {
        if (!finalized.compareAndSet(false, true)) return null
        isRecording = false
        recordingThread?.join(2000)
        recordingThread = null
        return doFinalize()
    }

    /** 停录音 + 转 WAV(stop 与 VAD 自动停共用)。 */
    private fun doFinalize(): File? {
        try { recorder?.stop() } catch (_: Exception) {}
        try { recorder?.release() } catch (_: Exception) {}
        recorder = null
        val pcmFile = outputFile ?: return null
        outputFile = null
        val wavFile = File(pcmFile.parentFile, pcmFile.nameWithoutExtension + ".wav")
        try {
            pcmToWav(pcmFile, wavFile)
        } catch (e: Exception) {
            Log.e(TAG, "PCM→WAV conversion failed", e)
        }
        pcmFile.delete()
        Log.d(TAG, "Recording stopped: ${wavFile.absolutePath}, size=${wavFile.length()}")
        return if (wavFile.exists()) wavFile else null
    }

    /** 16-bit LE PCM 的 RMS 音量。 */
    private fun rmsOf(buf: ByteArray, n: Int): Double {
        var sum = 0.0; var cnt = 0
        var i = 0
        while (i + 1 < n) {
            val s = (buf[i].toInt() and 0xFF) or (buf[i + 1].toInt() shl 8)
            sum += s.toDouble() * s.toDouble(); cnt++
            i += 2
        }
        return if (cnt > 0) kotlin.math.sqrt(sum / cnt) else 0.0
    }

    fun cancel() {
        finalized.set(true)   // 阻止 VAD 线程再触发 onAutoStop
        isRecording = false
        try { recorder?.stop() } catch (_: Exception) {}
        try { recorder?.release() } catch (_: Exception) {}
        recorder = null
        recordingThread?.join(1000)
        recordingThread = null
        outputFile?.delete()
        outputFile = null
    }

    /** 轻量 RMS 探测:打开麦克风读取一小段数据测音量,然后立即释放。
     *  用于 TTS barge-in — 朗读期间检测用户是否在说话。返回 null=失败。 */
    fun peekRms(durationMs: Int = 200): Double? {
        var probeRecorder: AudioRecord? = null
        try {
            val bufSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNELS, ENCODING)
            val probeSize = maxOf(bufSize, SAMPLE_RATE * 2 * durationMs / 1000)
            probeRecorder = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE, CHANNELS, ENCODING, probeSize
            )
            if (probeRecorder.state != AudioRecord.STATE_INITIALIZED) return null
            probeRecorder.startRecording()
            val buf = ByteArray(probeSize)
            val n = probeRecorder.read(buf, 0, probeSize)
            if (n <= 0) return null
            return rmsOf(buf, n)
        } catch (_: Exception) {
            return null
        } finally {
            try { probeRecorder?.stop() } catch (_: Exception) {}
            try { probeRecorder?.release() } catch (_: Exception) {}
        }
    }

    /** 在原始 PCM 数据前加 WAV 头 */
    private fun pcmToWav(pcm: File, wav: File) {
        val pcmData = pcm.readBytes()
        val dataSize = pcmData.size
        val chunkSize = 36 + dataSize
        val byteRate = SAMPLE_RATE * 2 // 16-bit mono
        val buf = ByteBuffer.allocate(44 + dataSize).apply { order(ByteOrder.LITTLE_ENDIAN) }
        // RIFF header
        buf.put("RIFF".toByteArray())
        buf.putInt(chunkSize)
        buf.put("WAVE".toByteArray())
        // fmt subchunk
        buf.put("fmt ".toByteArray())
        buf.putInt(16)          // subchunk size (PCM)
        buf.putShort(1)         // audio format (PCM)
        buf.putShort(1)         // mono
        buf.putInt(SAMPLE_RATE) // sample rate
        buf.putInt(byteRate)    // byte rate
        buf.putShort(2)         // block align
        buf.putShort(16)        // bits per sample
        // data subchunk
        buf.put("data".toByteArray())
        buf.putInt(dataSize)
        buf.put(pcmData)
        wav.writeBytes(buf.array())
    }
}
