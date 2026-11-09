package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.ui.pair.PairTexts
import com.thompsonfabco.filamentkit.ui.pair.groupFingerprint

/**
 * Shows the paired server. [onPairAgain] opens pairing; [onForget] should call `Settings.clear()` and go to pairing.
 * [onLicences] opens the licences screen.
 */
@Composable
fun SettingsScreen(
    config: ServerConfig?,
    onPairAgain: () -> Unit,
    onForget: () -> Unit,
    modifier: Modifier = Modifier,
    onLicences: () -> Unit = {},
    skipFingerprintCheck: Boolean = false,
    onSkipFingerprintCheck: (Boolean) -> Unit = {},
) {
    var confirmForget by remember { mutableStateOf(false) }
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        if (config == null) {
            Text("No server is paired.")
        } else {
            Text("Server", style = MaterialTheme.typography.titleMedium)
            Text(config.name)
            Text("${config.endpoints.firstOrNull().orEmpty()}:${config.port}")
            Text("Certificate fingerprint")
            Text(groupFingerprint(config.fingerprint), fontFamily = FontFamily.Monospace)
        }
        Button(onClick = onPairAgain, modifier = Modifier.fillMaxWidth()) { Text("Pair again") }
        if (config != null) {
            OutlinedButton(onClick = { confirmForget = true }, modifier = Modifier.fillMaxWidth()) { Text("Forget server") }
        }
        Row(
            Modifier.fillMaxWidth().toggleable(
                value = skipFingerprintCheck,
                role = Role.Switch,
                onValueChange = onSkipFingerprintCheck,
            ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(PairTexts.SKIP_CHECK_LABEL, Modifier.weight(1f).padding(end = 12.dp))
            Switch(checked = skipFingerprintCheck, onCheckedChange = null)
        }
        Text(PairTexts.SKIP_CHECK_HELP, style = MaterialTheme.typography.bodySmall)
        TextButton(onClick = onLicences, modifier = Modifier.fillMaxWidth()) { Text("Licences and third-party software") }
    }
    if (confirmForget) {
        AlertDialog(
            onDismissRequest = { confirmForget = false },
            title = { Text("Forget this server?") },
            text = { Text("This phone will stop using it until you pair again.") },
            confirmButton = {
                TextButton(onClick = { confirmForget = false; onForget() }) { Text("Forget") }
            },
            dismissButton = { TextButton(onClick = { confirmForget = false }) { Text("Cancel") } },
        )
    }
}
