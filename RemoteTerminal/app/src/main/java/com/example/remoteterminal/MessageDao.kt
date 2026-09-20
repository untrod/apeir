package com.example.remoteterminal

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface MessageDao {
    /** 按会话和时间序查询消息 —— Flow 使得 UI 自动刷新。 */
    @Query("SELECT * FROM messages WHERE session_id = :sessionId ORDER BY timestamp ASC")
    fun getMessages(sessionId: String): Flow<List<LocalMessage>>

    /** 一次性查询所有消息(导出用)。 */
    @Query("SELECT * FROM messages WHERE session_id = :sessionId ORDER BY timestamp ASC")
    suspend fun getMessagesOnce(sessionId: String): List<LocalMessage>

    /** 插入或替换(按 uid 去重,重装不会重复)。 */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(msg: LocalMessage)

    /** 获取本地有记录的会话列表(每个会话取最后一条消息时间)。 */
    @Query("SELECT session_id, MAX(timestamp) as last_ts FROM messages GROUP BY session_id ORDER BY last_ts DESC")
    suspend fun getLocalSessionIds(): List<SessionSummary>

    /** 获取某会话的最后一条消息(用于预览)。 */
    @Query("SELECT * FROM messages WHERE session_id = :sessionId ORDER BY timestamp DESC LIMIT 1")
    suspend fun getLastMessage(sessionId: String): LocalMessage?

    /** 获取某会话的消息条数。 */
    @Query("SELECT COUNT(*) FROM messages WHERE session_id = :sessionId")
    suspend fun getMessageCount(sessionId: String): Int

    /** 删除指定会话的全部本地消息(用户手动清理时用)。 */
    @Query("DELETE FROM messages WHERE session_id = :sessionId")
    suspend fun deleteSession(sessionId: String)

    /** 清空本地全部消息。 */
    @Query("DELETE FROM messages")
    suspend fun deleteAll()
}

/** 轻量会话摘要,仅用于列表展示。 */
data class SessionSummary(
    val session_id: String,
    val last_ts: Long,
)
