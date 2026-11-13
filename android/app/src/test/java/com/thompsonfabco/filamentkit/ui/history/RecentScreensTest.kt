package com.thompsonfabco.filamentkit.ui.history

import android.os.Build
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistorySaved
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.RevisionProposal
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The photo viewer (05-android-app 10.5) and the Hub notices of the record, with fake data (`*.example`, RFC 5737). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class RecentScreensTest {
    @get:Rule val rule = createComposeRule()

    private class Fake(val photo: () -> ByteArray) : HistoryBackend {
        var photoCalls = 0
        private val record = HistoryRecord(
            id = "a1", photos = 2, spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA")),
            saved = listOf(HistorySaved(0, listOf(214))),
        )
        override suspend fun list() = IntakeHistory(20, 1, null, true)
        override suspend fun record(id: String) = record
        override suspend fun photo(id: String, n: Int): ByteArray { photoCalls++; return photo() }
        override suspend fun revise(id: String, note: String, item: Int?): RevisionProposal = error("not used")
        override suspend fun applyProposal(id: String, proposal: String): HistoryRecord = error("not used")
        override suspend fun applyValues(id: String, item: Int, values: JsonObject): HistoryRecord = error("not used")
        override suspend fun undo(id: String, revision: Int): HistoryRecord = error("not used")
    }

    private fun viewer(fake: Fake, start: Int, onClose: () -> Unit = {}) {
        val list = HistoryListViewModel(fake)
        val record = RecordViewModel(fake, "a1")
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) { PhotoViewer(list, record, "a1", start, onClose) }
        }
    }

    private fun edit(fake: Fake, onClose: () -> Unit = {}) {
        val vm = RecordViewModel(fake, "a1")
        rule.setContent { SpoolwardenTheme(Look.Console, Appearance.Light) { EditScreen(vm, 0, onClose, {}) } }
    }

    @Test fun theEditScreenShowsNoClosedNoticeWhileOpeningOrAfterCancel() {
        var closed = 0
        edit(Fake { error("no photo") }) { closed++ }
        rule.onNodeWithText("This record has no spools to edit now.").assertDoesNotExist()
        rule.waitForIdle()
        rule.onNodeWithText("Save changes").assertExists()
        rule.onNodeWithText("This record has no spools to edit now.").assertDoesNotExist()
        rule.onNodeWithText("Cancel").performClick()
        rule.waitForIdle()
        assertEquals(1, closed)
        rule.onNodeWithText("This record has no spools to edit now.").assertDoesNotExist()
    }

    @Test fun theEditScreenSaysSoWhenTheItemIsGone() {
        val vm = RecordViewModel(Fake { error("no photo") }, "a1")
        rule.setContent { SpoolwardenTheme(Look.Console, Appearance.Light) { EditScreen(vm, 7, {}, {}) } }
        rule.waitForIdle()
        rule.onNodeWithText("This record has no spools to edit now.").assertExists()
    }

    @Test fun theViewerNamesThePhotoAndClosesIt() {
        var closed = 0
        viewer(Fake { error("no photo") }, start = 2) { closed++ }
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 2").assertExists()
        rule.onNodeWithContentDescription("Close photo").performClick()
        assertEquals(1, closed)
    }

    @Test fun aPhotoThatCannotBeLoadedSaysSoAndTriesAgain() {
        val fake = Fake { error("no photo") }
        viewer(fake, start = 1)
        rule.waitForIdle()
        rule.onNodeWithText("The photo could not be loaded.").assertExists()
        val before = fake.photoCalls
        rule.onNodeWithText("Try again").performClick()
        rule.waitForIdle()
        assertEquals(before + 1, fake.photoCalls)
    }
}
