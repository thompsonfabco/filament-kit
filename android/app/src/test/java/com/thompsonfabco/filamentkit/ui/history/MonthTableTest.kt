package com.thompsonfabco.filamentkit.ui.history

import com.thompsonfabco.filamentkit.net.UsageMonth
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Locale

/** The By month table (R84 5.7) and the CSV file names, as pure rules. */
class MonthTableTest {
    @Test fun rowsAreNewestFirstWithGramsPrintsUnfinishedAndTheMostUsedMaterial() {
        val rows = MonthTable.lines(
            listOf(
                UsageMonth("2026-10", 1520.5, 12, 1, null),
                UsageMonth("2026-11", 1840.0, 1, 0, "PA6"),
            ),
            Locale.US,
        )
        assertEquals(listOf("November 2026", "October 2026"), rows.map { it.month })
        assertEquals(MonthLine("November 2026", "1840 g", "1 print", "0 did not finish", "Most used: PA6"), rows[0])
        assertEquals(MonthLine("October 2026", "1520.5 g", "12 prints", "1 did not finish", null), rows[1])
        assertNull(rows[1].material)
    }

    @Test fun aRowIsOneSentenceForAScreenReader() {
        val row = MonthTable.lines(listOf(UsageMonth("2026-11", 1840.0, 15, 2, "PA6")), Locale.US).single()
        assertEquals("November 2026. 1840 g. 15 prints. 2 did not finish. Most used: PA6", row.spoken)
    }

    @Test fun aMonthTheAppCannotReadIsShownAsGiven() {
        assertEquals("sometime", MonthTable.monthName("sometime", Locale.US))
    }

    @Test fun noMonthsIsNoRows() {
        assertEquals(emptyList<MonthLine>(), MonthTable.lines(emptyList()))
    }

    @Test fun aCsvFileNameKeepsOnlySafeCharacters() {
        assertEquals("usage-0948AB.csv", csvFileName("usage", "0948AB"))
        assertEquals("recent.csv", csvFileName("recent", null))
        assertEquals("usage-a-b--c.csv", csvFileName("usage", "a/b: c"))
    }
}
