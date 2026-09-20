package com.example.remoteterminal

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

/**
 * Nous 手机 Agent — 无障碍服务,让 AI 能操控手机界面。
 *
 * 能力:
 *   - 读取屏幕元素树(文本/ID/坐标/可点击等)
 *   - 执行点击/长按/滑动/文本输入/导航操作
 *   - 通过 Brain 下发命令,本服务执行
 *
 * 安全:
 *   - 所有操作走 Brain 安全闸确认
 *   - 敏感应用(银行/支付)自动拒绝
 *   - 操作全量日志
 */
class NousAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "NousA11y"
        @Volatile var instance: NousAccessibilityService? = null
            private set

        /** 敏感应用包名(自动拒绝操作) */
        val BLOCKED_PACKAGES = setOf(
            "com.android.settings",
            // 银行/支付类由用户在 Brain 端配置,这里只做基础保护
        )

        /** 操作请求流: Brain 下发 → 本服务执行 → 返回结果 */
        val actionRequests = MutableSharedFlow<UiAction>(extraBufferCapacity = 10)
    }

    data class UiAction(
        val actionId: String,
        val action: String,  // list / click / long_click / type / scroll / back / home
        val target: String = "",   // 目标文本/ID
        val text: String = "",     // type 时的输入文本
        val x: Float = -1f,        // 坐标(备用)
        val y: Float = -1f,
    )

    data class UiElement(
        val text: String, val contentDesc: String, val resourceId: String,
        val className: String, val isClickable: Boolean, val isEditable: Boolean,
        val bounds: Rect?, val index: Int,
    )

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.d(TAG, "Accessibility service connected")

        // 监听操作请求
        scope.launch {
            actionRequests.collect { action ->
                executeAction(action)
            }
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // 可选的实时事件监控(保留扩展点)
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        instance = null
        scope.cancel()
        super.onDestroy()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        instance = null
        return super.onUnbind(intent)
    }

    // 公开 API(供 Brain 工具调用)

    /** 获取当前屏幕所有可交互元素 */
    fun getScreenElements(): List<UiElement> {
        val root = rootInActiveWindow ?: return emptyList()
        val elements = mutableListOf<UiElement>()
        collectElements(root, elements, 0)
        root.recycle()
        return elements
    }

    fun currentPackageName(): String = rootInActiveWindow?.packageName?.toString() ?: ""

    /** 按文本查找元素 */
    fun findByText(text: String): AccessibilityNodeInfo? {
        val matches = rootInActiveWindow?.findAccessibilityNodeInfosByText(text)
        return matches?.firstOrNull()
    }

    /** 按 resourceId 查找元素 */
    fun findByResourceId(id: String): AccessibilityNodeInfo? {
        val matches = rootInActiveWindow?.findAccessibilityNodeInfosByViewId(id)
        return matches?.firstOrNull()
    }

    // 操作执行

    private suspend fun executeAction(action: UiAction) {
        val pkg = rootInActiveWindow?.packageName?.toString() ?: ""
        if (BLOCKED_PACKAGES.any { pkg.startsWith(it) }) {
            Log.w(TAG, "Blocked action on sensitive app: $pkg")
            UiResult.emitResult(action.actionId, "error: blocked package '$pkg'")
            return
        }

        Log.d(TAG, "Executing: $action")

        when (action.action) {
            "list" -> {
                val elements = getScreenElements()
                val result = elements.take(30).joinToString("\n") { e ->
                    "[${e.index}] ${e.text.take(30)} | ${e.className} | " +
                    "${if (e.isClickable) "🖱" else ""}${if (e.isEditable) "⌨" else ""} | " +
                    "${e.bounds?.let { "(${it.left},${it.top})-(${it.right},${it.bottom})" } ?: ""}"
                }
                UiResult.emitResult(action.actionId, result)
            }
            "click" -> {
                val node = findElementByTarget(action.target)
                if (node != null && node.isClickable) {
                    node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    node.recycle()
                    UiResult.emitResult(action.actionId, "ok: clicked '${action.target}'")
                } else {
                    // 尝试坐标点击
                    if (action.x >= 0 && action.y >= 0) {
                        performClick(action.x, action.y)
                        UiResult.emitResult(action.actionId, "ok: clicked at (${action.x},${action.y})")
                    } else {
                        node?.recycle()
                        UiResult.emitResult(action.actionId, "error: element '${action.target}' not found or not clickable")
                    }
                }
            }
            "long_click" -> {
                val node = findElementByTarget(action.target)
                if (node != null && node.isLongClickable) {
                    node.performAction(AccessibilityNodeInfo.ACTION_LONG_CLICK)
                    node.recycle()
                    UiResult.emitResult(action.actionId, "ok: long clicked '${action.target}'")
                } else {
                    node?.recycle()
                    UiResult.emitResult(action.actionId, "error: element not found")
                }
            }
            "type" -> {
                val node = findElementByTarget(action.target)
                if (node != null && node.isEditable) {
                    val args = android.os.Bundle()
                    args.putCharSequence(
                        AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                        action.text
                    )
                    node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
                    node.recycle()
                    UiResult.emitResult(action.actionId, "ok: typed '${action.text.take(20)}'")
                } else {
                    node?.recycle()
                    UiResult.emitResult(action.actionId, "error: input field not found")
                }
            }
            "scroll" -> {
                performGesture(
                    GestureDescription.Builder()
                        .addStroke(GestureDescription.StrokeDescription(
                            Path().apply {
                                moveTo(540f, 1500f); lineTo(540f, 500f)
                            }, 0, 300
                        ))
                        .build(), null, null
                )
                UiResult.emitResult(action.actionId, "ok: scrolled")
            }
            "back" -> {
                performGlobalAction(GLOBAL_ACTION_BACK)
                UiResult.emitResult(action.actionId, "ok: back")
            }
            "home" -> {
                performGlobalAction(GLOBAL_ACTION_HOME)
                UiResult.emitResult(action.actionId, "ok: home")
            }
            else -> UiResult.emitResult(action.actionId, "error: unknown action '${action.action}'")
        }
    }

    private fun findElementByTarget(target: String): AccessibilityNodeInfo? {
        if (target.isBlank()) return null
        return findByText(target) ?: findByResourceId(target)
    }

    private fun performClick(x: Float, y: Float) {
        val path = Path().apply { moveTo(x, y); lineTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 1)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        performGesture(gesture, null, null)
    }

    private fun performGesture(
        gesture: GestureDescription,
        callback: AccessibilityService.GestureResultCallback?,
        handler: android.os.Handler?
    ): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            dispatchGesture(gesture, callback, handler)
        } else false
    }

    private fun collectElements(
        node: AccessibilityNodeInfo,
        list: MutableList<UiElement>,
        depth: Int
    ) {
        if (depth > 30) return  // 深度限制防无限递归
        val text = node.text?.toString() ?: ""
        val desc = node.contentDescription?.toString() ?: ""
        val id = node.viewIdResourceName ?: ""

        // 只收集有意义元素
        if (text.isNotBlank() || desc.isNotBlank() || node.isClickable || node.isEditable) {
            val bounds = Rect()
            node.getBoundsInScreen(bounds)
            list.add(
                UiElement(
                    text = text, contentDesc = desc, resourceId = id,
                    className = node.className?.toString() ?: "",
                    isClickable = node.isClickable, isEditable = node.isEditable,
                    bounds = if (bounds.width() > 0 && bounds.height() > 0) bounds else null,
                    index = list.size,
                )
            )
        }

        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            collectElements(child, list, depth + 1)
            child.recycle()
        }
    }

    /** 操作结果流 */
    object UiResult {
        private val _results = MutableSharedFlow<String>(extraBufferCapacity = 20)
        val results: SharedFlow<String> = _results

        fun emitResult(actionId: String, result: String) {
            _results.tryEmit("$actionId|$result")
        }
    }
}
