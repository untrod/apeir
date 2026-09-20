package com.example.remoteterminal

import android.content.ClipData
import android.content.ClipboardManager
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 纯 Compose Markdown 渲染器。
 * 支持:标题(# ~ ###)、**粗体**、*斜体*、`行内代码`、```代码块```(带语言标签+复制按钮)、
 * | 表格 |、- 无序列表、1. 有序列表、--- 分割线、> 引用。
 * 不引第三方库,深色模式自动跟随 MaterialTheme。
 */
@Composable
fun MarkdownText(text: String, modifier: Modifier = Modifier) {
    // 解析只在 text 变化时做一次,滚动重组时直接复用 → 不卡
    val blocks = remember(text) { parseMarkdownBlocks(text) }
    // 注:LaTeX 数学在各文本块渲染时用 preprocessMath 转成可读 Unicode(代码块不转)。
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        blocks.forEach { block ->
            when (block) {
                is MdBlock.Heading -> HeadingBlock(block)
                is MdBlock.CodeBlock -> CodeBlockView(block)
                is MdBlock.Table -> TableBlock(block)
                is MdBlock.HorizontalRule -> HorizontalDivider(
                    color = MaterialTheme.colorScheme.outlineVariant,
                    modifier = Modifier.padding(vertical = 4.dp)
                )
                is MdBlock.Quote -> QuoteBlock(block)
                is MdBlock.Paragraph -> {
                    val anno = remember(block.text) { parseInlineMarkdown(preprocessMath(block.text)) }
                    SelectionContainer {
                        Text(
                            text = anno,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
        }
    }
}

// 块级解析

sealed class MdBlock {
    data class Heading(val level: Int, val text: String) : MdBlock()
    data class CodeBlock(val language: String, val code: String) : MdBlock()
    data class Table(val headers: List<String>, val rows: List<List<String>>) : MdBlock()
    data class Quote(val text: String) : MdBlock()
    data class Paragraph(val text: String) : MdBlock()
    object HorizontalRule : MdBlock()
}

fun parseMarkdownBlocks(raw: String): List<MdBlock> {
    val lines = raw.lines()
    val blocks = mutableListOf<MdBlock>()
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        val trimmed = line.trim()

        // 代码块 ```
        if (trimmed.startsWith("```")) {
            val lang = trimmed.removePrefix("```").trim()
            val codeLines = mutableListOf<String>()
            i++
            while (i < lines.size && !lines[i].trim().startsWith("```")) {
                codeLines.add(lines[i])
                i++
            }
            if (i < lines.size) i++ // 跳过结束的 ```
            blocks.add(MdBlock.CodeBlock(lang, codeLines.joinToString("\n")))
            continue
        }

        // 标题
        val headingMatch = Regex("^(#{1,3})\\s+(.+)").find(trimmed)
        if (headingMatch != null) {
            blocks.add(MdBlock.Heading(headingMatch.groupValues[1].length, headingMatch.groupValues[2]))
            i++
            continue
        }

        // 分割线
        if (trimmed.matches(Regex("^[-*_]{3,}$"))) {
            blocks.add(MdBlock.HorizontalRule)
            i++
            continue
        }

        // 表格(检测 | 开头并且下一行是分隔线 |---|)
        if (trimmed.startsWith("|") && i + 1 < lines.size && lines[i + 1].trim().matches(Regex("^\\|[\\s:|-]+\\|$"))) {
            val headers = parseTableRow(trimmed)
            i += 2 // 跳过表头和分隔行
            val rows = mutableListOf<List<String>>()
            while (i < lines.size && lines[i].trim().startsWith("|")) {
                rows.add(parseTableRow(lines[i].trim()))
                i++
            }
            blocks.add(MdBlock.Table(headers, rows))
            continue
        }

        // 引用
        if (trimmed.startsWith("> ")) {
            val quoteLines = mutableListOf(trimmed.removePrefix("> "))
            i++
            while (i < lines.size && lines[i].trim().startsWith("> ")) {
                quoteLines.add(lines[i].trim().removePrefix("> "))
                i++
            }
            blocks.add(MdBlock.Quote(quoteLines.joinToString("\n")))
            continue
        }

        // 空行跳过
        if (trimmed.isEmpty()) {
            i++
            continue
        }

        // 普通段落(含列表标记也归入段落,由 inline 解析处理标记)
        val paraLines = mutableListOf(line)
        i++
        while (i < lines.size) {
            val next = lines[i].trim()
            // 遇到块级标记就停
            if (next.isEmpty() || next.startsWith("```") || next.startsWith("#") ||
                next.startsWith("|") || next.matches(Regex("^[-*_]{3,}$")) || next.startsWith("> ")) break
            paraLines.add(lines[i])
            i++
        }
        blocks.add(MdBlock.Paragraph(paraLines.joinToString("\n")))
    }
    return blocks
}

private fun parseTableRow(line: String): List<String> {
    return line.trim().removeSurrounding("|").split("|").map { it.trim() }
}

// LaTeX 数学 → 可读 Unicode
// App 不渲染 LaTeX,把常见数学写法转成可读符号(只用于文本块,不动代码块)。
private val _supMap = mapOf('0' to '⁰','1' to '¹','2' to '²','3' to '³','4' to '⁴','5' to '⁵',
    '6' to '⁶','7' to '⁷','8' to '⁸','9' to '⁹','+' to '⁺','-' to '⁻','=' to '⁼',
    '(' to '⁽',')' to '⁾','n' to 'ⁿ','i' to 'ⁱ','x' to 'ˣ')
private val _subMap = mapOf('0' to '₀','1' to '₁','2' to '₂','3' to '₃','4' to '₄','5' to '₅',
    '6' to '₆','7' to '₇','8' to '₈','9' to '₉','+' to '₊','-' to '₋','=' to '₌',
    '(' to '₍',')' to '₎','n' to 'ₙ','i' to 'ᵢ','x' to 'ₓ')

private fun toSup(s: String): String =
    if (s.isNotEmpty() && s.all { it in _supMap }) s.map { _supMap[it] }.joinToString("") else "^$s"
private fun toSub(s: String): String =
    if (s.isNotEmpty() && s.all { it in _subMap }) s.map { _subMap[it] }.joinToString("") else "_$s"

fun preprocessMath(input: String): String {
    if (!input.contains('\\') && !input.contains('^') && !input.contains('_')) return input
    var t = input
    // 去掉 LaTeX 行间/行内分隔符 \[ \] \( \)
    t = t.replace("\\[", " ").replace("\\]", " ").replace("\\(", "").replace("\\)", "")
    // \frac{a}{b} -> (a)/(b)(循环处理嵌套)
    val frac = Regex("\\\\frac\\{([^{}]*)\\}\\{([^{}]*)\\}")
    var prev: String
    do { prev = t; t = frac.replace(t) { "(${it.groupValues[1]})/(${it.groupValues[2]})" } } while (t != prev)
    // \sqrt{x} -> √(x)
    t = Regex("\\\\sqrt\\{([^{}]*)\\}").replace(t) { "√(${it.groupValues[1]})" }
    // 上标 ^{...} / ^x
    t = Regex("\\^\\{([^{}]*)\\}").replace(t) { toSup(it.groupValues[1]) }
    t = Regex("\\^([A-Za-z0-9])").replace(t) { toSup(it.groupValues[1]) }
    // 下标 _{...} / _x
    t = Regex("_\\{([^{}]*)\\}").replace(t) { toSub(it.groupValues[1]) }
    t = Regex("_([A-Za-z0-9])").replace(t) { toSub(it.groupValues[1]) }
    // 常见命令 → 符号
    val sym = listOf(
        "\\times" to "×", "\\cdot" to "·", "\\div" to "÷", "\\pm" to "±", "\\mp" to "∓",
        "\\leq" to "≤", "\\geq" to "≥", "\\neq" to "≠", "\\approx" to "≈", "\\equiv" to "≡",
        "\\infty" to "∞", "\\sum" to "Σ", "\\int" to "∫", "\\prod" to "∏", "\\partial" to "∂",
        "\\alpha" to "α", "\\beta" to "β", "\\gamma" to "γ", "\\delta" to "δ", "\\theta" to "θ",
        "\\pi" to "π", "\\lambda" to "λ", "\\mu" to "μ", "\\sigma" to "σ", "\\omega" to "ω",
        "\\Delta" to "Δ", "\\Omega" to "Ω", "\\Rightarrow" to "⇒", "\\rightarrow" to "→",
        "\\to" to "→", "\\leftarrow" to "←", "\\in" to "∈", "\\notin" to "∉",
        "\\sin" to "sin", "\\cos" to "cos", "\\tan" to "tan", "\\log" to "log",
        "\\ln" to "ln", "\\lim" to "lim", "\\cdots" to "…", "\\ldots" to "…",
        "\\left" to "", "\\right" to "", "\\;" to " ", "\\quad" to "  ", "\\!" to "", "\\," to " ",
    )
    for ((k, v) in sym) t = t.replace(k, v)
    return t
}

// 行内解析

fun parseInlineMarkdown(text: String): AnnotatedString {
    return buildAnnotatedString {
        var pos = 0
        val s = text
        while (pos < s.length) {
            when {
                // 行内代码 `...`
                s[pos] == '`' && pos + 1 < s.length -> {
                    val end = s.indexOf('`', pos + 1)
                    if (end > pos) {
                        withStyle(SpanStyle(
                            fontFamily = FontFamily.Monospace,
                            background = androidx.compose.ui.graphics.Color(0x20808080),
                            fontSize = 13.sp,
                        )) {
                            append(s.substring(pos + 1, end))
                        }
                        pos = end + 1
                    } else {
                        append(s[pos])
                        pos++
                    }
                }
                // 粗体 **...**
                s.startsWith("**", pos) -> {
                    val end = s.indexOf("**", pos + 2)
                    if (end > pos) {
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                            append(s.substring(pos + 2, end))
                        }
                        pos = end + 2
                    } else {
                        append(s[pos])
                        pos++
                    }
                }
                // 斜体 *...*
                s[pos] == '*' && pos + 1 < s.length && s[pos + 1] != '*' -> {
                    val end = s.indexOf('*', pos + 1)
                    if (end > pos) {
                        withStyle(SpanStyle(fontStyle = FontStyle.Italic)) {
                            append(s.substring(pos + 1, end))
                        }
                        pos = end + 1
                    } else {
                        append(s[pos])
                        pos++
                    }
                }
                // 列表标记转换
                s.startsWith("- ", pos) && (pos == 0 || s[pos - 1] == '\n') -> {
                    append("  • ") // bullet
                    pos += 2
                }
                else -> {
                    append(s[pos])
                    pos++
                }
            }
        }
    }
}

// 块级组件

@Composable
private fun HeadingBlock(h: MdBlock.Heading) {
    val style = when (h.level) {
        1 -> MaterialTheme.typography.titleLarge
        2 -> MaterialTheme.typography.titleMedium
        else -> MaterialTheme.typography.titleSmall
    }
    val anno = remember(h.text) { parseInlineMarkdown(preprocessMath(h.text)) }
    Text(
        text = anno,
        style = style,
        color = MaterialTheme.colorScheme.onSurface,
        modifier = Modifier.padding(top = 4.dp),
    )
}

@Composable
private fun CodeBlockView(block: MdBlock.CodeBlock) {
    val context = LocalContext.current
    val cs = MaterialTheme.colorScheme
    val codeBg = cs.surface.copy(alpha = 0.7f) // 代码块略微透明,区分气泡底色
    Column(
        modifier = Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(cs.inverseSurface.copy(alpha = 0.08f))
    ) {
        // 头部:语言标签 + 复制按钮
        Row(
            modifier = Modifier.fillMaxWidth().background(cs.inverseSurface.copy(alpha = 0.06f))
                .padding(horizontal = 12.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = block.language.ifEmpty { "code" },
                style = MaterialTheme.typography.labelSmall,
                color = cs.onSurfaceVariant,
            )
            IconButton(
                onClick = {
                    (context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as ClipboardManager)
                        .setPrimaryClip(ClipData.newPlainText("code", block.code))
                    Toast.makeText(context, "已复制代码", Toast.LENGTH_SHORT).show()
                },
                modifier = Modifier.size(28.dp),
            ) {
                Icon(Icons.Filled.ContentCopy, "复制", modifier = Modifier.size(14.dp), tint = cs.onSurfaceVariant)
            }
        }
        // 代码内容(可横向滚动)
        SelectionContainer {
            Text(
                text = block.code,
                style = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 12.sp, color = cs.onSurface),
                modifier = Modifier.horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            )
        }
    }
}

@Composable
private fun TableBlock(table: MdBlock.Table) {
    val cs = MaterialTheme.colorScheme
    Column(
        modifier = Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(cs.inverseSurface.copy(alpha = 0.05f))
            .horizontalScroll(rememberScrollState())
    ) {
        // 表头
        Row(modifier = Modifier.background(cs.primary.copy(alpha = 0.10f)).padding(vertical = 6.dp)) {
            table.headers.forEach { h ->
                Text(
                    text = parseInlineMarkdown(h),
                    style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Bold),
                    color = cs.onSurface,
                    modifier = Modifier.widthIn(min = 80.dp).padding(horizontal = 10.dp),
                )
            }
        }
        HorizontalDivider(color = cs.outlineVariant)
        // 数据行
        table.rows.forEachIndexed { idx, row ->
            val rowBg = if (idx % 2 == 0) cs.surface.copy(alpha = 0.3f) else androidx.compose.ui.graphics.Color.Transparent
            Row(modifier = Modifier.background(rowBg).padding(vertical = 5.dp)) {
                row.forEach { cell ->
                    Text(
                        text = parseInlineMarkdown(preprocessMath(cell)),
                        style = MaterialTheme.typography.bodySmall,
                        color = cs.onSurface,
                        modifier = Modifier.widthIn(min = 80.dp).padding(horizontal = 10.dp),
                    )
                }
            }
            if (idx < table.rows.size - 1) {
                HorizontalDivider(color = cs.outlineVariant.copy(alpha = 0.5f))
            }
        }
    }
}

@Composable
private fun QuoteBlock(block: MdBlock.Quote) {
    val cs = MaterialTheme.colorScheme
    val anno = remember(block.text) { parseInlineMarkdown(preprocessMath(block.text)) }
    Row(modifier = Modifier.fillMaxWidth()) {
        Box(modifier = Modifier.width(3.dp).height(IntrinsicSize.Max).background(cs.primary))
        SelectionContainer {
            Text(
                text = anno,
                style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
                color = cs.onSurfaceVariant,
                modifier = Modifier.padding(start = 10.dp),
            )
        }
    }
}
