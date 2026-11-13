package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.pair.Mismatch
import com.thompsonfabco.filamentkit.ui.pair.PairTexts
import com.thompsonfabco.filamentkit.ui.pair.groupFingerprint
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

// The notices and colour the screens of this section and the other screens that show a printer or a Hub problem
// still share; each moves to the catalogue with the step that rebuilds the last screen using it.

@Composable
internal fun stateColor(state: String): Color = when (state) {
    "connected" -> SpoolwardenTheme.colors.ok
    "wrong_code", "cert_changed" -> SpoolwardenTheme.colors.bad
    "needs_developer_mode" -> SpoolwardenTheme.colors.warn
    else -> SpoolwardenTheme.colors.muted
}

/** "Trust the new certificate" on the changed-certificate notice: the Pair screen's path, offered when [canTrust]. */
class TrustAction(
    val canTrust: (expected: String) -> Boolean,
    val trust: (expected: String, actual: String) -> Unit,
    val failed: Boolean = false,
    val reset: () -> Unit = {},
)

internal const val TRUST_FAILED = "The new certificate could not be trusted yet. Check that the server is reachable and " +
    "try again, or pair again."

@Composable
internal fun MismatchNotice(expected: String, actual: String, onPairAgain: () -> Unit, trust: TrustAction? = null) {
    // the Pair screen's words and grouped fingerprint, for a saved pairing whose certificate changed
    val text = mismatchText(MismatchSource.STORED)
    // a failure belongs to the notice it was shown under: gone when it leaves or shows another certificate
    DisposableEffect(expected, actual) { onDispose { trust?.reset?.invoke() } }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(text.title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.error)
        Text(text.body)
        Text(text.actualLabel)
        Text(groupFingerprint(actual), fontFamily = FontFamily.Monospace)
        text.whereToCheck?.let { Text(it) }
        val trustLabel = text.trustButton?.takeIf { trust?.canTrust(expected) == true }
        if (trustLabel == null) {
            Button(onClick = onPairAgain) { Text(text.button) }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Button(onClick = { trust?.trust?.invoke(expected, actual) }, modifier = Modifier.weight(1f)) {
                    Text(trustLabel, textAlign = TextAlign.Center)
                }
                OutlinedButton(onClick = onPairAgain, modifier = Modifier.weight(1f)) {
                    Text(text.button, textAlign = TextAlign.Center)
                }
            }
            if (trust?.failed == true) Text(TRUST_FAILED, color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
internal fun UnpairedNotice(onPairAgain: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("This phone is no longer paired with the server.", color = MaterialTheme.colorScheme.error)
        Button(onClick = onPairAgain) { Text("Pair again") }
    }
}
