package com.thompsonfabco.filamentkit.ui.hub

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.HealthAnswer
import com.thompsonfabco.filamentkit.net.HealthChange
import com.thompsonfabco.filamentkit.ui.home.printersFailure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.ZoneId
import java.util.Locale

/** One row of the health table (R84 4.2, 4.3): when a check changed, which, and from and to as words. */
data class HealthRow(val time: String, val check: String, val from: String, val to: String) {
    val spoken: String get() = HubTexts.healthRowSpoken(time, check, from, to)
}

/** The words for a check's three states; the screen gives the catalogue's OK and Needs a look. */
data class HealthWords(val ok: String, val look: String, val bad: String = HubTexts.STATE_BAD)

/** The table's rows and its footnote; pure, so the words are tested without a screen. */
object HealthTable {
    /** `ok`, `look` or `bad` as words; a state the app does not know is shown as the Hub wrote it. */
    fun stateWord(state: String, words: HealthWords): String = when (state) {
        "ok" -> words.ok
        "look" -> words.look
        "bad" -> words.bad
        else -> state
    }

    /** Newest change first; the time in the phone's zone and language. */
    fun rows(
        answer: HealthAnswer,
        words: HealthWords,
        zone: ZoneId = ZoneId.systemDefault(),
        locale: Locale = Locale.getDefault(),
    ): List<HealthRow> =
        answer.changes.sortedWith(compareByDescending<HealthChange> { it.atMillis ?: Long.MIN_VALUE }.thenByDescending { it.at })
            .map {
                HealthRow(hubTime(it.at, zone, locale) ?: it.at, it.text.ifBlank { it.key }, stateWord(it.from, words), stateWord(it.to, words))
            }

    /** "No history before Nov 14, 2026." when the Hub says its record starts then ([since]); null when it gives none. */
    fun footnote(answer: HealthAnswer, zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String? =
        answer.since?.let { hubDay(it, zone, locale) }?.let(HubTexts::noHistoryBefore)
}

/** What the health table draws from: [answer] is the last one read for [days]. */
data class HealthUi(
    val days: Int = DEFAULT_DAYS,
    val answer: HealthAnswer? = null,
    val loading: Boolean = false,
    /** 404: an older Hub without `GET api/health`; the table is left out. */
    val unavailable: Boolean = false,
    /** The Hub's own words, or the app's, for a failed read. */
    val message: String? = null,
    val failed: Boolean = false,
) {
    companion object {
        const val DEFAULT_DAYS = 7
        const val LONG_DAYS = 30
    }
}

/**
 * The Hub's `GET api/health` for the Hub screen. [load] asks each time (it resolves the session's current client) and
 * returns null for an older Hub (404). Seven days at first; [setDays] asks for 30 on request. A failed read keeps the
 * answer already shown.
 */
class HealthViewModel(private val load: suspend (days: Int) -> HealthAnswer?) : ViewModel() {
    private val _state = MutableStateFlow(HealthUi())
    val state: StateFlow<HealthUi> = _state.asStateFlow()

    fun refresh() {
        if (_state.value.loading) return
        val days = _state.value.days
        _state.update { it.copy(loading = true) }
        viewModelScope.launch {
            try {
                val answer = load(days)
                _state.update {
                    if (it.days != days) it.copy(loading = false)
                    else if (answer == null) it.copy(loading = false, unavailable = true, answer = null, failed = false, message = null)
                    else it.copy(loading = false, unavailable = false, answer = answer, failed = false, message = null)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val failure = printersFailure(e)
                _state.update { it.copy(loading = false, failed = true, message = failure.message) }
            }
            // the days were changed while this read ran: read again for the days now asked
            if (_state.value.days != days) refresh()
        }
    }

    /** 7 or 30 days; the table is read again. */
    fun setDays(days: Int) {
        if (days == _state.value.days) return
        _state.update { it.copy(days = days) }
        refresh()
    }
}
