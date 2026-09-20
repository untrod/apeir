package com.example.remoteterminal

import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class SessionItem(
    val sessionId: String,
    val name: String,      // 用户自定义名称或预览
    val preview: String,
    val updated: Long,
    val messageCount: Int,
)

@Composable
fun SessionsScreen(
    prefs: Prefs,
    db: AppDatabase,
    onSelectSession: (String) -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var sessions by remember { mutableStateOf<List<SessionItem>>(emptyList()) }
    var showDeleteDialog by remember { mutableStateOf<String?>(null) }
    var showRenameDialog by remember { mutableStateOf<Pair<String, String>?>(null) } // id, oldName
    var renameText by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        sessions = loadSessionsWithLocal(context, db)
    }

    fun refresh() { scope.launch { sessions = loadSessionsWithLocal(context, db) } }

    // 删除确认
    showDeleteDialog?.let { sid ->
        AlertDialog(
            onDismissRequest = { showDeleteDialog = null },
            title = { Text("删除会话") },
            text = { Text("确认删除此会话? 大脑端上下文将同步删除,本地消息也会清除。") },
            confirmButton = {
                Button(onClick = {
                    scope.launch {
                        deleteSessionRemote(context, sid)
                        db.messageDao().deleteSession(sid)
                        showDeleteDialog = null
                        refresh()
                    }
                }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFD32F2F))) { Text("删除") }
            },
            dismissButton = { TextButton(onClick = { showDeleteDialog = null }) { Text("取消") } },
        )
    }

    // 重命名对话框
    showRenameDialog?.let { (sid, oldName) ->
        AlertDialog(
            onDismissRequest = { showRenameDialog = null },
            title = { Text("重命名会话") },
            text = {
                OutlinedTextField(
                    value = renameText,
                    onValueChange = { renameText = it },
                    label = { Text("会话名称") },
                    singleLine = true,
                )
            },
            confirmButton = {
                Button(onClick = {
                    scope.launch {
                        renameSessionRemote(context, sid, renameText.trim())
                        showRenameDialog = null
                        refresh()
                    }
                }) { Text("保存") }
            },
            dismissButton = { TextButton(onClick = { showRenameDialog = null }) { Text("取消") } },
        )
    }

    var showClearAllDialog by remember { mutableStateOf(false) }

    // 全部清除确认
    if (showClearAllDialog) {
        AlertDialog(
            onDismissRequest = { showClearAllDialog = false },
            title = { Text("清除所有会话") },
            text = { Text("确认删除全部 ${sessions.size} 个会话?\n大脑端和本地记录将同步清除,不可恢复。") },
            confirmButton = {
                Button(onClick = {
                    scope.launch {
                        deleteAllSessionsRemote(context)
                        db.messageDao().deleteAll()
                        showClearAllDialog = false
                        refresh()
                    }
                }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFD32F2F))) { Text("全部清除") }
            },
            dismissButton = { TextButton(onClick = { showClearAllDialog = false }) { Text("取消") } },
        )
    }

    Column(modifier = Modifier.fillMaxSize().padding(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            Text("历史会话", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.weight(1f))
            if (sessions.isNotEmpty()) {
                TextButton(onClick = { showClearAllDialog = true }) {
                    Text("全部清除", color = Color(0xFFD32F2F))
                }
            }
            TextButton(onClick = onBack) { Text("返回") }
        }
        Spacer(Modifier.height(8.dp))

        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(sessions) { s ->
                Card(
                    modifier = Modifier.fillMaxWidth().clickable {
                        prefs.sessionId = s.sessionId
                        onSelectSession(s.sessionId)
                    },
                    shape = RoundedCornerShape(8.dp),
                ) {
                    Row(modifier = Modifier.fillMaxWidth().padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(s.name.ifEmpty { s.preview.ifEmpty { s.sessionId.take(12) + "..." } },
                                style = MaterialTheme.typography.bodyLarge)
                            Text("${s.messageCount}条消息 · ${formatTime(s.updated)}",
                                style = MaterialTheme.typography.bodySmall, color = Color.Gray)
                        }
                        IconButton(onClick = {
                            renameText = s.name
                            showRenameDialog = Pair(s.sessionId, s.name)
                        }) { Icon(Icons.Filled.Edit, "重命名", modifier = Modifier.size(18.dp)) }
                        IconButton(onClick = { showDeleteDialog = s.sessionId }) {
                            Icon(Icons.Filled.Delete, "删除", modifier = Modifier.size(18.dp), tint = Color(0xFFD32F2F))
                        }
                        IconButton(onClick = {
                            scope.launch { exportSession(context, db, s.sessionId, s.name.ifEmpty { s.preview }) }
                        }) { Icon(Icons.Filled.Share, "导出", modifier = Modifier.size(18.dp)) }
                    }
                }
            }
        }
    }
}

fun formatTime(epoch: Long): String {
    if (epoch == 0L) return ""
    val diff = System.currentTimeMillis() - epoch * 1000
    return when {
        diff < 60000 -> "刚刚"
        diff < 3600000 -> "${diff / 60000}分钟前"
        diff < 86400000 -> "${diff / 3600000}小时前"
        else -> "${diff / 86400000}天前"
    }
}

// 远程操作

