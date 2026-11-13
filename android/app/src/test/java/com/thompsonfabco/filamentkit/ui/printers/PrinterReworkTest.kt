package com.thompsonfabco.filamentkit.ui.printers

import android.content.pm.ActivityInfo
import android.os.Build
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.test.onNodeWithText
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.SwToastHost
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.NavHostController
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.nav.PrinterMapRoute
import com.thompsonfabco.filamentkit.nav.PrinterPickRoute
import com.thompsonfabco.filamentkit.nav.PrinterRoute
import com.thompsonfabco.filamentkit.nav.PrinterSettingsRoute
import com.thompsonfabco.filamentkit.nav.PrintersRoute
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.nav.settingsOverPairing
import com.thompsonfabco.filamentkit.tags.TagEvents
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummary
import androidx.compose.ui.test.onAllNodesWithText
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import com.thompsonfabco.filamentkit.ui.spool.LoadGate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Pick a spool for a slot (05-android-app 9.6): the view model's rules. */
@OptIn(ExperimentalCoroutinesApi::class)
class PickSpoolViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private class Fake : PickBackend {
        /** A dry run for these spools waits here, and ignores being cancelled, so a late answer really arrives. */
        val dryGates = mutableMapOf<Int, CompletableDeferred<Unit>>()
        var writeGate: CompletableDeferred<Unit>? = null
        var writeError: Exception? = null
        /** A dry run for these spools fails with this once its gate opens. */
        val dryErrors = mutableMapOf<Int, Exception>()
        val loads = mutableListOf<Pair<Int, Boolean>>()

