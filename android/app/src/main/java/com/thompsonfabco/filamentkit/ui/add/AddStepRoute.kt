package com.thompsonfabco.filamentkit.ui.add

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.navigation.NavController
import com.thompsonfabco.filamentkit.BuildConfig
import com.thompsonfabco.filamentkit.nav.AddReviewRoute
import com.thompsonfabco.filamentkit.nav.AddPhotosRoute
import com.thompsonfabco.filamentkit.nav.closeAdd
import com.thompsonfabco.filamentkit.nav.followStep

/**
 * One destination of Add spools (05-android-app 2.5): the flow of draft [draftId] is the app's ([flows]), so the screen
 * only shows it. The stack follows the draft ([followStep]); leaving drops a draft with nothing in it and keeps any
 * other on the phone. A draft that is gone (discarded elsewhere) closes the add.
 */
@Composable
internal fun AddStepRoute(
    flows: AddFlows,
    nav: NavController,
    draftId: String,
    step: AddStep,
    onPairAgain: () -> Unit,
    onAddCatalogLine: (vendor: String, line: String, material: String) -> Unit,
    onOpenRecord: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (!flows.exists(draftId)) {
        LaunchedEffect(draftId) { nav.closeAdd() }
        return
    }
    val vm = remember(draftId) { flows.get(draftId) }
    // a tap is the draft's tag on Photos and Check; on Preview and Done the shell opens the tag instead (2.6)
    if (step == AddStep.Photos || step == AddStep.Check) TagTaps(vm::onTag)
    if (BuildConfig.DEBUG && step == AddStep.Photos) LaunchedEffect(vm) { DebugPhotos.photos.collect(vm::addPhoto) }
    fun first(manual: Boolean, id: String): Any = if (manual) AddReviewRoute(id) else AddPhotosRoute(id)
    AddSpoolsScreen(
        vm = vm,
        step = step,
        onStep = { desired -> nav.followStep(draftId, step, desired) },
        onPop = { nav.popBackStack() },
        onClose = {
            nav.closeAdd()
            flows.leave(draftId)
        },
        onDone = {
            nav.closeAdd()
            flows.release(draftId)
        },
        onAddMore = {
            val manual = vm.state.value.manual
            val id = flows.again(draftId)
            nav.closeAdd()
            nav.navigate(first(manual, id))
        },
        onPairAgain = onPairAgain,
        // leaves this add (its draft stays unless it is empty) for one by hand
        onAddByHand = {
            val id = flows.start(manual = true)
            nav.closeAdd()
            flows.leave(draftId)
            nav.navigate(AddReviewRoute(id))
        },
        onAddCatalogLine = onAddCatalogLine,
        onOpenRecord = onOpenRecord,
        modifier = modifier,
    )
}
