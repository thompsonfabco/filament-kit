package com.thompsonfabco.filamentkit.ui.history

import android.content.Context
import android.view.accessibility.AccessibilityManager
import androidx.compose.material3.SnackbarResult
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ActivityEvent
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.spool.SpoolResult
import com.thompsonfabco.filamentkit.ui.spool.formatGrams
import com.thompsonfabco.filamentkit.ui.spool.LoadTexts

/**
 * How long the Undo toast is held: 10 seconds, or the time the phone's accessibility settings recommend for a message
 * with controls (people who asked for more time to act get it).
 */
internal fun undoHoldMs(context: Context): Long {
    val manager = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager
    val recommended = manager?.getRecommendedTimeoutMillis(UndoRules.TOAST_MS, AccessibilityManager.FLAG_CONTENT_CONTROLS)
    return UndoRules.holdMs(recommended ?: UndoRules.TOAST_MS)
}

/**
 * The toast of an action: [text] with Undo when the Hub offers one ([event] found), else the plain toast. Pressing Undo
 * calls [undo] (which also refreshes the screen) and says what came of it in a second toast.
 */
internal suspend fun SwToastState.showUndoable(
    text: String,
    undoLabel: String,
    event: ActivityEvent?,
    holdMs: Long,
    undo: suspend (ActivityEvent) -> UndoOutcome,
) {
    if (event == null) {
        show(text)
        return
    }
    if (show(text, undoLabel, holdMs = holdMs) != SnackbarResult.ActionPerformed) return
    show(undo(event).text)
}

/** The toast's words for a spool screen result: the same sentence as the result line. */
@Composable
internal fun spoolResultToastText(result: SpoolResult): String = when (result) {
    is SpoolResult.WeightUpdated ->
        stringResource(R.string.spool_result_weight, result.left?.let { formatGrams(it) } ?: stringResource(R.string.common_unknown))
    is SpoolResult.Moved -> stringResource(R.string.spool_result_moved, result.location)
    SpoolResult.MarkedEmpty -> stringResource(R.string.spool_result_empty)
    SpoolResult.TagLinked -> stringResource(R.string.spool_result_tag_linked)
    SpoolResult.TagMoved -> stringResource(R.string.spool_result_tag_moved)
    is SpoolResult.Loaded -> stringResource(R.string.spool_result_loaded, result.printer, result.slot)
    is SpoolResult.LoadedUnconfirmed -> stringResource(R.string.spool_load_unconfirmed)
    is SpoolResult.Waiting -> LoadTexts.waitingIn(result.slot)
}

/** The offer a spool screen result makes, or null when the Hub has no Undo for it. */
internal fun undoOfferFor(spoolId: Int, result: SpoolResult, serial: Long): UndoOffer? {
    val kinds = when (result) {
        is SpoolResult.WeightUpdated -> setOf(UndoKinds.WEIGHED)
        is SpoolResult.Moved -> setOf(UndoKinds.MOVED)
        SpoolResult.MarkedEmpty -> setOf(UndoKinds.EMPTIED)
        // a tag link writes a kind the contract does not name (R84 12.3: it may not be undoable at all)
        SpoolResult.TagLinked, SpoolResult.TagMoved -> UndoKinds.ALL
        is SpoolResult.Loaded, is SpoolResult.LoadedUnconfirmed, is SpoolResult.Waiting -> setOf(UndoKinds.LOADED)
    }
    return UndoOffer(listOf("spool:$spoolId"), kinds, serial)
}
