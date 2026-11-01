package com.thompsonfabco.filamentkit

import android.Manifest
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.espresso.Espresso
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import com.thompsonfabco.filamentkit.session.UNPAIRED_MESSAGE
import com.thompsonfabco.filamentkit.tags.TagEvents
import com.thompsonfabco.filamentkit.tags.formatUid
import com.thompsonfabco.filamentkit.ui.add.DebugPhotos
import com.thompsonfabco.filamentkit.ui.pair.groupFingerprint
import java.security.SecureRandom
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.RuleChain
import org.junit.runner.RunWith

private const val TAG = "FkE2E"

/**
 * End to end against a real filament-kit server (see docs/android-e2e.md). Skipped unless `fkPhase` is passed; the
 * phases run as separate instrumentation runs, in order, so `cold` starts in a new process:
 *
 * - `main` (`fkCode`, `fkHost`, `fkPhoto`, optional `fkPort`, `fkFingerprint`): manual pair → Printers (empty) →
 *   Add spools with the label photo injected instead of the camera, a new tag and a weight → Read → Preview → Add →
 *   the tag tapped on Home opens the new spool's card → Update weight → the device is unpaired on the server (the
 *   driver does that when it sees `UNPAIR_NOW` in logcat) → the next call lands on Pair with the unpaired message.
 * - `cold`: a cold start after that unpair opens Pair, still explaining why.
 * - `forget` (`fkCode`, `fkHost`, ...): pair again → Settings → Forget server → Pair.
 */
@RunWith(AndroidJUnit4::class)
class EndToEndTest {
    private val compose = createAndroidComposeRule<MainActivity>()

    @get:Rule val rules: RuleChain = RuleChain
        // ACCESS_LOCAL_NETWORK (API 37): without it, browsing for servers opens the system device picker over the app.
        .outerRule(GrantPermissionRule.grant(Manifest.permission.CAMERA, "android.permission.ACCESS_LOCAL_NETWORK"))
        .around(compose)

    private val args = InstrumentationRegistry.getArguments()
    private fun arg(name: String): String? = args.getString(name)?.takeIf { it.isNotBlank() }
    private fun need(name: String): String = arg(name) ?: error("instrumentation argument $name is missing")

    // ---------- phases ----------

    @Test fun main() {
        assumeTrue(arg("fkPhase") == "main")
        val photo = readDeviceFile(need("fkPhoto"))
        val uid = newUid()
        Log.i(TAG, "tag uid $uid, photo ${photo.size} bytes")

        waitFor("Pair with your server")
        pairManually(need("fkCode"))

        // Printers: the test server has none (it is behind NAT), so only the empty state is checked here.
        click("Printers")
        waitFor("No printers found yet", substring = true, timeoutMs = 30_000)
        Espresso.pressBack()
        waitFor("Search")

        // Add spools: photo (injected), tag, weight → Read.
        click("Add spools")
        waitFor("Photos: 0 of 8")
        DebugPhotos.emit(photo)
        waitFor("Photos: 1 of 8", timeoutMs = 30_000)
        emitUntil(uid) { exists("Tag $uid") }
        field("Weight on the scale, with spool (g)").performScrollTo().performTextInput("812.5")
        if (arg("fkStopBeforeRead") == "1") return // rehearsal: everything up to the paid Read step
        click("Read labels")
        compose.waitUntil(180_000) { exists("Check the spools") || exists("Your photos and edits are kept.") }
        assertTrue("Read failed: ${allText()}", exists("Check the spools"))
        Log.i(TAG, "read: ${allText()}")

        // One opened spool, so the tag is linked and the weight becomes its gross.
        val sealed = compose.onNode(hasContentDescription("Still sealed"))
        if (sealed.fetchSemanticsNode().config.getOrNull(SemanticsProperties.ToggleableState) == ToggleableState.On) {
            sealed.performScrollTo().performClick()
        }
        val count = field("Spools", substring = true)
        if (count.text() != "1") {
            count.performScrollTo().performTextClearance()
            count.performTextInput("1")
        }

        click("Preview")
        waitFor("would link tag $uid", timeoutMs = 60_000)
        click("Add 1 spool")
        compose.waitUntil(60_000) { exists("New spool: #", substring = true) || exists("Your photos and edits are kept.") }
        val done = allText().firstNotNullOfOrNull { Regex("New spool: #(\\d+)").find(it) }
        assertTrue("Add failed: ${allText()}", done != null)
        val spoolId = done!!.groupValues[1].toInt()
        assertTrue(exists("linked tag $uid to spool $spoolId"))
        Log.i(TAG, "ADDED spool=$spoolId tag=$uid")
        click("Done")
        waitFor("Search")

        // Tap the new tag on Home: the card shows the new spool.
        emitUntil(uid) { exists("Gross weight (g)") }
        assertTrue("card: ${allText()}", compose.onAllNodes(hasText("conjure", substring = true, ignoreCase = true))
            .fetchSemanticsNodes().isNotEmpty())
        field("Gross weight (g)").performTextInput("700")
        click("Update weight")
        waitFor("Remaining would change from", substring = true, timeoutMs = 30_000)
        click("Confirm")
        waitFor("Weight updated", timeoutMs = 30_000)
        Log.i(TAG, "card after update: ${allText()}")
        click("Done")

        Log.i(TAG, "spool=$spoolId tag=$uid")
        unpairedOnServerLandsOnPair(uid)
    }

