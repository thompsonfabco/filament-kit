package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.MapSlot
import com.thompsonfabco.filamentkit.net.MapStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Slot mapping panel (05-android-app 9.7): the status words and shapes, the problems, and which button is filled. */
class SlotMapHelpTest {
    private val fourSlots = listOf("A1", "A2", "A3", "A4").map { MapSlot(label = it) }
    private val note = "the loaded slots are numbered alike under shift8, legacy: the numbering of further " +
        "AMS units is settled when one is added (the map is made again then)"

    private fun words(id: Int, vararg args: Any) = Say.Words(id, args.toList())

    // ---- the states ----

    @Test fun noMapYetSaysNothing() {
        val v = SlotMapHelp.view(MapStatus(state = "none"))
        assertEquals(SlotMapOutcome.NONE, v.outcome)
        assertNull(v.headline)
        assertNull(v.detail)
        assertEquals(SlotMapOutcome.NONE, SlotMapHelp.view(null).outcome)
    }

    @Test fun runningShowsTheHubsStepWithTheHalfFilledCircle() {
        val v = SlotMapHelp.view(MapStatus(state = "running", step = "Testing A2"))
        assertEquals(SlotMapOutcome.RUNNING, v.outcome)
        assertEquals(Say.FromHub("Testing A2"), v.headline)
        assertEquals(MapShape.Running, v.shape)
        assertEquals(words(R.string.printer_map_running), SlotMapHelp.view(MapStatus(state = "running")).headline)
    }

