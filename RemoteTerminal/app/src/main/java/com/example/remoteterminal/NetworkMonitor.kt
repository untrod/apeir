package com.example.remoteterminal

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.util.Log
import kotlinx.coroutines.*

/**
 * 网络状态监听 — WiFi 切换/恢复时自动触发 WG 重连。
 * 手表只有 WiFi，断网等于整条链路死掉；此监听器确保网络恢复时自动重建隧道。
 */
object NetworkMonitor {
    private const val TAG = "NetMon"
    private var callback: ConnectivityManager.NetworkCallback? = null
    private var scope: CoroutineScope? = null
    @Volatile var isNetworkAvailable = false
        private set

    /** 网络恢复时触发。Activity/Service 可在此回调中执行 TunnelManager.connect()。 */
    var onNetworkRestored: (() -> Unit)? = null

    fun start(context: Context) {
        if (callback != null) return
        scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.i(TAG, "网络已恢复")
                val wasAvailable = isNetworkAvailable
                isNetworkAvailable = true
                // 只在网络从不可用到可用时触发重连(避免首次启动重复连)
                if (!wasAvailable) {
                    scope?.launch {
                        delay(2000) // 等网络栈就绪
                        onNetworkRestored?.invoke()
                    }
                }
            }

            override fun onLost(network: Network) {
                Log.w(TAG, "网络已断开")
                isNetworkAvailable = false
            }

            override fun onCapabilitiesChanged(
                network: Network,
                capabilities: NetworkCapabilities,
            ) {
                // WiFi 切换(如从校园网换到手机热点) → 触发重连
                val hasWifi = capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                val hasInternet = capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                if (hasWifi && hasInternet && isNetworkAvailable) {
                    Log.i(TAG, "WiFi 网络切换,触发重连检查")
                    scope?.launch {
                        delay(1500)
                        onNetworkRestored?.invoke()
                    }
                }
            }
        }

        try {
            cm.registerNetworkCallback(request, callback!!)
            // 初始状态: 检查当前网络
            val active = cm.activeNetwork
            val caps = active?.let { cm.getNetworkCapabilities(it) }
            isNetworkAvailable = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
            Log.i(TAG, "已启动, 当前网络: ${if (isNetworkAvailable) "可用" else "不可用"}")
        } catch (e: Exception) {
            Log.e(TAG, "注册网络回调失败: ${e.message}")
        }
    }

    fun stop() {
        callback = null
        scope?.cancel()
        scope = null
        Log.d(TAG, "已停止")
    }
}