    /** Resumes `main` at its unpair step on the phone `main` left paired (same tag), without another paid Read. */
    @Test fun unpair() {
        assumeTrue(arg("fkPhase") == "unpair")
        waitFor("Search") // Home: still paired
        unpairedOnServerLandsOnPair(need("fkTag"))
    }

    /** The driver unpairs this phone on the server when it sees `UNPAIR_NOW`; the next call must land on Pair. */
    private fun unpairedOnServerLandsOnPair(uid: String) {
        Log.i(TAG, "UNPAIR_NOW tag=$uid")
        val until = System.currentTimeMillis() + 180_000
        while (!exists(UNPAIRED_MESSAGE) && System.currentTimeMillis() < until) {
            if (!exists("Pair with your server")) TagEvents.emit(uid)
            Thread.sleep(3_000)
            compose.waitForIdle()
        }
        waitFor(UNPAIRED_MESSAGE)
        waitFor("Pair with your server")
        assertFalse("the spool card must not stay open", exists("Gross weight (g)"))
        Log.i(TAG, "UNPAIRED_SHOWN")
    }

    @Test fun cold() {
        assumeTrue(arg("fkPhase") == "cold")
        waitFor("Pair with your server")
        waitFor(UNPAIRED_MESSAGE)
        assertFalse(exists("Add spools"))
    }

    @Test fun forget() {
        assumeTrue(arg("fkPhase") == "forget")
        waitFor("Pair with your server")
        pairManually(need("fkCode"))
        assertFalse(exists(UNPAIRED_MESSAGE))

        click("Settings")
        click("Forget server")
        waitFor("Forget this server?")
        click("Forget")
        waitFor("Pair with your server")
        assertFalse("a forgotten server is not an unpaired one", exists(UNPAIRED_MESSAGE))
        compose.activityRule.scenario.recreate()
        waitFor("Pair with your server")
    }

    // ---------- steps ----------

    private fun pairManually(code: String) {
        click("Enter address")
        field("Host name or IP address").performTextClearance()
        field("Host name or IP address").performTextInput(need("fkHost"))
        field("Port").performTextClearance()
        field("Port").performTextInput(arg("fkPort") ?: "8710")
        click("Connect")
        waitFor("Check the server's fingerprint", timeoutMs = 30_000)
        arg("fkFingerprint")?.let { compose.onNodeWithText(groupFingerprint(it.lowercase())).assertExists() }
        click("It matches")
        field("6-digit code").performTextInput(code)
        click("Pair")
        waitFor("Search", timeoutMs = 30_000) // Home
        Log.i(TAG, "PAIRED ${allText()}")
    }

    /** Taps are only collected while a screen listens, so repeat until [seen]. */
    private fun emitUntil(uid: String, seen: () -> Boolean) {
        val until = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < until) {
            TagEvents.emit(uid)
            try {
                compose.waitUntil(3_000) { seen() }
                return
            } catch (_: Throwable) { // not yet
            }
        }
        compose.waitUntil(1) { seen() }
    }

    // ---------- helpers ----------

    private fun field(label: String, substring: Boolean = false) =
        compose.onNode(hasText(label, substring = substring) and hasSetTextAction())

    private fun click(text: String) {
        val node = compose.onNodeWithText(text)
        try {
            node.performScrollTo()
        } catch (_: AssertionError) { // not inside a scrolling container
        }
        node.performClick()
    }

    private fun exists(text: String, substring: Boolean = false) =
        compose.onAllNodes(hasText(text, substring = substring)).fetchSemanticsNodes().isNotEmpty()

    private fun waitFor(text: String, substring: Boolean = false, timeoutMs: Long = 15_000) {
        compose.waitUntil(timeoutMs) { exists(text, substring) }
    }

    private fun SemanticsNodeInteraction.text(): String? =
        fetchSemanticsNode().config.getOrNull(SemanticsProperties.EditableText)?.text

    private fun allText(): List<String> = compose.onAllNodes(hasText("", substring = true)).fetchSemanticsNodes()
        .flatMap { n -> n.config.getOrNull(SemanticsProperties.Text).orEmpty().map { it.text } }

    /** A random 7-byte UID in the app's canonical format, so each run links a tag no spool has yet. */
    private fun newUid(): String = formatUid(ByteArray(7).also { SecureRandom().nextBytes(it) })

    /** Files pushed with adb live in shell space the app cannot read; `cat` runs as the shell user. */
    private fun readDeviceFile(path: String): ByteArray {
        val pfd = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand("cat $path")
        val bytes = ParcelFileDescriptor.AutoCloseInputStream(pfd).use { it.readBytes() }
        assertTrue("could not read $path from the device", bytes.size > 1000)
        assertEquals("not a JPEG: $path", 0xFF.toByte(), bytes[0])
        return bytes
    }
}
