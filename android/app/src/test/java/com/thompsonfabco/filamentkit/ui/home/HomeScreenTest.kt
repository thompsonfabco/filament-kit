package com.thompsonfabco.filamentkit.ui.home

import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.semantics.CustomAccessibilityAction
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterSummary
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.MAIN_BUTTON_TAG
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.update.UpdateUi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

/** What Home shows and does (05-android-app 5), on fake data (RFC 5737 addresses). The accessibility audit is in `ScreenSemanticsTest`. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class HomeScreenTest {
    @get:Rule val rule = createComposeRule()

    private val toast = SwToastState()
    private val calls = mutableListOf<String>()

    private fun draft(id: String, photos: Int, hint: String = "", tag: String? = null, ago: Long = 180_000) = Draft(
        id = id, photos = List(photos) { File("p$it.jpg") }, hint = hint, tag = tag, weightGrams = null, sealed = false,
        readResult = null, editedItems = null, created = System.currentTimeMillis() - ago,
    )

    private fun printer(id: String, name: String, state: String = Printer.STATE_CONNECTED, summary: PrinterSummary? = null, configured: Boolean = true) =
        Printer(id = id, name = name, serial = id, ip = "192.0.2.4", configured = configured, state = state, summary = summary)

    private fun show(
        connection: Connection = Connection.Online("192.0.2.10"),
        drafts: List<Draft> = emptyList(),
        update: UpdateUi = UpdateUi(),
        printers: HomePrintersState = HomePrintersState(printers = emptyList()),
        showPrinters: Boolean = true,
        labelReaderOff: Boolean = false,
        localNetwork: Boolean = false,
        loadedAgo: Long = 0,
    ) {
        rule.setContent {
            Themed {
                HomeScreen(
                    connection = connection, drafts = drafts, update = update,
                    printers = printers.copy(loadedAt = printers.loadedAt ?: System.currentTimeMillis() - loadedAgo),
                    onAddSpools = { calls += "photos" }, onAddByHand = { calls += "hand" },
                    onResumeDraft = { calls += "resume $it" }, onDiscardDraft = { calls += "discard $it" },
                    onOpenPrinter = { calls += "printer $it" }, onOpenPrinters = { calls += "printers" },
                    onRefreshPrinters = { calls += "refresh" }, onReviewCertificate = { calls += "review" },
                    onPairAgain = { calls += "pair" }, onInstallUpdate = { calls += "install" },
                    onConfirmInstall = { calls += "confirm" },
                    showPrinters = showPrinters, labelReaderOff = labelReaderOff,
                    onAddCatalogLine = { calls += "catalog" },
                    localNetworkPanel = { SwButton("Allow", {}, kind = SwButtonKind.Main) },
                )
            }
        }
    }

    @Composable
    private fun Themed(content: @Composable () -> Unit) {
        CompositionLocalProvider(LocalToast provides toast) {
            SpoolwardenTheme(Look.Console, Appearance.Light) { content() }
        }
    }

    private fun text(t: String) = rule.onNodeWithText(t)

    private fun exists(t: String, substring: Boolean = false) =
        rule.onAllNodes(hasText(t, substring = substring)).fetchSemanticsNodes().isNotEmpty()

    @Test fun addSpoolsOffersThePhotoButtonAndTheHandButton() {
        show()
        text("Add spools").assertExists()
        text("Photograph each label, check what was read, then add. Nothing is saved until you add.").assertExists()
        text("Add from label photos").performClick()
        text("Add by hand").performClick()
        assertEquals(listOf("photos", "hand"), calls)
    }

    @Test fun withTheLabelReaderOffOnlyAddByHandIsLeftAndSaysWhy() {
        show(labelReaderOff = true)
        rule.onAllNodesWithText("Add from label photos").assertCountEquals(0)
        text("The Label Reader is switched off. Add the spool by hand, or switch it on in Features on the Hub page.").assertExists()
        text("Add by hand").performClick()
        assertEquals(listOf("hand"), calls)
    }

    @Test fun noDraftsMeansNoDraftsPanel() {
        show()
        rule.onAllNodesWithText("Drafts").assertCountEquals(0)
    }

    @Test fun draftsAreListedWithAgeAndTheirPartsAndResumeOnTap() {
        show(drafts = listOf(draft("d1", 2, "3 of the grey ones", "04A1"), draft("d2", 1, ago = 2 * 3_600_000)))
        assertTrue(exists("Drafts"))
        text("3 min ago").assertExists()
        text("2 photos · note: 3 of the grey ones · tag 04A1").assertExists()
        text("1 photo").assertExists()
        text("3 min ago").performClick()
        assertEquals(listOf("resume d1"), calls)
    }

    @Test fun discardAsksFirstAndKeepLeavesTheDraft() {
        show(drafts = listOf(draft("d1", 2)))
        rule.onNodeWithContentDescription("More actions for 3 min ago").performClick()
        text("Discard").performClick()
        text("Discard this add?").assertExists()
        text("Its photos and edits are removed from this phone.").assertExists()
        text("Keep").performClick()
        assertTrue(calls.isEmpty())
        rule.onAllNodesWithText("Discard this add?").assertCountEquals(0)
    }

    @Test fun confirmingDiscardDeletesTheDraftAndTellsInAToast() {
        show(drafts = listOf(draft("d1", 2)))
        rule.onNodeWithContentDescription("More actions for 3 min ago").performClick()
        text("Discard").performClick()
        // the dialog's confirming button carries the same word as the menu item that opened it
        val buttons = rule.onAllNodes(hasText("Discard") and hasClickAction())
        buttons[buttons.fetchSemanticsNodes().size - 1].performClick()
        rule.waitForIdle()
        assertEquals(listOf("discard d1"), calls)
        assertEquals("Add discarded.", toast.host.currentSnackbarData?.visuals?.message)
    }

    @Test fun aDraftRowOffersDiscardAsATalkBackAction() {
        show(drafts = listOf(draft("d1", 2)))
        val row = rule.onNodeWithText("3 min ago").fetchSemanticsNode()
        val actions = row.config.getOrNull(SemanticsActions.CustomActions).orEmpty()
        assertEquals(listOf("Discard"), actions.map(CustomAccessibilityAction::label))
        assertNotNull(row.config.getOrNull(SemanticsProperties.Text))
    }

    @Test fun printersShowStatusNameAndTheJob() {
        show(
            printers = HomePrintersState(
                printers = listOf(
                    printer("A", "Workshop X1", summary = PrinterSummary("RUNNING", 42, 72, "Benchy")),
                    printer("B", "Garage Voron"),
                    printer("C", "Study A1 mini", Printer.STATE_OFFLINE),
                    printer("D", "Spare P1S", Printer.STATE_WRONG_CODE),
                ),
            ),
        )
        text("Printing · 42 % · 1 h 12 min left").assertExists()
        text("Idle").assertExists()
        text("Offline").assertExists()
        text("Needs a look").assertExists()
        text("Workshop X1").performClick()
        text("Spare P1S").performClick()
        text("All printers").performClick()
        assertEquals(listOf("printer A", "printer D", "printers"), calls)
    }

    @Test fun atMostFourPrintersAreListedThenAndNMore() {
        show(printers = HomePrintersState(printers = List(6) { printer("P$it", "Printer $it") }))
        text("Printer 3").assertExists()
        rule.onAllNodesWithText("Printer 4").assertCountEquals(0)
        text("and 2 more").assertExists()
    }

    @Test fun withNoPrintersThePanelOffersAddAPrinter() {
        show()
        text("No printers yet.").assertExists()
        text("Add a printer").performClick()
        assertEquals(listOf("printers"), calls)
    }

    @Test fun whenThePrintersFeatureIsOffThePanelIsAbsent() {
        show(showPrinters = false)
        rule.onAllNodesWithText("All printers").assertCountEquals(0)
        rule.onAllNodesWithText("No printers yet.").assertCountEquals(0)
    }

    @Test fun aFailedFirstReadWhileOnlineSaysSoWithTryAgain() {
        show(printers = HomePrintersState(failed = true))
        text("Cannot reach the Hub. Check that this phone is on the home network.").assertExists()
        text("Try again").performClick()
        assertEquals(listOf("refresh"), calls)
    }

    @Test fun unknownHubInfoDoesNotMeanTheLabelReaderIsOff() {
        // a cold start or an offline phone: the Hub has not said, so both buttons stay
        show(connection = Connection.Offline, printers = HomePrintersState(failed = true))
        text("Add from label photos").assertExists()
        text("Add by hand").assertExists()
        rule.onAllNodesWithText("The Label Reader is switched off", substring = true).assertCountEquals(0)
    }

    @Test fun anOfflinePhoneWithNothingLoadedShowsTheOfflineStateNotSkeletons() {
        show(connection = Connection.Offline, printers = HomePrintersState())
        text("Cannot reach the Hub").assertExists()
        text("Try again").performClick()
        assertEquals(listOf("refresh"), calls)
    }

    @Test fun whileTheFirstReadRunsOnlineThePanelHasNoErrorYet() {
        show(printers = HomePrintersState(loading = true))
        rule.onAllNodesWithText("Cannot reach the Hub").assertCountEquals(0)
        rule.onAllNodesWithText("No printers yet.").assertCountEquals(0)
    }

    @Test fun printersTheHubOnlyFoundAreNotListed() {
        show(
            printers = HomePrintersState(
                printers = listOf(printer("A", "Workshop X1"), printer("B", "Found P1S", Printer.STATE_NOT_CONFIGURED, configured = false)),
            ),
        )
        text("Workshop X1").assertExists()
        rule.onAllNodesWithText("Found P1S").assertCountEquals(0)
    }

    @Test fun sectionTitlesAreHeadings() {
        show(drafts = listOf(draft("d1", 2)))
        for (title in listOf("Add spools", "Drafts", "Printers")) {
            val node = rule.onAllNodes(hasText(title)).fetchSemanticsNodes().first { it.config.contains(SemanticsProperties.Heading) }
            assertNotNull(title, node)
        }
    }

    private fun filledButtons(): Int = rule.onAllNodes(hasTestTag(MAIN_BUTTON_TAG)).fetchSemanticsNodes()
        .count { !it.config.contains(SemanticsProperties.Disabled) }

    @Test fun oneFilledButtonOnlineWithTheReaderOnAndDraftsAndAnUpdate() {
        show(update = UpdateUi(available = 3, offeredVersion = "0.5.3"), drafts = listOf(draft("d1", 1)))
        assertEquals(1, filledButtons())
    }

    @Test fun oneFilledButtonWhenTheHubIsNewerThanTheApp() {
        show(update = UpdateUi(serverTooNew = true))
        assertEquals(1, filledButtons())
    }

    @Test fun oneFilledButtonOfflineWithNothingKnown() {
        show(connection = Connection.Offline, printers = HomePrintersState(failed = true))
        assertEquals(1, filledButtons())
    }

    @Test fun oneFilledButtonWhenTheCertificateChanged() {
        show(connection = Connection.CertChanged("AA", "BB"))
        assertEquals(1, filledButtons())
    }

    @Test fun oneFilledButtonWhileThePrintersLoad() {
        show(printers = HomePrintersState(loading = true))
        assertEquals(1, filledButtons())
    }

    @Test fun oneFilledButtonWithTheLocalNetworkNoticeAndTheReaderOff() {
        show(connection = Connection.NeedsLocalNetwork, labelReaderOff = true)
        assertEquals(1, filledButtons())
        text("Allow").assertExists()
    }

    @Test fun theLocalNetworkAllowButtonIsTheOnlyFilledOne() {
        show(connection = Connection.NeedsLocalNetwork)
        assertEquals(1, filledButtons())
        text("Allow").assertExists()
        text("Add from label photos").assertExists()
    }

    @Test fun withTheLabelReaderOffAddByHandIsTheFilledOne() {
        show(labelReaderOff = true)
        assertEquals(1, filledButtons())
        val filled = rule.onAllNodes(hasTestTag(MAIN_BUTTON_TAG)).fetchSemanticsNodes()
        assertEquals("Add by hand", filled.single().config.getOrNull(SemanticsProperties.Text)?.joinToString { it.text })
    }

    @Test fun withNothingLoadedACertificateChangeIsShownOnceAtTheTopAndThePanelAddsNothing() {
        show(connection = Connection.CertChanged("AA", "BB"), printers = HomePrintersState(failed = true))
        rule.onAllNodesWithText("Review the certificate").assertCountEquals(1)
        text("Review the certificate").performClick()
        assertEquals(listOf("review"), calls)
        rule.onAllNodesWithText("Cannot reach the Hub", substring = true).assertCountEquals(0)
        rule.onAllNodesWithText("Try again").assertCountEquals(0)
    }

    @Test fun withNothingLoadedAnUnpairedPhoneIsShownOnceAtTheTopAndThePanelAddsNothing() {
        show(connection = Connection.Unpaired, printers = HomePrintersState(failed = true))
        rule.onAllNodesWithText("Pair again").assertCountEquals(1)
        text("Pair again").performClick()
        assertEquals(listOf("pair"), calls)
        rule.onAllNodesWithText("Try again").assertCountEquals(0)
    }

    @Test fun withNothingLoadedAndNoLocalNetworkAccessThePanelAddsNothing() {
        show(connection = Connection.NeedsLocalNetwork, printers = HomePrintersState(failed = true))
        rule.onAllNodesWithText("Try again").assertCountEquals(0)
        rule.onAllNodesWithText("Cannot reach the Hub").assertCountEquals(0)
        rule.onAllNodesWithText("No printers yet.").assertCountEquals(0)
    }

    @Test fun onlyOfflineSaysCannotReachTheHubWithTryAgain() {
        show(connection = Connection.Offline, printers = HomePrintersState(failed = true))
        text("Cannot reach the Hub").assertExists()
        text("Try again").assertExists()
    }

    @Test fun anAnswerTheAppCannotReadHasItsOwnWords() {
        show(printers = HomePrintersState(failed = true, unexpected = true))
        text("The Hub sent an answer this app does not understand. Update the app or the Hub, then try again.").assertExists()
        text("Try again").assertExists()
    }

    @Test fun theHubsOwnRefusalIsShownAsGiven() {
        show(printers = HomePrintersState(failed = true, message = "The printers service is restarting."))
        text("The printers service is restarting.").assertExists()
    }

    @Test fun offlineKeepsThePrintersAndSaysHowOldTheyAre() {
        show(
            connection = Connection.Offline,
            printers = HomePrintersState(printers = listOf(printer("A", "Workshop X1")), failed = true),
            loadedAgo = 2 * 60_000,
        )
        text("Workshop X1").assertExists()
        assertTrue(exists("Offline. Showing what was loaded 2 min ago.", substring = true))
        // the notice at the top is enough: no second error inside the panel
        rule.onAllNodesWithText("Try again").assertCountEquals(0)
        text("Add by hand").performClick()
        assertEquals(listOf("hand"), calls)
    }

    @Test fun anAppUpdateIsAnInfoNoticeWithItsInstallButton() {
        show(update = UpdateUi(available = 3, offeredVersion = "0.5.3"))
        assertTrue(exists("Update ready: ", substring = true))
        assertTrue(exists("0.5.3.", substring = true))
        text("Install update").performClick()
        assertEquals(listOf("install"), calls)
    }

    @Test fun aDownloadWaitingForTheInstallWindowSaysTapToInstall() {
        show(update = UpdateUi(available = 3, offeredVersion = "0.5.3", confirmPending = true))
        text("Update downloaded: tap to install.").assertExists()
        text("Tap to install").performClick()
        assertEquals(listOf("confirm"), calls)
    }

    @Test fun aHubNewerThanTheAppIsAWarning() {
        show(update = UpdateUi(serverTooNew = true))
        text("Update the app: the Hub is newer, so some things may not work.").assertExists()
        rule.onAllNodesWithText("Install update").assertCountEquals(0)
    }

    @Test fun noUpdateMeansNoNotice() {
        show()
        assertTrue(!exists("Update ready", substring = true))
        assertTrue(!exists("Update the app", substring = true))
    }

    @Test fun aChangedCertificateAndAnUnpairedPhoneShowTheHubNotice() {
        show(connection = Connection.CertChanged("AA".repeat(32), "BB".repeat(32)))
        text("The Hub's certificate has changed. This phone stopped talking to it to stay safe.").assertExists()
        text("Review the certificate").performClick()
        assertEquals(listOf("review"), calls)
    }

    @Test fun thePresetsPanelKeepsAWayIntoTheFilamentCatalog() {
        show()
        text("Add a line to the Filament Catalog").performClick()
        assertEquals(listOf("catalog"), calls)
    }

    @Test fun aPhoneThatIsNoLongerPairedOffersToPairAgain() {
        show(connection = Connection.Unpaired)
        text("This phone is no longer paired with the Hub.").assertExists()
        text("Pair again").performClick()
        assertEquals(listOf("pair"), calls)
    }
}
