package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.ui.pair.SkipCheckSwitch
import com.thompsonfabco.filamentkit.ui.pair.groupFingerprint

/**
 * Shows the paired server. [onPairAgain] opens pairing; [onForget] should call `Settings.clear()` and go to pairing.
 * [onLicences] opens the licences screen. [setupUrl] gives the server's setup page address at the moment it is opened
 * (the host the app reaches it on now), for the admin features that live only there.
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
    setupUrl: () -> String? = { null },
) {
    var confirmForget by remember { mutableStateOf(false) }
    var openProblem by remember { mutableStateOf<String?>(null) }
    val links = LocalUriHandler.current
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (config == null) {
            Text("No server is paired.")
        } else {
            Text("Server", style = MaterialTheme.typography.titleMedium)
            Text(config.name)
            Text("${config.endpoints.firstOrNull().orEmpty()}:${config.port}")
            Text("Certificate fingerprint")
            Text(groupFingerprint(config.fingerprint), fontFamily = FontFamily.Monospace)
        }
        if (config != null) {
            OutlinedButton(onClick = {
                val url = setupUrl()
                openProblem = if (url == null) SetupPageTexts.NO_ADDRESS
                else if (runCatching { links.openUri(url) }.isSuccess) null else SetupPageTexts.NO_BROWSER
            }, modifier = Modifier.fillMaxWidth()) { Text(SetupPageTexts.BUTTON) }
            Text(SetupPageTexts.HELP, style = MaterialTheme.typography.bodySmall)
            openProblem?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
        Button(onClick = onPairAgain, modifier = Modifier.fillMaxWidth()) { Text("Pair again") }
        if (config != null) {
            OutlinedButton(onClick = { confirmForget = true }, modifier = Modifier.fillMaxWidth()) { Text("Forget server") }
        }
        SkipCheckSwitch(skipFingerprintCheck, onSkipFingerprintCheck)
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

/** "Open the setup page": its texts and its address. */
object SetupPageTexts {
    const val BUTTON = "Open the setup page"
    const val HELP = "The server's own page in your browser, on the home network, for what this app doesn't do " +
        "(modules, keys, devices, backups). It asks for the setup code; the browser warns once about the server's own " +
        "certificate, whose fingerprint is the one above."
    const val NO_BROWSER = "No browser on this phone could open it"
    const val NO_ADDRESS = "The server's address isn't known yet"

    /** `https://<host>:<port>/setup` from the app's `https://<host>:<port>` (null: not paired). */
    fun url(base: String?): String? =
        base?.takeIf { it.startsWith("https://") && !it.startsWith("https://unpaired.invalid") }?.trimEnd('/')?.plus("/setup")
}
