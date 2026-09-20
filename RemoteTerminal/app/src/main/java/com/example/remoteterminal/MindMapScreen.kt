package com.example.remoteterminal

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
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
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** 思维导图页 — 缩进树状,带掌握度配色 + 折叠。 */

private data class MapNode(
    val id: Int,
    val title: String,
    val mastery: Int,
    val children: List<MapNode>,
)

private fun parseNodes(arr: JSONArray?): List<MapNode> {
    if (arr == null) return emptyList()
    val out = ArrayList<MapNode>(arr.length())
    for (i in 0 until arr.length()) {
        val o = arr.optJSONObject(i) ?: continue
        out.add(
            MapNode(
                id = o.optInt("id", i),
                title = o.optString("title"),
                mastery = o.optInt("mastery", 0),
                children = parseNodes(o.optJSONArray("children")),
            )
        )
    }
    return out
}

@Composable
fun MindMapScreen(onBack: () -> Unit, onOpenChat: (String) -> Unit = {}) {
    val cs = MaterialTheme.colorScheme
    var subjects by remember { mutableStateOf<List<String>>(emptyList()) }
    var selected by remember { mutableStateOf("") }
    var tree by remember { mutableStateOf<List<MapNode>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(selected, reload) {
        loading = true
        withContext(Dispatchers.IO) {
            try {
                val q = if (selected.isBlank()) "" else "&subject=${java.net.URLEncoder.encode(selected, "UTF-8")}"
                val url = URL("http://${Config.HOST}:${Config.BRAIN_PORT}/learn/kptree?token=${java.net.URLEncoder.encode(Config.AUTH_TOKEN, "UTF-8")}$q")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"; conn.connectTimeout = 5000; conn.readTimeout = 6000
                if (conn.responseCode == 200) {
                    val j = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    j.optJSONArray("subjects")?.let { s ->
                        subjects = (0 until s.length()).map { s.optString(it) }
                    }
                    tree = parseNodes(j.optJSONArray("tree"))
                }
                conn.disconnect()
            } catch (_: Exception) {}
        }
        loading = false
    }

    Column(Modifier.fillMaxSize().padding(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            IconButton(onClick = onBack, modifier = Modifier.size(32.dp)) { Icon(Icons.Filled.ArrowBack, null, Modifier.size(18.dp)) }
            Text("🧠 思维导图", fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
        }
        // 科目筛选
        if (subjects.isNotEmpty()) {
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                SubjectChip("全部", selected.isBlank()) { selected = "" }
                subjects.forEach { s -> SubjectChip(s, selected == s) { selected = s } }
            }
        }

        if (loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
            }
        } else if (tree.isEmpty()) {
            Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text("还没有知识图谱", fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text("先去资料页上传课本,或让 AI 帮你整理知识点", fontSize = 11.sp,
                    color = cs.onSurfaceVariant)
                Spacer(Modifier.height(12.dp))
                Button(onClick = { onOpenChat("把我学过的知识点整理成思维导图,按主题分层,并存入我的知识库") }) {
                    Text("让 AI 整理", fontSize = 12.sp)
                }
            }
        } else {
            LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                tree.forEach { node -> renderNode(node, 0, this) }
            }
        }
    }
}

@Composable
private fun SubjectChip(label: String, active: Boolean, onClick: () -> Unit) {
    val cs = MaterialTheme.colorScheme
    Surface(shape = RoundedCornerShape(14.dp),
        color = if (active) cs.primary else cs.surfaceVariant.copy(alpha = 0.5f),
        modifier = Modifier.clickable(onClick = onClick)) {
        Text(label, fontSize = 11.sp, color = if (active) cs.onPrimary else cs.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp))
    }
}

private fun masteryColor(m: Int): Color = when {
    m >= 80 -> Color(0xFF4CAF50)
    m >= 50 -> Color(0xFFFFB300)
    m > 0 -> Color(0xFFEF6C00)
    else -> Color(0xFF9E9E9E)
}

/** 递归渲染节点到 LazyColumn(用闭包展开/折叠由各节点自管)。 */
private fun renderNode(node: MapNode, depth: Int, scope: androidx.compose.foundation.lazy.LazyListScope) {
    scope.item(key = "${depth}_${node.id}_${node.title}") {
        NodeRow(node, depth)
    }
}

@Composable
private fun NodeRow(node: MapNode, depth: Int) {
    val cs = MaterialTheme.colorScheme
    var expanded by remember { mutableStateOf(depth < 2) }
    val hasChildren = node.children.isNotEmpty()
    val mc = masteryColor(node.mastery)

    Column {
        Row(verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth()
                .padding(start = (depth * 14).dp)
                .clickable(enabled = hasChildren) { expanded = !expanded }) {
            // 连接线/层级标记
            Box(Modifier.width(8.dp).height(20.dp).background(mc, RoundedCornerShape(2.dp)))
            Spacer(Modifier.width(6.dp))
            Surface(shape = RoundedCornerShape(8.dp), color = mc.copy(alpha = 0.12f),
                modifier = Modifier.weight(1f)) {
                Row(Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    if (hasChildren) {
                        Text(if (expanded) "▾ " else "▸ ", fontSize = 11.sp, color = cs.onSurfaceVariant)
                    }
                    Text(node.title, fontSize = if (depth == 0) 13.sp else 11.sp,
                        fontWeight = if (depth == 0) FontWeight.Bold else FontWeight.Normal,
                        color = cs.onSurface, modifier = Modifier.weight(1f))
                    if (node.mastery > 0) {
                        Text("${node.mastery}%", fontSize = 9.sp, color = mc, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
        if (expanded) {
            node.children.forEach { child -> NodeRow(child, depth + 1) }
        }
    }
}
