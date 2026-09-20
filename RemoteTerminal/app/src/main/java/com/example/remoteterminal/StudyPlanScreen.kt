package com.example.remoteterminal

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** 学习规划页 — 今日待办清单 + 勾选进度 + 目标卡。 */

private data class TodoItem(val kind: String, val text: String, val done: Boolean,
                            val reason: String = "", val est: Int = 0)

@Composable
fun StudyPlanScreen(onBack: () -> Unit, onOpenChat: (String) -> Unit = {}) {
    val cs = MaterialTheme.colorScheme
    val scope = rememberCoroutineScope()
    var goal by remember { mutableStateOf("") }
    var daysLeft by remember { mutableStateOf(-999) }
    var items by remember { mutableStateOf<List<TodoItem>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }

    suspend fun loadTodo() {
        withContext(Dispatchers.IO) {
            try {
                val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/study/plan_today?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"; conn.connectTimeout = 5000; conn.readTimeout = 8000
                if (conn.responseCode == 200) {
                    val j = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    goal = j.optString("exam")
                    daysLeft = j.optInt("exam_days", -999)
                    val arr = j.optJSONArray("tasks")
                    val list = ArrayList<TodoItem>()
                    if (arr != null) for (i in 0 until arr.length()) {
                        val o = arr.getJSONObject(i)
                        list.add(TodoItem(o.optString("kind"), o.optString("title"),
                            o.optBoolean("done"), o.optString("reason"), o.optInt("est_min")))
                    }
                    items = list
                }
                conn.disconnect()
            } catch (_: Exception) {}
        }
    }

    LaunchedEffect(Unit) { loadTodo(); loading = false }

    fun toggle(idx: Int) {
        val it = items[idx]
        val newDone = !it.done
        items = items.toMutableList().also { l -> l[idx] = it.copy(done = newDone) }
        scope.launch {
            withContext(Dispatchers.IO) {
                try {
                    val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/study/todo/check?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                    val conn = url.openConnection() as HttpURLConnection
                    conn.requestMethod = "POST"; conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/json")
                    conn.connectTimeout = 5000; conn.readTimeout = 6000
                    val body = JSONObject().put("text", it.text).put("done", newDone).toString()
                    conn.outputStream.use { os -> os.write(body.toByteArray()) }
                    conn.responseCode
                    conn.disconnect()
                } catch (_: Exception) {}
            }
        }
    }

    val total = items.size
    val doneCount = items.count { it.done }

    Column(Modifier.fillMaxSize().padding(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            IconButton(onClick = onBack, modifier = Modifier.size(32.dp)) { Icon(Icons.Filled.ArrowBack, null, Modifier.size(18.dp)) }
            Text("📋 今日计划", fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = { scope.launch { loading = true; loadTodo(); loading = false } },
                modifier = Modifier.height(30.dp)) { Text("🔄 重算", fontSize = 11.sp) }
        }

        if (loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                // 目标 + 倒计时
                item {
                    Card(colors = CardDefaults.cardColors(containerColor = cs.primary.copy(alpha = 0.10f)), shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.fillMaxWidth().padding(10.dp)) {
                            if (goal.isNotBlank()) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text("🎓 $goal", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = cs.onSurface, modifier = Modifier.weight(1f))
                                    if (daysLeft in 0..3650) {
                                        Text("还有 ", fontSize = 10.sp, color = cs.onSurfaceVariant)
                                        Text("$daysLeft", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = cs.primary)
                                        Text(" 天", fontSize = 10.sp, color = cs.onSurfaceVariant)
                                    }
                                }
                            } else {
                                Text("还没有学习目标", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                Spacer(Modifier.height(4.dp))
                                Button(onClick = { onOpenChat("结合我上传的资料和知识库,帮我制定一个学习目标和分阶段计划(基础→强化→冲刺),并注册到我的计划里") },
                                    modifier = Modifier.height(32.dp)) { Text("AI 制定规划", fontSize = 12.sp) }
                            }
                            if (total > 0) {
                                Spacer(Modifier.height(6.dp))
                                LinearProgressIndicator(progress = { doneCount.toFloat() / total },
                                    modifier = Modifier.fillMaxWidth().height(5.dp), color = cs.primary, trackColor = cs.surfaceVariant)
                                Text("今日 $doneCount/$total 完成", fontSize = 10.sp, color = cs.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
                            }
                        }
                    }
                }

                if (items.isEmpty()) {
                    item { Text("今天暂无任务。先上传资料/注册考试/建目标,我再为你编排。", fontSize = 11.sp, color = cs.onSurfaceVariant, modifier = Modifier.padding(8.dp)) }
                }

                itemsIndexed(items) { idx, it ->
                    val icon = when (it.kind) {
                        "review" -> "🔁"; "mistake" -> "❌"; "formula" -> "📐"; "weak" -> "⚠️"; "new" -> "📘"; else -> "📌"
                    }
                    Surface(shape = RoundedCornerShape(10.dp), color = cs.surfaceVariant.copy(alpha = 0.35f),
                        modifier = Modifier.clickable { onOpenChat("带我学/练这一项:${it.text}") }) {
                        Row(Modifier.fillMaxWidth().padding(horizontal = 6.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = it.done, onCheckedChange = { toggle(idx) }, modifier = Modifier.size(36.dp))
                            Text(icon, fontSize = 13.sp)
                            Spacer(Modifier.width(4.dp))
                            Column(Modifier.weight(1f)) {
                                Text(preprocessMath(it.text), fontSize = 11.sp, color = if (it.done) cs.onSurfaceVariant else cs.onSurface,
                                    textDecoration = if (it.done) TextDecoration.LineThrough else null)
                                if (it.reason.isNotBlank())
                                    Text("${it.reason}${if (it.est > 0) " · ${it.est}min" else ""}", fontSize = 9.sp, color = cs.onSurfaceVariant)
                            }
                        }
                    }
                }

                item {
                    Spacer(Modifier.height(4.dp))
                    OutlinedButton(onClick = { onOpenChat("按我现在的进度给我讲解今天计划里第一项,讲完出题检验") },
                        modifier = Modifier.fillMaxWidth().height(36.dp)) {
                        Text("▶ 让 AI 带我开始", fontSize = 12.sp)
                    }
                }
            }
        }
    }
}
