package com.thompsonfabco.filamentkit.ui.history

import com.thompsonfabco.filamentkit.net.UsageMonth
import com.thompsonfabco.filamentkit.ui.spool.formatGrams
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

/** One row of the By month table (R84 5.7): month, grams, prints, prints that did not finish, most used material. */
data class MonthLine(
    val month: String,
    val grams: String,
    val prints: String,
    val unfinished: String,
    val material: String?,
) {
    /** The row as one sentence, for a screen reader. */
    val spoken: String get() = listOfNotNull(month, grams, prints, unfinished, material).joinToString(". ")
}

/** The table's rows, newest month first; pure, so the numbers and words are tested without a screen. */
object MonthTable {
    /** "2026-11" as "November 2026" in the phone's language; the text as given when it is not a month. */
    fun monthName(month: String, locale: Locale = Locale.getDefault()): String = try {
        YearMonth.parse(month).format(DateTimeFormatter.ofPattern("LLLL yyyy", locale))
    } catch (_: Exception) {
        month
    }

    fun lines(months: List<UsageMonth>, locale: Locale = Locale.getDefault()): List<MonthLine> =
        months.sortedByDescending { it.month }.map { m ->
            MonthLine(
                month = monthName(m.month, locale),
                grams = formatGrams(m.grams) + " g",
                prints = HistoryTexts.prints(m.prints),
                unfinished = HistoryTexts.unfinished(m.unfinishedPrints),
                material = m.topMaterial?.let(HistoryTexts::mostUsed),
            )
        }
}
