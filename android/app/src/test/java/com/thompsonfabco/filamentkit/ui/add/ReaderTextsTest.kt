package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.net.ReadResult
import com.thompsonfabco.filamentkit.net.RevisionProposal
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ReaderTextsTest {
    private val none = JsonArray(emptyList())

    @Test fun theLineNamesTheReaderTierAndHowSure() {
        assertEquals("Read by the local reader (gpu tier, after the CPU tier), 86 % sure",
            ReaderTexts.line(ReadResult(none, reader = "local", confidence = 0.86, tier = "gpu", escalated = true)))
        assertEquals("Read by the local reader (? tier) (unsure: check the fields)",
            ReaderTexts.line(ReadResult(none, reader = "local", unsure = true)))
        assertEquals("Read by Claude", ReaderTexts.line(ReadResult(none, reader = "cloud")))
        assertNull(ReaderTexts.line(ReadResult(none)))
        assertEquals("Claude", ReaderTexts.info(ReadResult(none)).name)
        assertNull(ReaderTexts.info(ReadResult(none, note = " ")).note)
    }

    @Test fun anItemShowsColourHowSureAndItsLeastSureFields() {
        val it = buildJsonObject {
            put("color_name", "Charcoal"); put("color_family", "grey"); put("confidence", 0.86)
            put("field_confidence", buildJsonObject { put("color", 0.6); put("vendor", 0.95); put("net", 0.5) })
        }
        assertEquals("Colour: Charcoal (grey) · 86 % sure · least sure: color, net", ReaderTexts.item(it))
        assertEquals("Colour: colour name not in the library (red)",
            ReaderTexts.item(buildJsonObject { put("color_name", "unknown"); put("color_family", "red") }))
        assertNull(ReaderTexts.item(buildJsonObject { put("vendor", "SUNLU"); put("color_name", JsonPrimitive(3)) }))
    }

    @Test fun theProposalSaysWhoReadAgain() {
        val p = RevisionProposal("p-1", reader = "local", confidence = 0.93)
        assertEquals("Read again by the local reader, 93 % sure.", ReaderTexts.revisedBy(p))
        assertEquals("Read again by Claude (local reader: busy).",
            ReaderTexts.revisedBy(RevisionProposal("p-1", reader = "cloud", note = "local reader: busy")))
        assertNull(ReaderTexts.revisedBy(RevisionProposal("p-1")))
    }

    @Test fun localErrorsAreWordedAndOthersLeftAlone() {
        assertEquals("The local label reader is busy. Wait a moment, then retry.", ReaderTexts.localError("local_busy"))
        assertEquals("This local label reader can't revise a reading. Edit by hand instead.",
            ReaderTexts.localError("local_revise_unsupported"))
        assertEquals("The local label reader could not read the labels this time. Retry in a moment.",
            ReaderTexts.localError("local_new_kind"))
        assertNull(ReaderTexts.localError("rate_limited"))
    }
}