        /** The spool each tag is linked to; a tag not in here is linked to none. */
        val tags = mutableMapOf<String, JsonObject>()
        var tagError: Exception? = null
        /** The lookup of this tag waits here, and ignores being cancelled, so a late answer really arrives. */
        val tagGates = mutableMapOf<String, CompletableDeferred<Unit>>()
        override suspend fun search(query: String, sealedOnly: Boolean): List<JsonObject> = emptyList()
        override suspend fun tag(uid: String): JsonObject? {
            tagGates[uid]?.let { withContext(NonCancellable) { it.await() } }
            // a real call that was cancelled does not return an answer
            currentCoroutineContext().ensureActive()
            tagError?.let { throw it }
            return tags[uid]
        }
        override suspend fun load(printerId: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
            loads += spoolId to dryRun
            if (dryRun) {
                dryGates[spoolId]?.let { withContext(NonCancellable) { it.await() } }
                dryErrors[spoolId]?.let { throw it }
            }
            else {
                writeGate?.await()
                writeError?.let { throw it }
            }
            // the spool's number rides in the nozzle size, to tell whose answer this is
            return LoadResult(slot = LoadSlot(label, 0, 0), nozzleMm = spoolId.toDouble(), confirmed = !dryRun)
        }
    }

    private val fake = Fake()
    private val gate = LoadGate()
    private fun vm() = PickSpoolViewModel(fake, "ABC123", "A4", gate)
    private fun spoolJson(id: Int) = buildJsonObject {
        put("id", id)
        put("filament", buildJsonObject { put("name", "PolyTerra $id") })
    }
    private fun spool(id: Int) = SpoolSummary(id, "Example", "PolyTerra $id", "PLA", "2B2B2E", null, 620.0)

    @Test fun pickingAsksTheHubForADryRunThenLoadsForReal() = runTest(dispatcher) {
        val v = vm()
        v.pick(spool(1)); runCurrent()
        assertEquals(1.0, v.state.value.preview!!.result!!.nozzleMm!!, 0.0)
        v.confirm(); runCurrent()
        assertEquals(listOf(1 to true, 1 to false), fake.loads)
        assertNull(v.state.value.preview)
        assertEquals(true, v.state.value.loaded)
    }

    @Test fun aTagTapPicksThePreviewOfItsSpool() = runTest(dispatcher) {
        fake.tags["4:77:90:e"] = spoolJson(7)
        val v = vm()
        v.onTag("4:77:90:e"); runCurrent()
        assertEquals(7, v.state.value.preview!!.spool.id)
        assertEquals(listOf(7 to true), fake.loads)
        assertEquals(7.0, v.state.value.preview!!.result!!.nozzleMm!!, 0.0)
    }

    @Test fun aTagLinkedToNoSpoolPicksNothingAndSaysSo() = runTest(dispatcher) {
        val v = vm()
        v.onTag("4:77:90:f"); runCurrent()
        assertNull(v.state.value.preview)
        assertEquals("4:77:90:f", v.state.value.unlinkedTag)
        assertTrue(fake.loads.isEmpty())
        fake.tags["4:77:90:e"] = spoolJson(7)
        v.onTag("4:77:90:e"); runCurrent()
        assertNull("the next tap clears the message", v.state.value.unlinkedTag)
    }

    @Test fun aTagTapThatCannotReachTheHubShowsTheProblem() = runTest(dispatcher) {
        fake.tagError = ApiError(0, "offline", "x")
        val v = vm()
        v.onTag("4:77:90:e"); runCurrent()
        assertNull(v.state.value.preview)
        assertEquals(Problem.Unreachable, v.state.value.problem)
    }

    @Test fun aTagTapWhileTheLoadIsWrittenIsHeldAndTheLastTapWins() = runTest(dispatcher) {
        fake.tags["4:77:90:e"] = spoolJson(7)
        fake.writeGate = CompletableDeferred()
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        v.onTag("4:77:90:e"); runCurrent()
        v.onTag("4:77:90:f"); runCurrent()
        assertEquals(1, v.state.value.preview!!.spool.id)
        assertEquals("no lookup while the load is written", listOf(1 to true, 1 to false), fake.loads)
        assertEquals("4:77:90:f", v.state.value.heldTag)
        assertEquals("each tap says it is waiting", 2, v.state.value.tagWaits)
        assertNull("no message appears over the load being written", v.state.value.unlinkedTag)
    }

    @Test fun aHeldTagIsReadWhenTheLoadIsRefused() = runTest(dispatcher) {
        fake.tags["4:77:90:e"] = spoolJson(7)
        val open = CompletableDeferred<Unit>()
        fake.writeGate = open
        fake.writeError = ApiError(409, "printer_busy", "The printer is printing.")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        v.onTag("4:77:90:e"); runCurrent()
        open.complete(Unit); runCurrent()
        assertNull("used once", v.state.value.heldTag)
        assertEquals("the tag's spool is picked as on any other tap", 7, v.state.value.preview!!.spool.id)
    }

    @Test fun aHeldTagIsLetGoWhenTheAnswerToTheLoadWasLost() = runTest(dispatcher) {
        fake.tags["4:77:90:e"] = spoolJson(7)
        val open = CompletableDeferred<Unit>()
        fake.writeGate = open
        fake.writeError = ApiError(0, "offline", "x")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        v.onTag("4:77:90:e"); runCurrent()
        open.complete(Unit); runCurrent()
        assertNull(v.state.value.heldTag)
        assertEquals("the unknown load stays on screen", 1, v.state.value.preview!!.spool.id)
        assertTrue(v.state.value.preview!!.dropped)
    }

    @Test fun aSlowTagLookupDoesNotReplaceALaterRowTap() = runTest(dispatcher) {
        fake.tags["4:77:90:e"] = spoolJson(7)
        val slow = CompletableDeferred<Unit>()
        fake.tagGates["4:77:90:e"] = slow
        val v = vm()
        v.onTag("4:77:90:e"); runCurrent()
        v.pick(spool(2)); runCurrent()
        slow.complete(Unit); runCurrent()
        assertEquals(2, v.state.value.preview!!.spool.id)
        assertEquals(listOf(2 to true), fake.loads)
    }

    @Test fun aBadGatewayPageInAnswerToTheLoadIsUnknownToo() = runTest(dispatcher) {
        fake.writeError = ApiError(502, "bad_response", "Bad Gateway")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        assertTrue("not the Hub speaking: nobody knows if it worked", v.state.value.preview!!.dropped)
        assertEquals(Say.Words(R.string.spool_load_dropped), v.state.value.preview!!.problem)
    }

    @Test fun theLoadGateIsHeldWhileTheLoadIsWritten() = runTest(dispatcher) {
        val open = CompletableDeferred<Unit>()
        fake.writeGate = open
        val v = vm()
        v.pick(spool(1)); runCurrent()
        assertFalse("the dry run is not a write", gate.writing.value)
        v.confirm(); runCurrent()
        assertTrue(gate.writing.value)
        open.complete(Unit); runCurrent()
        assertFalse(gate.writing.value)
    }

    @Test fun theLoadGateIsReleasedWhenTheLoadFails() = runTest(dispatcher) {
        fake.writeError = ApiError(409, "printer_busy", "The printer is printing.")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        assertFalse(gate.writing.value)
        assertFalse("a printer's own refusal is a known answer", v.state.value.preview!!.dropped)
    }

    @Test fun aLostAnswerToTheLoadIsUnknownAndLoadIsNotOfferedAgain() = runTest(dispatcher) {
        fake.writeError = ApiError(0, "offline", "x")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        assertTrue(v.state.value.preview!!.dropped)
        assertEquals(Say.Words(R.string.spool_load_dropped), v.state.value.preview!!.problem)
        v.confirm(); runCurrent()
        assertEquals("Load does nothing once the answer is unknown", listOf(1 to true, 1 to false), fake.loads)
    }

    @Test fun anUnreadableAnswerToTheLoadIsUnknownToo() = runTest(dispatcher) {
        fake.writeError = IllegalStateException("not json")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        assertTrue(v.state.value.preview!!.dropped)
        assertEquals(Say.Words(R.string.spool_load_dropped), v.state.value.preview!!.problem)
    }

    @Test fun aRefusedPairingIsKnownSoLoadStaysOffered() = runTest(dispatcher) {
        fake.writeError = ApiError(401, "unauthorized", "x")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        assertFalse(v.state.value.preview!!.dropped)
    }

    @Test fun backIsBlockedWhileTheLoadIsWritten() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        fake.writeGate = gate
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        assertTrue(v.writing)
        v.back()
        assertNotNull("Back does nothing while the load is being written", v.state.value.preview)
        assertTrue(v.state.value.preview!!.writing)
        gate.complete(Unit); runCurrent()
        assertFalse(v.writing)
    }

    @Test fun backLeavesThePreviewWhenNothingIsBeingWritten() = runTest(dispatcher) {
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.back()
        assertNull(v.state.value.preview)
    }

    @Test fun aLateDryRunOfAnEarlierPickIsIgnored() = runTest(dispatcher) {
        val late = CompletableDeferred<Unit>()
        fake.dryGates[1] = late
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.pick(spool(2)); runCurrent()
        assertEquals(2, v.state.value.preview!!.spool.id)
        assertEquals(2.0, v.state.value.preview!!.result!!.nozzleMm!!, 0.0)
        late.complete(Unit); runCurrent()
        assertEquals("the earlier pick's answer is not shown for this spool", 2, v.state.value.preview!!.spool.id)
        assertEquals(2.0, v.state.value.preview!!.result!!.nozzleMm!!, 0.0)
    }

    @Test fun aLateErrorOfAnEarlierPickIsIgnoredToo() = runTest(dispatcher) {
        val late = CompletableDeferred<Unit>()
        fake.dryGates[1] = late
        fake.dryErrors[1] = ApiError(0, "offline", "x")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        // the second pick is for another spool whose dry run is still out when the first one's error arrives
        fake.dryGates[2] = CompletableDeferred()
        v.pick(spool(2)); runCurrent()
        late.complete(Unit); runCurrent()
        assertEquals(2, v.state.value.preview!!.spool.id)
        assertNull(v.state.value.preview!!.result)
        assertNull("the earlier pick's error is not shown for this spool", v.state.value.preview!!.problem)
    }

    @Test fun aRefusedLoadStaysAndNamesTheCause() = runTest(dispatcher) {
        fake.writeError = ApiError(401, "unauthorized", "x")
        val v = vm()
        v.pick(spool(1)); runCurrent()
        v.confirm(); runCurrent()
        assertEquals(Say.Words(R.string.spool_load_pairing_refused), v.state.value.preview!!.problem)
        assertFalse(v.writing)
        fake.writeError = ApiError(0, "offline", "x")
        v.confirm(); runCurrent()
        assertEquals(Say.Words(R.string.spool_load_dropped), v.state.value.preview!!.problem)
    }
}

