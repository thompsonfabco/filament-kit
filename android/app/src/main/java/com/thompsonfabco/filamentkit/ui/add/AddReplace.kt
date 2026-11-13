package com.thompsonfabco.filamentkit.ui.add

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.CreationExtras
import kotlin.reflect.KClass

/** What may happen to an add flow that is open when the spool card asks for a new one (05-android-app 2.5, Back rules). */
enum class AddReplace {
    /** Its draft is saved (photo path), or it is finished: it may be replaced. */
    Replace,

    /** It is writing or checking with the Hub: it stays, on screen. */
    KeepWriting,

    /** A hand add with fields typed in, nothing saved: ask "Leave without saving?" first. */
    AskLeave,
}

fun addReplace(state: AddUiState): AddReplace = when {
    state.stage == Stage.Previewing || state.stage == Stage.Adding -> AddReplace.KeepWriting
    state.manual && state.stage != Stage.Done && state.items.isNotEmpty() -> AddReplace.AskLeave
    else -> AddReplace.Replace
}

/**
 * The rule for the add flow whose screen is [owner] (its back stack entry), found in the entry's own view model store;
 * [AddReplace.Replace] when that entry never made one.
 */
fun addReplaceOf(owner: ViewModelStoreOwner): AddReplace {
    val none = object : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: KClass<T>, extras: CreationExtras): T = throw IllegalStateException()
    }
    val vm = runCatching { ViewModelProvider.create(owner.viewModelStore, none)[AddViewModel::class] }.getOrNull()
    return vm?.let { addReplace(it.state.value) } ?: AddReplace.Replace
}
