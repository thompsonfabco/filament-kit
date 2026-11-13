package com.thompsonfabco.filamentkit.ui

import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.components.SwToastHost
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import androidx.compose.ui.Alignment
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.runtime.key
import kotlinx.coroutines.CompletableDeferred
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsEnabled
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.activity.OnBackPressedDispatcher
import androidx.compose.ui.test.onAllNodesWithText
import com.thompsonfabco.filamentkit.nav.AddProfileTitle
import org.robolectric.RuntimeEnvironment
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.LocalEntryResult
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.ProfileLine
import com.thompsonfabco.filamentkit.ui.profile.ProfileField
import com.thompsonfabco.filamentkit.ui.profile.ProfileApi
import com.thompsonfabco.filamentkit.ui.profile.AddProfileViewModel
import com.thompsonfabco.filamentkit.ui.profile.AddProfileScreen
import android.os.Build
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isSelected
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick

import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.DiscoveredServer
import com.thompsonfabco.filamentkit.net.KlipperFound
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterReport
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.PrinterSummary
import com.thompsonfabco.filamentkit.net.UnloadResult
import com.thompsonfabco.filamentkit.net.UsageEntry
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.ui.LocalNetworkAccess
import com.thompsonfabco.filamentkit.ui.components.LocalTopBarActions
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
import com.thompsonfabco.filamentkit.ui.components.TopBarActions
import com.thompsonfabco.filamentkit.ui.components.TOP_BAR_TAG
import com.thompsonfabco.filamentkit.ui.home.HomePrintersState
import com.thompsonfabco.filamentkit.ui.home.HomeScreen
import com.thompsonfabco.filamentkit.ui.pair.Mismatch
import com.thompsonfabco.filamentkit.ui.pair.MismatchSource
import com.thompsonfabco.filamentkit.ui.pair.PairAddressScreen
import com.thompsonfabco.filamentkit.ui.pair.PairCertificateScreen
import com.thompsonfabco.filamentkit.ui.pair.PairCodeScreen
import com.thompsonfabco.filamentkit.ui.pair.PairField
import com.thompsonfabco.filamentkit.ui.pair.PairFingerprintScreen
import com.thompsonfabco.filamentkit.ui.pair.PairMessage
import com.thompsonfabco.filamentkit.ui.pair.PairNetworkAccessScreen
import com.thompsonfabco.filamentkit.ui.pair.PairStartScreen
import com.thompsonfabco.filamentkit.ui.pair.PairUi
import com.thompsonfabco.filamentkit.ui.pair.ScanProblem
import com.thompsonfabco.filamentkit.ui.pair.ScannerFrame
import com.thompsonfabco.filamentkit.ui.pair.ScannerState
import com.thompsonfabco.filamentkit.ui.pair.Step
import com.thompsonfabco.filamentkit.ui.printers.CameraSource
import com.thompsonfabco.filamentkit.ui.printers.PrinterBackend
import com.thompsonfabco.filamentkit.ui.printers.PrinterScreen
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsBackend
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrinterViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrintersScreen
import com.thompsonfabco.filamentkit.ui.printers.PrintersViewModel
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.nav.HubState
import com.thompsonfabco.filamentkit.ui.settings.LicencesScreen
import com.thompsonfabco.filamentkit.ui.settings.SettingsActions
import com.thompsonfabco.filamentkit.ui.settings.SettingsFacts
import com.thompsonfabco.filamentkit.ui.settings.SettingsGroup
import com.thompsonfabco.filamentkit.ui.settings.SettingsGroupPage
import com.thompsonfabco.filamentkit.ui.settings.SettingsHub
import com.thompsonfabco.filamentkit.ui.settings.SettingsScreen
import com.thompsonfabco.filamentkit.ui.settings.UpdateActions
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.update.UpdateFailure
import com.thompsonfabco.filamentkit.update.UpdateUi
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import com.thompsonfabco.filamentkit.net.HistoryChange
import com.thompsonfabco.filamentkit.net.HistoryRead
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistoryRevision
import com.thompsonfabco.filamentkit.net.HistorySaved
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.HistorySummary
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.RevisionProposal
import com.thompsonfabco.filamentkit.ui.history.EditScreen
import com.thompsonfabco.filamentkit.ui.history.HistoryBackend
import com.thompsonfabco.filamentkit.ui.history.HistoryListScreen
import com.thompsonfabco.filamentkit.ui.history.HistoryListViewModel
import com.thompsonfabco.filamentkit.ui.history.RecordScreen
import com.thompsonfabco.filamentkit.ui.history.RecordViewModel

/**
 * AUT-8 (07-accessibility 15): Home (with the Label Reader on and off, with printers loading, empty and listed), Spools, Printers, Printer and the pairing screens as they are, Settings as rebuilt (S4.15), drawn under the top bar that
 * names them, in light and dark at font scale 1 and 2. Data is fake (RFC 5737 addresses, `*.example`). Each later
 * screen step adds its screen here.
 */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
