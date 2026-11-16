package com.thompsonfabco.filamentkit.net

import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SlotPendingTest {
    private val json = Json { ignoreUnknownKeys = true }

    private fun slot(extra: String) =
        json.decodeFromString<AmsSlot>("""{"slot":0,"label":"A1","type":"","color_hex":"","present":false$extra}""")

    @Test fun pendingIsParsedWithItsSpoolId() {
        val s = slot(""","pending":{"spool_id":12,"text":"Waiting for slot A1"}""")
        assertEquals(12, s.pending?.spoolId)
    }

    @Test fun absentOrNullPendingIsNone() {
        assertNull(slot("").pending)
        assertNull(slot(""","pending":null""").pending)
    }

    @Test fun oddShapesAreNone() {
        assertNull(slot(""","pending":"yes"""").pending)
        assertNull(slot(""","pending":true""").pending)
        assertNull(slot(""","pending":[1]""").pending)
    }

    @Test fun badSpoolIdKeepsThePendingWithoutAnId() {
        assertNull(slot(""","pending":{"spool_id":"x"}""").pending?.spoolId)
        assertTrue(slot(""","pending":{"spool_id":"x"}""").pending != null)
    }

    @Test fun aWaitingSlotIsEmptyAndWaiting() {
        val s = slot(""","pending":{"spool_id":3}""")
        assertTrue(PrinterHelp.slotEmpty(s))
        assertTrue(PrinterHelp.slotWaiting(s))
    }

    @Test fun anOrdinaryEmptySlotIsNotWaiting() {
        assertFalse(PrinterHelp.slotWaiting(slot("")))
    }

    @Test fun aLoadedSlotIsNotWaitingEvenWithStalePending() {
        val s = json.decodeFromString<AmsSlot>("""{"slot":0,"label":"A1","type":"PLA","pending":{"spool_id":3}}""")
        assertFalse(PrinterHelp.slotWaiting(s))
    }
}
