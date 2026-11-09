package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.MapSlot
import com.thompsonfabco.filamentkit.net.MapStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SlotMapHelpTest {
    private val fourSlots = listOf("A1", "A2", "A3", "A4").map { MapSlot(label = it) }
    private val note = "the loaded slots are numbered alike under shift8, legacy: the numbering of further " +
        "AMS units is settled when one is added (the map is made again then)"

    // ---- the states ----

    @Test fun noMapYetSaysNothing() {
        val v = SlotMapHelp.view(MapStatus(state = "none"))
        assertEquals(SlotMapOutcome.NONE, v.outcome)
        assertNull(v.headline)
        assertNull(v.detail)
    }

    @Test fun noStatusLoadedYetSaysNothing() {
        assertEquals(SlotMapOutcome.NONE, SlotMapHelp.view(null).outcome)
    }

    @Test fun runningShowsTheServersStep() {
        val v = SlotMapHelp.view(MapStatus(state = "running", step = "Testing A2"))
        assertEquals(SlotMapOutcome.RUNNING, v.outcome)
        assertEquals("Testing A2", v.headline)
        assertFalse(v.headlineIsError)
    }

    @Test fun runningWithoutAStepStillSaysSomething() {
        assertEquals("Mapping slots…", SlotMapHelp.view(MapStatus(state = "running")).headline)
    }

    @Test fun confirmedCountsTheSlots() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots))
        assertEquals(SlotMapOutcome.CONFIRMED, v.outcome)
        assertEquals("Slots mapped (4)", v.headline)
        assertEquals("The slot numbering is confirmed.", v.detail)
        assertFalse(v.headlineIsError)
        assertNull(v.problemsHeading)
    }

    @Test fun partialSaysWhatIsConfirmedAndWhatPinsDownTheScheme() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots, notes = listOf(note)))
        assertEquals(SlotMapOutcome.PARTIAL, v.outcome)
        assertEquals("Slots mapped: confirmed for the loaded slots", v.headline)
        assertEquals("The numbering scheme is settled by mapping again once a second unit or an HT has a spool loaded.",
            v.detail)
        assertFalse(v.headlineIsError)
    }

    @Test fun theServersFlagDecidesPartialOverTheNote() {
        val flagged = MapStatus(state = "done", calibrated = true, schemeUnsettled = true)
        assertEquals(SlotMapOutcome.PARTIAL, SlotMapHelp.view(flagged).outcome)
        val otherNote = MapStatus(state = "done", calibrated = true, slots = fourSlots, schemeUnsettled = false,
            notes = listOf("some other remark"))
        val v = SlotMapHelp.view(otherNote)
        assertEquals(SlotMapOutcome.CONFIRMED, v.outcome)
        assertEquals("the note is still shown", listOf("Some other remark"), v.notes)
    }

    @Test fun anOlderServersNoteStillMeansPartial() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, schemeUnsettled = null, notes = listOf(note)))
        assertEquals(SlotMapOutcome.PARTIAL, v.outcome)
    }

    // ---- a map the server no longer trusts ----

    private val remap = "A new mapping starts by itself when the printer is idle. If it does not, tap Map slots again."

    @Test fun aChangedLayoutIsNotConfirmed() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots, stale = true))
        assertEquals(SlotMapOutcome.STALE, v.outcome)
        assertEquals("Layout changed: the map will be made again", v.headline)
        assertEquals(remap, v.detail)
        assertFalse(v.headlineIsError)
    }

    @Test fun printsThatDisagreeWithTheMapAreNotConfirmed() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots, suspect = true))
        assertEquals(SlotMapOutcome.SUSPECT, v.outcome)
        assertEquals("Recent prints disagreed with the map: map again", v.headline)
        assertEquals(remap, v.detail)
        assertTrue(v.headlineIsError)
    }

    @Test fun staleOrSuspectIsNeverConfirmedInAnyResult() {
        for (state in listOf("none", "done", "failed", "running")) for (notes in listOf(emptyList(), listOf(note))) {
            for ((stale, suspect) in listOf(true to false, false to true, true to true)) {
                val m = MapStatus(state = state, calibrated = true, stale = stale, suspect = suspect, notes = notes,
                    schemeUnsettled = notes.isNotEmpty())
                val o = SlotMapHelp.view(m).outcome
                assertTrue("$m gave $o", o != SlotMapOutcome.CONFIRMED && o != SlotMapOutcome.PARTIAL)
            }
        }
    }

    @Test fun aStaleMapComesBeforeASuspectOne() {
        val m = MapStatus(state = "done", calibrated = true, stale = true, suspect = true)
        assertEquals(SlotMapOutcome.STALE, SlotMapHelp.view(m).outcome)
    }

    @Test fun aRemapUnderWaySaysSoEvenOnAStaleMap() {
        val v = SlotMapHelp.view(MapStatus(state = "running", step = "Testing A2", calibrated = true, stale = true))
        assertEquals(SlotMapOutcome.RUNNING, v.outcome)
        assertEquals("Testing A2", v.headline)
    }

    @Test fun aFailedRemapOfAStaleMapStaysFailed() {
        val v = SlotMapHelp.view(MapStatus(state = "failed", stale = true, problems = listOf("x")))
        assertEquals(SlotMapOutcome.FAILED, v.outcome)
        assertTrue(v.problemsAreError)
    }

    @Test fun aStaleMapSeenWithNoJobResultStillSaysSo() {
        val v = SlotMapHelp.view(MapStatus(state = "none", calibrated = true, stale = true))
        assertEquals(SlotMapOutcome.STALE, v.outcome)
    }

    @Test fun leftoversOfAGoodMapStayCalmOnceItIsSuspect() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, suspect = true, problems = listOf("x")))
        assertEquals("Also reported during mapping:", v.problemsHeading)
        assertFalse(v.problemsAreError)
    }

    @Test fun anUnprovenMapThatWentStaleKeepsItsProblemsRed() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = false, stale = true, problems = listOf("x")))
        assertEquals(SlotMapOutcome.STALE, v.outcome)
        assertEquals("Problems the server reported:", v.problemsHeading)
        assertTrue(v.problemsAreError)
    }

    @Test fun neitherStaleNorSuspectGreysTheButton() {
        for (m in listOf(MapStatus(state = "done", stale = true), MapStatus(state = "done", suspect = true))) {
            assertTrue("$m", ToolsUiState(map = m).mapEnabled(canStart = true))
        }
    }

    @Test fun partialSaysTheSchemeOnceInPlainWords() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, notes = listOf(note)))
        assertTrue(v.detail!!, "second unit" in v.detail!!)
        assertNull("the server's note says the same", v.notesHeading)
        assertTrue(v.notes.isEmpty())
        assertNull("a note is not a problem", v.problemsHeading)
    }

    @Test fun partialStillShowsAnyOtherNote() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, schemeUnsettled = true,
            notes = listOf(note, "some other remark")))
        assertEquals("Not settled yet:", v.notesHeading)
        assertEquals(listOf("Some other remark"), v.notes)
    }

    /** The X2D report: this used to read "Slot mapping finished" with a list of failures under it. */
    @Test fun doneButNotCalibratedIsNeverCalledFinished() {
        val problems = listOf(
            "the calibration job ended as FAILED on the printer",
            "slot numbering not confirmed: filament use is only logged until mapping succeeds",
        )
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = false, observe = true, problems = problems))
        assertEquals(SlotMapOutcome.NOT_CONFIRMED, v.outcome)
        assertEquals("Slot numbering not confirmed", v.headline)
        assertEquals("The calibration did not prove how this printer numbers its slots. " +
            "Tap Map slots again when the printer is idle.", v.detail)
        assertTrue(v.headlineIsError)
        assertEquals("Problems the server reported:", v.problemsHeading)
        assertEquals("the only-logged line is the notice's", listOf("The calibration job ended as FAILED on the printer"), v.problems)
        assertTrue(v.problemsAreError)
    }

    @Test fun nothingButTheOnlyLoggedLineLeavesNoProblemsHeading() {
        val v = SlotMapHelp.view(MapStatus(state = "done", observe = true,
            problems = listOf("slot numbering not confirmed: filament use is only logged until mapping succeeds")))
        assertNull(v.problemsHeading)
        assertTrue(v.problems.isEmpty())
        assertFalse(v.problemsAreError)
    }

    @Test fun aServerCodeKeepsItsSpellingAndPlainWordsGetACapital() {
        val v = SlotMapHelp.view(MapStatus(state = "failed", problems = listOf("printer_busy: x", "error: y", "Ext-L is empty")))
        assertEquals(listOf("printer_busy: x", "Error: y", "Ext-L is empty"), v.problems)
    }

    @Test fun aFailedMappingSaysWhatToDoNext() {
        assertEquals("Tap Map slots again when the printer is idle.", SlotMapHelp.view(MapStatus(state = "failed")).detail)
        assertNull("old news needs no step", SlotMapHelp.view(MapStatus(state = "failed", problemsOld = true)).detail)
    }

    /** The server ends every failed job on the step "Mapping failed". */
    @Test fun failedSaysItOnceAndListsTheProblems() {
        val v = SlotMapHelp.view(MapStatus(state = "failed", step = "Mapping failed", problems = listOf("printer_busy: x")))
        assertEquals(SlotMapOutcome.FAILED, v.outcome)
        assertEquals("Slot mapping failed", v.headline)
        assertTrue(v.headlineIsError)
        assertEquals("Problems the server reported:", v.problemsHeading)
        assertEquals(listOf("printer_busy: x"), v.problems)
    }

    @Test fun failedHeadlineNeverCarriesTheStep() {
        for (step in listOf("", "Mapping failed", "Testing A2")) {
            assertEquals("Slot mapping failed", SlotMapHelp.view(MapStatus(state = "failed", step = step)).headline)
        }
    }

    @Test fun problemsWithoutAnyListGetNoHeading() {
        val v = SlotMapHelp.view(MapStatus(state = "failed"))
        assertNull(v.problemsHeading)
        assertTrue(v.problems.isEmpty())
    }

    @Test fun aConfirmedMapWithLeftoverProblemsStaysConfirmedAndCalm() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots,
            problems = listOf("could not delete the job file")))
        assertEquals(SlotMapOutcome.CONFIRMED, v.outcome)
        assertFalse(v.headlineIsError)
        assertEquals("Also reported during mapping:", v.problemsHeading)
        assertFalse(v.problemsAreError)
    }

    // ---- a result from an earlier server run ----

    @Test fun anOldFailureSaysItIsOldAndIsNotRed() {
        val v = SlotMapHelp.view(MapStatus(state = "failed", step = "Slot test", problems = listOf("x"), problemsOld = true))
        assertEquals(SlotMapOutcome.FAILED, v.outcome)
        assertEquals("The last slot mapping failed", v.headline)
        assertFalse(v.headlineIsError)
        assertEquals("From an earlier mapping, it may be fixed by now. Map the slots again to check:", v.problemsHeading)
        assertEquals(listOf("X"), v.problems)
        assertFalse(v.problemsAreError)
    }

    @Test fun anOldUnconfirmedResultSaysItIsOldAndIsNotRed() {
        val v = SlotMapHelp.view(MapStatus(state = "done", problems = listOf("x"), problemsOld = true))
        assertEquals(SlotMapOutcome.NOT_CONFIRMED, v.outcome)
        assertEquals("The last slot mapping did not confirm the numbering", v.headline)
        assertNull(v.detail)
        assertFalse(v.headlineIsError)
        assertFalse(v.problemsAreError)
    }

    // ---- the button ----

    @Test fun connectedAndIdleCanStart() {
        assertTrue(SlotMapHelp.canStart("connected", printing = false))
    }

    @Test fun aDeveloperModeRefusalDoesNotBlockMapping() {
        assertTrue(SlotMapHelp.canStart("needs_developer_mode", printing = false))
    }

    @Test fun printingOrOfflineCannotStart() {
        assertFalse(SlotMapHelp.canStart("connected", printing = true))
        assertFalse(SlotMapHelp.canStart("offline", printing = false))
    }

    @Test fun aGreyedButtonSaysWhy() {
        assertEquals("Available when the printer is idle.", SlotMapHelp.blockedReason("connected", printing = true))
        assertEquals("Available when the printer is connected.", SlotMapHelp.blockedReason("offline", printing = false))
        assertNull(SlotMapHelp.blockedReason("connected", printing = false))
    }

    @Test fun noFinishedResultEverGreysTheButton() {
        val results = listOf(
            MapStatus(state = "failed", problems = listOf("x")),
            MapStatus(state = "failed", problems = listOf("x"), problemsOld = true),
            MapStatus(state = "done", observe = true, problems = listOf("x")),
            MapStatus(state = "done", calibrated = true, notes = listOf(note)),
            MapStatus(state = "done", calibrated = true),
            MapStatus(state = "none", observe = true),
        )
        for (m in results) assertTrue("$m", ToolsUiState(map = m).mapEnabled(canStart = true))
    }

    @Test fun onlyARunningJobOrAPendingStartGreysIt() {
        assertFalse(ToolsUiState(map = MapStatus(state = "running")).mapEnabled(canStart = true))
        assertFalse(ToolsUiState(mapBusy = true).mapEnabled(canStart = true))
        assertFalse(ToolsUiState(map = MapStatus(state = "failed")).mapEnabled(canStart = false))
    }

    @Test fun theButtonSaysAgainOnceAResultExists() {
        assertEquals("Map slots", SlotMapHelp.buttonLabel(null))
        assertEquals("Map slots", SlotMapHelp.buttonLabel(MapStatus(state = "none")))
        assertEquals("Map slots again", SlotMapHelp.buttonLabel(MapStatus(state = "done")))
        assertEquals("Map slots again", SlotMapHelp.buttonLabel(MapStatus(state = "failed")))
    }

    // ---- a v0.5.0 server's outcome and reason ----

    private fun server(outcome: String, reason: String = "none", text: String = "T", next: String = "N", state: String = "done",
                       calibrated: Boolean = false, problemsOld: Boolean = false, step: String = "") =
        MapStatus(state = state, step = step, calibrated = calibrated, outcome = outcome, reason = reason,
            outcomeText = text, nextStep = next, problemsOld = problemsOld)

    @Test fun theServersSentencesAreShownAsTheyAre() {
        val v = SlotMapHelp.view(server("failed", "offline", "The last mapping failed.",
            "Map again when the printer is on and online.", state = "failed"))
        assertEquals(SlotMapOutcome.FAILED, v.outcome)
        assertEquals("The last mapping failed.", v.headline)
        assertEquals("Map again when the printer is on and online.", v.detail)
        assertTrue(v.headlineIsError)
        assertEquals(MapAction.RETRY, v.action)
    }

    @Test fun aPrinterThatCannotSayItsSlotNumbersGetsTheManualWay() {
        for (r in listOf("job_refused", "no_mapping", "numbers_unfit")) {
            assertEquals(r, MapAction.MANUAL, SlotMapHelp.view(server("not_confirmed", r)).action)
            assertEquals(r, MapAction.MANUAL, SlotMapHelp.view(server("failed", r, state = "failed")).action)
        }
    }

    @Test fun anUnconfirmedMapWithNoReasonGetsTheManualWayToo() {
        assertEquals(MapAction.MANUAL, SlotMapHelp.view(server("not_confirmed")).action)
    }

    @Test fun somethingInTheWayMeansMapAgain() {
        for (r in listOf("developer_mode", "busy", "offline", "not_configured", "cert_changed", "job_failed",
            "interrupted", "restore_failed", "kit_error")) {
            assertEquals(r, MapAction.RETRY, SlotMapHelp.view(server("failed", r, state = "failed")).action)
        }
        assertEquals(MapAction.RETRY, SlotMapHelp.view(server("failed", "none", state = "failed")).action)
    }

    @Test fun aConfirmedMapNeedsNothing() {
        val v = SlotMapHelp.view(server("confirmed", text = "Mapped and confirmed: filament use comes off the spools.",
            next = "", calibrated = true))
        assertEquals(SlotMapOutcome.CONFIRMED, v.outcome)
        assertEquals(MapAction.NONE, v.action)
        assertNull("no empty next step line", v.detail)
        assertFalse(v.headlineIsError)
    }

    @Test fun anUnknownReasonActsAsItsOutcome() {
        assertEquals(MapAction.RETRY, SlotMapHelp.view(server("failed", "something_new", state = "failed")).action)
        assertEquals(MapAction.NONE, SlotMapHelp.view(server("partial", "something_new", calibrated = true)).action)
    }

    @Test fun anUnknownOutcomeFallsBackToTheFlags() {
        val v = SlotMapHelp.view(server("brand_new", state = "failed"))
        assertEquals(SlotMapOutcome.FAILED, v.outcome)
        assertEquals("Slot mapping failed", v.headline)
        assertEquals(MapAction.RETRY, v.action)
    }

    @Test fun anOlderServerStillGetsAnAction() {
        assertEquals(MapAction.RETRY, SlotMapHelp.view(MapStatus(state = "failed")).action)
        assertEquals(MapAction.NONE, SlotMapHelp.view(MapStatus(state = "done", calibrated = true)).action)
    }

    @Test fun runningShowsTheStepAndNoNextStep() {
        val v = SlotMapHelp.view(server("running", text = "Mapping the slots…", next = "x", state = "running",
            step = "Testing slot A2 (2/3)"))
        assertEquals("Testing slot A2 (2/3)", v.headline)
        assertNull(v.detail)
        assertEquals(MapAction.NONE, v.action)
    }

    @Test fun anOldFailureIsNotRed() {
        assertFalse(SlotMapHelp.view(server("failed", "offline", state = "failed", problemsOld = true)).headlineIsError)
    }

    @Test fun theUnconfirmedHeadlineCarriesTheLoggedOnlyNotice() {
        assertTrue(SlotMapHelp.view(server("not_confirmed")).saysObserve)
        assertFalse(SlotMapHelp.view(MapStatus(state = "done", observe = true)).saysObserve)
    }
}