// a tall window, so nothing is scrolled out of view and every control has a touch area to measure
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class ScreenSemanticsTest {
    @get:Rule val rule = createComposeRule()

    private var dark by mutableStateOf(false)
    private var fontScale by mutableStateOf(1f)
    private var density = 1f
    private var title: String? = ""
    private val actions = TopBarActions()

    private fun host(title: String, screen: @Composable () -> Unit) {
        this.title = title
        rule.setContent {
            val base = LocalDensity.current
            density = base.density
            CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
                SpoolwardenTheme(Look.Console, if (dark) Appearance.Dark else Appearance.Light) {
                    CompositionLocalProvider(LocalTopBarActions provides actions) {
                        Column(Modifier.fillMaxSize()) {
                            SwTopBar(title = title) { actions.content?.invoke(this) }
                            Box(Modifier.weight(1f)) { screen() }
                        }
                    }
                }
            }
        }
    }

    /** A screen drawn as the shell draws it with no top bar (the scanner). */
    private fun hostNoBar(screen: @Composable () -> Unit) {
        title = null
        rule.setContent {
            val base = LocalDensity.current
            density = base.density
            CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
                SpoolwardenTheme(Look.Console, if (dark) Appearance.Dark else Appearance.Light) { screen() }
            }
        }
    }

    /** The audit's controls rules on every window root besides the screen's own (a dialog, a sheet). */
    private fun auditWindows(): List<String> {
        rule.waitForIdle()
        val merged = rule.onAllNodes(isRoot()).fetchSemanticsNodes()
        val unmerged = rule.onAllNodes(isRoot(), useUnmergedTree = true).fetchSemanticsNodes()
        assertTrue("a window root besides the screen is open", merged.size > 1)
        return merged.indices.drop(1).flatMap { SemanticsAudit.findings(merged[it], unmerged[it], density, title, screenRoot = false) }
    }

    /** Light and dark, font scale 1 and 2, on a dialog or sheet already open over the screen. */
    private fun auditWindowsAllFour(shows: String) {
        rule.waitForIdle()
        rule.onNodeWithText(shows).assertExists()
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), auditWindows())
            }
        }
    }

    private fun audit(sectionTitles: List<String> = emptyList()): List<String> {
        rule.waitForIdle()
        val merged = rule.onRoot().fetchSemanticsNode()
        val unmerged = rule.onRoot(useUnmergedTree = true).fetchSemanticsNode()
        return SemanticsAudit.findings(merged, unmerged, density, title, sectionTitles)
    }

    /** Light and dark, font scale 1 and 2, on the screen already shown. */
    private fun auditAllFour(shows: String, sectionTitles: List<String> = emptyList()) {
        rule.waitForIdle()
        rule.onNodeWithText(shows).assertExists()
        assertTrue("the screen has controls to audit", SemanticsAudit.clickableCount(rule.onRoot().fetchSemanticsNode()) >= 1)
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), audit(sectionTitles))
            }
        }
    }

    private fun draft(id: String, photos: Int, hint: String, tag: String?, created: Long) = Draft(
        id = id, photos = List(photos) { File("p$it.jpg") }, hint = hint, tag = tag, weightGrams = null,
        sealed = false, readResult = null, editedItems = null, created = created,
    )

    private fun homePrinter(id: String, name: String, state: String, summary: PrinterSummary? = null) =
        Printer(id = id, name = name, model = "X1C", serial = id, ip = "192.0.2.4", configured = true, state = state, summary = summary)

    private fun showHome(
        labelReaderOff: Boolean = false,
        printers: HomePrintersState = HomePrintersState(
            printers = listOf(
                homePrinter("A1", "Workshop X1", "connected", PrinterSummary("RUNNING", 42, 72, "Benchy")),
                homePrinter("B2", "Garage Voron", "connected"),
                homePrinter("C3", "Study A1 mini", "offline"),
                homePrinter("D4", "Spare P1S", "wrong_code"),
                homePrinter("E5", "Fifth", "connected"),
            ),
        ),
        update: UpdateUi = UpdateUi(available = 3, offeredVersion = "0.5.3"),
    ) = host("Home") {
        HomeScreen(
            connection = Connection.Online("192.0.2.10"),
            drafts = listOf(
                draft("d1", 2, "3 of the grey ones", "04A1", System.currentTimeMillis() - 180_000),
                draft("d2", 1, "", null, 1_700_000_000_000L),
            ),
            update = update, printers = printers, onAddSpools = {}, onAddByHand = {}, onResumeDraft = {},
            onDiscardDraft = {}, onOpenPrinter = {}, onOpenPrinters = {}, onRefreshPrinters = {},
            onReviewCertificate = {}, onPairAgain = {}, onInstallUpdate = {}, onConfirmInstall = {},
            labelReaderOff = labelReaderOff,
        )
    }

    @Test fun home() {
        showHome()
        auditAllFour("Add by hand", listOf("Add spools", "Drafts", "Printers"))
    }

    @Test fun homeWithTheLabelReaderOff() {
        showHome(labelReaderOff = true)
        auditAllFour("Add by hand", listOf("Add spools", "Drafts", "Printers"))
        rule.onNodeWithText("Add from label photos").assertDoesNotExist()
    }

    @Test fun homeWhilePrintersLoadAndWithoutAnUpdate() {
        showHome(printers = HomePrintersState(loading = true), update = UpdateUi())
        auditAllFour("Add by hand", listOf("Add spools", "Drafts", "Printers"))
    }

    @Test fun homeWithNoPrintersAndTheHubNewerThanTheApp() {
        showHome(printers = HomePrintersState(printers = emptyList()), update = UpdateUi(serverTooNew = true))
        auditAllFour("No printers yet.", listOf("Add spools", "Drafts", "Printers"))
    }

    @Test fun spools() {
        val spool = buildJsonObject {
            put("id", 12)
            put("location", "Shelf 2")
            put("remaining_weight", 640.0)
            put("filament", buildJsonObject {
                put("name", "PolyTerra Charcoal")
                put("material", "PLA")
                put("color_hex", "2B2B2E")
                put("vendor", buildJsonObject { put("name", "Example Filaments") })
            })
        }
        val vm = SearchViewModel { _, _ -> listOf(spool) }
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}) }
        vm.setQuery("pla")
        vm.search()
        rule.waitForIdle()
        assertTrue("a result row is on screen", vm.state.value.results.isNotEmpty())
        auditAllFour("Example Filaments PolyTerra Charcoal")
    }

    @Test fun printers() {
        val backend = FakePrinters()
        val vm = PrintersViewModel(backend)
        host("Printers") { PrintersScreen(vm, onOpen = {}, onPairAgain = {}) }
        auditAllFour("Bambu Lab P1S")
        // the set-up printers with their status words and fix lines, the group of found ones, and the Klipper button
        for (shown in listOf("Workshop X1", "Garage Voron", "Study A1 mini", "Found on the network".uppercase(), "Add a Klipper printer")) {
            rule.onNodeWithText(shown, substring = true).assertExists()
        }
        rule.onNodeWithText("The printer did not accept the Access Code. Enter the Access Code again.").assertExists()
        // the overflow is in the top bar, and it is audited with it
        rule.onNodeWithContentDescription("More actions").assertExists()
    }

    @Test fun theAddBambuFormAndTheReKeyFormOnPhone() {
        val vm = PrintersViewModel(FakePrinters())
        host("Printers") { PrintersScreen(vm, onOpen = {}, onPairAgain = {}) }
        rule.waitForIdle()
        vm.openAdd(vm.state.value.printers.first { !it.configured })
        auditWindowsAllFour("Access Code")
        vm.cancelAdd()
        rule.waitForIdle()
        vm.openAdd(vm.state.value.printers.first { it.state == "wrong_code" })
        auditWindowsAllFour("Replace Access Code: Study A1 mini")
    }

    @Test fun theAddKlipperFormOnPhone() {
        val vm = PrintersViewModel(FakePrinters())
        host("Printers") { PrintersScreen(vm, onOpen = {}, onPairAgain = {}) }
        rule.waitForIdle()
        vm.openAddKlipper("192.0.2.57", 7125)
        auditWindowsAllFour("Moonraker API key (optional)")
    }

    @Test fun theFindSheetOnPhone() {
        val vm = PrintersViewModel(FakePrinters())
        host("Printers") { PrintersScreen(vm, onOpen = {}, onPairAgain = {}) }
        rule.waitForIdle()
        vm.openFind()
        auditWindowsAllFour("Network to search (optional)")
    }

    @Test fun printersEmpty() {
        val vm = PrintersViewModel(FakePrinters(emptyList()))
        host("Printers") { PrintersScreen(vm, onOpen = {}, onPairAgain = {}) }
        auditAllFour("No printers yet")
    }

    @Test fun printer() {
        val backend = FakePrinters()
        val vm = PrinterViewModel(backend, "ABC123", pollMs = 600_000)
        val tools = PrinterToolsViewModel(FakeTools(), "ABC123", pollMs = 600_000)
        val camera = CameraSource(OkHttpClient(), "https://hub.example/hls", "https://hub.example/mjpeg", emptyMap())
        host("Printer") { PrinterScreen(vm, tools, camera, onBack = {}, onPairAgain = {}) }
        auditAllFour("Pause")
    }

    private val hub = SettingsHub("Workshop Hub", "192.0.2.10:8443", "AB12".repeat(16), "0.5.3")
    private fun facts(update: UpdateUi = UpdateUi(), paired: Boolean = true) = SettingsFacts(
        appearance = Appearance.System, hub = hub.takeIf { paired }, hubState = HubState.Connected, update = update,
        appVersion = "0.5.2", developer = true,
    )
    private fun actions(skip: Boolean = false) = SettingsActions(
        onAppearance = {}, skipFingerprintCheck = skip, onSkipFingerprintCheck = {}, onPairAgain = {}, onForget = {},
        setupUrl = { "https://192.0.2.10:8443/setup" },
        update = UpdateActions(install = {}, cancel = {}, openSettings = {}, tapToInstall = {}, tryAgain = {}),
        onCheckForUpdates = {}, onSimulateTag = {},
    )
    private fun group(title: String, group: SettingsGroup, facts: SettingsFacts = facts()) =
        host(title) { SettingsGroupPage(group, facts, actions()) }

    /** The title the app's top bar shows on the catalog route: the shell reads the same resource. */
    private fun catalogTitle() = RuntimeEnvironment.getApplication().getString(AddProfileTitle)

    @Test fun catalogLine() {
        val vm = AddProfileViewModel(FakeCatalog(refuse = false))
        host(catalogTitle()) { AddProfileScreen(vm, onBack = {}, onSaved = {}, onPairAgain = {}) }
        rule.waitForIdle()
        rule.onNodeWithText("Existing lines").assertExists()
        rule.onNodeWithText("Bambu Studio parent: none").assertExists()
        auditAllFour("Save to the catalog", CATALOG_SECTIONS)
    }

    @Test fun catalogLineWhileSavingBlocksBack() {
        val gate = CompletableDeferred<Unit>()
        val vm = AddProfileViewModel(FakeCatalog(refuse = false, gate = gate))
        val toast = SwToastState()
        var left = 0
        var saved = 0
        var dispatcher: OnBackPressedDispatcher? = null
        host(catalogTitle()) {
            dispatcher = LocalOnBackPressedDispatcherOwner.current?.onBackPressedDispatcher
            CompositionLocalProvider(LocalToast provides toast) {
                Box {
                    AddProfileScreen(vm, onBack = { left++ }, onSaved = { saved++ }, onPairAgain = {})
                    SwToastHost(toast, Modifier.align(Alignment.BottomCenter))
                }
            }
        }
        fillCatalog(vm)
        vm.save() // the Hub does not answer until the gate opens
        rule.waitForIdle()
        rule.runOnUiThread { dispatcher!!.onBackPressed() }
        rule.waitForIdle()
        rule.onNodeWithText("Leave without saving?").assertDoesNotExist()
        rule.onNodeWithText("Saving to the catalog… wait for the Hub's answer.").assertExists()
        assertEquals("Back does not leave while saving", 0, left)
        assertEquals(0, saved)
        gate.complete(Unit)
        rule.waitForIdle()
        assertEquals(1, saved)
    }

    @Test fun catalogLineKeepsItsFailureWhenTheScreenComesBackUnchanged() {
        val vm = AddProfileViewModel(FakeCatalog(refuse = false, failure = FingerprintMismatch("aa", "bb")))
        var round by mutableStateOf(0)
        host(catalogTitle()) {
            // a new composition of the screen over the same view model, as after "Review the certificate"
            key(round) { AddProfileScreen(vm, onBack = {}, onSaved = {}, onPairAgain = {}, paired = true) }
        }
        fillCatalog(vm)
        vm.save()
        rule.waitForIdle()
        rule.onNodeWithText("certificate has changed", substring = true).assertExists()
        round++
        rule.waitForIdle()
        rule.onNodeWithText("certificate has changed", substring = true).assertExists()
    }

    @Test fun catalogLineClearsAFailureWhenThePhoneBecomesPaired() {
        val vm = AddProfileViewModel(FakeCatalog(refuse = false, failure = ApiError(401, "unauthorized", "x")))
        var paired by mutableStateOf(false)
        host(catalogTitle()) { AddProfileScreen(vm, onBack = {}, onSaved = {}, onPairAgain = {}, paired = paired) }
        fillCatalog(vm)
        vm.save()
        rule.waitForIdle()
        rule.onAllNodesWithText("This phone is no longer paired with the Hub.").assertCountEquals(2)
        paired = true
        rule.waitForIdle()
        rule.onNodeWithText("This phone is no longer paired with the Hub.").assertDoesNotExist()
    }

    @Test fun catalogLineWithoutAPairingKeepsTheFormAndShowsTheHubNotice() {
        val vm = AddProfileViewModel(FakeCatalog(refuse = false))
        host(catalogTitle()) { AddProfileScreen(vm, onBack = {}, onSaved = {}, onPairAgain = {}, paired = false) }
        fillCatalog(vm)
        rule.waitForIdle()
        rule.onNodeWithText("This phone is no longer paired with the Hub.").assertExists()
        rule.onNodeWithText("Save to the catalog").assertIsNotEnabled()
        rule.onNodeWithText("Example Filaments").assertExists()
        rule.onNodeWithText("Existing lines").assertDoesNotExist()
        auditAllFour("Save to the catalog", CATALOG_SECTIONS - "Existing lines")
    }

    private fun fillCatalog(vm: AddProfileViewModel) {
        vm.set(ProfileField.Vendor, "Example Filaments")
        vm.set(ProfileField.Line, "PolyTerra")
        vm.set(ProfileField.Material, "PLA")
    }

    @Test fun catalogLineRefused() {
        val vm = AddProfileViewModel(FakeCatalog(refuse = true))
        host(catalogTitle()) { AddProfileScreen(vm, onBack = {}, onSaved = {}, onPairAgain = {}) }
        fillCatalog(vm)
        vm.set(ProfileField.Density, "9")
        vm.save()
        rule.waitForIdle()
        rule.onNodeWithText("The Hub could not use these values:").assertExists()
        // the notice lists the problem and the Density field carries it again under itself
        assertEquals(2, rule.onAllNodesWithText(DENSITY_PROBLEM, substring = true).fetchSemanticsNodes().size)
        auditAllFour("Save to the catalog", CATALOG_SECTIONS)
    }

    @Test fun settings() {
        host("Settings") { SettingsScreen(facts(UpdateUi(available = 7, offeredVersion = "0.5.3")), onOpen = {}) }
        auditAllFour("Hub connection")
    }

    @Test @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h8000dp")
    fun settingsInTwoPanes() {
        val facts = facts()
        host("Settings") { SettingsScreen(facts, onOpen = {}, detail = { SettingsGroupPage(it, facts, actions()) }) }
        auditAllFour("These choices are kept on this phone only.")
        rule.onNode(hasText("Appearance") and hasClickAction() and isSelected()).assertExists()
    }

    @Test fun settingsAppearance() {
        group("Appearance", SettingsGroup.Appearance)
        auditAllFour("These choices are kept on this phone only.")
    }

    @Test fun settingsHub() {
        group("Hub connection", SettingsGroup.Hub)
        auditAllFour("Forget this Hub")
    }

    @Test fun settingsHubNotPaired() {
        group("Hub connection", SettingsGroup.Hub, facts(paired = false))
        auditAllFour("No Hub is paired.")
    }

    @Test fun settingsUpdatesOffered() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(available = 7, offeredVersion = "0.5.3", checked = true)))
        auditAllFour("Install update")
    }

    @Test fun settingsUpdatesUpToDate() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(checked = true)))
        auditAllFour("This app is up to date.")
    }

    @Test fun settingsUpdatesDownloading() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(available = 7, busy = true, progress = 42)))
        auditAllFour("Downloading… 42 %")
    }

    @Test fun settingsUpdatesWaiting() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(available = 7, confirmPending = true)))
        auditAllFour("Tap to install")
    }

    @Test fun settingsUpdatesSignatureRefused() {
        group(
            "App updates", SettingsGroup.Updates,
            facts(UpdateUi(available = 7, failure = UpdateFailure.Signature, error = "refused")),
        )
        auditAllFour("What this means")
    }

    @Test fun settingsUpdatesFailed() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(available = 7, failure = UpdateFailure.Storage, error = "storage")))
        auditAllFour("Try again")
    }

    @Test fun settingsUpdatesNeedsPermission() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(available = 7, needsPermission = true)))
        auditAllFour("Open settings")
    }

    @Test fun settingsUpdatesInstalling() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(available = 7, installing = true, confirmPending = true)))
        auditAllFour("Tap Install in the window Android shows.")
    }

    @Test fun settingsUpdatesHubNewer() {
        group(
            "App updates", SettingsGroup.Updates,
            facts(UpdateUi(available = 7, serverTooNew = true, checked = true, offeredVersion = "0.5.3")),
        )
        auditAllFour("Install update")
    }

    @Test fun settingsUpdatesWritingCannotBeCancelled() {
        group("App updates", SettingsGroup.Updates, facts(UpdateUi(available = 7, busy = true, writing = true)))
        auditAllFour("Handing the update to Android. This can't be cancelled.")
    }

    @Test fun settingsUpdatesNotPaired() {
        group("App updates", SettingsGroup.Updates, facts(paired = false))
        auditAllFour("Pair with a Hub first: updates come from the Hub.")
    }

    @Test fun settingsHubWithTheFingerprintCheckOff() {
        host("Hub connection") { SettingsGroupPage(SettingsGroup.Hub, facts(), actions(skip = true)) }
        auditAllFour("Needs a look")
    }

    /** A dialog opened from a Settings page, in light and dark at font scale 1 and 2: its words and buttons are there and reachable. */
    private fun dialogShows(open: String, vararg shown: String) {
        rule.waitForIdle()
        rule.onNodeWithText(open).performClick()
        rule.waitForIdle()
        for (isDark in listOf(false, true)) for (scale in listOf(1f, 2f)) {
            dark = isDark
            fontScale = scale
            rule.waitForIdle()
            for (text in shown) rule.onNodeWithText(text).assertExists()
            for (button in shown.takeLast(2).filter { it.length < 24 }) rule.onNodeWithText(button).assertHeightIsAtLeast(44.dp) // Material grows the touch slot to 48
        }
    }

    @Test fun skipTheFingerprintCheckDialog() {
        group("Hub connection", SettingsGroup.Hub)
        dialogShows("Check the fingerprint when pairing by address", "Skip the fingerprint check?", "Only do this on a network you trust.", "Cancel", "Skip the check")
    }

    @Test fun forgetTheHubDialog() {
        group("Hub connection", SettingsGroup.Hub)
        dialogShows("Forget this Hub", "Forget Workshop Hub?", "Cancel", "Forget")
    }

    @Test fun whatThisMeansDialog() {
        group(
            "App updates", SettingsGroup.Updates,
            facts(UpdateUi(available = 7, failure = UpdateFailure.Signature, error = "refused")),
        )
        dialogShows("What this means", "An update signed with a different key", "Close")
    }

    @Test fun settingsLicences() {
        host("Licences") { LicencesScreen() }
        rule.waitUntil(timeoutMillis = 10_000) {
            rule.onAllNodesWithText("The Android app").fetchSemanticsNodes().isNotEmpty()
        }
        auditAllFour("Show the GPL-3.0 text")
    }

    @Test fun settingsDeveloper() {
        group("Developer", SettingsGroup.Developer)
        auditAllFour("Simulate a tag tap")
    }

    private val fp = "0123456789abcdef".repeat(4)

    @Test fun pairNetworkAccess() {
        host("Pair with your Hub") { PairNetworkAccessScreen(LocalNetworkAccess(false, false, {}, {}), "0.5.2") }
        auditAllFour("Allow")
    }

    @Test fun pairStart() {
        val hub = DiscoveredServer("Workshop Hub", "192.0.2.10", 8710)
        host("Pair with your Hub") {
            PairStartScreen(PairUi(), listOf(hub), "0.5.2", onScan = {}, onPick = {}, onEnterAddress = {}, unpairedBanner = true)
        }
        auditAllFour("Scan QR code")
    }

    @Test fun pairStartSearchingWithAFailure() {
        host("Pair with your Hub") {
            PairStartScreen(
                PairUi(error = PairMessage.Res(R.string.pair_error_not_code)), emptyList(), "0.5.2",
                onScan = {}, onPick = {}, onEnterAddress = {},
            )
        }
        auditAllFour("Scan QR code")
    }

    @Test fun pairStartConnecting() {
        host("Pair with your Hub") {
            PairStartScreen(PairUi(busy = true), emptyList(), "0.5.2", onScan = {}, onPick = {}, onEnterAddress = {})
        }
        auditAllFour("Connecting…")
    }

    @Test fun pairAddress() {
        host("Pair with your Hub") {
            PairAddressScreen(
                PairUi(step = Step.Address, host = "192.0.2.10", error = PairMessage.Res(R.string.pair_address_error_port), errorField = PairField.Port),
                onSubmit = { _, _ -> }, onBack = {},
            )
        }
        auditAllFour("Enter the Hub's address")
    }

    @Test fun pairAddressWithAConnectionFailure() {
        host("Pair with your Hub") {
            PairAddressScreen(
                PairUi(step = Step.Address, host = "hub.example", error = PairMessage.Res(R.string.common_hub_unreachable)),
                onSubmit = { _, _ -> }, onBack = {},
            )
        }
        auditAllFour("Enter the Hub's address")
    }

    @Test fun pairFingerprint() {
        host("Pair with your Hub") {
            PairFingerprintScreen(PairUi(step = Step.Confirm, host = "hub.example", fingerprint = fp), {}, {}, {})
        }
        auditAllFour("Check the Hub's fingerprint")
    }

    @Test fun pairCode() {
        host("Pair with your Hub") {
            PairCodeScreen(PairUi(step = Step.Code, error = PairMessage.Res(R.string.pair_error_refused)), {}, {})
        }
        auditAllFour("Enter the pairing code")
    }

    @Test fun pairCertificateOfASavedPairing() {
        host("Hub certificate") {
            PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.STORED), canTrust = true, {}, {}, {})
        }
        auditAllFour("The Hub's certificate has changed")
    }

    @Test fun pairCertificateOfASavedPairingThatCannotBeKept() {
        host("Hub certificate") {
            PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.STORED), canTrust = false, {}, {}, {})
        }
        auditAllFour("The Hub's certificate has changed")
    }

    @Test fun pairCertificateOfAScannedCode() {
        host("Pair with your Hub") {
            PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.QR), canTrust = false, {}, {}, {})
        }
        auditAllFour("This pairing code doesn't match the Hub")
    }

    @Test fun pairCertificateChangedWhilePairing() {
        host("Pair with your Hub") {
            PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.MANUAL), canTrust = false, {}, {}, {})
        }
        auditAllFour("The Hub's certificate changed while pairing")
    }

    // The scanner route as drawn: no top bar; close button, hint chip and viewfinder over a stubbed camera.
    @Test fun theScannerWithTheCamera() {
        hostNoBar {
            ScannerFrame(ScannerState.Scanning, onClose = {}, onTryAgain = {}, onEnterAddress = {}) { Box(Modifier.fillMaxSize()) }
        }
        auditAllFour("Point the camera at the QR code")
        rule.onNodeWithContentDescription("Close the scanner").assertExists()
        rule.onNodeWithContentDescription("Camera viewfinder. Point it at the QR code.").assertExists()
    }

    @Test fun theScannerRouteWithoutTheCamera() {
        hostNoBar { ScannerFrame(ScannerState.Denied, onClose = {}, onTryAgain = {}, onEnterAddress = {}) {} }
        auditAllFour("Try again")
    }

    @Test fun theScannerRouteWhoseCameraFailed() {
        hostNoBar { ScannerFrame(ScannerState.CameraFailed, onClose = {}, onTryAgain = {}, onEnterAddress = {}) {} }
        auditAllFour("Enter the address instead")
    }

    @Test fun aMissingLocalNetworkPermissionShowsThePanelOfTheAccessStep() {
        host("Pair with your Hub") {
            PairAddressScreen(
                PairUi(step = Step.Address, error = PairMessage.LocalNetwork), { _, _ -> }, {},
                access = LocalNetworkAccess(false, false, {}, {}),
            )
        }
        auditAllFour("Allow local network access")
    }

    @Test fun theScannerWithoutTheCamera() {
        host("Pair with your Hub") { ScanProblem(denied = true, onPrimary = {}, onEnterAddress = {}) }
        auditAllFour("Try again")
    }

    @Test fun theScannerWhoseCameraFailed() {
        host("Pair with your Hub") { ScanProblem(denied = false, onPrimary = {}, onEnterAddress = {}) }
        auditAllFour("Enter the address instead")
    }

    @Test fun recentList() {
        val history = FakeHistory()
        val vm = HistoryListViewModel(history)
        host("Recently added") { HistoryListScreen(vm, null, onOpen = {}, onPairAgain = {}) }
        auditAllFour("Polymaker PolyTerra PLA Charcoal Black")
    }

    @Test fun recentListWhenEmptyAndTheReaderIsOff() {
        val history = FakeHistory(records = emptyList(), ai = false)
        val vm = HistoryListViewModel(history)
        host("Recently added") { HistoryListScreen(vm, null, onOpen = {}, onPairAgain = {}) }
        rule.waitForIdle()
        rule.onNodeWithText("Nothing added yet").assertExists()
        rule.onNodeWithText("The Label Reader is switched off. Correct by hand, or switch it on in Features on the Hub page.").assertExists()
        assertEquals(emptyList<String>(), audit())
    }

    @Test fun recentRecord() {
        val history = FakeHistory()
        val list = HistoryListViewModel(history)
        val vm = RecordViewModel(history, "a1")
        host("Recently added") {
            RecordScreen(vm, list, null, onBack = {}, onOpenRecord = {}, onEdit = {}, onOpenPhoto = {}, onOpenSpool = {}, onPairAgain = {})
        }
        auditAllFour("Fields")
    }

    @Test fun recentRecordWithAProposalToAccept() {
        val history = FakeHistory()
        val list = HistoryListViewModel(history)
        val vm = RecordViewModel(history, "a1")
        host("Recently added") {
            RecordScreen(vm, list, null, onBack = {}, onOpenRecord = {}, onEdit = {}, onOpenPhoto = {}, onOpenSpool = {}, onPairAgain = {})
        }
        rule.waitForIdle()
        vm.ask("brand is Polymaker")
        rule.waitForIdle()
        rule.onNodeWithText("Proposal: 1 change").assertExists()
        auditAllFour("Accept")
    }

    @Test fun recentEdit() {
        val history = FakeHistory()
        val vm = RecordViewModel(history, "a1")
        host("Recently added") { EditScreen(vm, item = 0, onClose = {}, onPairAgain = {}) }
        auditAllFour("Save changes")
    }

    // The audit itself: each rule fails on a planted violation.

    @Test fun anUnnamedClickableFails() {
        host("Planted") { Box(Modifier.size(64.dp).clickable { }) }
        assertTrue(audit().any { "without text or content description" in it })
    }

    @Test fun aSmallClickableFails() {
        host("Planted") { Box(Modifier.size(20.dp).clickable { }) { Text("x") } }
        val found = audit()
        assertTrue(found.toString(), found.any { "under 48 x 48" in it })
    }

    @Test fun aClickableWithOuterPaddingAroundItFails() {
        // the box around it is 48 dp, the clickable inside is 20 dp
        host("Planted") { Box(Modifier.padding(14.dp).size(20.dp).clickable { }) { Text("x") } }
        val found = audit()
        assertTrue(found.toString(), found.any { "under 48 x 48" in it })
    }

    @Test fun aTopBarWithoutItsHeadingFails() {
        rule.setContent { Box(Modifier.testTag(TOP_BAR_TAG)) { Text("Planted") } }
        title = "Planted"
        assertTrue(audit().any { "found 0" in it })
    }

    @Test fun twoHeadingsInTheTopBarFail() {
        rule.setContent {
            Box(Modifier.testTag(TOP_BAR_TAG)) {
                Column {
                    Text("Planted", Modifier.semantics { heading() })
                    Text("Second", Modifier.semantics { heading() })
                }
            }
        }
        title = "Planted"
        assertTrue(audit().any { "found 2" in it })
    }

    @Test fun aTopBarHeadingThatIsNotTheTitleFails() {
        host("Planted") { }
        title = "Something else"
        assertTrue(audit().any { "not the title" in it })
    }

    @Test fun aListedSectionTitleMustBeAHeadingButOtherHeadingsAreFine() {
        host("Planted") {
            Column {
                Text("Server")
                Text("Another section", Modifier.semantics { heading() })
            }
        }
        assertTrue(audit(listOf("Server")).any { "section title \"Server\"" in it })
        assertEquals(emptyList<String>(), audit(listOf("Another section")))
    }

    @Test fun aCheckboxWithItsOwnClickBesideTextFails() {
        host("Planted") {
            Row { Checkbox(checked = false, onCheckedChange = {}); Text("Sealed spools only") }
        }
        assertTrue(audit().any { "own click" in it })
    }

    private class FakeHistory(
        val records: List<HistorySummary> = listOf(
            HistorySummary(
                "a1", "2026-11-12T14:05:00+00:00", "phone", "detected", photos = 2, undoable = true,
                spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E")),
            ),
            HistorySummary(
                "a2", "2026-11-12T09:41:00+00:00", "station", "revised_ai", photos = 1,
                spools = listOf(
                    HistorySpool(212, 40, "Bambu Lab", "PETG HF Orange", "PETG", "F2701D"),
                    HistorySpool(213, 40, "Bambu Lab", "PETG HF Orange", "PETG", "F2701D"),
                ),
            ),
            HistorySummary(
                "a3", "2026-11-11T18:20:00+00:00", "web", "edited", photos = 0,
                spools = listOf(HistorySpool(210, 39, "Example Filaments", "Silk Blue", "PLA", "1E50A0")),
            ),
        ),
        val ai: Boolean = true,
    ) : HistoryBackend {
        private val values = buildJsonObject {
            put("vendor", "Polymaker"); put("name", "PolyTerra PLA Charcoal Black"); put("material", "PLA")
            put("color_hex", "2B2B2E"); put("tare", 140); put("density", 1.24)
            put("nozzle_range", JsonArray(listOf(JsonPrimitive(190), JsonPrimitive(230))))
        }
        private val record = HistoryRecord(
            id = "a1", at = "2026-11-12T14:05:00+00:00", source = "phone", state = "edited", photos = 2, undoable = true,
            spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E")),
            read = HistoryRead(listOf(buildJsonObject {
                put("vendor", "Polymaker"); put("name", "PolyTerra PLA Charcoal Black"); put("material", "PLA")
                put("density", 1.24); put("estimates", JsonArray(listOf(JsonPrimitive("density"))))
            })),
            saved = listOf(HistorySaved(0, listOf(214), values)),
            revisions = listOf(
                HistoryRevision(
                    1, "2026-11-12T14:09:00+00:00", "hand",
                    changes = listOf(HistoryChange(214, "tare", JsonPrimitive(150), JsonPrimitive(140))),
                ),
            ),
        )

        override suspend fun list() = IntakeHistory(20, records.size, 14_900_000L, ai, records)
        override suspend fun record(id: String) = record
        override suspend fun photo(id: String, n: Int) = ByteArray(0)
        override suspend fun revise(id: String, note: String, item: Int?) = RevisionProposal(
            "p-1", 0, buildJsonObject { put("vendor", "Polymaker") }, buildJsonObject { put("vendor", "Polymaker Ltd") }, listOf("vendor"),
        )
        override suspend fun applyProposal(id: String, proposal: String) = record
        override suspend fun applyValues(id: String, item: Int, values: JsonObject) = record
        override suspend fun undo(id: String, revision: Int) = record
    }

    private class FakePrinters(private val list: List<Printer>? = null) : PrinterBackend {
        private val online = Printer(
            id = "ABC123", name = "Workshop X1", model = "X1C", serial = "ABC123", ip = "192.0.2.40", configured = true,
            state = "connected", summary = PrinterSummary("RUNNING", 42, 31, "Benchy"),
        )
        private val unset = Printer(id = "DEF456", name = "Spare P1S", model = "P1S", serial = "DEF456", ip = "192.0.2.41")
        private val klipper = Printer(
            id = "klipper-1", name = "Garage Voron", model = "Voron 2.4", serial = "klipper-1", configured = true,
            state = "connected", family = "klipper", host = "voron.example", summary = PrinterSummary("IDLE", 0, 0),
        )
        private val wrongCode = Printer(
            id = "GHI789", name = "Study A1 mini", model = "A1 mini", serial = "GHI789", ip = "192.0.2.42",
            configured = true, state = "wrong_code",
        )
        private val status = PrinterStatus(
            gcodeState = "RUNNING", job = "Benchy", percent = 42, remainingMin = 31,
            ams = listOf(AmsUnit(unit = 0, slots = listOf(AmsSlot(slot = 0, label = "A1", type = "PLA", colorHex = "2B2B2E")))),
        )

        override suspend fun printers() = list ?: listOf(online, klipper, wrongCode, unset)
        override suspend fun addPrinter(serial: String, accessCode: String, name: String?) = online
        override suspend fun addKlipperPrinter(host: String, port: Int, name: String?) = online
        override suspend fun scanKlipper(subnet: String?) = emptyList<KlipperFound>()
        override suspend fun setApiKey(id: String, key: String) = Unit
        override suspend fun printer(id: String) = PrinterDetail(online, status)
        override suspend fun command(id: String, action: String) = CommandResult(ok = true)
        override suspend fun unload(id: String, label: String, dryRun: Boolean): UnloadResult = error("not used")
    }

    private class FakeCatalog(
        private val refuse: Boolean,
        private val gate: CompletableDeferred<Unit>? = null,
        private val failure: Exception? = null,
    ) : ProfileApi {
        override suspend fun parents(material: String) = ParentList(listOf("Generic PLA", "Example PLA Basic"), synced = true)
        override suspend fun profileLines() = listOf(
            ProfileLine(lineId = "example--polyterra", vendor = "Example Filaments", product = "PolyTerra", material = "PLA", presets = 4, bambuParent = "Generic PLA"),
            ProfileLine(lineId = "example--silk", vendor = "Example Filaments", product = "Silk", material = "PLA"),
        )
        override suspend fun setLineParent(lineId: String, parent: String) = profileLines().first { it.lineId == lineId }
        override suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult {
            gate?.await()
            failure?.let { throw it }
            if (refuse) {
                throw ApiError(
                    400, "invalid_entry", "not valid",
                    JsonObject(mapOf("problems" to JsonArray(listOf(JsonPrimitive(DENSITY_PROBLEM))))),
                )
            }
            return LocalEntryResult(entry, "example--polyterra")
        }
    }

    private class FakeTools : PrinterToolsBackend {
        override suspend fun startMap(id: String): String = error("not used")
        override suspend fun mapStatus(id: String): MapStatus = error("not used")
        override suspend fun report(id: String): PrinterReport = error("not used")
        override suspend fun usage(id: String, days: Int): List<UsageEntry> = emptyList()
        override suspend fun undoUsage(entryId: String): UsageEntry = error("not used")
    }

    private companion object {
        const val DENSITY_PROBLEM = "fields.filament_density '9' is outside 0.5-3.0 g/cm3"
        val CATALOG_SECTIONS = listOf("Line", "Temperatures", "Material", "Slicer", "Notes", "Existing lines")
    }
}
