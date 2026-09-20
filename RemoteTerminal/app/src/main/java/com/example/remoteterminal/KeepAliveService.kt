package com.example.remoteterminal

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log
import kotlinx.coroutines.*

/**
 * 前台保活服务 — 持有一条持久通知防止 Android 12+ 杀掉进程。
 * 同时集成: 网络监控(WiFi 恢复→自动重连 WG) + 定期健康检查(不通→触发重连)。
 */
class KeepAliveService : Service() {
    companion object {
        const val CHANNEL_ID = "nous_keepalive"
        const val NOTIFICATION_ID = 1
        var isRunning = false
            private set
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var healthCheckJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Nous 运行状态",
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = "保持 Nous 在后台运行，确保 AI 回复不中断" }
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(channel)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Config.load(this)
        val openIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Nous")
            .setContentText("保持连接，AI 回复不中断")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
        isRunning = true

        // 启动网络监控 + 自动重连
        startNetworkWatch()
        startHealthCheck()
        PhoneControlServer.start(this)
        // 启动定期健康检查
        startHealthCheck()

        return START_STICKY
    }

    private fun startNetworkWatch() {
        NetworkMonitor.onNetworkRestored = {
            if (TunnelManager.hasConfig(this) && TunnelManager.state != com.wireguard.android.backend.Tunnel.State.UP) {
                Log.i("KeepAlive", "网络恢复,触发 WG 自动重连")
                TunnelManager.scheduleReconnect(this)
            }
        }
        NetworkMonitor.start(this)
    }

    private fun startHealthCheck() {
        healthCheckJob?.cancel()
        healthCheckJob = scope.launch {
            while (isActive) {
                delay(30_000) // 每30秒检查一次
                try {
                    val err = TunnelManager.testConnection()
                    if (err != null && TunnelManager.hasConfig(this@KeepAliveService)) {
                        Log.w("KeepAlive", "健康检查失败: $err, 触发重连")
                        TunnelManager.scheduleReconnect(this@KeepAliveService)
                    }
                } catch (_: Exception) { /* 检查失败不崩 */ }
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        healthCheckJob?.cancel()
        NetworkMonitor.stop()
        TunnelManager.resetReconnect()
        PhoneControlServer.stop()
        scope.cancel()
        isRunning = false
        super.onDestroy()
    }
}
