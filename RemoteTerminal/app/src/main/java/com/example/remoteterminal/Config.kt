package com.example.remoteterminal

import android.content.Context

/**
 * 集中配置。所有值从 SharedPreferences 读取(用户在设置页填写),不硬编码真实值。
 * 默认值全部为空或占位——首次使用时必须在设置页填入。
 *
 * HOST = Brain 服务器地址(VPN 隧道 IP,如 &lt;brain-ip&gt;)。
 * DIRECT_AGENT_HOST = 终端模式直连 Agent 的地址(可选,如 &lt;agent-ip&gt;)。
 */
object Config {
    // Brain 连接
    var HOST = ""               // Brain 服务器隧道地址(如 <brain-ip>)
        private set
    var BRAIN_PORT = 8770
        private set
    var AUTH_TOKEN = ""          // 共享鉴权令牌(与 Brain 通信用)
        private set
    var RELAY_ADDRESS = ""      // 中继服务器公网地址(WireGuard Endpoint)
        private set

    // 终端模式直连 Agent(可选)
    var TERMINAL_VIA_BRAIN = true    // true=终端命令走 brain 路由,false=直连 agent
        private set
    var DIRECT_AGENT_HOST = ""       // 直连 Agent 地址(如 &lt;agent-ip&gt;)
        private set
    var AGENT_PORT = 8765            // Agent 端口
        private set

    // LLM
    var LLM_API_KEY = ""        // LLM API Key
        private set
    var LLM_API_URL = ""        // LLM API Base URL
        private set
    var DEFAULT_MODEL = "deepseek-chat"
        private set

    // 超时
    var TIMEOUT_MS = 120000
        private set
    var PING_TIMEOUT_MS = 3000
        private set

    // 动态计算
    val CHAT_URL: String get() = "http://$HOST:$BRAIN_PORT/chat"
    /** 终端模式执行地址:走 brain 代理或直连 agent */
    val EXEC_URL: String get() =
        if (TERMINAL_VIA_BRAIN) "http://$HOST:$BRAIN_PORT/exec"
        else "http://$DIRECT_AGENT_HOST:$AGENT_PORT/exec"

    private const val PREFS_NAME = "nous_config"

    fun load(context: Context) {
        val sp = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        HOST = sp.getString("host", BuildConfig.NOUS_BRAIN_HOST) ?: BuildConfig.NOUS_BRAIN_HOST
        BRAIN_PORT = sp.getInt("brain_port", 8770)
        AUTH_TOKEN = sp.getString("auth_token", "") ?: ""
        RELAY_ADDRESS = sp.getString("relay_address", BuildConfig.NOUS_SERVER_URL) ?: BuildConfig.NOUS_SERVER_URL
        TERMINAL_VIA_BRAIN = sp.getBoolean("terminal_via_brain", true)
        DIRECT_AGENT_HOST = sp.getString("direct_agent_host", "") ?: ""
        AGENT_PORT = sp.getInt("agent_port", 8765)
        LLM_API_KEY = sp.getString("llm_api_key", "") ?: ""
        LLM_API_URL = sp.getString("llm_api_url", "") ?: ""
        DEFAULT_MODEL = sp.getString("default_model", "deepseek-chat") ?: "deepseek-chat"
        TIMEOUT_MS = sp.getInt("timeout_ms", 120000)
    }

    fun save(
        context: Context, host: String, brainPort: Int,
        authToken: String, relayAddress: String,
        terminalViaBrain: Boolean, directAgentHost: String, agentPort: Int,
        llmApiKey: String, llmApiUrl: String, defaultModel: String,
    ) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putString("host", host.trim())
            .putInt("brain_port", brainPort)
            .putString("auth_token", authToken.trim())
            .putString("relay_address", relayAddress.trim())
            .putBoolean("terminal_via_brain", terminalViaBrain)
            .putString("direct_agent_host", directAgentHost.trim())
            .putInt("agent_port", agentPort)
            .putString("llm_api_key", llmApiKey.trim())
            .putString("llm_api_url", llmApiUrl.trim())
            .putString("default_model", defaultModel.trim())
            .apply()
        HOST = host.trim()
        BRAIN_PORT = brainPort
        AUTH_TOKEN = authToken.trim()
        RELAY_ADDRESS = relayAddress.trim()
        TERMINAL_VIA_BRAIN = terminalViaBrain
        DIRECT_AGENT_HOST = directAgentHost.trim()
        AGENT_PORT = agentPort
        LLM_API_KEY = llmApiKey.trim()
        LLM_API_URL = llmApiUrl.trim()
        DEFAULT_MODEL = defaultModel.trim()
    }

    fun pushToBrain(configFields: Map<String, Any>, onResult: (Boolean, String) -> Unit) {
        Thread {
            try {
                val url = java.net.URL("http://$HOST:$BRAIN_PORT/config")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.connectTimeout = 10000
                conn.readTimeout = 10000
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.setRequestProperty("X-Auth-Token", AUTH_TOKEN)
                val configObj = org.json.JSONObject()
                configFields.forEach { (k, v) -> configObj.put(k, v) }
                val body = org.json.JSONObject().put("config", configObj)
                conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                val code = conn.responseCode
                val resp = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                conn.disconnect()
                onResult(code in 200..299, if (code in 200..299) "配置已同步到服务器" else "同步失败: HTTP $code")
            } catch (e: Exception) {
                onResult(false, "同步失败: ${e.message}")
            }
        }.start()
    }

    fun isConfigured(): Boolean = HOST.isNotBlank() && AUTH_TOKEN.isNotBlank()

    // 高级设置(从 Brain 拉取)
    var BRAIN_MAX_STEPS = 9999; private set
    var BRAIN_STEP_WARNING = 3000; private set
    var BRAIN_IDLE_LIMIT = 3; private set
    var COMMAND_TIMEOUT = 30; private set
    var RATE_LIMIT_PER_MINUTE = 30; private set
    var SAFETY_MODE = "normal"; private set

    fun loadAdvancedFromConfig(config: Map<String, Any>) {
        BRAIN_MAX_STEPS = (config["BRAIN_MAX_STEPS"] as? Number)?.toInt() ?: BRAIN_MAX_STEPS
        BRAIN_STEP_WARNING = (config["BRAIN_STEP_WARNING"] as? Number)?.toInt() ?: BRAIN_STEP_WARNING
        BRAIN_IDLE_LIMIT = (config["BRAIN_IDLE_LIMIT"] as? Number)?.toInt() ?: BRAIN_IDLE_LIMIT
        COMMAND_TIMEOUT = (config["COMMAND_TIMEOUT"] as? Number)?.toInt() ?: COMMAND_TIMEOUT
        RATE_LIMIT_PER_MINUTE = (config["RATE_LIMIT_PER_MINUTE"] as? Number)?.toInt() ?: RATE_LIMIT_PER_MINUTE
        SAFETY_MODE = (config["SAFETY_MODE"] as? String) ?: SAFETY_MODE
    }

    fun fetchUsage(onResult: (Boolean, String) -> Unit) {
        Thread {
            try {
                val url = java.net.URL("http://$HOST:$BRAIN_PORT/usage?token=${java.net.URLEncoder.encode(AUTH_TOKEN, "UTF-8")}")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "GET"; conn.connectTimeout = 8000; conn.readTimeout = 8000
                val code = conn.responseCode
                val resp = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                conn.disconnect()
                if (code in 200..299) onResult(true, resp) else onResult(false, "HTTP $code")
            } catch (e: Exception) { onResult(false, e.message ?: "unknown") }
        }.start()
    }
}