suspend fun loadSessionsWithLocal(context: Context, db: AppDatabase): List<SessionItem> =
    withContext(Dispatchers.IO) {
        var conn: HttpURLConnection? = null
        try {
            val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/sessions?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}"
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"; connectTimeout = 10000; readTimeout = 10000
            }
            if (conn.responseCode != 200) return@withContext loadLocalSessions(db)
            val text = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            val json = org.json.JSONObject(text)
            val arr = json.optJSONArray("sessions") ?: return@withContext loadLocalSessions(db)
            val list = mutableListOf<SessionItem>()
            for (i in 0 until arr.length()) {
                val s = arr.getJSONObject(i)
                val sid = s.optString("session_id")
                list.add(SessionItem(
                    sessionId = sid,
                    name = s.optString("name", ""),
                    preview = s.optString("preview", ""),
                    updated = s.optLong("updated", 0),
                    messageCount = s.optInt("message_count", 0),
                ))
            }
            if (list.isEmpty()) loadLocalSessions(db) else list
        } catch (_: Exception) { loadLocalSessions(db) }
        finally { conn?.disconnect() }
    }

/** 服务器不可达时从本地 Room DB 构建会话列表。 */
private suspend fun loadLocalSessions(db: AppDatabase): List<SessionItem> {
    return try {
        db.messageDao().getLocalSessionIds().map { s ->
            val lastMsg = db.messageDao().getLastMessage(s.session_id)
            val count = db.messageDao().getMessageCount(s.session_id)
            SessionItem(
                sessionId = s.session_id,
                name = s.session_id.take(12),
                preview = lastMsg?.content?.take(80) ?: "",
                updated = s.last_ts,
                messageCount = count,
            )
        }
    } catch (_: Exception) { emptyList() }
}

suspend fun deleteSessionRemote(context: Context, sessionId: String) =
    withContext(Dispatchers.IO) {
        var conn: HttpURLConnection? = null
        try {
            val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/session/$sessionId?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}"
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "DELETE"; connectTimeout = 10000; readTimeout = 10000
            }
            conn.responseCode // trigger
        } catch (_: Exception) {}
        finally { conn?.disconnect() }
    }

/**
 * 从服务器拉取某会话的完整历史,覆盖写入本地 Room。
 * 让手机/手表共用同一份对话历史(服务器 sessions.json 是真源)。
 * 失败(离线/拉不到)时不动本地,保证离线仍能看缓存。
 */
suspend fun syncSessionFromServer(db: AppDatabase, sessionId: String) =
    withContext(Dispatchers.IO) {
        var conn: HttpURLConnection? = null
        try {
            val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/session/$sessionId?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}"
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"; connectTimeout = 6000; readTimeout = 8000
            }
            if (conn.responseCode != 200) return@withContext
            val text = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            val json = JSONObject(text)
            val arr = json.optJSONArray("messages") ?: return@withContext
            // 只取可展示的 user/assistant 文本消息(跳过 tool / 空内容)
            val msgs = mutableListOf<LocalMessage>()
            var ts = System.currentTimeMillis() - arr.length() * 1000L
            for (i in 0 until arr.length()) {
                val m = arr.getJSONObject(i)
                val role = m.optString("role")
                // 工具调用轮次 content 是 JSON null,org.json 会给出 "null" 字符串 → 必须跳过
                val content = if (m.isNull("content")) "" else m.optString("content", "").trim()
                if ((role == "user" || role == "assistant") && content.isNotEmpty() && content != "null") {
                    // 从 tool_calls 重建 steps（保留命令执行记录）
                    val steps = buildString {
                        val tcs = m.optJSONArray("tool_calls")
                        if (tcs != null) {
                            for (j in 0 until tcs.length()) {
                                val tc = tcs.getJSONObject(j)
                                val fn = tc.optJSONObject("function")
                                val name = fn?.optString("name", "") ?: ""
                                if (name.isNotEmpty()) append("$ $name\n")
                            }
                        }
                    }.trim()
                    msgs.add(LocalMessage(sessionId = sessionId, role = role, content = content, steps = steps, timestamp = ts))
                    ts += 1000L
                }
            }
            if (msgs.isNotEmpty()) {
                db.messageDao().deleteSession(sessionId)
                msgs.forEach { db.messageDao().insert(it) }
            }
        } catch (_: Exception) { /* 离线:保留本地缓存 */ }
        finally { conn?.disconnect() }
    }

suspend fun deleteAllSessionsRemote(context: Context) =
    withContext(Dispatchers.IO) {
        var conn: HttpURLConnection? = null
        try {
            val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/sessions?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}"
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "DELETE"; connectTimeout = 10000; readTimeout = 10000
            }
            conn.responseCode // trigger
        } catch (_: Exception) {}
        finally { conn?.disconnect() }
    }

suspend fun exportSession(context: Context, db: AppDatabase, sessionId: String, title: String) =
    withContext(Dispatchers.IO) {
        val msgs = db.messageDao().getMessagesOnce(sessionId)
        val md = buildString {
            appendLine("# $title\n")
            msgs.forEach { m ->
                if (m.role == "user") appendLine("**👤 你:** ${m.content}\n")
                else {
                    appendLine("**🤖 助手:** ${m.content}")
                    if (m.steps.isNotBlank()) appendLine("\n```\n${m.steps}\n```\n")
                    else appendLine("")
                }
                appendLine("---\n")
            }
        }
        withContext(Dispatchers.Main) {
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_TEXT, md)
                putExtra(Intent.EXTRA_SUBJECT, title)
            }
            context.startActivity(Intent.createChooser(intent, "导出对话"))
        }
    }

suspend fun renameSessionRemote(context: Context, sessionId: String, name: String) =
    withContext(Dispatchers.IO) {
        var conn: HttpURLConnection? = null
        try {
            val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/session/$sessionId/rename?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}"
            val body = JSONObject().put("name", name).toString()
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "PUT"; doOutput = true
                connectTimeout = 10000; readTimeout = 10000
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            conn.responseCode
        } catch (_: Exception) {}
        finally { conn?.disconnect() }
    }
