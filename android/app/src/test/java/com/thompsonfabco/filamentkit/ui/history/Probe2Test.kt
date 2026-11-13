package com.thompsonfabco.filamentkit.ui.history

import android.os.Build
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.assertIsEnabled
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.HistoryChange
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistoryRevision
import com.thompsonfabco.filamentkit.net.HistorySaved
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.RevisionProposal
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class Probe2Test {
    @get:Rule val rule = createComposeRule()

    private class Fake : HistoryBackend {
        var fail: Exception? = null
        val values = buildJsonObject { put("vendor", "Polymaker"); put("name", "PolyTerra Matte"); put("material", "PLA") }
        // the Hub's apply(): one change entry per spool and field
        val rev = HistoryRevision(1, "2026-11-12T14:09:00+00:00", "hand", changes = listOf(
            HistoryChange(212, "name", JsonPrimitive("PolyTerra"), JsonPrimitive("PolyTerra Matte")),
            HistoryChange(213, "name", JsonPrimitive("PolyTerra"), JsonPrimitive("PolyTerra Matte")),
        ))
        var record = HistoryRecord("a1", "2026-11-12T14:05:00+00:00", "phone", "edited", photos = 0, undoable = true,
            spools = listOf(HistorySpool(212, 40, "Polymaker", "PolyTerra Matte", "PLA"), HistorySpool(213, 40, "Polymaker", "PolyTerra Matte", "PLA")),
            saved = listOf(HistorySaved(0, listOf(212, 213), values)), revisions = listOf(rev))
        override suspend fun list() = IntakeHistory(20, 1, null, true)
        override suspend fun record(id: String): HistoryRecord { fail?.let { throw it }; return record }
        override suspend fun photo(id: String, n: Int): ByteArray = error("none")
        override suspend fun revise(id: String, note: String, item: Int?): RevisionProposal = error("not used")
        override suspend fun applyProposal(id: String, proposal: String): HistoryRecord = error("not used")
        override suspend fun applyValues(id: String, item: Int, values: JsonObject): HistoryRecord { fail?.let { throw it }; return record }
        override suspend fun undo(id: String, revision: Int): HistoryRecord = error("not used")
    }

    @Test fun twoSpoolRevisionLine() {
        val fake = Fake()
        val vm = RecordViewModel(fake, "a1")
        val list = HistoryListViewModel(fake)
        rule.setContent { SpoolwardenTheme(Look.Console, Appearance.Light) {
            RecordScreen(vm, list, null, onBack = {}, onOpenRecord = {}, onEdit = {}, onOpenPhoto = {}, onOpenSpool = {}, onPairAgain = {})
        } }
        rule.waitForIdle()
        val dup = rule.onAllNodesWithText("Name PolyTerra → PolyTerra Matte; Name PolyTerra → PolyTerra Matte", substring = true, useUnmergedTree = true).fetchSemanticsNodes().size
        vm.askUndo(); rule.waitForIdle()
        val bodies = rule.onAllNodesWithText("Name goes back to PolyTerra.", useUnmergedTree = true).fetchSemanticsNodes().size
        assertEquals(0, dup)
        assertEquals(1, bodies)
    }

    @Test fun editStaysOfflineForever() {
        val fake = Fake()
        val vm = RecordViewModel(fake, "a1")
        rule.setContent { SpoolwardenTheme(Look.Console, Appearance.Light) { EditScreen(vm, 0, onClose = {}, onPairAgain = {}) } }
        rule.waitForIdle()
        vm.setText(RecentField.Name, "PolyTerra Silk")
        fake.fail = ApiError(0, "offline", "x")
        vm.saveEdit {}
        rule.waitForIdle()
        fake.fail = null
        rule.mainClock.advanceTimeBy(60_000)
        rule.waitForIdle()
        Thread.sleep(300); rule.waitForIdle()
        val enabled = runCatching { rule.onNodeWithText("Save changes").assertIsEnabled() }.isSuccess
        assertFalse(vm.state.value.offline)
        assertTrue(enabled)
    }

    @Test fun notPairedNoticeAfterRepairWhileAway() {
        val fake = Fake()
        val vm = RecordViewModel(fake, "a1")
        val list = HistoryListViewModel(fake)
        var shown by mutableStateOf(true)
        var client by mutableStateOf<Any?>("client-1")
        rule.setContent { SpoolwardenTheme(Look.Console, Appearance.Light) {
            Column { if (shown) RecordScreen(vm, list, client, onBack = {}, onOpenRecord = {}, onEdit = {}, onOpenPhoto = {}, onOpenSpool = {}, onPairAgain = {}) else Text("pairing") }
        } }
        rule.waitForIdle()
        fake.fail = ApiError(401, "unauthorized", "x")
        vm.load(); rule.waitForIdle(); Thread.sleep(200); rule.waitForIdle()
        fake.fail = null
        val before = vm.state.value.unauthorized
        shown = false; rule.waitForIdle()          // pairing pushed over the record
        client = "client-2"; rule.waitForIdle()    // paired again
        shown = true; rule.waitForIdle()           // back to the record
        Thread.sleep(300); rule.waitForIdle()
        assertTrue(before)
        assertFalse(vm.state.value.unauthorized)
    }
}
