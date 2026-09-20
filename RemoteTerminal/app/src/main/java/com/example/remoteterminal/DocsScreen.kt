package com.example.remoteterminal

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * 资料管理页:上传课本/资料(PDF/Word/txt/md),按科目分类,显示解析状态。
 * 上传方式:系统文件选择器选文件 → 读取字节 base64 → POST /learn/upload。
 */
@Composable
fun DocsScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val cs = MaterialTheme.colorScheme
    var docs by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var status by remember { mutableStateOf("") }
    var subject by remember { mutableStateOf("高等数学") }
    var showSubjectMenu by remember { mutableStateOf(false) }
    val subjects = listOf("高等数学", "英语", "语文", "计算机", "政治", "专业课", "其他")

    fun refresh() {
        scope.launch {
            loading = true
            docs = withContext(Dispatchers.IO) { fetchDocs() }
            loading = false
        }
    }
    LaunchedEffect(Unit) { refresh() }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) {
            status = "读取文件…"
            scope.launch {
                val r = withContext(Dispatchers.IO) { uploadDoc(ctx, uri, subject) }
                status = r
                refresh()
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("资料", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = { refresh() }) { Text("刷新") }
            TextButton(onClick = onBack) { Text("完成") }
        }
        Spacer(Modifier.height(8.dp))

        // 上传区:选科目 + 选文件
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box {
                OutlinedButton(onClick = { showSubjectMenu = true }) { Text("科目: $subject") }
                DropdownMenu(expanded = showSubjectMenu, onDismissRequest = { showSubjectMenu = false }) {
                    subjects.forEach { s ->
                        DropdownMenuItem(text = { Text(s) }, onClick = { subject = s; showSubjectMenu = false })
                    }
                }
            }
            Button(onClick = { picker.launch("*/*") }) { Text("上传文件") }
        }
        Text("支持 PDF / Word / txt / md，上传后服务器自动解析建库",
            fontSize = 11.sp, color = cs.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
        if (status.isNotBlank()) {
            Text(status, fontSize = 12.sp,
                color = if (status.contains("成功") || status.contains("处理")) cs.primary else cs.error,
                modifier = Modifier.padding(top = 4.dp))
        }

        HorizontalDivider(Modifier.padding(vertical = 10.dp), color = cs.outlineVariant)

        if (loading) {
            Box(Modifier.fillMaxWidth().padding(30.dp), Alignment.Center) { CircularProgressIndicator() }
        } else if (docs.isEmpty()) {
            Text("还没有资料。点「上传文件」添加你的课本。",
                style = MaterialTheme.typography.bodyMedium, color = cs.onSurfaceVariant)
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(docs) { d ->
                    DocCard(d, subjects) { newSub ->
                        scope.launch {
                            val ok = withContext(Dispatchers.IO) { setDocSubject(d.optInt("id"), newSub) }
                            if (ok) refresh() else status = "改科目失败"
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DocCard(d: JSONObject, subjects: List<String>, onSetSubject: (String) -> Unit) {
    val cs = MaterialTheme.colorScheme
    val parsed = d.optInt("parsed", 0) == 1
    val status = d.optString("status")
    var menu by remember { mutableStateOf(false) }
    Card(shape = RoundedCornerShape(10.dp),
        colors = CardDefaults.cardColors(containerColor = cs.surfaceVariant.copy(alpha = 0.5f))) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(d.optString("filename"), style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.weight(1f), maxLines = 1)
                when {
                    status == "error" -> Text("✗ 失败", fontSize = 11.sp, color = cs.error)
                    parsed -> Text("✓ 已解析", fontSize = 11.sp, color = cs.primary)
                    else -> Text("⏳ 解析中${d.optString("progress")}", fontSize = 11.sp, color = cs.onSurfaceVariant)
                }
            }
            // 三级标签:阶段 · 科目 · 类型
            val tags = listOf(d.optString("stage"), d.optString("subject"), d.optString("doc_type"))
                .filter { it.isNotBlank() }
            if (tags.isNotEmpty()) {
                Spacer(Modifier.height(2.dp))
                Text(tags.joinToString(" · "), fontSize = 10.sp, color = cs.primary)
            }
            if (status == "error" && d.optString("note").isNotBlank()) {
                Text("原因: ${d.optString("note")}", fontSize = 10.sp, color = cs.error, maxLines = 2)
            }
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                val sub = d.optString("subject").ifEmpty { "未分类" }
                Text("知识点 ${d.optInt("kp_count")} · 题目 ${d.optInt("ex_count")}",
                    fontSize = 11.sp, color = cs.onSurfaceVariant, modifier = Modifier.weight(1f))
                Box {
                    TextButton(onClick = { menu = true }, contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp)) {
                        Text("科目: $sub ▾", fontSize = 11.sp)
                    }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        subjects.forEach { s ->
                            DropdownMenuItem(text = { Text(s) }, onClick = { menu = false; onSetSubject(s) })
                        }
                    }
                }
            }
        }
    }
}

// 网络
private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

private fun setDocSubject(id: Int, subject: String): Boolean {
    var conn: HttpURLConnection? = null
    return try {
        val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/learn/doc/$id/subject"
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; doOutput = true; connectTimeout = 8000; readTimeout = 8000
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
        }
        conn.outputStream.use { it.write(JSONObject().put("subject", subject).toString().toByteArray(Charsets.UTF_8)) }
        conn.responseCode in 200..299
    } catch (_: Exception) { false } finally { conn?.disconnect() }
}

private fun fetchDocs(): List<JSONObject> {
    var conn: HttpURLConnection? = null
    return try {
        val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/learn/docs?token=${enc(Config.AUTH_TOKEN)}"
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"; connectTimeout = 8000; readTimeout = 8000
        }
        if (conn.responseCode != 200) return emptyList()
        val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
        val arr = json.optJSONArray("docs") ?: return emptyList()
        (0 until arr.length()).map { arr.getJSONObject(it) }
    } catch (_: Exception) { emptyList() } finally { conn?.disconnect() }
}

private fun uploadDoc(ctx: android.content.Context, uri: Uri, subject: String): String {
    var conn: HttpURLConnection? = null
    return try {
        // 读文件名 + 字节
        var name = "upload"
        ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) name = c.getString(idx)
        }
        val bytes = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: return "读取失败"
        if (bytes.size > 20 * 1024 * 1024) return "文件过大(>20MB)"
        val b64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
        val body = JSONObject().put("filename", name).put("subject", subject).put("content_b64", b64)
        val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/learn/upload"
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; doOutput = true; connectTimeout = 10000; readTimeout = 60000
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
        }
        conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
        val code = conn.responseCode
        val resp = (if (code in 200..299) conn.inputStream else conn.errorStream)
            ?.bufferedReader()?.use { it.readText() } ?: ""
        if (code in 200..299) {
            val j = JSONObject(resp)
            if (j.optBoolean("ok")) "上传成功，后台解析中：$name" else "失败: ${j.optString("error")}"
        } else "上传失败 HTTP $code"
    } catch (e: Exception) { "上传出错: ${e.message}" } finally { conn?.disconnect() }
}
