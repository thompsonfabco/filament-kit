package com.thompsonfabco.filamentkit.ui.add

import android.graphics.Bitmap
import android.os.Build
import androidx.activity.ComponentDialog
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.click
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.LocalWindowClass
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import java.io.File
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.emptyFlow
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowDialog

/** A thumbnail on the Photos step opens that photo full screen (05-android-app 6, viewer as 10.5); the draft stays as it was. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class AddPhotoViewerTest {
    @get:Rule val rule = createComposeRule()

    /** The thumbnail's lower right: its remove button sits in the upper right corner. */
    private fun SemanticsNodeInteraction.tapThumbnail() = performTouchInput { click(Offset(width * 0.75f, height * 0.75f)) }

    private var window by mutableStateOf(WindowClass.Phone)

    private fun show(photos: Int, loader: (suspend (File) -> ImageBitmap?)? = null): AddViewModel {
        val dir = kotlin.io.path.createTempDirectory("add-drafts").toFile().also { it.deleteOnExit() }
        val vm = AddViewModel(FakeIntakeApi(), DraftStore(dir), taps = emptyFlow(), prepare = { it }, io = Dispatchers.Unconfined)
        repeat(photos) { vm.addPhoto(byteArrayOf(it.toByte(), 2, 3)) }
        window = WindowClass.Phone
        rule.setContent {
            var step by mutableStateOf(AddStep.Photos)
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                // the window class is the test's to change, as a phone turned sideways changes it
                CompositionLocalProvider(
                    LocalWindowClass provides window,
                    *listOfNotNull(loader?.let { LocalThumbnailLoader provides it }).toTypedArray(),
                ) {
                    AddSpoolsScreen(
                        vm, step, onStep = { step = it }, onPop = {}, onClose = {}, onDone = {}, onAddMore = {}, onPairAgain = {},
                        onAddByHand = {}, onAddCatalogLine = { _, _, _ -> }, onOpenRecord = {}, camera = { _, _ -> },
                    )
                }
            }
        }
        rule.waitForIdle()
        return vm
    }

    @Test fun aThumbnailOpensItsOwnPhotoAndBackClosesIt() {
        val vm = show(3)
        rule.onNodeWithContentDescription("Close photo").assertDoesNotExist()
        rule.onNodeWithContentDescription("Photo 2").tapThumbnail()
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
        rule.onNodeWithContentDescription("Close photo").assertExists()
        rule.runOnUiThread { (ShadowDialog.getLatestDialog() as ComponentDialog).onBackPressedDispatcher.onBackPressed() }
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 3").assertDoesNotExist()
        assertEquals("the draft is unchanged", 3, vm.state.value.photos.size)
        rule.onNodeWithContentDescription("Photo 3").tapThumbnail()
        rule.waitForIdle()
        rule.onNodeWithText("Photo 3 of 3").assertExists()
        rule.onNodeWithContentDescription("Close photo").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Photo 3 of 3").assertDoesNotExist()
    }

    @Test fun theRemoveButtonRemovesAndDoesNotOpenTheViewer() {
        val vm = show(2)
        rule.onNodeWithContentDescription("Remove photo 1 of 2").performClick()
        rule.waitForIdle()
        assertEquals(1, vm.state.value.photos.size)
        rule.onNodeWithContentDescription("Close photo").assertDoesNotExist()
    }

    @Test fun aTapAsTheDecodedPictureReplacesThePlaceholderStillOpensTheViewer() {
        val decoded = CompletableDeferred<Unit>()
        show(2) { _ ->
            decoded.await()
            Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888).asImageBitmap()
        }
        rule.onNodeWithContentDescription("Photo 2").performTouchInput { down(Offset(width * 0.75f, height * 0.75f)) }
        // the picture arrives between the finger going down and coming up
        decoded.complete(Unit)
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Photo 2").performTouchInput { up() }
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 2").assertExists()
    }

    @Test fun theThumbnailIsAButton() {
        show(1)
        rule.onNodeWithContentDescription("Photo 1").assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Button))
    }

    @Test fun theViewerStaysOpenWhenTheWindowChangesClass() {
        show(3)
        rule.onNodeWithContentDescription("Photo 2").tapThumbnail()
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
        window = WindowClass.Tablet
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
        window = WindowClass.Phone
        rule.waitForIdle()
        rule.onNodeWithText("Photo 2 of 3").assertExists()
    }

    @Test fun theViewerClosesWhenItsPhotoIsRemoved() {
        val vm = show(2)
        rule.onNodeWithContentDescription("Photo 1").tapThumbnail()
        rule.waitForIdle()
        rule.onNodeWithText("Photo 1 of 2").assertExists()
        rule.runOnUiThread { vm.removePhoto(0) }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Close photo").assertDoesNotExist()
        assertEquals(1, vm.state.value.photos.size)
    }
}
