package com.thompsonfabco.filamentkit.ui.pair

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.net.DiscoveredServer

/**
 * Pairing entry point: scan the QR, pick a server found on the network, or type an address.
 * [discovered] comes from `Discovery.servers()`; [onPaired] is called once a server is saved and verified.
 * [scanner] is replaceable so UI tests need no camera.
 */
@Composable
fun PairScreen(
    viewModel: PairViewModel,
    discovered: List<DiscoveredServer>,
    onPaired: () -> Unit,
    modifier: Modifier = Modifier,
    /** The same switch as in Settings, so the choice can be made before the first pairing. */
    skipCheck: Boolean = false,
    onSkipCheck: (Boolean) -> Unit = {},
    /** The certificate change is about a pairing this phone still has, so it can be kept. */
    canTrust: (Mismatch) -> Boolean = { false },
    onTrust: (Mismatch) -> Unit = {},
    scanner: @Composable (onResult: (String) -> Unit, onClose: () -> Unit) -> Unit = { onResult, onClose ->
        QrScanner(onResult = onResult, onClose = onClose, onEnterAddress = { onClose(); viewModel.startManual() })
    },
) {
    val ui by viewModel.state.collectAsState()
    var scanning by remember { mutableStateOf(false) }

    LaunchedEffect(ui.step) { if (ui.step == Step.Done) onPaired() }

    // A saved pairing's certificate question and the first screen have nothing to go back to: Back leaves the app.
    val mismatchNow = ui.mismatch
    val hasStepBack = if (mismatchNow != null) mismatchNow.source != MismatchSource.STORED else ui.step != Step.Choose
    BackHandler(enabled = hasStepBack && !scanning, onBack = viewModel::back)
    BackHandler(enabled = scanning) { scanning = false }

    if (scanning) {
        scanner({ text ->
            scanning = false
            viewModel.onQrScanned(text)
        }, { scanning = false })
        return
    }

    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        val mismatch = ui.mismatch
        // Someone whose saved certificate changed is already paired: the panel's own title says what this is.
        if (mismatch?.source != MismatchSource.STORED) {
            Text("Pair with your server", style = MaterialTheme.typography.headlineSmall)
        }

        when {
            mismatch != null -> MismatchPanel(
                PairTexts.mismatch(mismatch, ui.host),
                mismatch,
                canTrust(mismatch),
                onTrust = { onTrust(mismatch) },
                onPairAgain = viewModel::pairAgain,
            )
            ui.step == Step.Choose -> {
                ChooseStep(ui, discovered, onScan = { scanning = true }, viewModel)
                SkipCheckSwitch(skipCheck, onSkipCheck)
            }
            else -> ManualPair(
                ui = ui,
                onSubmitAddress = viewModel::submitAddress,
                onConfirmFingerprint = viewModel::confirmFingerprint,
                onRejectFingerprint = viewModel::rejectFingerprint,
                onSubmitCode = viewModel::submitCode,
                onBack = viewModel::back,
            )
        }
    }
}

/** Off by default; [PairTexts.SKIP_CHECK_HELP] says what it does. */
@Composable
internal fun SkipCheckSwitch(checked: Boolean, onChange: (Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            Modifier.fillMaxWidth().toggleable(value = checked, role = Role.Switch, onValueChange = onChange),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(PairTexts.SKIP_CHECK_LABEL, Modifier.weight(1f).padding(end = 12.dp))
            Switch(checked = checked, onCheckedChange = null)
        }
        Text(PairTexts.SKIP_CHECK_HELP, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun ChooseStep(ui: PairUi, discovered: List<DiscoveredServer>, onScan: () -> Unit, vm: PairViewModel) {
    Text(PairTexts.SCAN_INTRO)
    Button(onClick = onScan, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) {
        Text(if (ui.busy) "Connecting..." else "Scan QR code")
    }
    ui.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

    Text("Servers found on this network", style = MaterialTheme.typography.titleMedium)
    if (discovered.isEmpty()) {
        LinearProgressIndicator(Modifier.fillMaxWidth())
        Text(PairTexts.NONE_FOUND)
    } else {
        discovered.forEach { server ->
            OutlinedButton(onClick = { vm.connectDiscovered(server.host, server.port) }, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) {
                Text("${server.name} (${server.host})")
            }
        }
    }

    OutlinedButton(onClick = { vm.startManual() }, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) {
        Text("Enter address")
    }
}

/** The server's certificate is not the expected one; never trusted without the user's tap. */
@Composable
private fun MismatchPanel(
    text: MismatchText,
    mismatch: Mismatch,
    canTrust: Boolean,
    onTrust: () -> Unit,
    onPairAgain: () -> Unit,
) {
    Text(text.title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.error)
    Text(text.body)
    text.expectedLabel?.let {
        Text(it)
        Text(groupFingerprint(mismatch.expected), fontFamily = FontFamily.Monospace)
    }
    Text(text.actualLabel)
    Text(groupFingerprint(mismatch.actual), fontFamily = FontFamily.Monospace)
    text.whereToCheck?.let { Text(it) }
    val trust = text.trustButton?.takeIf { canTrust }
    if (trust == null) {
        Button(onClick = onPairAgain) { Text(text.button) }
    } else {
        // Equal widths: the longer label wraps instead of squeezing the other button.
        val padding = PaddingValues(horizontal = 12.dp, vertical = 8.dp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = onTrust, contentPadding = padding, modifier = Modifier.weight(1f)) {
                Text(trust, textAlign = TextAlign.Center)
            }
            OutlinedButton(onClick = onPairAgain, contentPadding = padding, modifier = Modifier.weight(1f)) {
                Text(text.button, textAlign = TextAlign.Center)
            }
        }
    }
}
