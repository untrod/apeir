package com.example.remoteterminal

import android.graphics.drawable.AnimationDrawable
import android.os.Handler
import android.os.Looper
import android.widget.ImageView
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import kotlin.math.abs
import kotlin.math.roundToInt

import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.random.Random

enum class CatState {
    IDLE, WORKING, ALERT, SLEEP, THINKING, DONE, ERROR
}

/**
 * 像素风卫星猫吉祥物。逐帧 AnimationDrawable + Compose 互动动画。
 *
 * 互动:
 *   - 单击 → 弹跳
 *   - 双击 → 投喂 🐟
 *   - 长按 → 转圈 ⭐
 *   - 横划 → 抚摸歪头 + ❤️
 *   - 待机 → 偶尔眨眼
 */
@Composable
fun PetCat(state: CatState, modifier: Modifier = Modifier) {
    var currentState by remember { mutableStateOf(state) }
    var imageView by remember { mutableStateOf<ImageView?>(null) }

    // state 变化时更新(外部驱动)
    LaunchedEffect(state) {
        currentState = state
    }

    // 切逐帧动画
    LaunchedEffect(currentState, imageView) {
        val iv = imageView ?: return@LaunchedEffect
        val resId = when (currentState) {
            CatState.IDLE -> R.drawable.cat_anim_idle
            CatState.WORKING -> R.drawable.cat_anim_working
            CatState.ALERT -> R.drawable.cat_anim_alert
            CatState.SLEEP -> R.drawable.cat_anim_sleep
            CatState.THINKING -> R.drawable.cat_anim_thinking
            CatState.DONE -> R.drawable.cat_anim_done
            CatState.ERROR -> R.drawable.cat_anim_error
        }
        iv.setImageResource(resId)
        val anim = iv.drawable as? AnimationDrawable ?: return@LaunchedEffect
        anim.isFilterBitmap = false
        anim.stop()
        // 常态(idle/sleep)静止只显第一帧 → 不持续重绘,消除卡顿;
        // 仅工作/思考/警戒/出错/完成等瞬态才跑逐帧循环。
        if (currentState == CatState.IDLE || currentState == CatState.SLEEP) {
            anim.selectDrawable(0)
        } else {
            iv.post { anim.start() }
        }

        if (currentState == CatState.DONE) {
            val totalDuration = (0 until anim.numberOfFrames).sumOf { anim.getDuration(it) }
            Handler(Looper.getMainLooper()).postDelayed({
                currentState = CatState.IDLE
            }, totalDuration.toLong() + 100)
        }
    }

    // 互动动画状态
    val scale = remember { Animatable(1f) }
    val blinkSquash = remember { Animatable(1f) }     // 眨眼用 (独立于 scale 的 Y 轴)
    val tilt = remember { Animatable(0f) }       // 抚摸歪头
    val spin = remember { Animatable(0f) }       // 长按转圈
    val fishY = remember { Animatable(-80f) }    // 鱼的下落偏移

    // 触发器
    var tapTrigger by remember { mutableIntStateOf(0) }
    var feedTrigger by remember { mutableIntStateOf(0) }
    var spinTrigger by remember { mutableIntStateOf(0) }
    var blinkTrigger by remember { mutableIntStateOf(0) }
    var heartVisible by remember { mutableStateOf(false) }
    var petCount by remember { mutableIntStateOf(0) }
    var fishEmoji by remember { mutableStateOf("🐟") }
    var spinEmoji by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    // 单击弹跳
    LaunchedEffect(tapTrigger) {
        if (tapTrigger > 0) {
            scale.animateTo(1.3f, tween(70, easing = FastOutSlowInEasing))
            scale.animateTo(0.85f, tween(70, easing = FastOutSlowInEasing))
            scale.animateTo(1.05f, tween(50))
            scale.animateTo(1f, spring(dampingRatio = 0.3f, stiffness = 500f))
        }
    }

    // 双击投喂
    LaunchedEffect(feedTrigger) {
        if (feedTrigger > 0) {
            // 随机选鱼
            fishEmoji = listOf("🐟", "🐠", "🦐", "🍣", "🐱").random()
            // 鱼从上方落下
            fishY.snapTo(-80f)
            scope.launch { fishY.animateTo(8f, tween(350, easing = FastOutSlowInEasing)) }
            delay(200)
            // 猫跳起来吃
            scale.animateTo(1.35f, tween(100, easing = FastOutSlowInEasing))
            scale.animateTo(0.9f, tween(60))
            scale.animateTo(1.0f, spring(dampingRatio = 0.35f, stiffness = 400f))
            // 吃完开心冒心
            delay(100)
            heartVisible = true
            delay(700)
            heartVisible = false
        }
    }

    // 长按转圈
    LaunchedEffect(spinTrigger) {
        if (spinTrigger > 0) {
            spinEmoji = listOf("⭐", "✨", "💫").random()
            spin.animateTo(360f, tween(500, easing = LinearEasing))
            spin.snapTo(0f)  // 无缝重置
            spinEmoji = ""
        }
    }

    // 待机眨眼
    // 只在 IDLE 时随机眨眼
    LaunchedEffect(currentState) {
        if (currentState != CatState.IDLE) return@LaunchedEffect
        while (true) {
            delay(Random.nextLong(5_000L, 18_000L))
            blinkTrigger++
        }
    }
    LaunchedEffect(blinkTrigger) {
        if (blinkTrigger > 0 && currentState == CatState.IDLE) {
            blinkSquash.animateTo(0.7f, tween(60))
            blinkSquash.animateTo(1f, tween(60))
        }
    }

    // 抚摸
    LaunchedEffect(petCount) {
        if (petCount > 0) {
            heartVisible = true
            delay(900)
            heartVisible = false
        }
    }

    // UI
    Box(
        modifier = modifier
            .graphicsLayer {
                scaleX = scale.value
                scaleY = scale.value * blinkSquash.value  // blinkSquash 叠加眨眼
                rotationZ = tilt.value * 18f + spin.value
            }
            // 点击 / 双击 / 长按
            .pointerInput(Unit) {
                detectTapGestures(
                    onTap = { tapTrigger++ },
                    onDoubleTap = { feedTrigger++ },
                    onLongPress = { spinTrigger++ },
                )
            }
            // 横划抚摸
            .pointerInput(Unit) {
                detectHorizontalDragGestures(
                    onDragEnd = {
                        scope.launch { tilt.animateTo(0f, spring(dampingRatio = 0.4f, stiffness = 400f)) }
                    },
                    onHorizontalDrag = { _, dragAmount ->
                        scope.launch {
                            tilt.snapTo((tilt.value + dragAmount * 0.03f).coerceIn(-1f, 1f))
                        }
                        if (abs(dragAmount) > 12f && !heartVisible) {
                            petCount++
                        }
                    },
                )
            },
        contentAlignment = Alignment.Center,
    ) {
        // 逐帧动画本体
        AndroidView(
            factory = { ctx ->
                ImageView(ctx).apply {
                    scaleType = ImageView.ScaleType.FIT_CENTER
                    setImageResource(R.drawable.cat_anim_idle)
                    drawable?.isFilterBitmap = false
                    // 初始静止显第一帧(idle 不循环,省重绘)
                    (drawable as? AnimationDrawable)?.let { it.stop(); it.selectDrawable(0) }
                    imageView = this
                }
            },
            modifier = Modifier.size(56.dp),
        )

        // 鱼 (投喂时落下)
        if (fishY.value > -70f) {
            Text(
                fishEmoji,
                fontSize = 20.sp,
                modifier = Modifier
                    .offset { IntOffset(0, fishY.value.roundToInt()) }
                    .graphicsLayer {
                        alpha = if (fishY.value > 5f) 1f else (1f + fishY.value / 80f).coerceIn(0f, 1f)
                    },
            )
        }

        // 星星 (长按转圈时)
        if (spinEmoji.isNotEmpty()) {
            Text(
                spinEmoji,
                fontSize = 18.sp,
                modifier = Modifier.offset { IntOffset(20, -20) },
            )
        }

        // 爱心 (抚摸/投喂后)
        AnimatedVisibility(
            visible = heartVisible,
            enter = fadeIn(tween(100)) +
                slideInVertically(tween(300)) { it / 2 },
            exit = fadeOut(tween(250)) +
                slideOutVertically(tween(250)) { -it },
        ) {
            Text(
                "❤️",
                fontSize = 16.sp,
                modifier = Modifier.offset { IntOffset(0, -26.dp.roundToPx()) },
            )
        }
    }
}
