package com.thompsonfabco.filamentkit.ui.history

import android.os.Build
import androidx.compose.material3.Text
import androidx.compose.foundation.clickable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.HistoryChange
import com.thompsonfabco.filamentkit.net.HistoryFilaments
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
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class RefuterProbeTest {
    @get:Rule val rule = createComposeRule()

    private class Fake(val fail: Exception? = null) : HistoryBackend {
        val values = buildJsonObject { put("vendor", "Polymaker"); put("name", "PolyTerra"); put("material", "PLA") }
        val rev = HistoryRevision(1, "2026-11-12T14:09:00+00:00", "ai",
            changes = listOf(HistoryChange(214, "vendor", JsonPrimitive("Polymakr"), JsonPrimitive("Polymaker"))),
            filaments = HistoryFilaments(from = 41, to = 42, created = true, orphaned = listOf(41)))
        var record = HistoryRecord("a1", "2026-11-12T14:05:00+00:00", "phone", "revised_ai", photos = 0, undoable = true,
            spools = listOf(HistorySpool(214, 42, "Polymaker", "PolyTerra", "PLA")),
            saved = listOf(HistorySaved(0, listOf(214), values)), revisions = listOf(rev))
        override suspend fun list() = IntakeHistory(20, 1, null, true)
        override suspend fun record(id: String) = record
        override suspend fun photo(id: String, n: Int): ByteArray = error("none")
        override suspend fun revise(id: String, note: String, item: Int?): RevisionProposal = error("not used")
        override suspend fun applyProposal(id: String, proposal: String): HistoryRecord = error("not used")
        override suspend fun applyValues(id: String, item: Int, values: JsonObject): HistoryRecord {
            fail?.let { throw it }
            record = record.copy(saved = listOf(HistorySaved(0, listOf(214), JsonObject(this.values + values))))
            return record
        }
        override suspend fun undo(id: String, revision: Int): HistoryRecord {
            // the Hub moved the spools back to 41; 42 now has none (intake_history.undo: orphaned_by_undo)
            record = record.copy(revisions = listOf(rev.copy(undone = true)), spools = listOf(HistorySpool(214, 41, "Polymakr", "PolyTerra", "PLA")))
            return record
        }
    }

    @Test fun editResultLineSurvivesTheReturnToTheRecord() {
        val fake = Fake()
        val vm = RecordViewModel(fake, "a1")
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                val nav = rememberNavController()
                NavHost(nav, startDestination = "record") {
                    composable("record") {
                        val s by vm.state.collectAsState()
                        androidx.compose.foundation.layout.Column {
                            Text("saved=" + (s.saved != null) + " edit=" + (s.edit != null))
                            Text("open edit", androidx.compose.ui.Modifier.clickable { nav.navigate("edit") })
                        }
                    }
                    composable("edit") { EditScreen(vm, 0, onClose = { nav.popBackStack() }, onPairAgain = {}) }
                }
            }
        }
        rule.waitForIdle()
        vm.ensureLoaded()
        rule.waitForIdle()
        rule.onNodeWithText("open edit").performClick()
        rule.waitForIdle()
        vm.setText(RecentField.Name, "PolyTerra Matte")
        rule.waitForIdle()
        rule.onNodeWithText("Save changes").performClick()
        rule.mainClock.advanceTimeBy(3000)
        rule.waitForIdle()
        println("PROBE edit-return: saved=" + vm.state.value.saved + " edit=" + vm.state.value.edit)
        assertNotNull("result line state kept", vm.state.value.saved)
    }

    @Test fun anUnpairedAnswerDuringSaveKeepsTheTyping() {
        val vm = RecordViewModel(Fake(ApiError(401, "unauthorized", "no")), "a1")
        vm.load()
        Thread.sleep(200)
        rule.waitForIdle()
        vm.startEdit(0)
        vm.setText(RecentField.Name, "typed by the person")
        vm.saveEdit {}
        rule.waitForIdle()
        Thread.sleep(200)
        println("PROBE auth: unauthorized=" + vm.state.value.unauthorized + " edit=" + vm.state.value.edit)
        assertNotNull("typing kept (05 2.7)", vm.state.value.edit)
    }

    @Test fun badResponseWords() {
        val f = failureOf(ApiError(200, "bad_response", "The server sent a reply the app could not read"))
        println("PROBE bad_response -> $f")
        assertEquals(RecentFailure.Unexpected, f)
    }

    @Test fun spoolmanUnreachableWords() {
        val f = failureOf(ApiError(503, "spoolman_unreachable", "spoolman is not reachable"))
        println("PROBE spoolman_unreachable -> $f")
        assertEquals(false, f is RecentFailure.Hub)
    }

    @Test fun undoReportsWhatTheUndoDid() {
        val fake = Fake()
        val vm = RecordViewModel(fake, "a1")
        val list = HistoryListViewModel(fake)
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                RecordScreen(vm, list, onBack = {}, onOpenRecord = {}, onEdit = {}, onOpenPhoto = {}, onOpenSpool = {}, onPairAgain = {})
            }
        }
        rule.waitForIdle()
        vm.askUndo(); vm.undo()
        rule.waitForIdle()
        val wrongNew = runCatching { rule.onNodeWithText("The spools now use filament 42 (new).").assertExists() }.isSuccess
        val wrongEmpty = runCatching { rule.onNodeWithText("Filament 41 has no spools left; it was not deleted.").assertExists() }.isSuccess
        println("PROBE undo: says 'now use 42 (new)'=$wrongNew, says '41 has no spools'=$wrongEmpty")
        assertEquals(false, wrongNew || wrongEmpty)
    }
}
