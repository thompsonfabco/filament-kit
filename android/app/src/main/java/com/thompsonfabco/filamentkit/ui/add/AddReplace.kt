package com.thompsonfabco.filamentkit.ui.add

/** What may happen to an add flow that is open when the spool card asks for a new one (05-android-app 2.5, Back rules). */
enum class AddReplace {
    /** Its draft is saved (photo or hand path), or it is finished: it may be replaced. */
    Replace,

    /** It is writing or checking with the Hub: it stays, on screen. */
    KeepWriting,
}

/** Add spools never asks before leaving: every change is saved in its draft (05-android-app 6). */
fun addReplace(state: AddUiState): AddReplace = when (state.stage) {
    Stage.Previewing, Stage.Adding -> AddReplace.KeepWriting
    else -> AddReplace.Replace
}
