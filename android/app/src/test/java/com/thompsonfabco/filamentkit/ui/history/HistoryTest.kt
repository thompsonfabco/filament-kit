package com.thompsonfabco.filamentkit.ui.history

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.HistoryChange
import com.thompsonfabco.filamentkit.net.HistoryFilaments
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

    @Test fun aStaleProposalShowsTheHubsMessageAndTryAgainAcceptsAgain() = runTest(dispatcher) {
        val vm = loaded()
        vm.ask("x")
        runCurrent()
        fake.error = ApiError(409, "stale", "The record changed since the answer.")
        vm.accept()
        runCurrent()
        val failed = vm.state.value.ask as Ask.Failed
        assertEquals(RecentFailure.Hub("The record changed since the answer."), failed.failure)
        assertEquals("p-1", failed.proposal?.proposal)
        fake.error = null
        vm.retry()
        runCurrent()
        // the accept is tried again with the proposal kept; the Label Reader is not asked again
        assertEquals(1, fake.revises.size)
        assertEquals(listOf("p-1", "p-1"), fake.applied)
        assertTrue(vm.state.value.ask is Ask.Accepted)
    }

    @Test fun tryAgainAfterAFailedAcceptAcceptsTheSameProposal() = runTest(dispatcher) {
        val vm = loaded()
        vm.ask("x")
        runCurrent()
        fake.error = ApiError(0, "offline", "no route")
        vm.accept()
        runCurrent()
        val failed = vm.state.value.ask as Ask.Failed
        assertEquals("p-1", failed.proposal?.proposal)
        assertTrue(vm.state.value.offline)
        fake.error = null
        vm.retry()
        runCurrent()
        assertEquals(listOf("p-1", "p-1"), fake.applied)
        assertEquals(1, fake.revises.size)
        assertTrue(vm.state.value.ask is Ask.Accepted)
        assertFalse(vm.state.value.offline)
    }

    @Test fun failuresAreToldApartByTheHubsRealCodes() = runTest(dispatcher) {
        val vm = loaded()
        for ((code, want) in listOf(
            "ai_off" to RecentFailure.ReaderOff, "daily_cap" to RecentFailure.DailyLimit,
            "local_busy" to RecentFailure.ReaderBusy, "offline" to RecentFailure.Offline,
            "bad_key" to RecentFailure.KeyRefused, "unreachable" to RecentFailure.CloudDown,
            "api_error" to RecentFailure.Unreadable, "no_photo" to RecentFailure.NoPhoto,
            "spoolman_unreachable" to RecentFailure.SpoolmanDown, "bad_response" to RecentFailure.Unexpected,
        )) {
            fake.error = ApiError(409, code, "the Hub's words")
            vm.ask("x")
            runCurrent()
            assertEquals(code, Ask.Failed(want), vm.state.value.ask)
        }
        // a page with no message of the Hub's own is an answer the app does not understand
        fake.error = ApiError(502, "internal", com.thompsonfabco.filamentkit.net.apiStandIn(502))
        vm.ask("x")
        runCurrent()
        assertEquals(Ask.Failed(RecentFailure.Unexpected), vm.state.value.ask)
        fake.error = IllegalStateException("not json")
        vm.ask("x")
        runCurrent()
        assertEquals(Ask.Failed(RecentFailure.Unexpected), vm.state.value.ask)
        fake.error = ApiError(409, "something_else", "Only the newest revision can be undone.")
        vm.ask("x")
        runCurrent()
        assertEquals(Ask.Failed(RecentFailure.Hub("Only the newest revision can be undone.")), vm.state.value.ask)
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
            put("nozzle", 215)
            put("nozzle_range", "200-235")
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

    @Test fun badValuesStayUnderTheirFieldsAllAtOnceWithTheHubsRule() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Nozzle to "hot", RecentField.Bed to "600", RecentField.BedRange to "200",
            RecentField.Colour to "12345", RecentField.Net to "0", RecentField.Density to "-1", RecentField.Price to "free")
        vm.saveEdit {}
        runCurrent()
        assertTrue(fake.edits.isEmpty())
        assertEquals(
            mapOf(
                RecentField.Nozzle to FieldError.Whole, RecentField.Bed to FieldError.DegreesMax,
                RecentField.BedRange to FieldError.Range, RecentField.Colour to FieldError.Colour,
                RecentField.Net to FieldError.Grams, RecentField.Density to FieldError.Density, RecentField.Price to FieldError.Price,
            ),
            vm.state.value.edit!!.errors,
        )
        vm.setText(RecentField.Nozzle, "215")
        assertFalse(RecentField.Nozzle in vm.state.value.edit!!.errors)
    }

    @Test fun aSavedFormDoesNotOpenAgainWhileItLeavesButDoesOnTheNextVisit() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "Polymaker")
        vm.saveEdit {}
        runCurrent()
        assertNull(vm.state.value.edit)
        vm.startEdit(0) // the screen still composed, the record has just changed
        assertNull(vm.state.value.edit)
        assertEquals(listOf(RecentField.Vendor), vm.state.value.saved?.fields)
        vm.beginEdit(0)
        vm.startEdit(0)
        assertEquals(0, vm.state.value.edit?.item)
        assertNull(vm.state.value.saved)
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

    @Test fun anUnpairedPhoneKeepsTheTypingAndShowsTheNotice() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "X")
        fake.error = ApiError(401, "unauthorized", "x")
        vm.saveEdit {}
        runCurrent()
        assertTrue(vm.state.value.unauthorized)
        val e = vm.state.value.edit!!
        assertEquals("X", e.texts[RecentField.Vendor])
        assertFalse(e.busy)
        assertTrue(e.dirty)
    }

    @Test fun aChangedCertificateKeepsTheTypingToo() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "X")
        fake.error = com.thompsonfabco.filamentkit.net.FingerprintMismatch("AA", "BB")
        vm.saveEdit {}
        runCurrent()
        assertEquals("AA" to "BB", vm.state.value.mismatch)
        assertEquals("X", vm.state.value.edit!!.texts[RecentField.Vendor])
    }

    @Test fun aHubOutOfReachDuringASaveIsTheOfflineStateAndKeepsTheForm() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "X")
        fake.error = ApiError(0, "offline", "no route")
        vm.saveEdit {}
        runCurrent()
        assertTrue(vm.state.value.offline)
        assertEquals(RecentFailure.Offline, vm.state.value.edit!!.failure)
        assertEquals("X", vm.state.value.edit!!.texts[RecentField.Vendor])
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

    @Test fun theUndoResultIsWhatTheHubsAnswerSaysTheUndoDid() = runTest(dispatcher) {
        val before = rev1.copy(filaments = HistoryFilaments(41, 42, created = true, orphaned = listOf(41)))
        fake.rec = record.copy(revisions = listOf(before))
        val vm = loaded()
        // the Hub's answer: revision 1 undone, the spools on a copy (filament 43), filament 42 left without spools
        fake.rec = record.copy(revisions = listOf(before.copy(undone = true, filaments = before.filaments!!.copy(undoTo = 43, orphanedByUndo = listOf(42)))))
        vm.askUndo()
        vm.undo()
        runCurrent()
        val done = vm.state.value.undone!!
        assertEquals(43, done.filaments?.undoTo)
        assertEquals(listOf(42), done.filaments?.orphanedByUndo)
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

    @Test fun parseFollowsTheHubsRulePerField() {
        assertEquals(Parsed.Ok(JsonNull), RecentValues.parse(" ", RecentField.Line))
        assertEquals(Parsed.Bad(FieldError.Required), RecentValues.parse(" ", RecentField.Name))
        assertEquals(Parsed.Ok(JsonPrimitive(1.5)), RecentValues.parse("1.5", RecentField.Density))
        assertEquals(Parsed.Bad(FieldError.Density), RecentValues.parse("0", RecentField.Density))
        assertEquals(Parsed.Bad(FieldError.Grams), RecentValues.parse("abc", RecentField.Tare))
        assertEquals(Parsed.Ok(JsonPrimitive("abc")), RecentValues.parse("abc", RecentField.Line))
        // temperatures: whole degrees, 1 to 499, sent as whole numbers
        assertEquals(Parsed.Ok(JsonPrimitive(215)), RecentValues.parse("215", RecentField.Nozzle))
        assertEquals(Parsed.Ok(JsonPrimitive(215)), RecentValues.parse("215.0", RecentField.Nozzle))
        assertEquals(Parsed.Bad(FieldError.Whole), RecentValues.parse("215.5", RecentField.Nozzle))
        assertEquals(Parsed.Bad(FieldError.Degrees), RecentValues.parse("0", RecentField.Bed))
        assertEquals(Parsed.Bad(FieldError.DegreesMax), RecentValues.parse("500", RecentField.Bed))
        assertEquals(Parsed.Ok(JsonPrimitive(499)), RecentValues.parse("499", RecentField.Bed))
        // ranges go as the text the Hub keeps
        assertEquals(Parsed.Ok(JsonPrimitive("55-65")), RecentValues.parse("55, 65", RecentField.BedRange))
        assertEquals(Parsed.Ok(JsonPrimitive("190-230")), RecentValues.parse("190–230", RecentField.NozzleRange))
        assertEquals(Parsed.Bad(FieldError.Range), RecentValues.parse("200", RecentField.BedRange))
        assertEquals(Parsed.Bad(FieldError.Range), RecentValues.parse("1-2-3", RecentField.BedRange))
        assertEquals(Parsed.Ok(JsonPrimitive("2B2B2E")), RecentValues.parse("#2b2b2e", RecentField.Colour))
        assertEquals(Parsed.Bad(FieldError.Colour), RecentValues.parse("2B2B2", RecentField.Colour))
        assertEquals(Parsed.Bad(FieldError.Colour), RecentValues.parse("GGGGGG", RecentField.Colour))
    }

    @Test fun whatTheReaderSaidWhenItReadTheItem() {
        val read = HistoryRead(listOf(buildJsonObject {
            put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("material", "PLA")
            put("color_name", "Charcoal"); put("color_family", "grey"); put("confidence", 0.86)
            put("field_confidence", buildJsonObject { put("density", 0.5); put("vendor", 0.95) })
        }))
        val r = record.copy(read = read, saved = listOf(savedWith()))
        val d = ReadDetails.of(r, 0)!!
        assertEquals("Charcoal", d.colourName)
        assertEquals("grey", d.colourFamily)
        assertEquals(86, d.percent)
        assertEquals(listOf("density"), d.leastSure)
        assertNull(ReadDetails.of(record.copy(read = null), 0))
        // a colour the library has no name for
        val unnamed = HistoryRead(listOf(buildJsonObject {
            put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("material", "PLA"); put("color_name", "unknown")
        }))
        val u = ReadDetails.of(record.copy(read = unnamed, saved = listOf(savedWith())), 0)!!
        assertTrue(u.unnamed)
        assertNull(u.colourName)
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

    @Test fun aSuccessfulLoadClearsTheHubNotices() = runTest(dispatcher) {
        val list = HistoryListViewModel(fake)
        fake.listError = ApiError(401, "unauthorized", "x")
        list.refresh(); runCurrent()
        assertTrue(list.state.value.unauthorized)
        fake.listError = null
        list.refresh(); runCurrent()
        assertFalse(list.state.value.unauthorized)
        val vm = RecordViewModel(fake, "a1")
        fake.error = null
        val real = fake.rec
        vm.load(); runCurrent()
        edited(vm, RecentField.Vendor to "X")
        fake.error = ApiError(401, "unauthorized", "x")
        vm.saveEdit {}; runCurrent()
        assertTrue(vm.state.value.unauthorized)
        fake.error = null
        vm.load(); runCurrent()
        assertFalse(vm.state.value.unauthorized)
        assertNull(vm.state.value.mismatch)
        assertEquals(real, vm.state.value.record)
    }

    @Test fun brandNameAndMaterialCannotBeCleared() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to " ", RecentField.Name to "", RecentField.Material to "PLA", RecentField.Line to "")
        vm.saveEdit {}; runCurrent()
        assertTrue(fake.edits.isEmpty())
        assertEquals(
            mapOf(RecentField.Vendor to FieldError.Required, RecentField.Name to FieldError.Required),
            vm.state.value.edit!!.errors,
        )
    }

    @Test fun aSuccessfulSaveAfterA401ClearsTheNotice() = runTest(dispatcher) {
        val vm = loaded()
        edited(vm, RecentField.Vendor to "X")
        fake.error = ApiError(401, "unauthorized", "x")
        vm.saveEdit {}; runCurrent()
        assertTrue(vm.state.value.unauthorized)
        fake.error = null
        vm.saveEdit {}; runCurrent()
        assertFalse(vm.state.value.unauthorized)
        assertNull(vm.state.value.mismatch)
        vm.ask("x"); runCurrent()
        fake.error = com.thompsonfabco.filamentkit.net.FingerprintMismatch("AA", "BB")
        vm.accept(); runCurrent()
        assertEquals("AA" to "BB", vm.state.value.mismatch)
        fake.error = null
        vm.retry(); runCurrent()
        assertNull(vm.state.value.mismatch)
    }

    @Test fun theFormIsUnavailableOnlyOnceTheRecordIsThereWithoutTheItem() = runTest(dispatcher) {
        val vm = RecordViewModel(fake, "a1")
        vm.startEdit(0)
        assertFalse(vm.state.value.editUnavailable)
        vm.load(); runCurrent()
        vm.startEdit(0)
        assertFalse(vm.state.value.editUnavailable)
        vm.closeEdit()
        assertFalse(vm.state.value.editUnavailable)
        vm.startEdit(9)
        assertTrue(vm.state.value.editUnavailable)
        vm.beginEdit(0)
        assertFalse(vm.state.value.editUnavailable)
    }

    @Test fun identicalChangesAcrossSpoolsAreOneLine() {
        val c = { id: Int -> HistoryChange(id, "name", JsonPrimitive("A"), JsonPrimitive("B")) }
        val m = mergedChanges(listOf(c(41), c(42), HistoryChange(41, "tare", JsonPrimitive(150), JsonPrimitive(140))))
        assertEquals(2, m.size)
        assertEquals(listOf(41, 42), m[0].spoolIds)
        assertEquals(listOf(41), m[1].spoolIds)
    }

    @Test fun equalNumbersAndRangesAreNotChanges() = runTest(dispatcher) {
        assertTrue(sameValue(JsonPrimitive(140.0), JsonPrimitive(140)))
        assertTrue(sameValue(JsonPrimitive("190-230"), values["nozzle_range"]))
        assertTrue(sameValue(JsonNull, null))
        val vm = loaded()
        edited(vm, RecentField.Nozzle to "210.0")
        vm.saveEdit {}; runCurrent()
        assertTrue(fake.edits.isEmpty())
        assertTrue(vm.state.value.edit!!.nothingChanged)
    }

    @Test fun aNewClientReloadsTheRecordAndClearsTheNotice() = runTest(dispatcher) {
        val vm = RecordViewModel(fake, "a1")
        vm.clientSeen("one"); runCurrent()
        fake.error = null
        vm.load(); runCurrent()
        val before = fake.rec
        vm.clientSeen("one"); runCurrent()
        vm.clientSeen("two"); runCurrent()
        assertEquals(before, vm.state.value.record)
    }
}
