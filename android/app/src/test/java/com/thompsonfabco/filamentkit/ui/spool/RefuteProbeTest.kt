package com.thompsonfabco.filamentkit.ui.spool

import android.os.Build
import androidx.activity.ComponentDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowDialog

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class RefuteProbeTest {
    @get:Rule val rule = createComposeRule()

    @Test fun systemBackWithATypedWeightAsksAndKeepsIt() {
        val backend = FakeSpoolBackend()
        backend.updateAnswer = { _, _, _, _ -> spoolJson(214, remaining = 482.0) }
        SpoolCache.clear()
        val vm = SpoolViewModel(214, backend, spoolJson(214, tag = "04A1B2").toSpoolSummary(), null)
        rule.setContent { SpoolwardenTheme(Look.Console, Appearance.Light) { SpoolScreen(vm, onLoad = {}, onPairAgain = {}) } }
        rule.waitForIdle()
        rule.onNodeWithText("Update weight").performClick()
        rule.waitForIdle()
        vm.setWeight("622")
        rule.waitForIdle()
        rule.runOnUiThread { (ShadowDialog.getLatestDialog() as ComponentDialog).onBackPressedDispatcher.onBackPressed() }
        rule.waitForIdle()
        assertNotNull("typed weight kept after system Back", vm.state.value.weight)
        assertEquals("622", vm.state.value.weight?.text)
        rule.onNodeWithText("Leave without saving?").assertExists()
    }

    @Test fun refreshByTagKeepsThisSpool() {
        val backend = FakeSpoolBackend()
        SpoolCache.clear()
        val vm = SpoolViewModel(214, backend, spoolJson(214, tag = "04A1B2").toSpoolSummary(), null)
        // the tag was moved to spool 300 meanwhile
        backend.tagAnswer = spoolJson(300, tag = "04A1B2", remaining = 10.0)
        vm.refresh()
        org.robolectric.shadows.ShadowLooper.idleMainLooper()
        assertEquals("the screen of spool 214 still shows spool 214", 214, vm.state.value.spool?.id)
    }

    @Test fun restartWithoutTagNotFoundShowsSomething() {
        val backend = FakeSpoolBackend()
        backend.spools = emptyList()
        SpoolCache.clear()
        val vm = SpoolViewModel(214, backend, null, null)
        org.robolectric.shadows.ShadowLooper.idleMainLooper()
        val s = vm.state.value
        assert(s.spool != null || s.failure != null || s.loading) { "blank: spool=null failure=null loading=false" }
    }
}
