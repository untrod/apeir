package com.example.remoteterminal

import android.content.Context
import android.graphics.Rect
import android.util.Log
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.flow.first
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

object PhoneControlServer {
    private const val TAG = "PhoneControlServer"
    private const val PORT = 8788

    private val running = AtomicBoolean(false)
    private var serverSocket: ServerSocket? = null
    private var serverThread: Thread? = null

    fun start(context: Context) {
        if (!running.compareAndSet(false, true)) return
        Config.load(context.applicationContext)
        serverThread = Thread {
            try {
                ServerSocket(PORT).use { socket ->
                    serverSocket = socket
                    Log.i(TAG, "Phone control server listening on $PORT")
                    while (running.get()) {
                        val client = try {
                            socket.accept()
                        } catch (_: Exception) {
                            if (running.get()) Log.w(TAG, "accept failed")
                            break
                        }
                        Thread { handleClient(client) }.start()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "server failed: ${e.message}", e)
            } finally {
                serverSocket = null
                running.set(false)
            }
        }.apply {
            name = "NousPhoneControlServer"
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running.set(false)
        try {
            serverSocket?.close()
        } catch (_: Exception) {
        }
        serverSocket = null
        serverThread = null
    }

    private fun handleClient(socket: Socket) {
        socket.use { client ->
            try {
                client.soTimeout = 8000
                if (!sourceAllowed(client)) {
                    Log.w(TAG, "reject source: ${client.inetAddress?.hostAddress ?: ""}")
                    sendJson(client.getOutputStream(), 403, error("forbidden", "Source IP is not allowed"))
                    return
                }
                val reader = BufferedReader(InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8))
                val requestLine = reader.readLine() ?: return
                val parts = requestLine.split(" ")
                if (parts.size < 2) {
                    sendJson(client.getOutputStream(), 400, error("bad_request", "Invalid request line"))
                    return
                }
                val method = parts[0].uppercase()
                val target = parts[1]
                val headers = mutableMapOf<String, String>()
                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isEmpty()) break
                    val idx = line.indexOf(":")
                    if (idx > 0) headers[line.substring(0, idx).trim().lowercase()] = line.substring(idx + 1).trim()
                }
                val contentLength = headers["content-length"]?.toIntOrNull() ?: 0
                val body = if (contentLength > 0) {
                    val chars = CharArray(contentLength)
                    var read = 0
                    while (read < contentLength) {
                        val n = reader.read(chars, read, contentLength - read)
                        if (n < 0) break
                        read += n
                    }
                    String(chars, 0, read)
                } else ""

                val path = target.substringBefore("?")
                val query = parseQuery(target.substringAfter("?", ""))
                if (!authorized(headers, query)) {
                    sendJson(client.getOutputStream(), 401, error("unauthorized", "Invalid token"))
                    return
                }

                val response = when {
                    method == "GET" && path == "/health" -> health()
                    method == "GET" && path == "/phone/ui" -> observe()
                    method == "POST" && path == "/phone/action" -> act(JSONObject(if (body.isBlank()) "{}" else body))
                    else -> error("not_found", "Unknown endpoint")
                }
                val status = if (response.optBoolean("ok", false)) 200 else 400
                sendJson(client.getOutputStream(), status, response)
            } catch (e: Exception) {
                Log.w(TAG, "request failed: ${e.message}", e)
                sendJson(client.getOutputStream(), 500, error("server_error", e.message ?: "unknown"))
            }
        }
    }

    private fun authorized(headers: Map<String, String>, query: Map<String, String>): Boolean {
        val configured = Config.AUTH_TOKEN
        if (configured.isBlank()) return false
        val provided = headers["x-auth-token"] ?: query["token"] ?: ""
        return provided == configured
    }

    private fun sourceAllowed(client: Socket): Boolean {
        val ip = client.inetAddress?.hostAddress ?: return false
        if (client.inetAddress?.isLoopbackAddress == true) return true
        if (Config.HOST.isNotBlank() && ip == Config.HOST) return true
        if (ip.startsWith("10.10.")) return true
        if (ip.startsWith("fd") || ip.startsWith("fc")) return true
        return false
    }

    private fun health(): JSONObject {
        val service = NousAccessibilityService.instance
        return JSONObject()
            .put("ok", true)
            .put("port", PORT)
            .put("accessibility_enabled", service != null)
            .put("package", service?.currentPackageName() ?: "")
    }

    private fun observe(): JSONObject {
        val service = NousAccessibilityService.instance
            ?: return error("accessibility_disabled", "Nous Accessibility Service is not enabled")
        val elements = service.getScreenElements()
        return JSONObject()
            .put("ok", true)
            .put("package", service.currentPackageName())
            .put("elements", elementsToJson(elements))
    }

    private fun act(payload: JSONObject): JSONObject {
        val service = NousAccessibilityService.instance
            ?: return error("accessibility_disabled", "Nous Accessibility Service is not enabled")
        val action = payload.optString("action").trim()
        if (action.isBlank()) return error("bad_request", "action is required")

        val actionId = payload.optString("action_id").ifBlank { UUID.randomUUID().toString() }
        val timeoutMs = payload.optLong("timeout_ms", 4000L).coerceIn(500L, 15000L)
        val request = NousAccessibilityService.UiAction(
            actionId = actionId,
            action = action,
            target = payload.optString("target", ""),
            text = payload.optString("text", ""),
            x = if (payload.has("x")) payload.optDouble("x").toFloat() else -1f,
            y = if (payload.has("y")) payload.optDouble("y").toFloat() else -1f,
        )

        return runBlocking(Dispatchers.Default) {
            val result = async(start = CoroutineStart.UNDISPATCHED) {
                withTimeoutOrNull(timeoutMs) {
                    NousAccessibilityService.UiResult.results.first { it.startsWith("$actionId|") }
                }
            }
            NousAccessibilityService.actionRequests.emit(request)
            val raw = result.await()
            if (raw == null) {
                error("timeout", "No result returned from accessibility service")
            } else {
                JSONObject()
                    .put("ok", !raw.substringAfter("|").startsWith("error:"))
                    .put("package", service.currentPackageName())
                    .put("result", raw.substringAfter("|"))
            }
        }
    }

    private fun elementsToJson(elements: List<NousAccessibilityService.UiElement>): JSONArray {
        val arr = JSONArray()
        elements.take(120).forEach { e ->
            arr.put(
                JSONObject()
                    .put("index", e.index)
                    .put("text", e.text)
                    .put("content_desc", e.contentDesc)
                    .put("resource_id", e.resourceId)
                    .put("class_name", e.className)
                    .put("clickable", e.isClickable)
                    .put("editable", e.isEditable)
                    .put("bounds", boundsToJson(e.bounds))
            )
        }
        return arr
    }

    private fun boundsToJson(bounds: Rect?): Any {
        if (bounds == null) return JSONObject.NULL
        return JSONObject()
            .put("left", bounds.left)
            .put("top", bounds.top)
            .put("right", bounds.right)
            .put("bottom", bounds.bottom)
            .put("center_x", bounds.centerX())
            .put("center_y", bounds.centerY())
    }

    private fun parseQuery(query: String): Map<String, String> {
        if (query.isBlank()) return emptyMap()
        return query.split("&").mapNotNull { part ->
            val idx = part.indexOf("=")
            if (idx < 0) return@mapNotNull null
            val key = URLDecoder.decode(part.substring(0, idx), "UTF-8")
            val value = URLDecoder.decode(part.substring(idx + 1), "UTF-8")
            key to value
        }.toMap()
    }

    private fun sendJson(out: OutputStream, status: Int, json: JSONObject) {
        val bytes = json.toString().toByteArray(StandardCharsets.UTF_8)
        val reason = if (status in 200..299) "OK" else "ERROR"
        val header = "HTTP/1.1 $status $reason\r\n" +
            "Content-Type: application/json; charset=utf-8\r\n" +
            "Content-Length: ${bytes.size}\r\n" +
            "Connection: close\r\n\r\n"
        out.write(header.toByteArray(StandardCharsets.UTF_8))
        out.write(bytes)
        out.flush()
    }

    private fun error(code: String, message: String): JSONObject =
        JSONObject().put("ok", false).put("error", code).put("message", message)
}
