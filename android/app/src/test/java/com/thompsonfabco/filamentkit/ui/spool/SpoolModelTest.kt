package com.thompsonfabco.filamentkit.ui.spool

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.apiStandIn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

class SpoolModelTest {
    @Test fun aSpoolIsReadWithEveryFieldTheHubSends() {
        val s = spoolJson(214, tag = "04A1B2", lot = "L-77").toSpoolSummary()
        assertEquals(214, s.id)
        assertEquals("Polymaker", s.brand)
        assertEquals("PolyTerra PLA Charcoal Black", s.name)
        assertEquals("Polymaker PolyTerra PLA Charcoal Black", s.title)
        assertEquals("PLA", s.material)
        assertEquals("2B2B2E", s.colorHex)
        assertEquals("Workshop X1 A1", s.location)
        assertEquals(620.0, s.remaining!!, 0.0)
        assertEquals(1000.0, s.total!!, 0.0)
        assertEquals(62, s.percent)
        assertEquals(SpoolState.Opened, s.state)
        assertEquals("04A1B2", s.tag)
        assertEquals(41, s.filamentId)
        assertEquals(140.0, s.emptyWeight!!, 0.0)
        assertEquals("L-77", s.lot)
    }

    @Test fun sealedAndEmptySpoolsAreToldApart() {
        assertEquals(SpoolState.Sealed, spoolJson(1, sealed = true).toSpoolSummary().state)
        assertEquals(SpoolState.Empty, spoolJson(1, archived = true).toSpoolSummary().state)
        assertEquals(SpoolState.Empty, spoolJson(1, sealed = true, archived = true).toSpoolSummary().state)
    }

    @Test fun aFieldTheHubDidNotSendIsNullAndNothingIsInvented() {
        val s = spoolJson(5, remaining = null, location = null, total = null).toSpoolSummary()
        assertNull(s.remaining)
        assertNull(s.location)
        assertNull(s.percent)
        assertNull(s.tag)
        assertNull(s.lot)
    }

    @Test fun theTotalFallsBackToTheFilamentsNetWeight() {
        val json = spoolJson(5, total = null)
        val filament = json["filament"] as kotlinx.serialization.json.JsonObject
        val withNet = kotlinx.serialization.json.JsonObject(
            json + ("filament" to kotlinx.serialization.json.JsonObject(filament + ("weight" to kotlinx.serialization.json.JsonPrimitive(750)))),
        )
        assertEquals(750.0, withNet.toSpoolSummary().total!!, 0.0)
    }

    @Test fun aBlankTagIsNoTag() {
        assertNull(spoolJson(5, tag = "").toSpoolSummary().tag)
    }

    @Test fun everyResultSurvivesBeingHandedToAnotherScreenAsText() {
        for (r in listOf(
            SpoolResult.WeightUpdated(481.5), SpoolResult.WeightUpdated(null), SpoolResult.Moved("Shelf B"), SpoolResult.MarkedEmpty,
            SpoolResult.TagLinked, SpoolResult.TagMoved, SpoolResult.Loaded("Workshop X1", "A2"),
            SpoolResult.LoadedUnconfirmed("Workshop X1", "Ext-L"),
        )) {
            assertEquals(r, SpoolResult.decode(r.encode()))
        }
        assertNull(SpoolResult.decode("nonsense"))
    }

    @Test fun gramsAreWholeOrOneDecimal() {
        assertEquals("482", formatGrams(482.0))
        assertEquals("482", formatGrams(482.02))
        assertEquals("482.5", formatGrams(482.5))
        assertEquals("0", formatGrams(0.0))
    }

    @Test fun failuresAreSortedByTheRealApiErrorShapes() {
        assertEquals(HubFailure.CertificateChanged, hubFailure(FingerprintMismatch("aa", "bb")))
        assertEquals(HubFailure.NotPaired, hubFailure(ApiError(401, "unauthorized", "nope")))
        assertEquals(HubFailure.Unreachable, hubFailure(ApiError(0, "offline", "The connection failed")))
        assertEquals(HubFailure.Unreachable, hubFailure(ApiError(0, "local_network", "Allow local network access")))
        assertEquals(HubFailure.Unreachable, hubFailure(IOException("reset")))
        assertEquals(HubFailure.Unexpected, hubFailure(ApiError(200, ApiError.BAD_RESPONSE, "The server did not return a token")))
        assertEquals(HubFailure.Unexpected, hubFailure(ApiError(502, "internal", apiStandIn(502), noHubMessage = true)))
        assertEquals(HubFailure.Unexpected, hubFailure(ApiError(500, "internal", "", noHubMessage = true)))
        assertEquals(HubFailure.Unexpected, hubFailure(IllegalStateException("boom")))
        assertEquals(HubFailure.SpoolmanDown, hubFailure(ApiError(503, "spoolman_unreachable", "Spoolman is not reachable")))
        assertEquals(HubFailure.Message("tag 04A1 is taken"), hubFailure(ApiError(409, "tag_conflict", "tag 04A1 is taken")))
    }

    @Test fun onlyTheHubNoticesAreClearedByASuccess() {
        assertNull(HubFailure.NotPaired.afterSuccess())
        assertNull(HubFailure.CertificateChanged.afterSuccess())
        assertEquals(HubFailure.Unreachable, HubFailure.Unreachable.afterSuccess())
        assertTrue(HubFailure.NotPaired.isNotice)
        assertFalse(HubFailure.Message("x").isNotice)
    }
}
