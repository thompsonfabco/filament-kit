package com.thompsonfabco.filamentkit.ui

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
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterReport
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.PrinterSummary
import com.thompsonfabco.filamentkit.net.UnloadResult
import com.thompsonfabco.filamentkit.net.UsageEntry
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
import com.thompsonfabco.filamentkit.ui.components.TOP_BAR_TAG
import com.thompsonfabco.filamentkit.ui.home.HomeScreen
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

/**
 * AUT-8 (07-accessibility 15): Home, Spools, Printers and Printer as they are, Settings as rebuilt (S4.15), drawn under the top bar that
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
    private var title = ""

    private fun host(title: String, screen: @Composable () -> Unit) {
        this.title = title
        rule.setContent {
            val base = LocalDensity.current
            density = base.density
            CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
                SpoolwardenTheme(Look.Console, if (dark) Appearance.Dark else Appearance.Light) {
                    Column(Modifier.fillMaxSize()) {
                        SwTopBar(title = title)
                        Box(Modifier.weight(1f)) { screen() }
                    }
                }
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
    private fun auditAllFour(shows: String) {
        rule.waitForIdle()
        rule.onNodeWithText(shows).assertExists()
        assertTrue("the screen has controls to audit", SemanticsAudit.clickableCount(rule.onRoot().fetchSemanticsNode()) >= 1)
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), audit())
            }
        }
    }

    @Test fun home() {
        host("Home") {
            HomeScreen(
                serverName = "Workshop Hub", connection = Connection.Online("192.0.2.10"),
                drafts = listOf(
                    Draft(
                        id = "d1", photos = listOf(File("a.jpg"), File("b.jpg")), hint = "grey", tag = null, weightGrams = null,
                        sealed = false, readResult = null, editedItems = null, created = 1_700_000_000_000L,
                    ),
                ),
                update = UpdateUi(), version = "App 1.0.0", onAddSpools = {}, onAddByHand = {}, onAddProfile = {},
                onSearch = {}, onPrinters = {}, onSettings = {}, onResumeDraft = {}, onDiscardDraft = {},
                onRetryConnection = {}, onReviewCertificate = {}, onInstallUpdate = {}, onConfirmInstall = {},
                labelPhotos = true,
            )
        }
        auditAllFour("Add spool")
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
        auditAllFour("Spare P1S")
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
    private fun actions() = SettingsActions(
        onAppearance = {}, skipFingerprintCheck = false, onSkipFingerprintCheck = {}, onPairAgain = {}, onForget = {},
        setupUrl = { "https://192.0.2.10:8443/setup" },
        update = UpdateActions(install = {}, cancel = {}, openSettings = {}, tapToInstall = {}, tryAgain = {}),
        onCheckForUpdates = {}, onSimulateTag = {},
    )
    private fun group(title: String, group: SettingsGroup, facts: SettingsFacts = facts()) =
        host(title) { SettingsGroupPage(group, facts, actions()) }

    @Test fun settings() {
        host("Settings") { SettingsScreen(facts(UpdateUi(available = 7, offeredVersion = "0.5.3")), onOpen = {}) }
        auditAllFour("Hub connection")
    }

    @Test @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h8000dp")
    fun settingsInTwoPanes() {
        val facts = facts()
        host("Settings") { SettingsScreen(facts, onOpen = {}, detail = { SettingsGroupPage(it, facts, actions()) }) }
        auditAllFour("These choices are kept on this phone only.")
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

    private class FakePrinters : PrinterBackend {
        private val online = Printer(
            id = "ABC123", name = "Workshop X1", model = "X1C", serial = "ABC123", ip = "192.0.2.40", configured = true,
            state = "connected", summary = PrinterSummary("RUNNING", 42, 31, "Benchy"),
        )
        private val unset = Printer(id = "DEF456", name = "Spare P1S", model = "P1S", serial = "DEF456", ip = "192.0.2.41")
        private val status = PrinterStatus(
            gcodeState = "RUNNING", job = "Benchy", percent = 42, remainingMin = 31,
            ams = listOf(AmsUnit(unit = 0, slots = listOf(AmsSlot(slot = 0, label = "A1", type = "PLA", colorHex = "2B2B2E")))),
        )

        override suspend fun printers() = listOf(online, unset)
        override suspend fun addPrinter(serial: String, accessCode: String, name: String?) = online
        override suspend fun addKlipperPrinter(host: String, port: Int, name: String?) = online
        override suspend fun printer(id: String) = PrinterDetail(online, status)
        override suspend fun command(id: String, action: String) = CommandResult(ok = true)
        override suspend fun unload(id: String, label: String, dryRun: Boolean): UnloadResult = error("not used")
    }

    private class FakeTools : PrinterToolsBackend {
        override suspend fun startMap(id: String): String = error("not used")
        override suspend fun mapStatus(id: String): MapStatus = error("not used")
        override suspend fun report(id: String): PrinterReport = error("not used")
        override suspend fun usage(id: String, days: Int): List<UsageEntry> = emptyList()
        override suspend fun undoUsage(entryId: String): UsageEntry = error("not used")
    }
}