/** The pure rules and small helpers of the S4.11 rework. */
class PrinterReworkRulesTest {
    @Test fun settingsOverPairingOnlyWhenOpenedFromAPairingStepBelow() {
        assertTrue(settingsOverPairing(inPairing = false, tab = Tab.Settings, pairGraphOnStack = true))
        assertFalse("no pairing below: ordinary Settings", settingsOverPairing(false, Tab.Settings, false))
        assertFalse("another tab", settingsOverPairing(false, Tab.Printers, true))
        assertFalse("the pairing graph itself", settingsOverPairing(true, Tab.Settings, true))
        assertFalse(settingsOverPairing(false, null, true))
    }

    @Test fun theAccessCodeRowSaysNotSetUntilThePrinterHasOne() {
        val p = Printer(id = "A", name = "Workshop X1", serial = "A", configured = true)
        assertEquals(R.string.status_set, accessCodeValue(p))
        assertEquals(R.string.status_not_set, accessCodeValue(p.copy(configured = false)))
    }
}

/** The top bar's title on the printer routes, and the full-screen camera's orientation lock, in a real activity. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class PrinterShellPartsTest {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    private lateinit var nav: NavHostController

    private fun host() {
        rule.setContent {
            nav = rememberNavController()
            val entry by nav.currentBackStackEntryAsState()
            NavHost(nav, startDestination = PrinterRoute("A1")) {
                composable<PrintersRoute> { Text("list") }
                composable<PrinterRoute> { Text("title:" + (printerPlaceTitle(entry?.destination, entry) ?: "none")) }
                composable<PrinterSettingsRoute> { Text("title:" + (printerPlaceTitle(entry?.destination, entry) ?: "none")) }
                composable<PrinterMapRoute> { Text("title:" + (printerPlaceTitle(entry?.destination, entry) ?: "none")) }
                composable<PrinterPickRoute> { Text("title:" + (printerPlaceTitle(entry?.destination, entry) ?: "none")) }
            }
        }
        rule.waitForIdle()
    }

    private fun title() = rule.onNode(hasText("title:", substring = true))

    @Test fun aPrintersScreenIsTitledByItsNameOnceKnown() {
        host()
        title().assertTextEquals("title:none")
        rule.runOnIdle { PrinterTitles.known("A1", "Workshop X1") }
        rule.waitForIdle()
        title().assertTextEquals("title:Workshop X1")
    }

    @Test fun settingsAndMapHaveTheirOwnTitlesAndPickKeepsTheShellsTitle() {
        host()
        rule.runOnUiThread { nav.navigate(PrinterSettingsRoute("A1")) }
        rule.waitForIdle()
        title().assertTextEquals("title:" + rule.activity.getString(R.string.printer_settings_title))
        rule.runOnUiThread { nav.navigate(PrinterMapRoute("A1")) }
        rule.waitForIdle()
        title().assertTextEquals("title:" + rule.activity.getString(R.string.printers_map_loading))
        rule.runOnUiThread { nav.navigate(PrinterPickRoute("A1", "A4")) }
        rule.waitForIdle()
        title().assertTextEquals("title:none")
    }

    @Test fun theFullScreenCameraLocksLandscapeAndGivesTheOrientationBack() {
        var shown by mutableStateOf(false)
        rule.setContent { if (shown) Landscape() }
        val before = rule.activity.requestedOrientation
        rule.runOnUiThread { shown = true }
        rule.waitForIdle()
        assertEquals(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE, rule.activity.requestedOrientation)
        rule.runOnUiThread { shown = false }
        rule.waitForIdle()
        assertEquals("closing gives it back", before, rule.activity.requestedOrientation)
    }

    @Test fun backWhileAWriteIsOutShowsTheSnackbarAndDoesNotLeave() {
        var busy by mutableStateOf(true)
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                val toast = remember { SwToastState() }
                CompositionLocalProvider(LocalToast provides toast) {
                    Box {
                        BusyBack(busy, rememberBusySay())
                        SwToastHost(toast)
                    }
                }
            }
        }
        rule.runOnUiThread { rule.activity.onBackPressedDispatcher.onBackPressed() }
        rule.waitForIdle()
        rule.onNodeWithText(rule.activity.getString(R.string.common_busy_wait)).assertExists()
        assertFalse("Back was taken by the busy screen", rule.activity.isFinishing)
    }

    @Test fun backWhenNothingIsBusyIsNotTaken() {
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) { BusyBack(false) { throw AssertionError("not busy") } }
        }
        rule.runOnUiThread { rule.activity.onBackPressedDispatcher.onBackPressed() }
        rule.waitForIdle()
    }
}

/** The pick screen's wiring of tag taps (05-android-app 2.6, 9.6), in a real activity. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class PickSpoolScreenTapsTest {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    private class Backend : PickBackend {
        val linked = buildJsonObject {
            put("id", 7)
            put("filament", buildJsonObject { put("name", "PolyTerra 7") })
        }
        var writeGate: CompletableDeferred<Unit>? = null
        override suspend fun search(query: String, sealedOnly: Boolean): List<JsonObject> = emptyList()
        override suspend fun tag(uid: String): JsonObject? = if (uid == "04:aa") linked else null
        override suspend fun load(printerId: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
            if (!dryRun) writeGate?.await()
            return LoadResult(slot = LoadSlot(label, 0, 0), nozzleMm = 0.4, confirmed = !dryRun)
        }
    }

    private val backend = Backend()
    private val opened = mutableListOf<String>()
    private val loaded = mutableListOf<Boolean>()

    private fun show(): PickSpoolViewModel {
        val vm = PickSpoolViewModel(backend, "ABC123", "A4", LoadGate())
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                val toast = remember { SwToastState() }
                CompositionLocalProvider(LocalToast provides toast) {
                    Box {
                        PickSpoolScreen(
                            vm, "Workshop X1", "A4", onLoaded = { loaded += it }, onPairAgain = {}, onOpenTag = { opened += it },
                        )
                        SwToastHost(toast)
                    }
                }
            }
        }
        rule.waitForIdle()
        return vm
    }

    private fun text(id: Int) = rule.activity.getString(id)

    @Test fun aTagTapOnTheScreenPicksItsSpool() {
        val vm = show()
        TagEvents.emit("04:aa")
        rule.waitForIdle()
        assertEquals(7, vm.state.value.preview!!.spool.id)
    }

    @Test fun aTapOfAnUnlinkedTagSaysSoEvenWithThePreviewOpen() {
        val vm = show()
        TagEvents.emit("04:bb")
        rule.waitForIdle()
        rule.onNodeWithText(text(R.string.printer_pick_tag_unlinked)).assertExists()
        TagEvents.emit("04:aa")
        rule.waitForIdle()
        assertNull("the preview of the linked tag is open", vm.state.value.unlinkedTag)
        TagEvents.emit("04:bb")
        rule.waitForIdle()
        assertEquals("04:bb", vm.state.value.unlinkedTag)
        assertNotNull(vm.state.value.preview)
        // the dialog and the page both carry it: one of the two is behind the dialog's scrim
        assertEquals(2, rule.onAllNodesWithText(text(R.string.printer_pick_tag_unlinked), useUnmergedTree = true).fetchSemanticsNodes().size)
    }

    @Test fun aTapDuringTheWriteSaysItWaitsAndOpensWhenTheLoadEnds() {
        val open = CompletableDeferred<Unit>()
        backend.writeGate = open
        val vm = show()
        vm.pick(SpoolSummary(1, "Example", "PolyTerra 1", "PLA", "2B2B2E", null, 620.0))
        rule.waitForIdle()
        vm.confirm()
        rule.waitForIdle()
        TagEvents.emit("04:cc")
        rule.waitForIdle()
        rule.onNodeWithText(text(R.string.tag_read_wait)).assertExists()
        assertTrue("nothing opens while the load is written", opened.isEmpty())
        open.complete(Unit)
        rule.waitForIdle()
        assertEquals(listOf(true), loaded)
        assertEquals(listOf("04:cc"), opened)
    }
}

/** A tap handed on to a screen that is not listening yet. */
@OptIn(ExperimentalCoroutinesApi::class)
class TagEventsHandOnTest {
    @Test fun aHandedOnTapReachesTheNextListener() = runTest {
        val got = mutableListOf<String>()
        TagEvents.emitWhenListening("04:dd", this)
        runCurrent()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { TagEvents.taps.collect { got += it } }
        runCurrent()
        assertEquals(listOf("04:dd"), got)
    }

    @Test fun aHandedOnTapComesAnywayWhenNobodyListens() = runTest {
        val got = mutableListOf<String>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { TagEvents.taps.collect { got += it } }
        runCurrent()
        // the old listener never leaves: the wait is over after its time
        TagEvents.emitWhenListening("04:ee", this, waitMs = 500)
        advanceTimeBy(600); runCurrent()
        assertEquals(listOf("04:ee"), got)
    }
}

/** The load gate comes from the app's activity; there is no private one. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class LoadGateSourceTest {
    @Test fun withoutTheAppsActivityTheGateIsAnError() {
        val context = androidx.test.core.app.ApplicationProvider.getApplicationContext<android.content.Context>()
        val e = runCatching { context.appLoadGate() }.exceptionOrNull()
        assertTrue(e is IllegalStateException)
    }
}
