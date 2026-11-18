package com.thompsonfabco.filamentkit.ui.spool

import android.os.Build
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.net.ActivityEvent
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.UndoAnswer
import com.thompsonfabco.filamentkit.net.UndoState
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.SwToastHost
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.history.UndoKinds
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The spool screen end to end (R84 3.3): the action's toast with Undo, what Undo answers, and the list's Undo. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class SpoolUndoToastTest {
    @get:Rule val rule = createComposeRule()

    private val fake = FakeSpoolBackend()
    private var events: List<ActivityEvent> = emptyList()
    private val undone = mutableListOf<Long>()
    private var refusal: ApiError? = null

    private val backend = object : SpoolBackend by fake {
        override suspend fun activity(subject: String, limit: Int) = events.filter { it.subject == subject }
        override suspend fun undoEvent(id: Long): UndoAnswer {
            undone += id
            refusal?.let { throw it }
            return UndoAnswer(true, id + 1, null)
        }
    }

    private fun event(id: Long, kind: String, possible: Boolean = true) = ActivityEvent(
        id, "2026-11-17T04:00:00Z", System.currentTimeMillis() - 1_000, kind, "Pixel", "Moved to Shelf B.", "spool:214",
        UndoState(possible, null, null), false, null,
    )

    private fun show(vm: SpoolViewModel, toast: SwToastState) {
        SpoolCache.clear()
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                CompositionLocalProvider(LocalToast provides toast) {
                    Box(Modifier.fillMaxSize()) {
                        SpoolScreen(vm, onLoad = {}, onPairAgain = {})
                        SwToastHost(toast, Modifier.align(Alignment.BottomCenter))
                    }
                }
            }
        }
    }

    private fun moved(): Pair<SpoolViewModel, SwToastState> {
        fake.updateAnswer = { _, location, _, _ -> spoolJson(214, location = location) }
        fake.spools = listOf(spoolJson(214))
        val toast = SwToastState()
        val vm = SpoolViewModel(214, backend, spoolJson(214).toSpoolSummary(), null)
        show(vm, toast)
        rule.waitForIdle()
        vm.openMove()
        rule.waitForIdle()
        return vm to toast
    }

    @Test fun aMoveShowsTheToastWithUndoAndUndoSaysPutBack() {
        val (vm, _) = moved()
        events = listOf(event(31, UndoKinds.MOVED))
        vm.move("Shelf B")
        rule.waitUntil(5_000) { rule.onAllNodesWithText("Undo").fetchSemanticsNodes().size >= 1 }
        // the toast says what happened, with Undo
        assertTrue(rule.onAllNodesWithText("Moved to Shelf B.").fetchSemanticsNodes().isNotEmpty())
        rule.onAllNodesWithText("Undo").fetchSemanticsNodes().let { assertEquals("the toast's Undo and the list's", 2, it.size) }
        rule.onAllNodesWithText("Undo")[0].performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithText("Put back.").fetchSemanticsNodes().isNotEmpty() }
        assertEquals(listOf(31L), undone)
    }

    @Test fun aRefusedUndoShowsTheHubsWords() {
        val (vm, _) = moved()
        events = listOf(event(31, UndoKinds.MOVED))
        refusal = ApiError(409, "changed_since", "x", JsonObject(mapOf("text" to JsonPrimitive("This changed again since, so it cannot be undone."))))
        vm.move("Shelf B")
        rule.waitUntil(5_000) { rule.onAllNodesWithText("Undo").fetchSemanticsNodes().isNotEmpty() }
        rule.onAllNodesWithText("Undo")[0].performClick()
        rule.waitUntil(5_000) {
            rule.onAllNodesWithText("This changed again since, so it cannot be undone.").fetchSemanticsNodes().isNotEmpty()
        }
    }

    @Test fun withoutAnUndoOnTheHubAMoveKeepsTheScreensOwnUndo() {
        val (vm, _) = moved()
        events = emptyList()
        vm.move("Shelf B")
        rule.waitUntil(5_000) { rule.onAllNodesWithText("Undo").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("Undo").performClick()
        rule.waitUntil(5_000) { fake.calls.any { it.contains("location=Workshop X1 A1") } }
        assertTrue("no Hub undo was asked", undone.isEmpty())
    }

    @Test fun theListShowsTimeWhoWhatAndUndoOnlyForARowTheHubAllows() {
        events = listOf(event(31, UndoKinds.MOVED), event(30, UndoKinds.WEIGHED, possible = false))
        fake.spools = listOf(spoolJson(214))
        val vm = SpoolViewModel(214, backend, spoolJson(214).toSpoolSummary(), null)
        show(vm, SwToastState())
        rule.waitUntil(5_000) { rule.onAllNodesWithText("Recent activity").fetchSemanticsNodes().isNotEmpty() }
        assertEquals(2, rule.onAllNodesWithText("Moved to Shelf B.").fetchSemanticsNodes().size)
        assertEquals("one Undo: the row the Hub allows", 1, rule.onAllNodesWithText("Undo").fetchSemanticsNodes().size)
        assertTrue(rule.onAllNodesWithText("Pixel", substring = true).fetchSemanticsNodes().size >= 2)
    }

    @Test fun anOlderHubLeavesTheSectionOut() {
        val vm = SpoolViewModel(214, backend, spoolJson(214).toSpoolSummary(), null)
        show(vm, SwToastState())
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithText("Recent activity").fetchSemanticsNodes().size)
    }
}
