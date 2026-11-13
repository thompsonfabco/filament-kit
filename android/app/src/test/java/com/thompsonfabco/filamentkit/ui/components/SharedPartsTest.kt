package com.thompsonfabco.filamentkit.ui.components

import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.hasProgressBarRangeInfo
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.LocalNetworkAccess
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** The shared parts and page states of 05-android-app 3: buttons, notices, states, toast, the local network notice. */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class SharedPartsTest {
    @get:Rule val rule = createComposeRule()

    private val context = RuntimeEnvironment.getApplication()
    private fun str(id: Int, vararg args: Any) = context.getString(id, *args)

    /** The control's layout slot, which Material grows to 48 dp around a smaller drawn button. */
    private fun SemanticsNodeInteraction.assertTouchAtLeast48dp(): SemanticsNodeInteraction {
        val slot = fetchSemanticsNode().layoutInfo
        val density = context.resources.displayMetrics.density
        assertTrue("slot ${slot.width / density} x ${slot.height / density} dp", slot.width / density >= 48 && slot.height / density >= 48)
        return this
    }

    private fun themed(content: @Composable () -> Unit) = rule.setContent {
        SpoolwardenTheme(Look.Console, Appearance.Light, content)
    }

    // --- buttons ---

    @Test fun everyKindOfButtonIsLabelledPressableAndAtLeast48dp() {
        val pressed = mutableListOf<SwButtonKind>()
        themed {
            Column {
                SwButtonKind.entries.forEach { kind -> SwButton(kind.name, { pressed += kind }, kind = kind) }
            }
        }
        SwButtonKind.entries.forEach { kind ->
            rule.onNodeWithText(kind.name).assertTouchAtLeast48dp().performClick()
        }
        assertEquals(SwButtonKind.entries.toList(), pressed)
    }

    @Test fun aDisabledOrBusyButtonDoesNothing() {
        var presses = 0
        themed {
            Column {
                SwButton("Off", { presses++ }, enabled = false)
                SwButton("Busy", { presses++ }, kind = SwButtonKind.Main, busy = true)
            }
        }
        rule.onNodeWithText("Off").assertIsNotEnabled()
        rule.onNodeWithText("Busy").assertIsNotEnabled()
        assertEquals(0, presses)
    }

    // --- spinner and progress ---

    @Test fun theSpinnerIsTheWordWorkingWhenAnimationsAreOff() {
        Settings.Global.putFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 0f)
        themed { SwSpinner() }
        rule.onNodeWithText(str(R.string.common_working)).assertExists()
    }

    @Test fun theSpinnerIsARingWithNoWordsWhenAnimationsAreOn() {
        Settings.Global.putFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f)
        themed { SwSpinner() }
        rule.onNodeWithText(str(R.string.common_working)).assertDoesNotExist()
    }

    @Test fun theProgressLineIsDeterminateWithANumberAndIndeterminateWithout() {
        var value by mutableStateOf<Float?>(0.25f)
        themed { SwProgress(value) }
        rule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo(0.25f, 0f..1f))).assertExists()
        value = null
        rule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo.Indeterminate)).assertExists()
    }

    // --- notices ---

    @Test fun aNoticeSaysItsWordsAndRunsItsActionAndBadOnesAreAssertive() {
        var again = 0
        themed {
            NoticeCard(NoticeKind.Bad, "It failed.", actions = listOf(SwAction("Try again", { again++ })))
        }
        rule.onNodeWithText("It failed.").assertExists()
        rule.onNodeWithText("Try again").assertTouchAtLeast48dp().performClick()
        assertEquals(1, again)
        rule.onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.LiveRegion)).assertExists()
    }

    @Test fun theHubNoticeHasFixedWordsAndOneAction() {
        var pressed = ""
        themed {
            Column {
                HubNotice(HubNoticeKind.CertificateChanged, { pressed = "review" })
                HubNotice(HubNoticeKind.NoLongerPaired, { pressed = "pair" })
            }
        }
        rule.onNodeWithText(str(R.string.common_cert_changed_notice)).assertExists()
        rule.onNodeWithText(str(R.string.common_not_paired_notice)).assertExists()
        rule.onNodeWithText(str(R.string.common_review_certificate)).performClick()
        assertEquals("review", pressed)
        rule.onNodeWithText(str(R.string.common_pair_again)).performClick()
        assertEquals("pair", pressed)
    }

    // --- empty state ---

    @Test fun theEmptyStateHasATitleSentenceAndTwoButtons() {
        var added = 0
        themed {
            SwEmptyState(
                R.drawable.sw_ic_printer, "No printers yet", "Printers appear here.",
                primary = SwAction("Add a printer", { added++ }), secondary = SwAction("Find printers", {}),
            )
        }
        rule.onNodeWithText("No printers yet").assertExists()
        rule.onNodeWithText("Printers appear here.").assertExists()
        rule.onNodeWithText("Find printers").assertExists()
        rule.onNodeWithText("Add a printer").performClick()
        assertEquals(1, added)
    }

    // --- page states ---

    private var loaded by mutableStateOf(false)
    private var loading by mutableStateOf(true)
    private var error by mutableStateOf<String?>(null)
    private var offline by mutableStateOf(false)
    private var isEmpty by mutableStateOf(false)
    private var tries = 0

    private fun page() = themed {
        ScreenState(
            loaded = loaded, loading = loading, isEmpty = isEmpty, error = error, onTryAgain = { tries++ },
            offline = offline, loadedSecondsAgo = 130,
            empty = { Text("Nothing here") },
        ) { Text("The data") }
    }

    @Test fun theFirstLoadShowsASkeletonAndTheProgressLineAndNoSpinnerOrContent() {
        page()
        rule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo.Indeterminate)).assertExists()
        rule.onNodeWithText("The data").assertDoesNotExist()
        rule.onNodeWithText(str(R.string.common_still_waiting)).assertDoesNotExist()
    }

    @Test fun afterTenSecondsTheFirstLoadSaysItIsStillWaiting() {
        page()
        rule.mainClock.autoAdvance = false // otherwise waiting for idle skips the delay
        rule.mainClock.advanceTimeBy(STILL_WAITING_MS - 1)
        rule.onNodeWithText(str(R.string.common_still_waiting)).assertDoesNotExist()
        rule.mainClock.advanceTimeBy(2)
        rule.onNodeWithText(str(R.string.common_still_waiting)).assertExists()
        Snapshot.withMutableSnapshot {
            loaded = true
            loading = false
        }
        rule.mainClock.advanceTimeBy(100)
        rule.onNodeWithText(str(R.string.common_still_waiting)).assertDoesNotExist()
        rule.onNodeWithText("The data").assertExists()
        rule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo.Indeterminate)).assertDoesNotExist()
    }

    @Test fun refreshingKeepsTheDataUnderTheProgressLine() {
        loaded = true
        page()
        rule.onNodeWithText("The data").assertExists()
        rule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo.Indeterminate)).assertExists()
    }

    @Test fun anEmptyLoadShowsTheEmptyState() {
        loaded = true
        loading = false
        isEmpty = true
        page()
        rule.onNodeWithText("Nothing here").assertExists()
        rule.onNodeWithText("The data").assertDoesNotExist()
    }

    @Test fun anErrorIsANoticeWithTryAgainAndTheDataStays() {
        loaded = true
        loading = false
        error = str(R.string.common_hub_unreachable)
        page()
        rule.onNodeWithText(str(R.string.common_hub_unreachable)).assertExists()
        rule.onNodeWithText("The data").assertExists()
        rule.onNodeWithText(str(R.string.common_try_again)).performClick()
        assertEquals(1, tries)
    }

    @Test fun offlineKeepsTheDataUnderANoticeSayingHowOldItIs() {
        loaded = true
        loading = false
        offline = true
        page()
        rule.onNodeWithText(str(R.string.common_offline_notice, "2 min ago")).assertExists()
        rule.onNodeWithText("The data").assertExists()
    }

    @Test fun offlineWithNothingLoadedIsTheCannotReachTheHubState() {
        loading = false
        offline = true
        page()
        rule.onNodeWithText(str(R.string.common_offline_title)).assertExists()
        rule.onNodeWithText(str(R.string.common_offline_text)).assertExists()
        rule.onNodeWithText(str(R.string.common_try_again)).assertIsEnabled().performClick()
        assertEquals(1, tries)
        rule.onNodeWithText("The data").assertDoesNotExist()
    }

    @Test fun theNeedsTheHubReasonIsShown() {
        themed { NeedsHubReason() }
        rule.onNodeWithText(str(R.string.common_needs_hub)).assertExists()
    }

    // --- toast ---

    private fun toastHost(): Pair<SwToastState, () -> CoroutineScope> {
        val state = SwToastState()
        lateinit var scope: CoroutineScope
        themed {
            scope = rememberCoroutineScope()
            Box { SwToastHost(state) }
        }
        rule.waitForIdle()
        return state to { scope }
    }

    @Test fun aToastIsHeldFiveSeconds() {
        val (state, scope) = toastHost()
        rule.mainClock.autoAdvance = false
        rule.runOnIdle { scope().launch { state.show("Saved.") } }
        rule.mainClock.advanceTimeBy(1_000)
        rule.onNodeWithText("Saved.").assertExists()
        rule.mainClock.advanceTimeBy(TOAST_MS)
        rule.mainClock.advanceTimeBy(1_000)
        rule.onNodeWithText("Saved.").assertDoesNotExist()
    }

    @Test fun aToastWithAnActionIsHeldTenSecondsAndTheActionDismissesIt() {
        val (state, scope) = toastHost()
        var result: androidx.compose.material3.SnackbarResult? = null
        rule.mainClock.autoAdvance = false
        rule.runOnIdle { scope().launch { result = state.show("Removed.", actionLabel = "Undo") } }
        rule.mainClock.advanceTimeBy(TOAST_MS + 1_000)
        rule.onNodeWithText("Removed.").assertExists()
        rule.onNodeWithText("Undo").assertTouchAtLeast48dp().performClick()
        rule.mainClock.advanceTimeBy(1_000)
        rule.onNodeWithText("Removed.").assertDoesNotExist()
        assertEquals(androidx.compose.material3.SnackbarResult.ActionPerformed, result)
    }

    @Test fun aToastWithAnActionGoesAfterTenSecondsWhenNobodyPressesIt() {
        val (state, scope) = toastHost()
        rule.mainClock.autoAdvance = false
        rule.runOnIdle { scope().launch { state.show("Removed.", actionLabel = "Undo") } }
        rule.mainClock.advanceTimeBy(TOAST_WITH_ACTION_MS - 1_000)
        rule.onNodeWithText("Removed.").assertExists()
        rule.mainClock.advanceTimeBy(TOAST_WITH_ACTION_MS + 1_000)
        rule.onNodeWithText("Removed.").assertDoesNotExist()
    }

    @Test fun queuedToastsEachGetTheirOwnTimeAndOneNeverClosesAnother() {
        val (state, scope) = toastHost()
        rule.mainClock.autoAdvance = false
        rule.runOnIdle {
            scope().launch { state.show("First", actionLabel = "Undo") }
            scope().launch { state.show("Second") }
        }
        rule.mainClock.advanceTimeBy(1_000)
        rule.onNodeWithText("First").assertExists()
        // past the 5 s of a plain toast: the first has an action, so it is held 10 s, and the second still waits
        rule.mainClock.advanceTimeBy(TOAST_MS + 1_500)
        rule.onNodeWithText("First").assertExists()
        rule.onNodeWithText("Second").assertDoesNotExist()
        rule.mainClock.advanceTimeBy(TOAST_WITH_ACTION_MS - TOAST_MS - 1_500 + 1_000)
        rule.onNodeWithText("First").assertDoesNotExist()
        // the second is shown now and is held its own 5 s from here
        rule.mainClock.advanceTimeBy(1_000)
        rule.onNodeWithText("Second").assertExists()
        rule.mainClock.advanceTimeBy(1_500)
        rule.onNodeWithText("Second").assertExists()
        rule.mainClock.advanceTimeBy(1_500)
        rule.onNodeWithText("Second").assertDoesNotExist()
    }

    // --- dialog ---

    private fun dialog(confirmed: () -> Unit = {}, cancelled: () -> Unit = {}) = themed {
        SwDialog(
            title = "Leave without saving?", onClose = cancelled,
            confirm = SwDialogButton("Leave", confirmed, kind = SwButtonKind.DestructiveFilled),
            cancel = SwAction("Stay", cancelled),
        ) { Text("Your changes are not saved.") }
    }

    @Test fun onAPhoneTheDialogIsABottomSheetWithStackedButtonsConfirmingOnTop() {
        var left = 0
        var stayed = 0
        dialog({ left++ }, { stayed++ })
        rule.onNodeWithText("Leave without saving?").assertExists()
        rule.onNodeWithText("Your changes are not saved.").assertExists()
        val leave = rule.onNodeWithText("Leave").fetchSemanticsNode().boundsInWindow
        val stay = rule.onNodeWithText("Stay").fetchSemanticsNode().boundsInWindow
        assertTrue("confirming button above Cancel: $leave $stay", leave.top < stay.top)
        assertEquals("full width, both", leave.width, stay.width, 1f)
        rule.onNodeWithText("Leave").assertTouchAtLeast48dp().performClick()
        assertEquals(1, left)
        rule.onNodeWithText("Stay").performClick()
        assertEquals(1, stayed)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w900dp-h700dp")
    @Test fun onATabletTheDialogIsACentredPanelWithTheConfirmingButtonLast() {
        var left = 0
        dialog({ left++ })
        rule.onNodeWithText("Your changes are not saved.").assertExists()
        val leave = rule.onNodeWithText("Leave").fetchSemanticsNode().boundsInWindow
        val stay = rule.onNodeWithText("Stay").fetchSemanticsNode().boundsInWindow
        assertTrue("Cancel before the confirming button in reading order: $stay $leave", stay.left < leave.left)
        assertEquals("same row", stay.top, leave.top, 8f)
        val panel = rule.onNodeWithText("Leave without saving?").fetchSemanticsNode().boundsInWindow
        assertTrue("at most 30 rem (480 dp) wide", leave.right - stay.left <= 480f)
        assertTrue(panel.left > 100f)
        rule.onNodeWithText("Leave").performClick()
        assertEquals(1, left)
    }

    // --- local network notice ---

    @Test fun theLocalNetworkNoticeAsksThenPointsToSettings() {
        var asked = 0
        var opened = 0
        var access by mutableStateOf(LocalNetworkAccess(false, false, { asked++ }, { opened++ }))
        themed { LocalNetworkNotice(access) }
        rule.onNodeWithText(str(R.string.network_title)).assertExists()
        rule.onNodeWithText(str(R.string.network_text)).assertExists()
        rule.onNodeWithText(str(R.string.network_no_ask)).assertDoesNotExist()
        rule.onNodeWithText(str(R.string.common_allow)).assertTouchAtLeast48dp().performClick()
        assertEquals(1, asked)

        access = LocalNetworkAccess(false, true, { asked++ }, { opened++ })
        rule.onNodeWithText(str(R.string.network_no_ask)).assertExists()
        rule.onNodeWithText(str(R.string.common_allow)).assertDoesNotExist()
        rule.onNodeWithText(str(R.string.common_open_app_settings)).performClick()
        assertEquals(1, opened)
        assertTrue(asked == 1)
    }
}
