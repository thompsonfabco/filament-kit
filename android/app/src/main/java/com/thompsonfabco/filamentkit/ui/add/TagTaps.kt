package com.thompsonfabco.filamentkit.ui.add

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.thompsonfabco.filamentkit.tags.TagEvents

/**
 * Hands tag taps to [onTag] only while the screen it sits in is showing and resumed: a screen kept in a saved tab stack
 * or under another screen takes none (05-android-app 2.6).
 */
@Composable
fun TagTaps(onTag: (String) -> Unit) {
    val latest = rememberUpdatedState(onTag)
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { TagEvents.taps.collect { latest.value(it) } }
    }
}
