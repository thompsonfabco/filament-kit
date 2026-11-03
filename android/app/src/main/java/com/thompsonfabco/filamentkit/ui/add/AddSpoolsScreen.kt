package com.thompsonfabco.filamentkit.ui.add

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * The whole add-spools flow: [CaptureScreen] until the labels are read, then [ReviewScreen]; a manual add is
 * [ReviewScreen] throughout. [onClose] leaves the flow (the draft stays on the phone); [onDone] follows a successful
 * add; [onPairAgain] is offered when the server no longer accepts this phone or its certificate changed.
 */
@Composable
fun AddSpoolsScreen(
    vm: AddViewModel,
    onClose: () -> Unit,
    onDone: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val state by vm.state.collectAsStateWithLifecycle()
    when {
        state.manual -> {
            BackHandler(enabled = state.stage == Stage.Review || state.stage == Stage.Preview, onBack = onClose)
            ReviewScreen(state, vm, onDone = onDone, onPairAgain = onPairAgain, modifier = modifier, onClose = onClose)
        }
        state.stage == Stage.Capture || state.stage == Stage.Reading -> {
            BackHandler(enabled = state.stage == Stage.Capture, onBack = onClose)
            CaptureScreen(state, vm, onCancel = onClose, onPairAgain = onPairAgain, modifier = modifier)
        }
        else -> {
            BackHandler(enabled = state.stage == Stage.Review || state.stage == Stage.Preview, onBack = vm::backToPhotos)
            ReviewScreen(state, vm, onDone = onDone, onPairAgain = onPairAgain, modifier = modifier)
        }
    }
}
