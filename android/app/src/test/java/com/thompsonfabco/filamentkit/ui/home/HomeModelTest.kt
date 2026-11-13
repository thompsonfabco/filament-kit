package com.thompsonfabco.filamentkit.ui.home

import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterSummary
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.update.UpdateUi
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class HomeModelTest {
    private val noon = 1_700_000_000_000L
    private val midnight = noon - 12 * 3_600_000L

    @Test fun draftAgeIsSecondsThenMinutesThenHours() {
        assertEquals(DraftAge.Seconds(0), draftAge(noon, noon, midnight))
        assertEquals(DraftAge.Seconds(59), draftAge(noon - 59_999, noon, midnight))
        assertEquals(DraftAge.Minutes(3), draftAge(noon - 3 * 60_000, noon, midnight))
        assertEquals(DraftAge.Minutes(59), draftAge(noon - 3_599_000, noon, midnight))
        assertEquals(DraftAge.Hours(2), draftAge(noon - 2 * 3_600_000, noon, midnight))
    }

    @Test fun aDraftFromTheDayBeforeIsYesterdayAndOlderIsADate() {
        assertEquals(DraftAge.Yesterday, draftAge(midnight - 1, noon, midnight))
        assertEquals(DraftAge.Yesterday, draftAge(midnight - 24 * 3_600_000L, noon, midnight))
        assertEquals(DraftAge.Older, draftAge(midnight - 24 * 3_600_000L - 1, noon, midnight))
    }

    @Test fun justPastMidnightStillReadsAsSecondsOrMinutes() {
        val now = midnight + 10_000
        assertEquals(DraftAge.Seconds(40), draftAge(midnight - 30_000, now, midnight))
    }

    @Test fun aClockSetBackReadsAsZeroSeconds() {
        assertEquals(DraftAge.Seconds(0), draftAge(noon + 5_000, noon, midnight))
    }

    private fun draft(photos: Int = 2, hint: String = "", tag: String? = null) = Draft(
        id = "d", photos = List(photos) { File("p$it.jpg") }, hint = hint, tag = tag, weightGrams = null, sealed = false,
        readResult = null, editedItems = null, created = noon,
    )

    @Test fun aDraftLineHasOnlyTheNoteAndTagThatExist() {
        val full = draftParts(draft(2, " 3 of the grey ones ", "04A1"))
        assertEquals(2, full.photos)
        assertEquals("3 of the grey ones", full.note)
        assertEquals("04A1", full.tag)
        val bare = draftParts(draft(1, "  ", " "))
        assertNull(bare.note)
        assertNull(bare.tag)
    }

    private fun printer(
        state: String = Printer.STATE_CONNECTED, configured: Boolean = true, gcode: String? = null,
        percent: Int = 0, left: Int = 0,
    ) = Printer(
        id = "P", name = "Workshop X1", serial = "P", configured = configured, state = state,
        summary = gcode?.let { PrinterSummary(it, percent, left, "Benchy") },
    )

    @Test fun aPrinterIsPrintingIdleOfflineOrNeedsALook() {
        assertEquals(HomePrinterStatus.Printing, homePrinterStatus(printer(gcode = "RUNNING", percent = 42)))
        assertEquals(HomePrinterStatus.Idle, homePrinterStatus(printer(gcode = "IDLE")))
        assertEquals(HomePrinterStatus.Idle, homePrinterStatus(printer()))
        assertEquals(HomePrinterStatus.Offline, homePrinterStatus(printer(state = Printer.STATE_OFFLINE)))
        assertEquals(HomePrinterStatus.NeedsLook, homePrinterStatus(printer(state = Printer.STATE_WRONG_CODE)))
        assertEquals(HomePrinterStatus.NeedsLook, homePrinterStatus(printer(state = "cert_changed")))
        assertEquals(HomePrinterStatus.NotConfigured, homePrinterStatus(printer(configured = false)))
        assertEquals(HomePrinterStatus.NotConfigured, homePrinterStatus(printer(state = Printer.STATE_NOT_CONFIGURED)))
    }

    @Test fun theJobIsPercentAndTimeLeftAndOnlyWhilePrinting() {
        val job = printerJob(printer(gcode = "RUNNING", percent = 42, left = 72))!!
        assertEquals(42, job.percent)
        assertEquals(1, job.hours)
        assertEquals(12, job.minutes)
        assertNull(printerJob(printer(gcode = "IDLE", percent = 100)))
        assertNull(printerJob(printer()))
        assertEquals(0, printerJob(printer(gcode = "RUNNING", percent = 150, left = -3))!!.let { it.hours + it.minutes })
        assertEquals(100, printerJob(printer(gcode = "RUNNING", percent = 150))!!.percent)
    }

    @Test fun atMostFourPrinterRowsThenTheRestAreCounted() {
        val seven = List(7) { printer() }
        assertEquals(4, printerRows(seven).shown.size)
        assertEquals(3, printerRows(seven).more)
        assertEquals(0, printerRows(seven.take(4)).more)
        assertEquals(2, printerRows(seven.take(2)).shown.size)
        assertEquals(0, printerRows(emptyList()).more)
    }

    @Test fun theUpdateNoticeIsOfferedForAnUpdateAHubNewerThanTheAppOrADownloadWaiting() {
        assertNull(updateNotice(UpdateUi()))
        assertEquals(UpdateNoticeKind.Ready, updateNotice(UpdateUi(available = 3)))
        assertEquals(UpdateNoticeKind.Downloaded, updateNotice(UpdateUi(available = 3, confirmPending = true)))
        assertEquals(UpdateNoticeKind.Downloaded, updateNotice(UpdateUi(confirmPending = true)))
        assertEquals(UpdateNoticeKind.HubNewer, updateNotice(UpdateUi(serverTooNew = true)))
        assertEquals(UpdateNoticeKind.HubNewer, updateNotice(UpdateUi(available = 3, serverTooNew = true)))
    }

    @Test fun startOfDayIsLocalMidnightInTheGivenZone() {
        val zone = java.time.ZoneId.of("America/New_York")
        val at = java.time.ZonedDateTime.of(2026, 11, 13, 23, 30, 0, 0, zone).toInstant().toEpochMilli()
        val midnightNy = java.time.ZonedDateTime.of(2026, 11, 13, 0, 0, 0, 0, zone).toInstant().toEpochMilli()
        assertEquals(midnightNy, startOfDay(at, zone))
        // an hour later it is the next local day
        assertEquals(midnightNy + 24 * 3_600_000L, startOfDay(at + 3_600_000L, zone))
        // the day of a daylight-saving change is 25 hours long
        val change = java.time.ZonedDateTime.of(2026, 11, 1, 12, 0, 0, 0, zone).toInstant().toEpochMilli()
        val dayStart = java.time.ZonedDateTime.of(2026, 11, 1, 0, 0, 0, 0, zone).toInstant().toEpochMilli()
        assertEquals(dayStart, startOfDay(change, zone))
    }

    @Test fun onlyAnExplicitNoFromTheHubMeansTheLabelReaderIsOff() {
        assertFalse("unknown", labelReaderOff(null))
        assertTrue(labelReaderOff(ServerInfo("W", "1.0", 1, modules = listOf("spoolman"))))
        assertFalse(labelReaderOff(ServerInfo("W", "1.0", 1, modules = listOf("ai_intake"))))
        assertFalse("an older server reads labels", labelReaderOff(ServerInfo("W", "0.1.0", 1)))
    }

    @Test fun thePrintersFeatureIsOnUnlessTheHubListsModulesWithoutPrinters() {
        fun info(modules: List<String>?) = ServerInfo(name = "Hub", version = "1.0", api = 1, modules = modules)
        assertTrue(info(null).printersOn)
        assertTrue(info(listOf("spoolman", "printers")).printersOn)
        assertTrue(info(listOf("klipper")).printersOn)
        assertFalse(info(listOf("spoolman", "ai_intake")).printersOn)
        assertFalse(info(emptyList()).printersOn)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class HomePrintersViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    private val one = Printer(id = "A", name = "Workshop X1", serial = "A", configured = true, state = Printer.STATE_CONNECTED)

    @Test fun beforeTheFirstAnswerThereAreNoPrinters() {
        val vm = HomePrintersViewModel({ listOf(one) })
        assertNull(vm.state.value.printers)
        assertFalse(vm.state.value.loading)
    }

    @Test fun refreshLoadsThePrintersAndNotesWhen() {
        val vm = HomePrintersViewModel({ listOf(one) }, now = { 1234L })
        vm.refresh()
        assertTrue(vm.state.value.loading)
        dispatcher.scheduler.runCurrent()
        assertEquals(listOf(one), vm.state.value.printers)
        assertEquals(1234L, vm.state.value.loadedAt)
        assertFalse(vm.state.value.loading)
        assertFalse(vm.state.value.failed)
    }

    @Test fun aSecondRefreshWhileOneRunsIsDropped() {
        var calls = 0
        val gate = CompletableDeferred<List<Printer>>()
        val vm = HomePrintersViewModel({ calls++; gate.await() })
        vm.refresh()
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertEquals(1, calls)
        gate.complete(listOf(one))
        dispatcher.scheduler.runCurrent()
        assertEquals(listOf(one), vm.state.value.printers)
    }

    @Test fun aFailedReadKeepsTheRowsAlreadyShown() {
        var fail = false
        val vm = HomePrintersViewModel({ if (fail) throw ApiError(0, "offline", "no route") else listOf(one) }, now = { 7L })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        fail = true
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertEquals(listOf(one), vm.state.value.printers)
        assertEquals(7L, vm.state.value.loadedAt)
        assertTrue(vm.state.value.failed)
        assertNull("no route: the screen uses the catalogue's words", vm.state.value.message)
        assertFalse(vm.state.value.loading)
    }

    @Test fun noRouteIsNotAnUnexpectedAnswerButAnUnreadableOneIs() {
        var boom: Exception = java.io.IOException("timeout")
        val vm = HomePrintersViewModel({ throw boom })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.failed)
        assertFalse(vm.state.value.unexpected)
        boom = IllegalStateException("not json")
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.unexpected)
        assertNull(vm.state.value.message)
    }

    // the shapes `Api` really throws (net/Api.kt)
    @Test fun noRouteIsStatusZero() {
        val f = printersFailure(ApiError(0, "offline", "Could not reach the server"))
        assertNull(f.message)
        assertFalse(f.unexpected)
        assertFalse(printersFailure(ApiError(0, "local_network", "Allow local network access")).unexpected)
    }

    @Test fun aReplyTheAppCouldNotReadIsBadResponse() {
        assertTrue(printersFailure(ApiError(200, "bad_response", "The server did not return the printer")).unexpected)
        assertTrue(printersFailure(ApiError(200, "bad_response", "The server sent a reply the app could not read")).unexpected)
    }

    @Test fun aBadGatewayPageWithoutAHubMessageIsNotTheHubSpeaking() {
        val f = printersFailure(ApiError(502, "internal", "The server returned an error (502)"))
        assertNull(f.message)
        assertTrue(f.unexpected)
    }

    @Test fun aRefusalWithTheHubsOwnMessageKeepsIt() {
        val f = printersFailure(ApiError(400, "bad_request", "The printers service is restarting."))
        assertEquals("The printers service is restarting.", f.message)
        assertFalse(f.unexpected)
    }

    @Test fun theViewModelUsesThatClassification() {
        var boom: Exception = ApiError(502, "internal", "The server returned an error (502)")
        val vm = HomePrintersViewModel({ throw boom })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.unexpected)
        assertNull(vm.state.value.message)
        boom = ApiError(0, "offline", "Could not reach the server")
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertFalse(vm.state.value.unexpected)
        assertNull(vm.state.value.message)
        assertTrue(vm.state.value.failed)
    }

    @Test fun theHubsOwnRefusalIsKept() {
        val vm = HomePrintersViewModel({ throw ApiError(503, "unavailable", "The printers service is restarting.") })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.failed)
        assertEquals("The printers service is restarting.", vm.state.value.message)
        assertNull(vm.state.value.printers)
    }

    @Test fun aLaterGoodReadClearsTheFailure() {
        var fail = true
        val vm = HomePrintersViewModel({ if (fail) throw ApiError(0, "offline", "no route") else listOf(one) })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.failed)
        fail = false
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertFalse(vm.state.value.failed)
        assertEquals(listOf(one), vm.state.value.printers)
    }
}
