package com.thompsonfabco.filamentkit.ui.history

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.HistoryChange
import com.thompsonfabco.filamentkit.net.HistoryRead
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.ZoneId

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
        var listError: Exception? = null
        var proposal = RevisionProposal("p-1", 0, buildJsonObject { put("vendor", "SUNLU") },
            buildJsonObject { put("vendor", "Polymaker") }, listOf("vendor"))
        override suspend fun list(): IntakeHistory {
            lists++
            listError?.let { throw it }
            return IntakeHistory(20, 1, 1_500_000L, ai)
        }
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

    private fun edited(vm: RecordViewModel, vararg texts: Pair<RecentField, String>) {
        vm.startEdit(0)
        texts.forEach { (f, t) -> vm.setText(f, t) }
    }

    // ---- the Label Reader panel ----

    @Test fun askShowsTheProposalWithoutWriting() = runTest(dispatcher) {
        val vm = loaded()
        vm.ask("  brand is Polymaker ")
        assertEquals(Ask.Waiting, vm.state.value.ask)
        runCurrent()
        assertEquals(listOf(Triple("a1", "brand is Polymaker", null as Int?)), fake.revises)
        assertEquals("p-1", (vm.state.value.ask as Ask.Proposal).proposal.proposal)
        assertTrue(fake.applied.isEmpty())
        vm.discard()
        assertEquals(Ask.Discarded, vm.state.value.ask)
        assertTrue(fake.applied.isEmpty())
    }

    @Test fun anEmptyNoteIsNotSentAndTypingClearsTheError() = runTest(dispatcher) {
        val vm = loaded()
        vm.ask("  ")
        runCurrent()
        assertTrue(fake.revises.isEmpty())
        assertTrue(vm.state.value.noteMissing)
        assertEquals(Ask.Idle, vm.state.value.ask)
        vm.noteTyped()
        assertFalse(vm.state.value.noteMissing)
    }

    @Test fun aProposalWithNoChangeSaysSo() = runTest(dispatcher) {
        fake.proposal = fake.proposal.copy(changes = emptyList())
        val vm = loaded()
        vm.ask("x")
        runCurrent()
        assertEquals(Ask.NoChange, vm.state.value.ask)
    }

    @Test fun acceptAppliesTheProposalShownAndCountsTheChanges() = runTest(dispatcher) {
        fake.rec = record.copy(revisions = listOf(rev1, HistoryRevision(n = 2, by = "ai")))
        val vm = loaded()
        vm.ask("brand is Polymaker")
        runCurrent()
        vm.accept()
        runCurrent()
        assertEquals(listOf("p-1"), fake.applied)
        assertEquals(Ask.Accepted(count = 1, revision = 2), vm.state.value.ask)
        assertFalse(vm.state.value.applyBusy)
    }

    @Test fun aStaleProposalShowsTheHubsMessageAndTryAgainAsksAgain() = runTest(dispatcher) {
        val vm = loaded()
        vm.ask("x")
        runCurrent()
        fake.error = ApiError(409, "stale", "The record changed since the answer.")
        vm.accept()
        runCurrent()
        assertEquals(Ask.Failed(RecentFailure.Hub("The record changed since the answer.")), vm.state.value.ask)
        fake.error = null
        vm.askAgain()
        runCurrent()
        assertEquals(2, fake.revises.size)
        assertTrue(vm.state.value.ask is Ask.Proposal)
    }

    @Test fun readerFailuresAreToldApart() = runTest(dispatcher) {
        val vm = loaded()
        for ((code, want) in listOf(
            "ai_off" to RecentFailure.ReaderOff, "daily_cap" to RecentFailure.DailyLimit,
            "local_busy" to RecentFailure.ReaderBusy, "offline" to RecentFailure.Offline,
        )) {
            fake.error = ApiError(409, code, "x")
            vm.ask("x")
            runCurrent()
            assertEquals(code, Ask.Failed(want), vm.state.value.ask)
        }
        fake.error = IllegalStateException("not json")
        vm.ask("x")
        runCurrent()
        assertEquals(Ask.Failed(RecentFailure.Unexpected), vm.state.value.ask)
    }

    // ---- edit by hand ----

    @Test fun anEditSendsOnlyChangedFieldsTypedAndReportsThem() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "Polymaker", RecentField.Name to "PLA+ Grey", RecentField.Nozzle to "215",
            RecentField.NozzleRange to "200-235", RecentField.Colour to "#8a8d8f")
        var done = 0
        vm.saveEdit { done++ }
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
        assertEquals(1, done)
        assertEquals(
            SavedEdit(0, listOf(RecentField.Vendor, RecentField.Colour, RecentField.Nozzle, RecentField.NozzleRange).sortedBy { it.ordinal }),
            vm.state.value.saved?.let { SavedEdit(it.item, it.fields.sortedBy { f -> f.ordinal }) },
        )
    }

    @Test fun clearingAFieldSendsNull() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Nozzle to " ")
        vm.saveEdit {}
        runCurrent()
        assertEquals(JsonNull, fake.edits.single().second["nozzle"])
    }

    @Test fun anUnchangedEditSendsNothingAndSaysSo() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "SUNLU", RecentField.Nozzle to "210", RecentField.NozzleRange to "190–230")
        assertFalse(vm.state.value.edit!!.dirty)
        var done = 0
        vm.saveEdit { done++ }
        runCurrent()
        assertTrue(fake.edits.isEmpty())
        assertTrue(vm.state.value.edit!!.nothingChanged)
        assertEquals(0, done)
        vm.setText(RecentField.Vendor, "eSUN")
        assertFalse(vm.state.value.edit!!.nothingChanged)
    }

    @Test fun badValuesStayUnderTheirFieldsAllAtOnce() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Nozzle to "hot", RecentField.BedRange to "200", RecentField.Colour to "12345")
        vm.saveEdit {}
        runCurrent()
        assertTrue(fake.edits.isEmpty())
        assertEquals(
            mapOf(RecentField.Nozzle to FieldError.Number, RecentField.BedRange to FieldError.Range, RecentField.Colour to FieldError.Colour),
            vm.state.value.edit!!.errors,
        )
        vm.setText(RecentField.Nozzle, "215")
        assertFalse(RecentField.Nozzle in vm.state.value.edit!!.errors)
    }

    @Test fun aFailedSaveKeepsTheFormWithItsReason() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "X")
        fake.error = ApiError(400, "bad_request", "Spoolman refused that.")
        vm.saveEdit {}
        runCurrent()
        val e = vm.state.value.edit!!
        assertFalse(e.busy)
        assertEquals(RecentFailure.Hub("Spoolman refused that."), e.failure)
        assertEquals("X", e.texts[RecentField.Vendor])
    }

    @Test fun aFormOpenOnTheItemIsNotReset() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "X")
        vm.startEdit(0)
        assertEquals("X", vm.state.value.edit!!.texts[RecentField.Vendor])
        vm.closeEdit()
        assertNull(vm.state.value.edit)
    }

    @Test fun anUnpairedPhoneClosesTheFormAndTheDialogs() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "X")
        fake.error = ApiError(401, "unauthorized", "x")
        vm.saveEdit {}
        runCurrent()
        assertTrue(vm.state.value.unauthorized)
        assertNull(vm.state.value.edit)
    }

    // ---- undo ----

    @Test fun undoAsksThenTakesBackTheNewestNotUndone() = runTest(dispatcher) {
        val rev2 = HistoryRevision(n = 2, by = "hand", undone = true)
        fake.rec = record.copy(revisions = listOf(rev1, rev2))
        val vm = loaded()
        assertEquals(1, vm.state.value.undoTarget?.n)
        vm.askUndo()
        assertTrue(vm.state.value.undoAsk)
        vm.cancelUndo()
        assertFalse(vm.state.value.undoAsk)
        assertTrue(fake.undos.isEmpty())
        vm.askUndo()
        vm.undo()
        runCurrent()
        assertEquals(listOf(1), fake.undos)
        assertEquals(rev1, vm.state.value.undone)
        assertFalse(vm.state.value.undoAsk)
    }

    @Test fun nothingToUndoWhenTheHubSaysSo() = runTest(dispatcher) {
        fake.rec = record.copy(undoable = false)
        val vm = loaded()
        assertNull(vm.state.value.undoTarget)
        vm.askUndo()
        vm.undo()
        runCurrent()
        assertFalse(vm.state.value.undoAsk)
        assertTrue(fake.undos.isEmpty())
    }

    @Test fun aFailedUndoSaysWhy() = runTest(dispatcher) {
        val vm = loaded()
        fake.error = ApiError(409, "not_latest", "A newer revision exists.")
        vm.askUndo()
        vm.undo()
        runCurrent()
        assertEquals(RecentFailure.Hub("A newer revision exists."), vm.state.value.undoFailure)
        assertFalse(vm.state.value.undoAsk)
        assertNull(vm.state.value.undone)
    }

    // ---- the list and its photos ----

    @Test fun aPhotoIsFetchedOncePerVisit() = runTest(dispatcher) {
        val list = HistoryListViewModel(fake)
        list.photo("a1", 1)
        list.photo("a1", 1)
        list.photo("a1", 2)
        assertEquals(listOf(1, 2), fake.photoCalls)
    }

    @Test fun aRecordOpenedAloneLoadsTheReaderFlag() = runTest(dispatcher) {
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

    @Test fun readerOffComesOnlyFromTheHub() = runTest(dispatcher) {
        fake.ai = false
        val list = HistoryListViewModel(fake)
        list.ensureLoaded()
        runCurrent()
        assertEquals(false, list.state.value.aiAvailable)
    }

    @Test fun aFailedRefreshKeepsTheListAndSaysWhen() = runTest(dispatcher) {
        var clock = 1_000L
        val list = HistoryListViewModel(fake) { clock }
        list.refresh()
        runCurrent()
        assertEquals(1_000L, list.state.value.loadedAt)
        clock = 9_000L
        fake.listError = ApiError(0, "offline", "no route")
        list.refresh()
        runCurrent()
        val s = list.state.value
        assertNotNull(s.history)
        assertEquals(RecentFailure.Offline, s.error)
        assertEquals(1_000L, s.loadedAt)
        assertFalse(s.loading)
        fake.listError = null
        list.refresh()
        runCurrent()
        assertNull(list.state.value.error)
        assertEquals(9_000L, list.state.value.loadedAt)
    }

    @Test fun anUnpairedPhoneIsToldOnTheList() = runTest(dispatcher) {
        fake.listError = ApiError(401, "unauthorized", "x")
        val list = HistoryListViewModel(fake)
        list.refresh()
        runCurrent()
        assertTrue(list.state.value.unauthorized)
        assertNull(list.state.value.error)
    }

    // ---- words and values ----

    @Test fun valuesReadPlainly() {
        assertEquals("210", RecentValues.text(JsonPrimitive(210.0)))
        assertEquals("1.24", RecentValues.text(JsonPrimitive(1.24)))
        assertEquals("190–230", RecentValues.text(values["nozzle_range"]))
        assertEquals("SUNLU", RecentValues.text(JsonPrimitive("SUNLU")))
        assertNull(RecentValues.text(JsonNull))
        assertNull(RecentValues.text(null))
        assertNull(RecentValues.text(JsonPrimitive("  ")))
        assertNull(RecentValues.text(JsonArray(listOf(JsonNull, JsonNull))))
    }

    @Test fun parseKeepsTheFieldsShape() {
        assertEquals(Parsed.Ok(JsonNull), RecentValues.parse(" ", RecentField.Name))
        assertEquals(Parsed.Ok(JsonPrimitive(1.5)), RecentValues.parse("1.5", RecentField.Density))
        assertEquals(Parsed.Bad(FieldError.Number), RecentValues.parse("abc", RecentField.Nozzle))
        assertEquals(Parsed.Ok(JsonPrimitive("abc")), RecentValues.parse("abc", RecentField.Line))
        assertEquals(Parsed.Bad(FieldError.Range), RecentValues.parse("200", RecentField.BedRange))
        assertEquals(Parsed.Bad(FieldError.Range), RecentValues.parse("1-2-3", RecentField.BedRange))
        assertEquals(
            Parsed.Ok(JsonArray(listOf(JsonPrimitive(55.0), JsonPrimitive(65.0)))),
            RecentValues.parse("55, 65", RecentField.BedRange),
        )
        assertEquals(Parsed.Ok(JsonPrimitive("2B2B2E")), RecentValues.parse("#2b2b2e", RecentField.Colour))
        assertEquals(Parsed.Bad(FieldError.Colour), RecentValues.parse("2B2B2", RecentField.Colour))
        assertEquals(Parsed.Bad(FieldError.Colour), RecentValues.parse("GGGGGG", RecentField.Colour))
    }

    @Test fun theFieldsFollowTheFourGroups() {
        val groups = RecentField.entries.groupBy { it.group }.mapValues { (_, v) -> v.map { it.wire } }
        assertEquals(listOf("vendor", "name", "material", "color_hex"), groups[RecentGroup.Identity])
        assertEquals(listOf("net", "tare", "density"), groups[RecentGroup.Weights])
        assertEquals(listOf("nozzle", "bed", "nozzle_range", "bed_range"), groups[RecentGroup.Temperatures])
        assertEquals(listOf("price_per_kg", "line"), groups[RecentGroup.Other])
        assertEquals(R.string.unit_g, RecentField.of("tare")?.unit)
        assertNull(RecentField.of("nope"))
    }

    @Test fun timesAreInThePhonesZoneToTheMinute() {
        assertEquals("2026-11-12 14:05", RecentValues.time("2026-11-12T14:05:33+00:00", ZoneId.of("UTC")))
        assertEquals("2026-11-12 09:05", RecentValues.time("2026-11-12T14:05:33+00:00", ZoneId.of("America/New_York")))
        assertEquals("not a time", RecentValues.time("not a time"))
    }

    @Test fun sizesAreMegabytesWithOneDecimal() {
        assertEquals("14.2", RecentValues.megabytes(14_900_000L).replace(',', '.'))
        assertEquals("0.0", RecentValues.megabytes(0L).replace(',', '.'))
    }

    @Test fun filamentsAndSpoolsOfARecord() {
        val a = HistorySpool(214, 1, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA")
        val b = HistorySpool(215, 1, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA")
        val c = HistorySpool(null, null, null, null, null)
        assertEquals("Polymaker PolyTerra PLA Charcoal Black", RecentValues.filaments(listOf(a, b, c)))
        assertEquals("SUNLU PLA+ Grey, Polymaker PolyTerra PLA Charcoal Black", RecentValues.filaments(record.spools + a))
        assertNull(RecentValues.filaments(listOf(c)))
        assertEquals("214, 215", RecentValues.idList(RecentValues.spoolIds(listOf(a, b, a, c))))
    }

    @Test fun theSourceIsSaidInWordsOrAsTheHubGivesIt() {
        assertEquals(R.string.recent_source_phone, sourceLabel("phone", 2).word)
        assertEquals(R.string.recent_source_station, sourceLabel("station", 1).word)
        assertEquals(R.string.recent_source_hand, sourceLabel("phone", 0).word)
        assertEquals(R.string.recent_source_hand, sourceLabel("web", 0).word)
        val other = sourceLabel("cli", 1)
        assertNull(other.word)
        assertEquals("cli", other.raw)
    }

    @Test fun theStateVocabularyHasShapesAndWords() {
        assertEquals(R.string.status_as_detected, IntakeState.of("detected")?.word)
        assertEquals(R.string.status_revised_ai, IntakeState.of("revised_ai")?.word)
        assertEquals(R.string.status_edited, IntakeState.of("edited")?.word)
        assertNull(IntakeState.of("other"))
        assertEquals(3, IntakeState.entries.map { it.shape }.toSet().size)
    }

    // ---- marks ----

    private fun readItem(vararg extra: Pair<String, String>) = buildJsonObject {
        put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("material", "PLA")
        extra.forEach { (k, v) -> put(k, v) }
    }

    private fun savedWith(vararg extra: Pair<String, JsonPrimitive>) = HistorySaved(0, listOf(41), buildJsonObject {
        put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("material", "PLA")
        extra.forEach { (k, v) -> put(k, v) }
    })

    @Test fun estimatedAndUnreadFieldsAreMarked() {
        val read = HistoryRead(listOf(buildJsonObject {
            put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("material", "PLA"); put("density", 1.24)
            put("estimates", JsonArray(listOf(JsonPrimitive("density"))))
        }))
        val saved = savedWith("density" to JsonPrimitive(1.24))
        val marks = RecentMarks.of(record.copy(read = read, saved = listOf(saved)), saved)
        assertEquals(FieldMark.Estimated, marks[RecentField.Density])
        assertEquals(FieldMark.NotOnLabel, marks[RecentField.Bed])
        assertNull(marks[RecentField.Vendor])
    }

    @Test fun aFieldChangedSinceTheReadHasNoMark() {
        val read = HistoryRead(listOf(buildJsonObject {
            put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("material", "PLA"); put("density", 1.24)
            put("estimates", JsonArray(listOf(JsonPrimitive("density"))))
        }))
        val saved = savedWith("density" to JsonPrimitive(1.3), "bed" to JsonPrimitive(60))
        val marks = RecentMarks.of(record.copy(read = read, saved = listOf(saved)), saved)
        assertNull(marks[RecentField.Density])
        assertNull(marks[RecentField.Bed])
    }

    @Test fun aRecordAddedByHandHasNoMarks() {
        val saved = savedWith()
        assertTrue(RecentMarks.of(record.copy(read = null, saved = listOf(saved)), saved).isEmpty())
    }

    @Test fun aRemovedCardDoesNotShiftTheReadItem() {
        // the read had two items; the first card was removed, so saved item 0 is read item 1
        val r = record.copy(read = HistoryRead(listOf(
            buildJsonObject { put("vendor", "eSUN"); put("name", "PLA+ Black"); put("material", "PLA") },
            readItem("note" to "second"),
        )), saved = listOf(savedWith()))
        assertEquals("second", (RecentMarks.readItem(r, 0)?.get("note") as JsonPrimitive).content)
    }

    @Test fun noReadItemWhenItIsNotKnownForSure() {
        val read = HistoryRead(listOf(
            buildJsonObject { put("vendor", "eSUN"); put("name", "PLA+ Black"); put("material", "PLA") }, readItem(),
        ))
        val renamed = buildJsonObject { put("vendor", "Polymaker"); put("name", "PolyLite Grey"); put("material", "PLA") }
        // renamed and one card dropped: no match, counts differ
        assertNull(RecentMarks.readItem(record.copy(read = read, saved = listOf(HistorySaved(0, listOf(41), renamed))), 0))
        // renamed, nothing dropped: same place, same material
        val two = listOf(
            HistorySaved(0, listOf(40), buildJsonObject { put("vendor", "eSUN"); put("name", "PLA+ Black"); put("material", "PLA") }),
            HistorySaved(1, listOf(41), renamed),
        )
        assertNotNull(RecentMarks.readItem(record.copy(read = read, saved = two), 1))
        // a saved item the record does not have
        assertNull(RecentMarks.readItem(record.copy(read = read, saved = two), 5))
    }
}
