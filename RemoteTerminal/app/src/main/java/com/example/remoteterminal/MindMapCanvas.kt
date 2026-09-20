package com.example.remoteterminal

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.*
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.*
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.*

/**
 * 交互式思维导图 Canvas — 替代原缩进树视图。
 */

// 数据模型(使用独特命名避免与 MindMapScreen.kt 冲突)
data class CanvasMapNode(
    val id: Int,
    val title: String,
    val mastery: Float = 0f,
    val children: List<CanvasMapNode> = emptyList(),
    val expanded: Boolean = true,
)

data class CanvasLayoutNode(
    val node: CanvasMapNode,
    val x: Float, val y: Float,
    val width: Float, val height: Float,
    val children: List<CanvasLayoutNode> = emptyList(),
)

// 颜色
internal fun canvasMasteryColor(mastery: Float): Color = when {
    mastery >= 80 -> Color(0xFF5CC98A)
    mastery >= 50 -> Color(0xFFE0A83A)
    mastery > 0 -> Color(0xFFE0804A)
    else -> Color(0xFF6B7386)
}

// 布局算法
private const val CNODE_PAD_H = 16f
private const val CNODE_PAD_V = 8f
private const val CLEVEL_H = 80f
private const val CSIB_GAP = 28f

data class CanvasLayoutResult(
    val nodes: List<CanvasLayoutNode>,
    val totalWidth: Float,
    val totalHeight: Float,
)

fun computeCanvasLayout(
    node: CanvasMapNode, x: Float = 0f, y: Float = 0f,
    textMeasurer: TextMeasurer
): CanvasLayoutResult {
    val style = TextStyle(fontSize = 13.sp, color = Color.White)
    val textLayout = textMeasurer.measure(
        text = AnnotatedString(node.title),
        style = style,
        maxLines = 1,
    )
    val nw = textLayout.size.width.toFloat() + CNODE_PAD_H * 2
    val nh = textLayout.size.height.toFloat() + CNODE_PAD_V * 2

    if (node.children.isEmpty() || !node.expanded) {
        return CanvasLayoutResult(
            nodes = listOf(CanvasLayoutNode(node, x, y, nw, nh)),
            totalWidth = nw, totalHeight = nh,
        )
    }

    val childResults = node.children.map { computeCanvasLayout(it, 0f, 0f, textMeasurer) }
    var cx = 0f
    val childLayoutNodes = mutableListOf<CanvasLayoutNode>()
    for (cr in childResults) {
        childLayoutNodes.addAll(cr.nodes.map { it.copy(x = it.x + cx, y = it.y + CLEVEL_H) })
        cx += cr.totalWidth + CSIB_GAP
    }
    val totalChildWidth = max(cx - CSIB_GAP, nw)
    val parentCenterX = totalChildWidth / 2
    val parentNode = CanvasLayoutNode(node, parentCenterX, y, nw, nh, childLayoutNodes)

    val allNodes = mutableListOf(parentNode)
    allNodes.addAll(childLayoutNodes)
    return CanvasLayoutResult(
        nodes = allNodes,
        totalWidth = totalChildWidth,
        totalHeight = CLEVEL_H + (childResults.maxOfOrNull { it.totalHeight } ?: 0f),
    )
}

// Canvas Composable
@Composable
fun MindMapCanvasView(
    rootNode: CanvasMapNode?,
    onNodeClick: (CanvasMapNode) -> Unit = {},
) {
    if (rootNode == null) {
        Box(Modifier.fillMaxSize()) {
            Text("加载中…", modifier = Modifier.padding(16.dp), color = Color.Gray)
        }
        return
    }

    val textMeasurer = rememberTextMeasurer()
    val layout = remember(rootNode) { computeCanvasLayout(rootNode, textMeasurer = textMeasurer) }

    var scale by remember { mutableStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    val textStyle = TextStyle(fontSize = 13.sp, color = Color.White)

    Canvas(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0F1115))
            .pointerInput(Unit) {
                detectTransformGestures { _, pan, zoom, _ ->
                    scale = (scale * zoom).coerceIn(0.3f, 3f)
                    offset = Offset(
                        (offset.x + pan.x).coerceIn(-2000f, 2000f),
                        (offset.y + pan.y).coerceIn(-2000f, 2000f),
                    )
                }
            }
            .pointerInput(rootNode) {
                detectTapGestures { tapOffset ->
                    val drawOffset = Offset(offset.x + size.width / 2, offset.y + 80f)
                    val worldX = (tapOffset.x - drawOffset.x) / scale
                    val worldY = (tapOffset.y - drawOffset.y) / scale
                    val hit = layout.nodes.find { ln ->
                        worldX >= ln.x - ln.width / 2 && worldX <= ln.x + ln.width / 2 &&
                        worldY >= ln.y - ln.height / 2 && worldY <= ln.y + ln.height / 2
                    }
                    if (hit != null) onNodeClick(hit.node)
                }
            }
    ) {
        val drawOffset = Offset(offset.x + size.width / 2, offset.y + 80f)
        drawContext.transform.translate(drawOffset.x, drawOffset.y)
        drawContext.transform.scale(scale, scale, Offset.Zero)
        // 保存变换以便后续恢复(在同一 Canvas 内无需恢复)
        run {
            // 连线
            for (ln in layout.nodes) {
                for (child in ln.children) {
                    val path = Path().apply {
                        moveTo(ln.x, ln.y + ln.height / 2)
                        val midY = (ln.y + ln.height / 2 + child.y - child.height / 2) / 2
                        cubicTo(ln.x, midY, child.x, midY, child.x, child.y - child.height / 2)
                    }
                    drawPath(path, Color(0xFF3A4250), style = Stroke(width = 1.5f))
                }
            }
            // 节点
            for (ln in layout.nodes) {
                val color = canvasMasteryColor(ln.node.mastery)
                val rect = androidx.compose.ui.geometry.Rect(
                    ln.x - ln.width / 2, ln.y - ln.height / 2,
                    ln.x + ln.width / 2, ln.y + ln.height / 2,
                )
                drawRoundRect(color.copy(alpha = 0.25f), rect.topLeft, rect.size,
                    androidx.compose.ui.geometry.CornerRadius(8f))
                drawRoundRect(color, rect.topLeft, rect.size,
                    androidx.compose.ui.geometry.CornerRadius(8f), style = Stroke(width = 1.5f))
                if (ln.node.mastery > 0) {
                    drawRoundRect(color.copy(alpha = 0.6f),
                        Offset(rect.left, rect.bottom - 3f),
                        Size(rect.width * (ln.node.mastery / 100f), 3f),
                        androidx.compose.ui.geometry.CornerRadius(1.5f))
                }
                // 文本
                val tl = textMeasurer.measure(
                    text = AnnotatedString(ln.node.title), style = textStyle, maxLines = 1)
                drawText(tl,
                    topLeft = Offset(ln.x - tl.size.width / 2, ln.y - tl.size.height / 2),
                    color = Color.White)
                // 展开/折叠指示
                if (ln.node.children.isNotEmpty()) {
                    val ind = if (ln.node.expanded) "▼" else "▶"
                    val il = textMeasurer.measure(
                        text = AnnotatedString(ind),
                        style = TextStyle(fontSize = 9.sp, color = Color.White.copy(alpha = 0.5f)))
                    drawText(il, topLeft = Offset(rect.right - 14f, rect.top + 2f),
                        color = Color.White.copy(alpha = 0.5f))
                }
            }
        }
    }
}
