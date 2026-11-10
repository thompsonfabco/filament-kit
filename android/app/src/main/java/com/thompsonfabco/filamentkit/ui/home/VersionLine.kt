package com.thompsonfabco.filamentkit.ui.home

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/** `App 0.4.3 · Server 0.4.3`; the server part is left out while a paired server's version is not known. */
internal fun versionLine(app: String, paired: Boolean, server: String?): String = when {
    !paired -> "App $app · not paired"
    server.isNullOrBlank() -> "App $app"
    else -> "App $app · Server $server"
}

/** The small version line, directly under the title of the home and pairing screens (inside their padded column). */
@Composable
internal fun VersionLine(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}
