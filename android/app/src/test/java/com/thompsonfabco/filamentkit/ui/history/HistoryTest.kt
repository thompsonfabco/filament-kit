package com.thompsonfabco.filamentkit.ui.history

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.HistoryChange
import com.thompsonfabco.filamentkit.net.HistoryFilaments
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistoryRevision
import com.thompsonfabco.filamentkit.net.HistorySaved
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.RevisionProposal
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class HistoryTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private val values = buildJsonObject {
        put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("nozzle", 210)
        put("nozzle_range", JsonArray(listOf(JsonPrimitive(190), JsonPrimitive(230))))
    }
    private val rev1 = HistoryRevision(n = 1, by = "ai", note = "brand is Polymaker",
        changes = listOf(HistoryChange(41, "vendor", JsonPrimitive("SUNLU"), JsonPrimitive("Polymaker"))))
    private val record = HistoryRecord(id = "a1", photos = 1, undoable = true,
        spools = listOf(HistorySpool(41, 12, "SUNLU", "PLA+ Grey", "PLA")),
        saved = listOf(HistorySaved(0, listOf(41, 42), values)), revisions = listOf(rev1))

    private class Fake(var rec: HistoryRecord) : HistoryBackend {
        val revises = mutableListOf<Triple<String, String, Int?>>()
        val applied = mutableListOf<String>()
        val edits = mutableListOf<Pair<Int, JsonObject>>()
        val undos = mutableListOf<Int>()
        val photoCalls = mutableListOf<Int>()
        var lists = 0
        var ai = true
        var error: Exception? = null
        var proposal = RevisionProposal("p-1", 0, buildJsonObject { put("vendor", "SUNLU") },
            buildJsonObject { put("vendor", "Polymaker") }, listOf("vendor"))
        override suspend fun list(): IntakeHistory { lists++; return IntakeHistory(20, 1, null, ai) }
        override suspend fun record(id: String) = rec
        override suspend fun photo(id: String, n: Int): ByteArray { photoCalls += n; return byteArrayOf(1, 2) }
        override suspend fun revise(id: String, note: String, item: Int?): RevisionProposal {
            revises += Triple(id, note, item); error?.let { throw it }; return proposal
        }
        override suspend fun applyProposal(id: String, proposal: String): HistoryRecord {
            applied += proposal; error?.let { throw it }; return rec
        }
        override suspend fun applyValues(id: String, item: Int, values: JsonObject): HistoryRecord {
            edits += item to values; error?.let { throw it }; return rec
        }
        override suspend fun undo(id: String, revision: Int): HistoryRecord {
            undos += revision; error?.let { throw it }; return rec
        }
    }

    private val fake = Fake(record)

    private fun loaded() = RecordViewModel(fake, "a1").also { it.load(); dispatcher.scheduler.runCurrent() }

    @Test fun reviseAsksAndShowsTheProposalWithoutWriting() = runTest(dispatcher) {
        val vm = loaded()
        vm.revise("  brand is Polymaker ")
        runCurrent()
        assertEquals(listOf(Triple("a1", "brand is Polymaker", null as Int?)), fake.revises)
        assertEquals("p-1", vm.state.value.proposal?.proposal)
        assertTrue(fake.applied.isEmpty())
        vm.discard()
        assertNull(vm.state.value.proposal)
        assertTrue(fake.applied.isEmpty())
    }

    @Test fun anEmptyNoteIsNotSent() = runTest(dispatcher) {
        val vm = loaded()
        vm.revise("  ")
        runCurrent()
        assertTrue(fake.revises.isEmpty())
        assertEquals(HistoryTexts.NEED_NOTE, vm.state.value.noteError)
    }

    @Test fun acceptAppliesTheProposalShown() = runTest(dispatcher) {
        val vm = loaded()
        vm.revise("brand is Polymaker")
        runCurrent()
        vm.accept()
        runCurrent()
        assertEquals(listOf("p-1"), fake.applied)
        assertNull(vm.state.value.proposal)
        assertEquals(HistoryTexts.SAVED, vm.state.value.message)
    }

    @Test fun aStaleProposalSaysAskAgain() = runTest(dispatcher) {
        val vm = loaded()
        vm.revise("x")
        runCurrent()
        fake.error = ApiError(409, "stale", "x")
        vm.accept()
        runCurrent()
        assertEquals(HistoryTexts.STALE, vm.state.value.message)
        assertTrue(vm.state.value.messageIsError)
        assertNull(vm.state.value.proposal)
    }

    @Test fun aiOffAndTheDailyCapAreSaidPlainly() = runTest(dispatcher) {
        val vm = loaded()
        fake.error = ApiError(409, "ai_off", "x")
        vm.revise("x")
        runCurrent()
        assertEquals(HistoryTexts.AI_OFF, vm.state.value.noteError)
        fake.error = ApiError(429, "daily_cap", "x")
        vm.revise("x")
        runCurrent()
        assertTrue(vm.state.value.noteError!!.contains("limit"))
    }

    @Test fun anEditSendsOnlyChangedFieldsTyped() = runTest(dispatcher) {
        val vm = loaded()
        vm.openEdit(0)
        vm.saveEdit(mapOf("vendor" to "Polymaker", "name" to "PLA+ Grey", "nozzle" to "215", "nozzle_range" to "200-235",
            "density" to "", "color_hex" to "#8a8d8f"))
        runCurrent()
        val (item, sent) = fake.edits.single()
        assertEquals(0, item)
        assertEquals(buildJsonObject {
            put("vendor", "Polymaker")
            put("nozzle", 215.0)
            put("nozzle_range", JsonArray(listOf(JsonPrimitive(200.0), JsonPrimitive(235.0))))
            put("color_hex", "8A8D8F")
        }, sent)
        assertNull(vm.state.value.edit)
    }

    @Test fun anUnchangedEditSendsNothing() = runTest(dispatcher) {
        val vm = loaded()
        vm.openEdit(0)
        vm.saveEdit(mapOf("vendor" to "SUNLU", "nozzle" to "210", "nozzle_range" to "190–230"))
        runCurrent()
        assertTrue(fake.edits.isEmpty())
        assertNull(vm.state.value.edit)
    }

    @Test fun aBadNumberStaysInTheForm() = runTest(dispatcher) {
        val vm = loaded()
        vm.openEdit(0)
        vm.saveEdit(mapOf("nozzle" to "hot"))
        runCurrent()
        assertTrue(fake.edits.isEmpty())
        assertTrue(vm.state.value.edit!!.error!!.startsWith("Nozzle"))
    }

    @Test fun undoTakesBackTheNewestNotUndone() = runTest(dispatcher) {
        val rev2 = HistoryRevision(n = 2, by = "hand", undone = true)
        fake.rec = record.copy(revisions = listOf(rev1, rev2))
        val vm = loaded()
        assertEquals(1, vm.state.value.undoTarget?.n)
        vm.undo()
        runCurrent()
        assertEquals(listOf(1), fake.undos)
        assertEquals(HistoryTexts.UNDONE, vm.state.value.message)
    }

    @Test fun nothingToUndoWhenTheServerSaysSo() = runTest(dispatcher) {
        fake.rec = record.copy(undoable = false)
        val vm = loaded()
        assertNull(vm.state.value.undoTarget)
        vm.undo()
        runCurrent()
        assertTrue(fake.undos.isEmpty())
    }

    @Test fun anUnpairedPhoneClosesDialogs() = runTest(dispatcher) {
        val vm = loaded()
        vm.openEdit(0)
        fake.error = ApiError(401, "unauthorized", "x")
        vm.saveEdit(mapOf("vendor" to "X"))
        runCurrent()
        assertTrue(vm.state.value.unauthorized)
        assertNull(vm.state.value.edit)
    }

    @Test fun aPhotoIsFetchedOncePerVisit() = runTest(dispatcher) {
        val list = HistoryListViewModel(fake)
        list.photo("a1", 1)
        list.photo("a1", 1)
        list.photo("a1", 2)
        assertEquals(listOf(1, 2), fake.photoCalls)
    }

    @Test fun aRecordOpenedAloneLoadsTheAiFlag() = runTest(dispatcher) {
        val list = HistoryListViewModel(fake)
        assertNull(list.state.value.aiAvailable)
        list.ensureLoaded()
        list.ensureLoaded()
        runCurrent()
        assertEquals(1, fake.lists)
        assertEquals(true, list.state.value.aiAvailable)
        list.ensureLoaded()
        runCurrent()
        assertEquals(1, fake.lists)
    }

    @Test fun aiOffComesOnlyFromTheServer() = runTest(dispatcher) {
        fake.ai = false
        val list = HistoryListViewModel(fake)
        list.ensureLoaded()
        runCurrent()
        assertEquals(false, list.state.value.aiAvailable)
    }

    @Test fun valuesReadPlainly() {
        assertEquals("210", HistoryTexts.value(JsonPrimitive(210.0)))
        assertEquals("1.24", HistoryTexts.value(JsonPrimitive(1.24)))
        assertEquals("190–230", HistoryTexts.value(values["nozzle_range"]))
        assertEquals("–", HistoryTexts.value(JsonNull))
        assertEquals("–", HistoryTexts.value(null))
    }

    @Test fun parseKeepsTheValuesShape() {
        assertEquals(JsonNull, HistoryTexts.parse(" ", JsonPrimitive("x")))
        assertEquals(JsonPrimitive(1.5), HistoryTexts.parse("1.5", JsonNull, "density"))
        assertNull(HistoryTexts.parse("abc", JsonPrimitive(210)))
        assertEquals(JsonPrimitive("abc"), HistoryTexts.parse("abc", JsonPrimitive("x")))
        assertNull(HistoryTexts.parse("200", null, "bed_range"))
        assertEquals(JsonArray(listOf(JsonPrimitive(55.0), JsonPrimitive(65.0))), HistoryTexts.parse("55, 65", null, "bed_range"))
    }

    @Test fun aLeftOverFilamentIsReportedNotHidden() {
        val r = rev1.copy(filaments = HistoryFilaments(12, 31, created = true, orphaned = listOf(12)))
        val text = HistoryTexts.filaments(r)!!
        assertTrue(text.contains("new filament (#31)"))
        assertTrue(text.contains("#12 now has no spools"))
        assertNull(HistoryTexts.filaments(rev1))
    }

    @Test fun revisionLinesNameTheFieldAndSpool() {
        assertEquals(listOf("Brand: SUNLU → Polymaker (spool #41)"), HistoryTexts.changes(rev1))
        assertTrue(HistoryTexts.revision(rev1).startsWith("AI · “brand is Polymaker”"))
        assertTrue(HistoryTexts.revision(rev1.copy(undone = true)).endsWith("(undone)"))
    }

    @Test fun listLinesNameSpoolsStateAndSource() {
        assertEquals("SUNLU PLA+ Grey (PLA)", HistoryTexts.spools(record.spools))
        assertEquals("SUNLU PLA+ Grey (PLA) · 2 spools", HistoryTexts.spools(record.spools + record.spools))
        assertEquals("Revised by AI", HistoryTexts.state("revised_ai"))
        assertEquals("intake station", HistoryTexts.source("station"))
        assertFalse(HistoryTexts.time("not a time").isEmpty())
    }
}
