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
 * The whole add-spools flow (05-android-app 6): [CaptureScreen] (Photos), [ReviewScreen] (Check the spools), [PreviewScreen]
 * and [DoneScreen]; a hand add starts at Check. [onClose] leaves the flow (the draft stays on the phone); [onDone] follows
 * "Done" and Back from the last step; [onPairAgain] is offered when the Hub no longer accepts this phone or its
 * certificate changed; [onAddByHand] leaves this add for one by hand; [onAddCatalogLine] opens the Filament Catalog form
 * filled from a panel; [onOpenRecord] opens the Hub's record of the add. Back goes one step back (2.5); while the Hub is
 * writing it does nothing but say why.
 */
@Composable
fun AddSpoolsScreen(
    vm: AddViewModel,
    onClose: () -> Unit,
    onDone: () -> Unit,
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
    val waiting = stringResource(R.string.add_preview_adding_wait)
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
    when (state.stage) {
        Stage.Capture -> BackHandler(onBack = onClose)
        Stage.Reading -> BackHandler(onBack = vm::cancelRead)
        Stage.Review -> BackHandler(onBack = if (state.manual) onClose else vm::backToPhotos)
        Stage.Previewing, Stage.Preview -> BackHandler(onBack = vm::backToCheck)
        Stage.Adding -> BackHandler { scope.launch { toast?.show(waiting) } }
        Stage.Done -> BackHandler(onBack = onDone)
    }
    when (stepOf(state.stage)) {
        AddStep.Photos -> CaptureScreen(state, vm, onPairAgain, onAddByHand, modifier, camera)
        AddStep.Check -> ReviewScreen(state, vm, onPairAgain, onAddByHand, onAddCatalogLine, modifier)
        AddStep.Preview -> PreviewScreen(state, vm, onPairAgain, onAddByHand, modifier)
        AddStep.Done -> DoneScreen(state, vm, onDone, onOpenRecord, modifier)
    }
}
