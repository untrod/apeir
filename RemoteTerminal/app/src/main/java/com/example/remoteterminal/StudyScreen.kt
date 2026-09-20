package com.example.remoteterminal

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * 学习计划页:备考目标设定、今日任务、打卡、出题、历史总结。
 * 提问走 ChatScreen 的学习模式(#study 前缀)。
 */
@Composable
fun StudyScreen(onBack: () -> Unit, onAskQuestion: () -> Unit) {
    val scope = rememberCoroutineScope()
    var today by remember { mutableStateOf<JSONObject?>(null) }
    var loading by remember { mutableStateOf(true) }
    var showPlanDialog by remember { mutableStateOf(false) }
    var showQuizDialog by remember { mutableStateOf(false) }
    var quizResult by remember { mutableStateOf("") }
    var statusMsg by remember { mutableStateOf("") }
    val cs = MaterialTheme.colorScheme

    fun refresh() {
        scope.launch {
            loading = true
            today = studyGet("today")?.optJSONObject("today")
            loading = false
        }
    }
    LaunchedEffect(Unit) { refresh() }

    // 设置计划对话框
    if (showPlanDialog) {
        PlanDialog(
            onDismiss = { showPlanDialog = false },
            onCreate = { goal, deadline, subjects, extra ->
                showPlanDialog = false
                statusMsg = "正在生成计划…"
                scope.launch {
                    val body = JSONObject()
                        .put("goal", goal).put("deadline", deadline)
                        .put("subjects", JSONArray(subjects)).put("extra", extra)
                    val r = studyPost("plan", body)
                    statusMsg = if (r?.optBoolean("ok") == true) "计划已生成" else "生成失败: ${r?.optString("error")}"
                    refresh()
                }
            },
        )
    }

    // 出题对话框
    if (showQuizDialog) {
        QuizDialog(
            onDismiss = { showQuizDialog = false },
            onQuiz = { subject, type, count ->
                showQuizDialog = false
                quizResult = "出题中…"
                scope.launch {
                    val r = studyGet("quiz?subject=${enc(subject)}&type=${enc(type)}&count=$count")
                    quizResult = if (r?.optBoolean("ok") == true) r.optString("quiz") else "出题失败"
                }
            },
        )
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("学习", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = { refresh() }) { Text("刷新") }
            TextButton(onClick = onBack) { Text("完成") }
        }
        if (statusMsg.isNotBlank()) {
            Text(statusMsg, style = MaterialTheme.typography.bodySmall, color = cs.primary,
                modifier = Modifier.padding(vertical = 4.dp))
        }
        Spacer(Modifier.height(8.dp))

        val hasPlan = today?.optBoolean("has_plan") == true
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (loading) {
                item { Box(Modifier.fillMaxWidth().padding(40.dp), Alignment.Center) { CircularProgressIndicator() } }
            } else if (!hasPlan) {
                item {
                    Card(shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("还没有学习计划", style = MaterialTheme.typography.titleMedium)
                            Spacer(Modifier.height(8.dp))
                            Text("告诉 AI 你的备考目标和截止日期，它会为你生成每日学习计划",
                                style = MaterialTheme.typography.bodySmall, color = cs.onSurfaceVariant)
                            Spacer(Modifier.height(12.dp))
                            Button(onClick = { showPlanDialog = true }) { Text("设置学习计划") }
                        }
                    }
                }
            } else {
                val t = today!!
                // 目标卡片
                item {
                    Card(shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = cs.primary.copy(alpha = 0.08f))) {
                        Column(Modifier.padding(16.dp)) {
                            Text(t.optString("goal"), style = MaterialTheme.typography.titleMedium)
                            Spacer(Modifier.height(4.dp))
                            Text("截止 ${t.optString("deadline")} · 还剩 ${t.optInt("days_left")} 天",
                                fontSize = 12.sp, color = cs.onSurfaceVariant)
                        }
                    }
                }
                // 今日任务
                item {
                    val daily = t.optJSONObject("daily_plan")
                    Card(shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.padding(16.dp)) {
                            Text("今日任务", style = MaterialTheme.typography.titleSmall)
                            Spacer(Modifier.height(8.dp))
                            if (daily != null) {
                                daily.keys().forEach { subject ->
                                    Row(Modifier.padding(vertical = 3.dp)) {
                                        Text("· $subject: ", fontSize = 13.sp, color = cs.primary)
                                        Text(daily.optString(subject), fontSize = 13.sp,
                                            color = cs.onSurfaceVariant)
                                    }
                                }
                            }
                            val checked = t.optBoolean("checked_in")
                            Spacer(Modifier.height(8.dp))
                            Text(if (checked) "✓ 今日已打卡" else "今日未打卡",
                                fontSize = 12.sp,
                                color = if (checked) cs.primary else cs.onSurfaceVariant)
                        }
                    }
                }
                // 提醒
                item {
                    val reminders = t.optJSONArray("reminders")
                    if (reminders != null && reminders.length() > 0) {
                        Card(shape = RoundedCornerShape(12.dp)) {
                            Column(Modifier.padding(16.dp)) {
                                Text("每日提醒", style = MaterialTheme.typography.titleSmall)
                                Spacer(Modifier.height(8.dp))
                                for (i in 0 until reminders.length()) {
                                    val r = reminders.getJSONObject(i)
                                    Text("⏰ ${r.optString("time")} — ${r.optString("text")}",
                                        fontSize = 13.sp, color = cs.onSurfaceVariant,
                                        modifier = Modifier.padding(vertical = 2.dp))
                                }
                            }
                        }
                    }
                }
                // 操作按钮
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            scope.launch {
                                val r = studyPost("checkin", JSONObject().put("done", JSONArray()).put("note", "已完成今日任务"))
                                statusMsg = if (r?.optBoolean("ok") == true) "打卡成功" else "打卡失败"
                                refresh()
                            }
                        }) { Text("打卡") }
                        OutlinedButton(onClick = { showQuizDialog = true }) { Text("出题") }
                        OutlinedButton(onClick = onAskQuestion) { Text("提问") }
                    }
                }
                // 重设计划
                item {
                    TextButton(onClick = { showPlanDialog = true }) { Text("重新设置计划") }
                }
            }

            // 出题结果
            if (quizResult.isNotBlank()) {
                item {
                    Card(shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.padding(16.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("练习题", style = MaterialTheme.typography.titleSmall)
                                Spacer(Modifier.weight(1f))
                                TextButton(onClick = { quizResult = "" }) { Text("关闭") }
                            }
                            SelectionContainer { MarkdownText(quizResult) }
                        }
                    }
                }
            }
        }
    }
}

