package com.thompsonfabco.filamentkit.ui.add

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import kotlinx.coroutines.launch

/**
 * One step of the add-spools flow (05-android-app 6), a destination of its own: [CaptureScreen] (Photos), [ReviewScreen]
 * (Check the spools), [PreviewScreen] or [DoneScreen]; a hand add starts at Check. [step] is the step this destination
 * is; [onStep] says where the draft is now, so the stack follows it (forward pushes, back pops). [onClose] leaves the
 * flow (the draft stays on the phone; a read or an add goes on); [onDone] follows "Done" and Back from the last step;
 * [onAddMore] starts a new draft on the same path; [onPairAgain] is offered when the Hub no longer accepts this phone or
 * its certificate changed; [onAddByHand] leaves this add for one by hand; [onAddCatalogLine] opens the Filament Catalog
 * form filled from a panel; [onOpenRecord] opens the Hub's record of the add. Back goes one step back (2.5).
 */
@Composable
fun AddSpoolsScreen(
    vm: AddViewModel,
    step: AddStep,
    onStep: (desired: AddStep) -> Unit,
    /** Takes this step off the stack at once: the system Back (and the Home tab pressed again) goes one step at a time. */
    onPop: () -> Unit,
    onClose: () -> Unit,
    onDone: () -> Unit,
    onAddMore: () -> Unit,
    onPairAgain: () -> Unit,
    onAddByHand: () -> Unit,
    onAddCatalogLine: (vendor: String, line: String, material: String) -> Unit,
    onOpenRecord: (String) -> Unit,
    modifier: Modifier = Modifier,
    camera: @Composable (photos: Int, onPhoto: (ByteArray) -> Unit) -> Unit = { n, onPhoto -> CameraCapture(n, onPhoto) },
) {
    val state by vm.state.collectAsStateWithLifecycle()
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val removedPhoto = stringResource(R.string.add_photos_removed)
    val removedSpool = stringResource(R.string.add_review_removed)
    val undo = stringResource(R.string.common_undo)
    // a removed photo or spool is answered with a snackbar that can put it back
    LaunchedEffect(vm, toast) {
        vm.events.collect { event ->
            scope.launch {
                val text = if (event == AddEvent.PhotoRemoved) removedPhoto else removedSpool
                val result = toast?.show(text, undo)
                if (result == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                    if (event == AddEvent.PhotoRemoved) vm.undoPhoto() else vm.undoRemoveItem()
                }
            }
        }
    }
    // the stack follows the draft: a step that is reached pushes its destination, a step back pops this one
    val where = stepOf(state.stage)
    LaunchedEffect(where) { onStep(where) }
    when (step) {
        AddStep.Photos -> BackHandler(onBack = onClose)
        AddStep.Check -> BackHandler(onBack = if (state.manual) onClose else ({ vm.backToPhotos(); onPop() }))
        // an add that is under way goes on when the person leaves; its result arrives as a snackbar
        AddStep.Preview -> BackHandler(onBack = if (state.stage == Stage.Adding) onClose else ({ vm.backToCheck(); onPop() }))
        AddStep.Done -> BackHandler(onBack = onDone)
    }
    when (step) {
        AddStep.Photos -> CaptureScreen(state, vm, onPairAgain, onAddByHand, modifier, camera)
        AddStep.Check -> ReviewScreen(state, vm, onPairAgain, onAddByHand, onAddCatalogLine, modifier)
        AddStep.Preview -> PreviewScreen(state, vm, onPairAgain, onAddByHand, modifier)
        AddStep.Done -> DoneScreen(state, onDone, onAddMore, onOpenRecord, modifier)
    }
}
