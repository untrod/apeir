package com.example.remoteterminal

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Room 实体:一条本地聊天消息。
 * 大脑 sessions.json 是上下文真源,本表是展示缓存——手机重启不丢显示,
 * 但重装 App 后从零开始(大脑端上下文仍在)。
 */
@Entity(tableName = "messages")
data class LocalMessage(
    @PrimaryKey(autoGenerate = true) val uid: Long = 0,
    @ColumnInfo(name = "session_id") val sessionId: String,
    @ColumnInfo(name = "role") val role: String,       // "user" | "assistant"
    @ColumnInfo(name = "content") val content: String,
    @ColumnInfo(name = "steps") val steps: String = "", // 助手执行步骤(灰字展示用)
    @ColumnInfo(name = "timestamp") val timestamp: Long = System.currentTimeMillis(),
)
