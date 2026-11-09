package com.thompsonfabco.filamentkit.ui.home

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** `App 0.4.3 · Server 0.4.3`; the server part is left out while a paired server's version is not known. */
internal fun versionLine(app: String, paired: Boolean, server: String?): String = when {
    !paired -> "App $app · not paired"
    server.isNullOrBlank() -> "App $app"
    else -> "App $app · Server $server"
}

/** The small line at the bottom of the first screen. */
@Composable
internal fun VersionLine(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
    )
}