    @Test fun confirmedCountsTheSlotsAndSaysTheNumberingIsConfirmed() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots))
        assertEquals(SlotMapOutcome.CONFIRMED, v.outcome)
        assertEquals(words(R.string.printer_map_mapped_count, 4), v.headline)
        assertEquals(words(R.string.printer_map_confirmed_text), v.detail)
        assertEquals(MapShape.Filled, v.shape)
        assertNull(v.problemsHeading)
    }

    @Test fun partialSaysWhatIsConfirmed() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots, notes = listOf(note)))
        assertEquals(SlotMapOutcome.PARTIAL, v.outcome)
        assertEquals(words(R.string.printer_map_confirmed_loaded), v.headline)
        assertEquals(MapShape.Filled, v.shape)
        assertTrue("the Hub's note says the same as the headline", v.notes.isEmpty())
    }

    @Test fun theHubsFlagDecidesPartialOverTheNote() {
        assertEquals(SlotMapOutcome.PARTIAL, SlotMapHelp.view(MapStatus(state = "done", calibrated = true, schemeUnsettled = true)).outcome)
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots, schemeUnsettled = false,
            notes = listOf("some other remark")))
        assertEquals(SlotMapOutcome.CONFIRMED, v.outcome)
        assertEquals("the note is still shown", listOf("Some other remark"), v.notes)
    }

    @Test fun anOlderHubsNoteStillMeansPartial() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, schemeUnsettled = null, notes = listOf(note)))
        assertEquals(SlotMapOutcome.PARTIAL, v.outcome)
    }

    @Test fun aChangedLayoutAndPrintsThatDisagreeAreTrianglesAndAskForAnotherMapping() {
        val stale = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots, stale = true))
        assertEquals(SlotMapOutcome.STALE, stale.outcome)
        assertEquals(words(R.string.printer_map_layout_changed), stale.headline)
        assertEquals(MapShape.Triangle, stale.shape)
        assertEquals(MapAction.RETRY, stale.action)
        val suspect = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, slots = fourSlots, suspect = true))
        assertEquals(words(R.string.printer_map_disagreed), suspect.headline)
        assertEquals(MapShape.Triangle, suspect.shape)
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

    @Test fun aStaleMapComesBeforeASuspectOneAndARemapUnderWaySaysSo() {
        assertEquals(SlotMapOutcome.STALE, SlotMapHelp.view(MapStatus(state = "done", calibrated = true, stale = true, suspect = true)).outcome)
        val running = SlotMapHelp.view(MapStatus(state = "running", step = "Testing A2", calibrated = true, stale = true))
        assertEquals(SlotMapOutcome.RUNNING, running.outcome)
    }

    @Test fun leftoversOfAGoodMapStayCalm() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = true, suspect = true, problems = listOf("x")))
        assertEquals(R.string.printer_map_problems_also, v.problemsHeading)
        assertFalse(v.problemsAreError)
    }

    @Test fun anUnprovenMapThatWentStaleKeepsItsProblemsRed() {
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = false, stale = true, problems = listOf("x")))
        assertEquals(R.string.printer_map_problems, v.problemsHeading)
        assertTrue(v.problemsAreError)
    }

    @Test fun doneButNotCalibratedIsNotConfirmedAndNeverCalledFinished() {
        val problems = listOf(
            "the calibration job ended as FAILED on the printer",
            "slot numbering not confirmed: filament use is only logged until mapping succeeds",
        )
        val v = SlotMapHelp.view(MapStatus(state = "done", calibrated = false, observe = true, problems = problems))
        assertEquals(SlotMapOutcome.NOT_CONFIRMED, v.outcome)
        assertEquals(words(R.string.printer_map_unconfirmed), v.headline)
        assertEquals(MapShape.Triangle, v.shape)
        assertEquals(R.string.printer_map_problems, v.problemsHeading)
        assertEquals("the only-logged line is the notice's", listOf("The calibration job ended as FAILED on the printer"), v.problems)
        assertTrue(v.problemsAreError)
        assertEquals(MapAction.RETRY, v.action)
    }

    @Test fun aHubCodeKeepsItsSpellingAndPlainWordsGetACapital() {
        val v = SlotMapHelp.view(MapStatus(state = "failed", problems = listOf("printer_busy: x", "error: y", "Ext-L is empty")))
        assertEquals(listOf("printer_busy: x", "Error: y", "Ext-L is empty"), v.problems)
    }

    @Test fun failedIsAnOctagonThatNeverCarriesTheStep() {
        for (step in listOf("", "Mapping failed", "Testing A2")) {
            val v = SlotMapHelp.view(MapStatus(state = "failed", step = step))
            assertEquals(SlotMapOutcome.FAILED, v.outcome)
            assertEquals(words(R.string.printer_map_failed), v.headline)
            assertEquals(MapShape.Octagon, v.shape)
        }
        assertNull(SlotMapHelp.view(MapStatus(state = "failed")).problemsHeading)
    }

    @Test fun aResultFromAnEarlierRunSaysItIsOldAndIsNotRed() {
        val failed = SlotMapHelp.view(MapStatus(state = "failed", problems = listOf("x"), problemsOld = true))
        assertEquals(words(R.string.printer_map_failed_last), failed.headline)
        assertEquals(R.string.printer_map_problems_old, failed.problemsHeading)
        assertEquals(listOf("X"), failed.problems)
        assertFalse(failed.problemsAreError)
        val unconfirmed = SlotMapHelp.view(MapStatus(state = "done", problems = listOf("x"), problemsOld = true))
        assertEquals(words(R.string.printer_map_unconfirmed_last), unconfirmed.headline)
    }

    // ---- the buttons ----

    @Test fun onlyAnIdleConnectedPrinterCanStartAndAGreyedButtonSaysWhy() {
        assertTrue(SlotMapHelp.canStart("connected", printing = false))
        assertTrue("a Developer Mode refusal does not block", SlotMapHelp.canStart("needs_developer_mode", printing = false))
        assertFalse(SlotMapHelp.canStart("connected", printing = true))
        assertFalse(SlotMapHelp.canStart("offline", printing = false))
        assertEquals(R.string.printer_available_idle, SlotMapHelp.blockedReason("connected", printing = true))
        assertEquals(R.string.printer_available_connected, SlotMapHelp.blockedReason("offline", printing = false))
        assertNull(SlotMapHelp.blockedReason("connected", printing = false))
    }

    @Test fun noFinishedResultEverGreysTheButton() {
        val results = listOf(
            MapStatus(state = "failed", problems = listOf("x")),
            MapStatus(state = "done", observe = true, problems = listOf("x")),
            MapStatus(state = "done", calibrated = true, notes = listOf(note)),
            MapStatus(state = "done", stale = true),
            MapStatus(state = "done", suspect = true),
            MapStatus(state = "none", observe = true),
        )
        for (m in results) assertTrue("$m", ToolsUiState(map = m).mapEnabled(canStart = true))
        assertFalse(ToolsUiState(map = MapStatus(state = "running")).mapEnabled(canStart = true))
        assertFalse(ToolsUiState(mapBusy = true).mapEnabled(canStart = true))
        assertFalse(ToolsUiState(map = MapStatus(state = "failed")).mapEnabled(canStart = false))
    }

    @Test fun theButtonSaysAgainOnceAResultExists() {
        assertEquals(R.string.printer_map_slots, SlotMapHelp.buttonLabel(null))
        assertEquals(R.string.printer_map_slots, SlotMapHelp.buttonLabel(MapStatus(state = "none")))
        assertEquals(R.string.printer_map_slots_again, SlotMapHelp.buttonLabel(MapStatus(state = "done")))
        assertEquals(R.string.printer_map_slots_again, SlotMapHelp.buttonLabel(MapStatus(state = "failed")))
    }

    // ---- one filled button per printer screen (F1.2) ----

    @Test fun pauseOrResumeComesFirstThenMapByLoadingThenMapSlotsThenTheReport() {
        // every condition holds: only the first is filled
        assertEquals(MainButton.PauseResume, mainButton(true, MapAction.MANUAL, true, true, true, true))
        assertEquals(MainButton.MapByLoading, mainButton(false, MapAction.MANUAL, true, true, true, true))
        assertEquals(MainButton.MapSlots, mainButton(false, MapAction.RETRY, true, true, true, true))
        assertEquals(MainButton.Report, mainButton(false, MapAction.NONE, true, true, true, true))
        assertEquals(MainButton.None, mainButton(false, MapAction.NONE, true, true, false, true))
    }

    @Test fun aDisabledButtonNeverCountsAsTheFilledOne() {
        assertEquals("Pause disabled: the next one is filled", MainButton.MapByLoading, mainButton(false, MapAction.MANUAL, true, true, true, true))
        assertEquals(MainButton.MapSlots, mainButton(false, MapAction.RETRY, true, false, true, true))
        assertEquals("both maps disabled: the report", MainButton.Report, mainButton(false, MapAction.RETRY, false, false, true, true))
        assertEquals(MainButton.None, mainButton(false, MapAction.RETRY, false, false, true, false))
    }

    // ---- a v0.5.0 Hub's outcome and reason ----

    private fun server(outcome: String, reason: String = "none", text: String = "T", next: String = "N", state: String = "done",
                       calibrated: Boolean = false, problemsOld: Boolean = false, step: String = "") =
        MapStatus(state = state, step = step, calibrated = calibrated, outcome = outcome, reason = reason,
            outcomeText = text, nextStep = next, problemsOld = problemsOld)

    @Test fun theHubsSentencesAreShownAsTheyAre() {
        val v = SlotMapHelp.view(server("failed", "offline", "The last mapping failed.",
            "Map again when the printer is on and online.", state = "failed"))
        assertEquals(SlotMapOutcome.FAILED, v.outcome)
        assertEquals(Say.FromHub("The last mapping failed."), v.headline)
        assertEquals(Say.FromHub("Map again when the printer is on and online."), v.detail)
        assertEquals(MapShape.Octagon, v.shape)
        assertEquals(MapAction.RETRY, v.action)
    }

    @Test fun aPrinterThatCannotSayItsSlotNumbersGetsTheManualWay() {
        for (r in listOf("job_refused", "no_mapping", "numbers_unfit")) {
            assertEquals(r, MapAction.MANUAL, SlotMapHelp.view(server("not_confirmed", r)).action)
            assertEquals(r, MapAction.MANUAL, SlotMapHelp.view(server("failed", r, state = "failed")).action)
        }
        assertEquals(MapAction.MANUAL, SlotMapHelp.view(server("not_confirmed")).action)
    }

    @Test fun somethingInTheWayMeansMapAgain() {
        for (r in listOf("developer_mode", "busy", "offline", "not_configured", "cert_changed", "job_failed",
            "interrupted", "restore_failed", "kit_error")) {
            assertEquals(r, MapAction.RETRY, SlotMapHelp.view(server("failed", r, state = "failed")).action)
        }
        assertEquals(MapAction.RETRY, SlotMapHelp.view(server("failed", "none", state = "failed")).action)
    }

    @Test fun aConfirmedMapNeedsNothingAndAnUnknownReasonActsAsItsOutcome() {
        val v = SlotMapHelp.view(server("confirmed", text = "Mapped.", next = "", calibrated = true))
        assertEquals(SlotMapOutcome.CONFIRMED, v.outcome)
        assertEquals(MapAction.NONE, v.action)
        assertNull("no empty next step line", v.detail)
        assertEquals(MapAction.RETRY, SlotMapHelp.view(server("failed", "something_new", state = "failed")).action)
        assertEquals(MapAction.NONE, SlotMapHelp.view(server("partial", "something_new", calibrated = true)).action)
    }

    @Test fun anUnknownOutcomeFallsBackToTheFlags() {
        val v = SlotMapHelp.view(server("brand_new", state = "failed"))
        assertEquals(SlotMapOutcome.FAILED, v.outcome)
        assertEquals(words(R.string.printer_map_failed), v.headline)
        assertEquals(MapAction.RETRY, v.action)
    }

    @Test fun runningShowsTheStepAndNoNextStep() {
        val v = SlotMapHelp.view(server("running", text = "Mapping the slots…", next = "x", state = "running", step = "Testing slot A2 (2/3)"))
        assertEquals(Say.FromHub("Testing slot A2 (2/3)"), v.headline)
        assertNull(v.detail)
        assertEquals(MapAction.NONE, v.action)
    }

    @Test fun theUnconfirmedHeadlineCarriesTheLoggedOnlyNotice() {
        assertTrue(SlotMapHelp.view(server("not_confirmed")).saysObserve)
        assertFalse(SlotMapHelp.view(MapStatus(state = "done", observe = true)).saysObserve)
    }
}
