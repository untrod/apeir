package com.example.remoteterminal

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Watch
import androidx.compose.material.icons.filled.Tablet
import androidx.compose.material.icons.filled.DevicesOther
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 设备管理页:列出注册到 Brain 的设备(电脑/手机/手表/平板),显示在线状态、能力。
 * 未接入的设备类型(手表/平板)显示为占位空位,提示如何添加。
 */
@Composable
fun DevicesScreen(onBack: () -> Unit) {
    val devices by ChatWorker.devices.collectAsState()
    val defaultDevice by ChatWorker.defaultDevice.collectAsState()

    LaunchedEffect(Unit) { ChatWorker.fetchDeviceStatusOnce() }

    // 已接入的设备类型(用于判断哪些空位还没填)
    val presentTypes = devices.map { deviceType(it) }.toSet()
    val placeholderSlots = listOf(
        "watch" to "手表", "tablet" to "平板",
    ).filter { it.first !in presentTypes }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("设备", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = { ChatWorker.fetchDeviceStatusOnce() }) { Text("刷新") }
            TextButton(onClick = onBack) { Text("完成") }
        }
        Spacer(Modifier.height(8.dp))

        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (devices.isEmpty()) {
                item {
                    Text("暂无在线设备(检查设置页服务器地址 / 隧道是否连上)",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 8.dp))
                }
            } else {
                item { Text("已接入", style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(devices) { dev -> DeviceCard(dev, isDefault = dev.id == defaultDevice) }
            }

            // 未接入的设备类型占位
            if (placeholderSlots.isNotEmpty()) {
                item {
                    Spacer(Modifier.height(4.dp))
                    Text("待接入", style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                items(placeholderSlots) { (type, label) -> PlaceholderCard(type, label) }
            }

            // 添加设备说明
            item {
                Spacer(Modifier.height(8.dp))
                Card(shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f))) {
                    Column(Modifier.padding(14.dp)) {
                        Text("如何添加新设备", style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.height(6.dp))
                        Text("1. 新设备装好 WireGuard,接入隧道(分配一个 10.10.0.x 地址)\n" +
                             "2. 在服务器 devices.json 添加一条(填 type: watch/tablet、host、port、独立 token、能力)\n" +
                             "3. 回到本页刷新,设备即出现并显示在线状态",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

/** 按 type 优先、否则按 os 推断设备类型。 */
private fun deviceType(d: ChatWorker.DeviceInfo): String {
    if (d.type.isNotBlank()) return d.type
    return when {
        d.os.equals("windows", true) || d.os.equals("linux", true) || d.os.equals("mac", true) -> "laptop"
        d.os.equals("android", true) -> "phone"
        else -> "other"
    }
}

private fun typeIcon(type: String): ImageVector = when (type) {
    "laptop" -> Icons.Filled.Computer
    "phone" -> Icons.Filled.PhoneAndroid
    "watch" -> Icons.Filled.Watch
    "tablet" -> Icons.Filled.Tablet
    else -> Icons.Filled.DevicesOther
}

@Composable
private fun DeviceCard(dev: ChatWorker.DeviceInfo, isDefault: Boolean) {
    val cs = MaterialTheme.colorScheme
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isDefault) cs.primary.copy(alpha = 0.08f) else cs.surfaceVariant.copy(alpha = 0.5f)),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(typeIcon(deviceType(dev)), null, modifier = Modifier.size(22.dp),
                    tint = if (dev.online) cs.primary else cs.onSurfaceVariant)
                Spacer(Modifier.width(10.dp))
                Box(modifier = Modifier.size(10.dp).background(
                    if (dev.online) Color(0xFF4CAF50) else Color(0xFF9E9E9E), RoundedCornerShape(50)))
                Spacer(Modifier.width(8.dp))
                Text(dev.name, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.width(8.dp))
                Text(if (dev.online) "在线" else "离线", fontSize = 12.sp,
                    color = if (dev.online) Color(0xFF4CAF50) else cs.onSurfaceVariant)
                Spacer(Modifier.weight(1f))
                if (isDefault) {
                    Surface(shape = RoundedCornerShape(8.dp), color = cs.primary.copy(alpha = 0.15f)) {
                        Text("默认目标", fontSize = 11.sp, color = cs.primary,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp))
                    }
                }
            }
            Spacer(Modifier.height(6.dp))
            Text("ID: ${dev.id} · 系统: ${dev.os.ifEmpty { "未知" }}", fontSize = 12.sp, color = cs.onSurfaceVariant)
            if (dev.capabilities.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text("能力: ${dev.capabilities.joinToString(" · ")}", fontSize = 11.sp, color = cs.onSurfaceVariant)
            }
            if (dev.lastSeen > 0) {
                Spacer(Modifier.height(4.dp))
                Text("最后活跃: ${formatTime(dev.lastSeen)}", fontSize = 11.sp, color = cs.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun PlaceholderCard(type: String, label: String) {
    val cs = MaterialTheme.colorScheme
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = cs.surfaceVariant.copy(alpha = 0.25f)),
    ) {
        Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(typeIcon(type), null, modifier = Modifier.size(22.dp), tint = cs.onSurfaceVariant.copy(alpha = 0.5f))
            Spacer(Modifier.width(10.dp))
            Column {
                Text("$label · 待接入", style = MaterialTheme.typography.titleMedium,
                    color = cs.onSurfaceVariant.copy(alpha = 0.7f))
                Text("尚未连接,稍后接入后将在此显示", fontSize = 11.sp,
                    color = cs.onSurfaceVariant.copy(alpha = 0.6f))
            }
        }
    }
}
