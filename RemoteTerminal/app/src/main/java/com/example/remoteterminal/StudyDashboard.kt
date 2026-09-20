package com.example.remoteterminal

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * 学习仪表盘 — 手表紧凑版。
 * 内联模块: 点击快捷操作展开对应面板,无需跳转。
 */

enum class ActivePanel { NONE, FOCUS, REVIEW, QUIZ, FLASHCARD, NOTES }

@Composable
fun StudyDashboard(
    prefs: Prefs,
    onNavigateBack: () -> Unit,
    onOpenChat: (String) -> Unit = {},
    onOpenTimetable: () -> Unit = {},
    onOpenPlan: () -> Unit = {},
    onOpenMindMap: () -> Unit = {},
) {
    val cs = MaterialTheme.colorScheme
    var activePanel by remember { mutableStateOf(ActivePanel.NONE) }

    var streak by remember { mutableStateOf(0) }
    var kpCount by remember { mutableStateOf(0) }; var fmCount by remember { mutableStateOf(0) }
    var todayMin by remember { mutableStateOf(0) }; var todayEx by remember { mutableStateOf(0) }
    var mistakes by remember { mutableStateOf(0) }; var hwPending by remember { mutableStateOf(0) }
    var weakText by remember { mutableStateOf("") }; var formulaText by remember { mutableStateOf("") }
    var scheduleText by remember { mutableStateOf("") }
    var examName by remember { mutableStateOf("") }; var examDays by remember { mutableStateOf(-999) }
    var planGoal by remember { mutableStateOf("") }; var planMilestones by remember { mutableStateOf<List<String>>(emptyList()) }
    var coverage by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var timelineSlots by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var freeSlots by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }

    // 番茄钟状态
    var focusSeconds by remember { mutableStateOf(0) }
    var focusRunning by remember { mutableStateOf(false) }
    var isResting by remember { mutableStateOf(false) }
    var workMinutes by remember { mutableStateOf(25) }
    var restMinutes by remember { mutableStateOf(5) }
    var cycleCount by remember { mutableStateOf(0) }
    var totalCycles by remember { mutableStateOf(4) }
    var focusTarget by remember { mutableStateOf(25 * 60) }
    var focusDone by remember { mutableStateOf(false) }

    LaunchedEffect(focusRunning) {
        if (focusRunning) {
            while (focusRunning) {
                kotlinx.coroutines.delay(1000)
                focusSeconds++
                if (focusSeconds >= focusTarget) {
                    focusRunning = false; focusDone = true
                }
            }
        }
    }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            try {
                val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/learn/dashboard?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"; conn.connectTimeout = 5000; conn.readTimeout = 5000
                if (conn.responseCode == 200) {
                    val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    val d = json.optJSONObject("dashboard") ?: JSONObject()
                    val stats = d.optJSONObject("stats") ?: JSONObject()
                    kpCount = stats.optInt("total_knowledge_points")
                    fmCount = stats.optInt("total_formulas")
                    todayMin = stats.optInt("today_study_minutes")
                    todayEx = stats.optInt("today_exercises")
                    mistakes = stats.optInt("unreviewed_mistakes")
                    streak = d.optInt("streak")
                    hwPending = d.optInt("homework_pending")
                    d.optJSONArray("coverage")?.let { cv ->
                        coverage = (0 until cv.length()).map { cv.getJSONObject(it) }
                    }
                    d.optJSONArray("exams")?.let { ex ->
                        if (ex.length() > 0) {
                            examName = ex.getJSONObject(0).optString("name")
                            examDays = ex.getJSONObject(0).optInt("days_left", -999)
                        }
                    }
                    val weak = d.optJSONArray("weak_topics")
                    if (weak != null && weak.length() > 0) {
                        val sb = StringBuilder()
                        for (i in 0 until minOf(weak.length(), 3)) {
                            val w = weak.getJSONObject(i)
                            sb.append("${w.optString("title")} ${w.optInt("mastery")}%  ")
                        }
                        weakText = sb.toString().trim()
                    }
                    val fms = d.optJSONArray("due_formulas")
                    if (fms != null && fms.length() > 0) {
                        val sb = StringBuilder()
                        for (i in 0 until minOf(fms.length(), 3)) {
                            val f = fms.getJSONObject(i)
                            sb.append("${f.optString("name")}  ")
                        }
                        formulaText = sb.toString().trim()
                    }
                    val sched = d.optJSONArray("today_schedule")
                    val freeArr = d.optJSONArray("free_slots")
                    // Build timeline
                    val tl = mutableListOf<JSONObject>()
                    if (sched != null) for (i in 0 until sched.length()) {
                        val s = sched.getJSONObject(i); s.put("type", "class"); tl.add(s)
                    }
                    if (freeArr != null) for (i in 0 until freeArr.length()) {
                        val f = freeArr.getJSONObject(i); f.put("type", "free"); tl.add(f)
                    }
                    tl.sortBy { it.optString("start") }
                    timelineSlots = tl

                    if (sched != null && sched.length() > 0) {
                        val sb = StringBuilder()
                        for (i in 0 until sched.length()) {
                            val s = sched.getJSONObject(i)
                            sb.append("${s.optString("start")}-${s.optString("end")} ${s.optString("name")}\n")
                        }
                        scheduleText = sb.toString().trim()
                    } else {
                        var totalMin = 0
                        if (freeArr != null) for (i in 0 until freeArr.length()) totalMin += freeArr.getJSONObject(i).optInt("duration_min", 0)
                        scheduleText = "空闲 ${totalMin}分钟 可学习"
                    }
                }
                conn.disconnect()
            } catch (_: Exception) {}
            // 拉学习计划(目标+里程碑)
            try {
                val u2 = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/study/plan?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}")
                val c2 = u2.openConnection() as HttpURLConnection
                c2.requestMethod = "GET"; c2.connectTimeout = 5000; c2.readTimeout = 5000
                if (c2.responseCode == 200) {
                    val pj = JSONObject(c2.inputStream.bufferedReader().use { it.readText() }).optJSONObject("plan")
                    if (pj != null) {
                        planGoal = pj.optString("goal")
                        pj.optJSONArray("milestones")?.let { ms ->
                            planMilestones = (0 until ms.length()).map { ms.optString(it) }
                        }
                    }
                }
                c2.disconnect()
            } catch (_: Exception) {}
        }
        loading = false
    }

    Column(modifier = Modifier.fillMaxSize().padding(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(bottom = 2.dp)) {
            IconButton(onClick = onNavigateBack, modifier = Modifier.size(32.dp)) { Icon(Icons.Filled.ArrowBack, null, Modifier.size(18.dp)) }
            Text("学习", fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            if (streak > 0) Surface(shape = RoundedCornerShape(8.dp), color = cs.primary.copy(alpha = 0.15f)) {
                Text("🔥$streak", fontSize = 11.sp, modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp))
            }
            IconButton(onClick = onOpenTimetable, modifier = Modifier.size(32.dp)) { Icon(Icons.Filled.CalendarToday, null, Modifier.size(18.dp)) }
        }

        if (loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp) }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                // 统计条
                item {
                    Card(colors = CardDefaults.cardColors(containerColor = cs.primary.copy(alpha = 0.08f)), shape = RoundedCornerShape(12.dp)) {
                        Row(Modifier.fillMaxWidth().padding(8.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
                            StatItem("知识点", kpCount.toString(), cs.primary)
                            StatItem("公式", fmCount.toString(), cs.tertiary)
                            StatItem("今日", "${todayMin}min", cs.secondary)
                            if (mistakes > 0) StatItem("错题", mistakes.toString(), cs.error)
                        }
                    }
                }

                // 考试倒计时
                if (examDays in 0..3650) {
                    item {
                        Card(colors = CardDefaults.cardColors(containerColor = cs.primary.copy(alpha = 0.12f)), shape = RoundedCornerShape(12.dp)) {
                            Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text("🎯 $examName", fontSize = 12.sp, color = cs.onSurface, modifier = Modifier.weight(1f))
                                Text("还有 ", fontSize = 11.sp, color = cs.onSurfaceVariant)
                                Text("$examDays", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = cs.primary)
                                Text(" 天", fontSize = 11.sp, color = cs.onSurfaceVariant)
                            }
                        }
                    }
                }

                // 学习进度(各科覆盖度进度条)
                if (coverage.isNotEmpty()) {
                    item {
                        Card(colors = CardDefaults.cardColors(containerColor = cs.surfaceVariant.copy(alpha = 0.4f)), shape = RoundedCornerShape(12.dp)) {
                            Column(Modifier.fillMaxWidth().padding(10.dp)) {
                                Text("📈 学习进度", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = cs.onSurface)
                                Spacer(Modifier.height(4.dp))
                                coverage.forEach { c ->
                                    val total = c.optInt("total").coerceAtLeast(1)
                                    val mastered = c.optInt("mastered")
                                    val pct = mastered.toFloat() / total
                                    Spacer(Modifier.height(3.dp))
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text(c.optString("subject").ifEmpty { "未分科" }, fontSize = 10.sp,
                                            color = cs.onSurface, modifier = Modifier.width(64.dp), maxLines = 1)
                                        LinearProgressIndicator(progress = { pct.coerceIn(0f, 1f) },
                                            modifier = Modifier.weight(1f).height(6.dp), color = cs.primary,
                                            trackColor = cs.surface)
                                        Spacer(Modifier.width(6.dp))
                                        Text("$mastered/$total", fontSize = 9.sp, color = cs.onSurfaceVariant, modifier = Modifier.width(48.dp))
                                    }
                                }
                            }
                        }
                    }
                }

                // 今日计划:一键开始学/复习/AI总结
                item {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        ActionChip("▶ 开始学习", cs.primary) {
                            onOpenChat("根据我的课表和计划,现在开始今天该学的内容,带我一步步学")
                        }
                        ActionChip("📖 复习", cs.tertiary) {
                            onOpenChat("复习今天到期的内容,先挑2个考我")
                        }
                        ActionChip("🤖 总结", cs.secondary) {
                            onOpenChat("总结我今天的学习情况,分析进度、薄弱点和明天该重点学什么")
                        }
                    }
                }
                // 规划 / 思维导图
                item {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        ActionChip("📋 学习规划", cs.primary) { onOpenPlan() }
                        ActionChip("🧠 思维导图", cs.tertiary) { onOpenMindMap() }
                    }
                }
                // 学习目标 + 里程碑(规划生成后显示)
                if (planGoal.isNotBlank()) {
                    item {
                        Card(colors = CardDefaults.cardColors(containerColor = cs.tertiary.copy(alpha = 0.10f)), shape = RoundedCornerShape(12.dp)) {
                            Column(Modifier.padding(10.dp)) {
                                Text("🎓 目标:$planGoal", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = cs.onSurface)
                                if (planMilestones.isNotEmpty()) {
                                    Spacer(Modifier.height(4.dp))
                                    planMilestones.take(5).forEachIndexed { i, m ->
                                        Text("${i + 1}. $m", fontSize = 11.sp, color = cs.onSurfaceVariant,
                                            modifier = Modifier.padding(vertical = 1.dp))
                                    }
                                }
                            }
                        }
                    }
                }

                // 弱项+公式
                if (weakText.isNotBlank() || formulaText.isNotBlank()) {
                    item {
                        Card(colors = CardDefaults.cardColors(containerColor = cs.surfaceVariant.copy(alpha = 0.4f)), shape = RoundedCornerShape(12.dp)) {
                            Column(Modifier.padding(8.dp)) {
                                if (weakText.isNotBlank()) Text("⚠️ ${preprocessMath(weakText)}", fontSize = 11.sp, color = cs.error)
                                if (formulaText.isNotBlank()) Text("📐 ${preprocessMath(formulaText)}", fontSize = 11.sp, color = cs.onSurfaceVariant)
                            }
                        }
                    }
                }

                // 快捷操作
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                        ActionChip("🍅 专注", if (activePanel == ActivePanel.FOCUS) cs.primary else cs.onSurfaceVariant) {
                            activePanel = if (activePanel == ActivePanel.FOCUS) ActivePanel.NONE else ActivePanel.FOCUS
                            focusRunning = false; focusSeconds = 0  // 不自动开始
                        }
                        ActionChip("📝 笔记", if (activePanel == ActivePanel.NOTES) cs.primary else cs.onSurfaceVariant) {
                            activePanel = if (activePanel == ActivePanel.NOTES) ActivePanel.NONE else ActivePanel.NOTES
                        }
                        ActionChip("🎯 真题", cs.onSurfaceVariant) { onOpenChat("从我上传的真题/题库里出2道题考我,我答完帮我判分并记录对错") }
                        ActionChip("📕 错题本", cs.onSurfaceVariant) { onOpenChat("打开我的错题本,挑1-2道最近做错的带我重做,先讲清当初为什么错") }
                        ActionChip("🃏 闪卡", cs.onSurfaceVariant) { onOpenChat("复习闪卡") }
                        ActionChip("🧠 复盘", cs.onSurfaceVariant) { onOpenChat("今日学习复盘") }
                    }
                }

                // 内联面板
                when (activePanel) {
                    ActivePanel.FOCUS -> item {
                        Card(colors = CardDefaults.cardColors(
                            containerColor = if (isResting) cs.tertiaryContainer.copy(alpha = 0.3f)
                            else cs.primaryContainer.copy(alpha = 0.3f)), shape = RoundedCornerShape(12.dp)) {
                            Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                // 状态标题
                                val label = when {
                                    focusDone && isResting -> "☕ 休息完成！"
                                    focusDone && !isResting -> "✅ 番茄完成！"
                                    isResting -> "☕ 休息中"
                                    focusRunning -> "🍅 专注中"
                                    else -> "🍅 番茄钟"
                                }
                                Text(label, fontSize = 14.sp, fontWeight = FontWeight.Bold,
                                     color = if (isResting) cs.tertiary else cs.primary)

                                // 进度条
                                val progress = if (focusTarget > 0) focusSeconds.toFloat() / focusTarget else 0f
                                LinearProgressIndicator(progress = { progress.coerceIn(0f, 1f) },
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp).height(4.dp),
                                    color = if (isResting) cs.tertiary else cs.primary,
                                    trackColor = cs.surfaceVariant)

                                Text(formatTime(focusSeconds), fontSize = 26.sp, fontWeight = FontWeight.Bold,
                                     color = if (focusRunning) cs.primary else cs.onSurfaceVariant)

                                // 周期计数
                                Text("第 ${cycleCount + 1}/$totalCycles 个番茄  |  ${if (isResting) "休息" else "专注"} ${if (isResting) restMinutes else workMinutes}分钟",
                                     fontSize = 10.sp, color = cs.onSurfaceVariant)

                                Spacer(Modifier.height(4.dp))

                                // 按钮组
                                if (focusDone) {
                                    // 完成当前段 → 切换到下一段
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        OutlinedButton(onClick = {
                                            val newCycle = if (!isResting) cycleCount + 1 else cycleCount
                                            if (newCycle >= totalCycles) {
                                                // 全部完成
                                                activePanel = ActivePanel.NONE; focusSeconds = 0
                                                focusRunning = false; cycleCount = 0; focusDone = false
                                            } else {
                                                isResting = !isResting
                                                focusTarget = if (isResting) restMinutes * 60 else workMinutes * 60
                                                focusSeconds = 0; focusDone = false; focusRunning = true
                                                cycleCount = newCycle
                                            }
                                        }, modifier = Modifier.height(32.dp)) {
                                            Text(if (cycleCount + 1 >= totalCycles && !isResting) "🎉 完成"
                                                 else if (isResting) "▶ 开始专注" else "☕ 休息一下",
                                                 fontSize = 12.sp)
                                        }
                                        TextButton(onClick = { activePanel = ActivePanel.NONE; focusSeconds = 0; focusRunning = false; cycleCount = 0; focusDone = false },
                                                   modifier = Modifier.height(32.dp)) {
                                            Text("关闭", fontSize = 11.sp)
                                        }
                                    }
                                } else if (!focusRunning && focusSeconds == 0) {
                                    // 初始状态: 显示开始+设置
                                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                        Button(onClick = {
                                            focusTarget = workMinutes * 60; focusRunning = true; isResting = false
                                        }, modifier = Modifier.height(32.dp)) {
                                            Text("▶ 开始", fontSize = 12.sp)
                                        }
                                        // 时间快捷设置
                                        TextButton(onClick = { workMinutes = if (workMinutes == 25) 45 else if (workMinutes == 45) 15 else 25 },
                                                   modifier = Modifier.height(28.dp)) {
                                            Text("${workMinutes}min", fontSize = 10.sp)
                                        }
                                        TextButton(onClick = { totalCycles = if (totalCycles == 4) 2 else if (totalCycles == 2) 6 else 4 },
                                                   modifier = Modifier.height(28.dp)) {
                                            Text("×${totalCycles}", fontSize = 10.sp)
                                        }
                                    }
                                } else if (focusRunning) {
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(onClick = { focusRunning = false }, modifier = Modifier.height(32.dp),
                                               colors = ButtonDefaults.buttonColors(containerColor = cs.tertiary)) {
                                            Text("⏸", fontSize = 12.sp)
                                        }
                                        OutlinedButton(onClick = { focusRunning = false; focusSeconds = 0; focusDone = false },
                                                       modifier = Modifier.height(32.dp)) {
                                            Text("跳过", fontSize = 12.sp)
                                        }
                                    }
                                } else {
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(onClick = { focusRunning = true }, modifier = Modifier.height(32.dp)) {
                                            Text("▶ 继续", fontSize = 12.sp)
                                        }
                                        OutlinedButton(onClick = { focusSeconds = 0; activePanel = ActivePanel.NONE; cycleCount = 0 },
                                                       modifier = Modifier.height(32.dp)) {
                                            Text("重置", fontSize = 12.sp)
                                        }
                                    }
                                }
                            }
                        }
                    }
                    ActivePanel.NOTES -> item {
                        Card(colors = CardDefaults.cardColors(containerColor = cs.tertiaryContainer.copy(alpha = 0.3f)), shape = RoundedCornerShape(12.dp)) {
                            Column(Modifier.padding(10.dp)) {
                                Text("📝 快速笔记", fontSize = 13.sp, fontWeight = FontWeight.Bold)
                                Spacer(Modifier.height(4.dp))
                                var noteText by remember { mutableStateOf("") }
                                OutlinedTextField(value = noteText, onValueChange = { noteText = it },
                                    placeholder = { Text("记下想法...", fontSize = 11.sp) },
                                    modifier = Modifier.fillMaxWidth(), singleLine = true, textStyle = MaterialTheme.typography.bodySmall)
                                Spacer(Modifier.height(4.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Button(onClick = {
                                        if (noteText.isNotBlank()) { onOpenChat("记一下: $noteText"); activePanel = ActivePanel.NONE }
                                    }, modifier = Modifier.height(30.dp), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp)) {
                                        Text("保存", fontSize = 11.sp)
                                    }
                                    TextButton(onClick = { activePanel = ActivePanel.NONE }, modifier = Modifier.height(30.dp)) {
                                        Text("取消", fontSize = 11.sp)
                                    }
                                }
                            }
                        }
                    }
                    else -> {}
                }

                // 今日时间轴（彩色）
                if (timelineSlots.isNotEmpty()) item {
                    Card(colors = CardDefaults.cardColors(containerColor = cs.surface.copy(alpha = 0.5f)),
                         shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.padding(8.dp)) {
                            Text("⏰ 今日时间轴", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            Spacer(Modifier.height(4.dp))
                            val now = java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault())
                                .format(java.util.Date())
                            timelineSlots.forEach { slot ->
                                val start = slot.optString("start", "")
                                val end = slot.optString("end", "")
                                val name = slot.optString("name", if (slot.optString("type") == "free") "空闲" else "")
                                val isClass = slot.optString("type") == "class"
                                val isPast = end < now
                                val isCurrent = start <= now && end >= now
                                val bgColor = when {
                                    isCurrent -> cs.primary.copy(alpha = 0.2f)
                                    isPast -> Color.Gray.copy(alpha = 0.15f)
                                    isClass -> Color(0xFF4A90D9).copy(alpha = 0.12f)
                                    else -> Color(0xFF7CB342).copy(alpha = 0.1f)
                                }
                                Row(Modifier.fillMaxWidth()
                                    .background(bgColor, RoundedCornerShape(6.dp))
                                    .padding(horizontal = 6.dp, vertical = 3.dp),
                                    verticalAlignment = Alignment.CenterVertically) {
                                    Text("$start-$end", fontSize = 9.sp, color = if (isPast) Color.Gray else cs.onSurfaceVariant,
                                         modifier = Modifier.width(58.dp))
                                    Text(if (isClass) name else if (isCurrent) "📍 现在" else "空闲",
                                         fontSize = 10.sp,
                                         fontWeight = if (isCurrent) FontWeight.Bold else FontWeight.Normal,
                                         color = when {
                                             isCurrent -> cs.primary
                                             isPast -> Color.Gray
                                             isClass -> cs.onSurface
                                             else -> Color(0xFF7CB342)
                                         })
                                    if (isCurrent) {
                                        Spacer(Modifier.weight(1f))
                                        Text("←", fontSize = 10.sp, color = cs.primary)
                                    }
                                }
                            }
                        }
                    }
                }

                if (hwPending > 0) item {
                    Surface(shape = RoundedCornerShape(12.dp), color = cs.errorContainer.copy(alpha = 0.5f), modifier = Modifier.clickable { onOpenChat("查看我的作业") }) {
                        Row(Modifier.padding(8.dp)) { Text("📝", fontSize = 14.sp); Spacer(Modifier.width(4.dp)); Text("$hwPending 项作业待完成", fontSize = 11.sp, color = cs.onErrorContainer) }
                    }
                }
            }
        }
    }
}

fun formatTime(seconds: Int): String {
    val m = seconds / 60; val s = seconds % 60
    return "${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}"
}

@Composable fun StatItem(label: String, value: String, color: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = color)
        Text(label, fontSize = 9.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable fun ActionChip(label: String, color: Color, onClick: () -> Unit) {
    Surface(shape = RoundedCornerShape(16.dp), color = color.copy(alpha = 0.12f), modifier = Modifier.clickable(onClick = onClick)) {
        Text(label, fontSize = 11.sp, color = color, modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp))
    }
}
