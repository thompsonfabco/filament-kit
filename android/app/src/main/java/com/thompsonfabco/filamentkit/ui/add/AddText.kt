package com.thompsonfabco.filamentkit.ui.add

import android.content.Context
import androidx.annotation.PluralsRes
import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

/**
 * A text of the add flow that the view model cannot resolve (it has no context): a catalogue text with its arguments,
 * a plural chosen by [count], or the Hub's own words ([verbatim]) shown as given (05-android-app 15). The screen turns
 * it into words with [string].
 */
data class AddText(
    @StringRes val res: Int = 0,
    val args: List<Any> = emptyList(),
    /** When set, [res] is a plurals resource and [count] picks the form ([args] are all its format arguments). */
    val count: Int? = null,
    val verbatim: String? = null,
) {
    fun resolve(context: Context): String = when {
        verbatim != null -> verbatim
        count != null -> context.resources.getQuantityString(res, count, *args.toTypedArray())
        else -> context.getString(res, *args.toTypedArray())
    }

    companion object {
        fun of(@StringRes res: Int, vararg args: Any) = AddText(res, args.toList())

        fun plural(@PluralsRes res: Int, count: Int, vararg args: Any) = AddText(res, args.toList(), count = count)

        /** The Hub's message, as it gave it. */
        fun hub(text: String) = AddText(verbatim = text)
    }
}

@Composable
internal fun AddText.string(): String = resolve(LocalContext.current)
