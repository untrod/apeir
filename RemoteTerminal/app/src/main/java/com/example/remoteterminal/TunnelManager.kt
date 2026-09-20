package com.example.remoteterminal

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.util.Log
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.BufferedReader
import java.io.StringReader
import java.net.InetSocketAddress
import java.net.Socket

/**
 * WireGuard 隧道管理器。
 * 配置按字段存储(私钥/地址/DNS/对端公钥/Endpoint/AllowedIPs/保活间隔),
 * 避免用户粘贴完整 .conf 时因空格/符号出错。
 */
object TunnelManager {
    private const val TAG = "TunnelMgr"
    private const val PREFS = "wg_config"
    private var backend: GoBackend? = null
    private var tunnel: MyTunnel? = null

    var state: Tunnel.State = Tunnel.State.DOWN
        internal set

    // 自动重连: 指数退避参数
    private var reconnectJob: kotlinx.coroutines.Job? = null
    private var retryCount = 0
    private const val MAX_RETRY_DELAY_MS = 60_000L  // 最大重试间隔 60s
    private const val BASE_RETRY_DELAY_MS = 2000L   // 起始重试间隔 2s

    fun init(context: Context) {
        if (backend == null) backend = GoBackend(context.applicationContext)
    }

    // 分字段存取
    data class WgFields(
        val privateKey: String = "",
        val address: String = "",
        val dns: String = "",
        val peerPublicKey: String = "",
        val endpoint: String = "",
        val allowedIPs: String = "",
        val keepalive: String = "25",
    )

    fun saveFields(context: Context, f: WgFields) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString("private_key", f.privateKey.trim())
            .putString("address", f.address.trim())
            .putString("dns", f.dns.trim())
            .putString("peer_public_key", f.peerPublicKey.trim())
            .putString("endpoint", f.endpoint.trim())
            .putString("allowed_ips", f.allowedIPs.trim())
            .putString("keepalive", f.keepalive.trim())
            .apply()
    }

    fun loadFields(context: Context): WgFields {
        val sp = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return WgFields(
            privateKey = sp.getString("private_key", "") ?: "",
            address = sp.getString("address", "") ?: "",
            dns = sp.getString("dns", "") ?: "",
            peerPublicKey = sp.getString("peer_public_key", "") ?: "",
            endpoint = sp.getString("endpoint", "") ?: "",
            allowedIPs = sp.getString("allowed_ips", "") ?: "",
            keepalive = sp.getString("keepalive", "25") ?: "25",
        )
    }

    fun hasConfig(context: Context): Boolean {
        val f = loadFields(context)
        return f.privateKey.isNotBlank() && f.peerPublicKey.isNotBlank()
    }

    /** 从分字段构建标准 WireGuard .conf 格式 */
    private fun buildConf(f: WgFields): String {
        return """[Interface]
PrivateKey = ${f.privateKey}
Address = ${f.address}
DNS = ${f.dns}

[Peer]
PublicKey = ${f.peerPublicKey}
Endpoint = ${f.endpoint}
AllowedIPs = ${f.allowedIPs}
PersistentKeepalive = ${f.keepalive}"""
    }

    /** 连接隧道 */
    suspend fun connect(context: Context): String? = withContext(Dispatchers.IO) {
        try {
            val be = backend ?: run { init(context); backend!! }
            val f = loadFields(context)
            if (f.privateKey.isBlank()) return@withContext "请填写设备私钥(PrivateKey)"
            if (f.peerPublicKey.isBlank()) return@withContext "请填写中继公钥(Peer PublicKey)"

            val confText = buildConf(f)
            val config = Config.parse(BufferedReader(StringReader(confText)))
            val t = MyTunnel("remote-terminal")
            tunnel = t

            be.setState(t, Tunnel.State.UP, config)
            state = Tunnel.State.UP
            retryCount = 0  // 连接成功,重置退避计数
            Log.i(TAG, "隧道已连接")
            null
        } catch (e: Exception) {
            Log.e(TAG, "连接失败", e)
            state = Tunnel.State.DOWN
            "连接失败: ${e.message}"
        }
    }

    /**
     * 自动重连: 网络恢复或隧道断开时调用。
     * 使用指数退避: 2s → 4s → 8s → ... → 最大 60s。
     * 幂等: 多次调用只保留最新一次重连任务。
     */
    fun scheduleReconnect(context: Context) {
        reconnectJob?.cancel()
        reconnectJob = CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            while (state != Tunnel.State.UP) {
                val backoff = (BASE_RETRY_DELAY_MS * (1L shl retryCount.coerceAtMost(5)))
                    .coerceAtMost(MAX_RETRY_DELAY_MS)
                Log.i(TAG, "自动重连 #${retryCount + 1}, ${backoff}ms 后尝试")
                delay(backoff)
                val err = connect(context)
                if (err == null) {
                    Log.i(TAG, "自动重连成功")
                    break
                }
                retryCount++
                if (retryCount > 10) {
                    Log.w(TAG, "自动重连已失败 ${retryCount} 次,暂停等待下次网络事件")
                    break
                }
            }
        }
    }

    /** 强制重置重连状态(手动断开时调用) */
    fun resetReconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
        retryCount = 0
    }

    /** 断开隧道 */
    suspend fun disconnect(): String? = withContext(Dispatchers.IO) {
        try {
            val be = backend ?: return@withContext "backend 未初始化"
            val t = tunnel ?: return@withContext "隧道未连接"
            be.setState(t, Tunnel.State.DOWN, null)
            state = Tunnel.State.DOWN
            tunnel = null
            Log.i(TAG, "隧道已断开")
            null
        } catch (e: Exception) {
            Log.e(TAG, "断开失败", e)
            "断开失败: ${e.message}"
        }
    }

    /** 检查 VPN 权限 */
    fun prepareVpn(context: Context): Intent? = VpnService.prepare(context)

    /**
     * 测试连通性:尝试 TCP 连接到 Agent(大脑端口)。
     * 返回 null=通,否则返回错误描述。
     */
    suspend fun testConnection(): String? = withContext(Dispatchers.IO) {
        try {
            val host = com.example.remoteterminal.Config.HOST
            val port = com.example.remoteterminal.Config.BRAIN_PORT
            val sock = Socket()
            sock.connect(InetSocketAddress(host, port), 5000)
            sock.close()
            null  // 通
        } catch (e: Exception) {
            val host = com.example.remoteterminal.Config.HOST
            val port = com.example.remoteterminal.Config.BRAIN_PORT
            "无法连接 $host:$port — ${e.message}"
        }
    }
}

internal class MyTunnel(private val tunnelName: String) : Tunnel {
    override fun getName(): String = tunnelName
    override fun onStateChange(newState: Tunnel.State) {
        TunnelManager.state = newState
    }
}
