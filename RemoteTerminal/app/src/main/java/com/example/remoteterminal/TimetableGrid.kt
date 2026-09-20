package com.example.remoteterminal

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalContext
import android.widget.Toast
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * 可视化课表 — 手表紧凑版。
 * 一天一屏,左右滑动切换天。
 * 时间段: 6个块(上午3块 8-10/10-12/12-14, 下午2块 14-16/16-18, 晚上2块 19-21/21-22)
 */

data class TimeBlock(
    val start: String,
    val end: String,
    val label: String,
    val subject: String = "",
    val location: String = "",
    val isFree: Boolean = true,
    val category: String = ""
)

val TIME_SLOTS = listOf(
    TimeBlock("08:00", "10:00", "上午①"),
    TimeBlock("10:00", "12:00", "上午②"),
    TimeBlock("12:00", "14:00", "午间"),
    TimeBlock("14:00", "16:00", "下午①"),
    TimeBlock("16:00", "18:00", "下午②"),
    TimeBlock("19:00", "21:00", "晚上①"),
    TimeBlock("21:00", "22:00", "晚上②"),
)

val WEEKDAY_NAMES = listOf("周一", "周二", "周三", "周四", "周五", "周六", "周日")

val CATEGORY_COLORS = mapOf(
    "class" to Color(0xFF4A90D9),
    "self_study" to Color(0xFF7CB342),
    "exam" to Color(0xFFE53935),
    "lab" to Color(0xFF8E24AA),
    "sport" to Color(0xFFFF9800),
    "review" to Color(0xFF00BCD4),
    "free" to Color(0xFFBDBDBD),
)

@Composable
fun TimetableView(onBack: () -> Unit) {
    var selectedDay by remember {
        val raw = java.util.Calendar.getInstance().get(java.util.Calendar.DAY_OF_WEEK) - 1 // 0=周日
        mutableStateOf(if (raw == 0) 6 else raw - 1) // → 周一=0
    }

    var blocks by remember { mutableStateOf<List<TimeBlock>>(TIME_SLOTS) }
    var loading by remember { mutableStateOf(true) }

    // 简化: 从本地生成块,后续可从 API 加载
    LaunchedEffect(Unit) {
        // TODO: 从 schedule_engine 加载真实数据
        loading = false
    }

    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var showBulk by remember { mutableStateOf(false) }

    // 批量添加课表对话框
    if (showBulk) {
        var text by remember { mutableStateOf("") }
        var busy by remember { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { if (!busy) showBulk = false },
            title = { Text("批量添加课表") },
            text = {
                Column {
                    Text("每行一节课,例如:\n周一 8:00-9:40 高数 教3-101\n周三 下午2-4点 英语",
                        fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = text, onValueChange = { text = it },
                        modifier = Modifier.fillMaxWidth().height(160.dp),
                        placeholder = { Text("粘贴整张课表…") })
                }
            },
            confirmButton = {
                Button(enabled = !busy && text.isNotBlank(), onClick = {
                    busy = true
                    scope.launch {
                        val r = withContext(Dispatchers.IO) { bulkAddSchedule(text) }
                        Toast.makeText(ctx, r, Toast.LENGTH_LONG).show()
                        busy = false; showBulk = false
                    }
                }) { Text(if (busy) "添加中…" else "添加") }
            },
            dismissButton = { TextButton(onClick = { if (!busy) showBulk = false }) { Text("取消") } },
        )
    }

    Column(modifier = Modifier.fillMaxSize().padding(6.dp)) {
        // 顶栏: 天选择器
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            IconButton(onClick = onBack) { Icon(Icons.Filled.ArrowBack, null, Modifier.size(18.dp)) }
            Text("课表", fontSize = 14.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = { showBulk = true }) { Text("批量添加", fontSize = 12.sp) }
        }

        Spacer(Modifier.height(4.dp))

        // 星期横向滚动选择
        Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            WEEKDAY_NAMES.forEachIndexed { idx, name ->
                val selected = idx == selectedDay
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = if (selected) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.clickable { selectedDay = idx }
                ) {
                    Text(name, fontSize = 12.sp,
                         modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                         color = if (selected) MaterialTheme.colorScheme.onPrimary
                                 else MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }

        Spacer(Modifier.height(6.dp))

        // 时间段卡片
        LazyColumn(verticalArrangement = Arrangement.spacedBy(3.dp)) {
            items(blocks.size) { idx ->
                val block = blocks[idx]
                TimeBlockCard(block, idx == blocks.lastIndex)
            }
        }
    }
}

@Composable
fun TimeBlockCard(block: TimeBlock, isLast: Boolean) {
    val bgColor = if (!block.isFree) CATEGORY_COLORS[block.category] ?: Color(0xFF4A90D9)
                  else Color.Transparent
    val borderColor = if (block.isFree) MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f)
                      else bgColor

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (block.isFree) MaterialTheme.colorScheme.surface
                             else bgColor.copy(alpha = 0.12f)),
        shape = RoundedCornerShape(10.dp),
        border = if (block.isFree) androidx.compose.foundation.BorderStroke(1.dp, borderColor) else null
    ) {
        Row(modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            // 时间标签
            Column(horizontalAlignment = Alignment.CenterHorizontally,
                   modifier = Modifier.width(50.dp)) {
                Text(block.start, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                     color = if (block.isFree) MaterialTheme.colorScheme.onSurfaceVariant
                             else MaterialTheme.colorScheme.onSurface)
                Text(block.end, fontSize = 9.sp,
                     color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f))
            }

            // 分隔线
            Box(Modifier.width(2.dp).height(28.dp).background(
                if (block.isFree) MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f)
                else bgColor, RoundedCornerShape(1.dp)))

            Spacer(Modifier.width(8.dp))

            // 内容
            if (block.isFree) {
                Text("空闲 · 点击添加安排",
                     fontSize = 11.sp,
                     color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                     modifier = Modifier.weight(1f))
            } else {
                Column(modifier = Modifier.weight(1f)) {
                    Text(block.subject, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                    if (block.location.isNotBlank()) {
                        Text(block.location, fontSize = 10.sp,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

// 批量提交课表到 brain
private fun bulkAddSchedule(text: String): String {
    var conn: HttpURLConnection? = null
    return try {
        val url = "http://${Config.HOST}:${Config.BRAIN_PORT}/schedule/bulk"
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; doOutput = true; connectTimeout = 10000; readTimeout = 30000
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("X-Auth-Token", Config.AUTH_TOKEN)
        }
        conn.outputStream.use { it.write(JSONObject().put("text", text).toString().toByteArray(Charsets.UTF_8)) }
        val code = conn.responseCode
        val resp = (if (code in 200..299) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
        if (code in 200..299) {
            val j = JSONObject(resp)
            val added = j.optInt("added", 0)
            val failed = j.optJSONArray("failed")?.length() ?: 0
            "已添加 $added 节课" + (if (failed > 0) ",$failed 行未能识别" else "")
        } else "添加失败 HTTP $code"
    } catch (e: Exception) { "出错: ${e.message}" } finally { conn?.disconnect() }
}