// 设置计划对话框
@Composable
private fun PlanDialog(onDismiss: () -> Unit, onCreate: (String, String, List<String>, String) -> Unit) {
    var goal by remember { mutableStateOf("") }
    var deadline by remember { mutableStateOf("") }
    var subjectsText by remember { mutableStateOf("") }
    var extra by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("设置学习计划") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(goal, { goal = it }, label = { Text("目标") },
                    placeholder = { Text("如 考研复习计划") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(deadline, { deadline = it }, label = { Text("截止日期") },
                    placeholder = { Text("YYYY-MM-DD，如 2026-04-01") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(subjectsText, { subjectsText = it }, label = { Text("科目(逗号分隔)") },
                    placeholder = { Text("高等数学,英语,语文,计算机") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(extra, { extra = it }, label = { Text("补充说明(可选)") },
                    placeholder = { Text("如 每天能学4小时,英语基础薄弱") }, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            Button(onClick = {
                val subjects = subjectsText.split(",", "，").map { it.trim() }.filter { it.isNotEmpty() }
                if (goal.isNotBlank() && deadline.isNotBlank()) onCreate(goal, deadline, subjects, extra)
            }) { Text("生成计划") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

// 出题对话框
@Composable
private fun QuizDialog(onDismiss: () -> Unit, onQuiz: (String, String, Int) -> Unit) {
    var subject by remember { mutableStateOf("") }
    var type by remember { mutableStateOf("选择题") }
    var count by remember { mutableStateOf("5") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("出题练习") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(subject, { subject = it }, label = { Text("科目") },
                    placeholder = { Text("如 英语 / 高等数学") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(type, { type = it }, label = { Text("题型") },
                    placeholder = { Text("单词/选择题/例句/概念") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(count, { count = it }, label = { Text("题量") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            Button(onClick = {
                if (subject.isNotBlank()) onQuiz(subject, type, count.toIntOrNull() ?: 5)
            }) { Text("出题") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

// 网络辅助
private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

private suspend fun studyGet(pathAndQuery: String): JSONObject? = withContext(Dispatchers.IO) {
    var conn: HttpURLConnection? = null
    try {
        val sep = if (pathAndQuery.contains("?")) "&" else "?"
        val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/study/$pathAndQuery${sep}token=${enc(Config.AUTH_TOKEN)}"
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"; connectTimeout = 10000; readTimeout = 60000
        }
        if (conn.responseCode !in 200..299) return@withContext null
        JSONObject(conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() })
    } catch (_: Exception) { null } finally { conn?.disconnect() }
}

private suspend fun studyPost(path: String, body: JSONObject): JSONObject? = withContext(Dispatchers.IO) {
    var conn: HttpURLConnection? = null
    try {
        val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/study/$path"
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; doOutput = true; connectTimeout = 10000; readTimeout = 90000
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
        }
        conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
        val code = conn.responseCode
        val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
            ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: return@withContext null
        JSONObject(text)
    } catch (_: Exception) { null } finally { conn?.disconnect() }
}
