package com.example.remoteterminal

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import java.util.Calendar

/**
 * 学习提醒:把今日时间线(几点干什么)用 AlarmManager 调度成本地系统通知。
 * 到点弹通知,不依赖服务器推送;点开进 App。
 */
object ReminderScheduler {
    private const val CHANNEL_ID = "nous_study"
    const val EXTRA_TITLE = "title"
    const val EXTRA_TEXT = "text"

    fun ensureChannel(ctx: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL_ID, "学习提醒", NotificationManager.IMPORTANCE_HIGH)
            ch.description = "到点提醒该学什么/复习什么"
            ctx.getSystemService(NotificationManager::class.java)?.createNotificationChannel(ch)
        }
    }

    /**
     * 调度今天剩余的提醒。items: (time "HH:mm", title, text)。
     * 已过的时间点跳过;每个时间点一个精确闹钟。
     */
    fun scheduleToday(ctx: Context, items: List<Triple<String, String, String>>) {
        ensureChannel(ctx)
        val am = ctx.getSystemService(Context.ALARM_SERVICE) as? AlarmManager ?: return
        val now = System.currentTimeMillis()
        var reqId = 7000
        for ((time, title, text) in items) {
            val parts = time.split(":")
            if (parts.size != 2) continue
            val h = parts[0].toIntOrNull() ?: continue
            val m = parts[1].toIntOrNull() ?: continue
            val cal = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m)
                set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
            }
            if (cal.timeInMillis <= now) continue  // 已过,跳过
            val intent = Intent(ctx, ReminderReceiver::class.java).apply {
                putExtra(EXTRA_TITLE, title.ifBlank { "学习提醒" })
                putExtra(EXTRA_TEXT, text)
            }
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            val pi = PendingIntent.getBroadcast(ctx, reqId++, intent, flags)
            try {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cal.timeInMillis, pi)
            } catch (_: SecurityException) {
                am.set(AlarmManager.RTC_WAKEUP, cal.timeInMillis, pi)  // 无精确权限则普通闹钟
            }
        }
    }

    fun notify(ctx: Context, title: String, text: String) {
        ensureChannel(ctx)
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(ctx, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .setContentIntent(open)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        try {
            androidx.core.app.NotificationManagerCompat.from(ctx)
                .notify((System.currentTimeMillis() % 100000).toInt(), n)
        } catch (_: SecurityException) { /* 无通知权限 */ }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val title = intent.getStringExtra(ReminderScheduler.EXTRA_TITLE) ?: "学习提醒"
        val text = intent.getStringExtra(ReminderScheduler.EXTRA_TEXT) ?: ""
        ReminderScheduler.notify(context, title, text)
    }
}
