package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
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
    scanner: @Composable (onResult: (String) -> Unit, onClose: () -> Unit) -> Unit = { onResult, onClose ->
        QrScanner(onResult = onResult, onClose = onClose)
    },
) {
    val ui by viewModel.state.collectAsState()
    var scanning by remember { mutableStateOf(false) }

    LaunchedEffect(ui.step) { if (ui.step == Step.Done) onPaired() }

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
        Text("Pair with your server", style = MaterialTheme.typography.headlineSmall)

        val mismatch = ui.mismatch
        when {
            mismatch != null -> MismatchPanel(mismatch, viewModel::pairAgain)
            ui.step == Step.Choose -> ChooseStep(ui, discovered, onScan = { scanning = true }, viewModel)
            else -> ManualPair(
                ui = ui,
                onSubmitAddress = viewModel::submitAddress,
                onConfirmFingerprint = viewModel::confirmFingerprint,
                onRejectFingerprint = viewModel::rejectFingerprint,
                onSubmitCode = viewModel::submitCode,
                onBack = viewModel::pairAgain,
            )
        }
    }
}

@Composable
private fun ChooseStep(ui: PairUi, discovered: List<DiscoveredServer>, onScan: () -> Unit, vm: PairViewModel) {
    Text("On the server, open the pairing page and scan its QR code with this phone.")
    Button(onClick = onScan, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) {
        Text(if (ui.busy) "Connecting..." else "Scan QR code")
    }
    ui.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

    Text("Servers found on this network", style = MaterialTheme.typography.titleMedium)
    if (discovered.isEmpty()) {
        Text("None found yet. You can still enter an address below.")
    } else {
        discovered.forEach { server ->
            OutlinedButton(onClick = { vm.startManual(server.host, server.port) }, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) {
                Text("${server.name} (${server.host})")
            }
        }
    }

    OutlinedButton(onClick = { vm.startManual() }, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) {
        Text("Enter address")
    }
}

/** The server's certificate is not the one that was paired; never trusted silently. */
@Composable
private fun MismatchPanel(mismatch: Mismatch, onPairAgain: () -> Unit) {
    Text("The server's certificate has changed", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.error)
    Text("This can happen if the server was reinstalled. If you did not expect that, do not continue.")
    Text("Paired fingerprint")
    Text(groupFingerprint(mismatch.expected), fontFamily = FontFamily.Monospace)
    Text("Fingerprint now")
    Text(groupFingerprint(mismatch.actual), fontFamily = FontFamily.Monospace)
    Button(onClick = onPairAgain) { Text("Pair again") }
}
