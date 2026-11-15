package com.thompsonfabco.filamentkit.ui.add

import android.graphics.Bitmap
import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.test.junit4.StateRestorationTester
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.emptyFlow
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The Add spools viewer follows a photo by its own identity, not by its place in the strip (05-android-app 10.5). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class AddPhotoViewerFollowsTest {
    @get:Rule val rule = createComposeRule()

    private fun SemanticsNodeInteraction.tapThumbnail() = performTouchInput { click(Offset(width * 0.75f, height * 0.75f)) }

    private fun png(): ByteArray =
        ByteArrayOutputStream().also { Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888).compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()

    /** Photos 1 and 2 cannot be decoded, photo 3 can. */
    private fun vm(): AddViewModel {
        val dir = kotlin.io.path.createTempDirectory("add-drafts").toFile().also { it.deleteOnExit() }
        val vm = AddViewModel(FakeIntakeApi(), DraftStore(dir), taps = emptyFlow(), prepare = { it }, io = Dispatchers.Unconfined)
        vm.addPhoto(byteArrayOf(1, 2, 3)); vm.addPhoto(byteArrayOf(4, 5, 6)); vm.addPhoto(png())
        return vm
    }

    private fun content(vm: AddViewModel): @androidx.compose.runtime.Composable () -> Unit = {
        var step by mutableStateOf(AddStep.Photos)
        SpoolwardenTheme(Look.Console, Appearance.Light) {
            AddSpoolsScreen(
                vm, step, onStep = { step = it }, onPop = {}, onClose = {}, onDone = {}, onAddMore = {}, onPairAgain = {},
                onAddByHand = {}, onAddCatalogLine = { _, _, _ -> }, onOpenRecord = {}, camera = { _, _ -> },
            )
        }
    }

    private fun show(): AddViewModel = vm().also { rule.setContent(content(it)); rule.waitForIdle() }

    private fun swipeViewer() {
        rule.onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.HorizontalScrollAxisRange) and hasAnyAncestor(isDialog()))
            .performTouchInput { swipeLeft() }
        rule.waitForIdle()
    }

    @Test fun removingAnEarlierPhotoKeepsTheShownPhotoAndItsCounter() {
        val vm = show()
        rule.onNodeWithContentDescription("Photo 2").tapThumbnail()
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
        rule.runOnUiThread { vm.removePhoto(0) }
        rule.waitForIdle()
        rule.onNodeWithText("Photo 1 of 2").assertExists()
        rule.onNodeWithText("Photo 2 of 2").assertDoesNotExist()
    }

    @Test fun tryAgainLoadsTheShownPhotoAfterAnEarlierOneIsRemoved() {
        val vm = show()
        rule.onNodeWithContentDescription("Photo 2").tapThumbnail()
        rule.waitForIdle()
        rule.onNodeWithText("The photo could not be loaded.").assertExists()
        rule.runOnUiThread { vm.removePhoto(0) }
        rule.waitForIdle()
        rule.onNodeWithText("Try again").performClick()
        rule.waitForIdle()
        // the shown photo is still the unreadable one; the readable photo that moved into its slot is not loaded in its place
        rule.onNodeWithText("The photo could not be loaded.").assertExists()
        rule.onNodeWithText("Photo 1 of 2").assertExists()
    }

    @Test fun removingThePhotoOpenedFirstWhileAnotherIsShownKeepsTheViewerOpen() {
        val vm = show()
        rule.onNodeWithContentDescription("Photo 1").tapThumbnail()
        rule.waitForIdle()
        swipeViewer()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
        rule.runOnUiThread { vm.removePhoto(0) }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Close photo").assertExists()
        rule.onNodeWithText("Photo 1 of 2").assertExists()
    }

    @Test fun removingTheShownPhotoAfterSwipingClosesTheViewer() {
        val vm = show()
        rule.onNodeWithContentDescription("Photo 1").tapThumbnail()
        rule.waitForIdle()
        swipeViewer()
        rule.runOnUiThread { vm.removePhoto(1) }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Close photo").assertDoesNotExist()
    }

    @Test fun theShownPhotoSurvivesRecreatingTheActivity() {
        val vm = vm()
        val restoration = StateRestorationTester(rule)
        restoration.setContent(content(vm))
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Photo 1").tapThumbnail()
        rule.waitForIdle()
        swipeViewer()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
        restoration.emulateSavedInstanceStateRestore()
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
        rule.onNodeWithText("Photo 1 of 3").assertDoesNotExist()
    }

    @Test fun aTapOutsideTheThumbnailsRoundedCornerDoesNotOpenIt() {
        show()
        rule.onNodeWithContentDescription("Photo 1").performTouchInput { click(Offset(1f, height - 2f)) }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Close photo").assertDoesNotExist()
        rule.onNodeWithContentDescription("Photo 1").tapThumbnail()
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Close photo").assertExists()
    }
}
