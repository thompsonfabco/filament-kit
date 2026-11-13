package com.thompsonfabco.filamentkit.ui

import androidx.compose.ui.graphics.Color
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.SlotSpool
import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import com.thompsonfabco.filamentkit.ui.spool.LoadHelp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ColorSwatchTest {
    @Test fun readsSixDigitsWithOrWithoutHashAndIgnoresAlpha() {
        assertEquals(Color(0xFFFFFFFF), swatchColor("FFFFFF"))
        assertEquals(Color(0xFFFF0000), swatchColor("ff0000"))
        assertEquals(Color(0xFF808080), swatchColor(" #808080 "))
        assertEquals(Color(0xFF00FF00), swatchColor("00FF00FF"))
    }

    @Test fun anythingElseIsNoColour() {
        for (bad in listOf(null, "", " ", "FFF", "12345", "1234567", "GGGGGG", "-12345", "+12345", "123456789")) {
            assertNull(bad, swatchColor(bad))
        }
    }

    @Test fun aColourIsFilledAndAnUnknownColourIsHollow() {
        assertEquals(SwatchLook.Filled(Color(0xFFFFFFFF)), swatchLook("FFFFFF"))
        assertEquals(SwatchLook.NoColour, swatchLook(""))
        assertEquals(SwatchLook.NoColour, swatchLook(null))
    }

    @Test fun anEmptySlotIsEmptyWhateverColourTheReportStillHolds() {
        assertEquals(SwatchLook.Empty, swatchLook("000000", empty = true))
        assertEquals(SwatchLook.Empty, swatchLook("", empty = true))
    }

    @Test fun whiteAndBlackFilamentAreLoadedNotEmpty() {
        assertFalse(PrinterHelp.slotEmpty(slot(type = "PLA", hex = "FFFFFF")))
        assertFalse(PrinterHelp.slotEmpty(slot(type = "PLA", hex = "000000", present = true)))
    }

    @Test fun aSlotIsEmptyWhenThePrinterSaysSoOrNothingIsKnownToBeInIt() {
        assertTrue(PrinterHelp.slotEmpty(slot(type = "", hex = "000000")))
        assertTrue(PrinterHelp.slotEmpty(slot(type = "", hex = "", present = true)))
        assertTrue(PrinterHelp.slotEmpty(slot(type = "PLA", hex = "FFFFFF", present = false)))
        assertTrue(PrinterHelp.slotEmpty(slot(type = "", hex = "", present = false, spool = SlotSpool(id = 7))))
    }

    @Test fun anInventorySpoolInASlotWithNoSettingIsLoaded() {
        assertFalse(PrinterHelp.slotEmpty(slot(type = "", hex = "", spool = SlotSpool(id = 7))))
    }

    @Test fun theLoadFlowSaysEmptyByTheSameRule() {
        assertEquals("A1 · empty", LoadHelp.slotLine(slot(type = "PLA", hex = "FFFFFF", present = false)))
        assertEquals("A1 · x", LoadHelp.slotLine(slot(type = "", hex = "", spool = SlotSpool(id = 7, name = "x"))))
        assertEquals("A1 · PLA", LoadHelp.slotLine(slot(type = "PLA", hex = "FFFFFF")))
    }

    private fun slot(type: String, hex: String, present: Boolean? = null, spool: SlotSpool? = null) =
        AmsSlot(slot = 0, label = "A1", type = type, colorHex = hex, present = present, spool = spool)
}
