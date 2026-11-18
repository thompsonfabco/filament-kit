package com.thompsonfabco.filamentkit.ui.history

import com.thompsonfabco.filamentkit.net.ActivityEvent
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.UndoAnswer

/**
 * The Hub's activity and undo calls (R84 9.1) as the spool and printer screens need them. The defaults answer like an
 * older Hub (no events, 404 on undo), so a backend or a test fake that does not know them compiles and offers no Undo.
 */
interface ActivityBackend {
    /** `GET api/events?activity=1` for [subject] (`spool:<id>`), newest first. */
    suspend fun activity(subject: String, limit: Int): List<ActivityEvent> = emptyList()

    /** `POST api/events/{id}/undo`; 409 is a refusal, 404 an older Hub. */
    suspend fun undoEvent(id: Long): UndoAnswer = throw ApiError(404, "not_found", HistoryTexts.UNDO_UPDATE_HUB)

    companion object {
        /** Calls go to whatever [current] returns at that moment, so a re-pair reaches the screen. */
        fun of(current: () -> Api): ActivityBackend = object : ActivityBackend {
            override suspend fun activity(subject: String, limit: Int) = current().activity(subject, limit)
            override suspend fun undoEvent(id: Long) = current().undoEvent(id)
        }
    }
}
