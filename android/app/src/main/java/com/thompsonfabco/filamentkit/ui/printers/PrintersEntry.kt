package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel
import com.thompsonfabco.filamentkit.net.Api

// The Printers section, one entry per route: the list, one printer, and the manual slot map of one printer.
// Each route has its own back stack entry, so its view models are its own and a visit to the map starts fresh.

/** The printers list. */
@Composable
fun PrintersListEntry(api: Api, onOpen: (String) -> Unit, onPairAgain: () -> Unit, trust: TrustAction? = null) {
    val backend = remember(api) { ApiPrinterBackend(api) }
    val vm = viewModel(key = System.identityHashCode(api).toString()) { PrintersViewModel(backend) }
    PrintersScreen(vm, onOpen = onOpen, onPairAgain = onPairAgain, trust = trust)
}

/** One printer's screen; [onManualMap] opens the manual slot map, [onBack] also runs after the printer is removed. */
@Composable
fun PrinterEntry(
    api: Api,
    id: String,
    onBack: () -> Unit,
    onManualMap: () -> Unit,
    onPairAgain: () -> Unit,
    trust: TrustAction? = null,
) {
    val backend = remember(api) { ApiPrinterBackend(api) }
    val apiKey = System.identityHashCode(api)
    val vm = viewModel(key = apiKey.toString()) { PrinterViewModel(backend, id) }
    val tools = viewModel(key = apiKey.toString()) { PrinterToolsViewModel(backend, id) }
    val camera = remember(api, id) {
        CameraSource(api.client, api.cameraHlsUrl(id), api.cameraMjpegUrl(id), api.authHeaders())
    }
    val family = vm.state.collectAsState().value.printer?.family
    // made once the printer's family is known (it decides the fields); kept for the visit
    val edit = family?.let { f ->
        viewModel(key = "${apiKey}-${f}") { PrinterEditViewModel(backend, id, f, vm::showPrinter) }
    }
    PrinterScreen(vm, tools, camera, onBack = onBack, onPairAgain = onPairAgain,
        onManualMap = onManualMap,
        edit = edit,
        onRemoved = onBack,
        trust = trust,
    )
}

/** Map a printer's slots by loading filament by hand. */
@Composable
fun ManualMapEntry(api: Api, id: String, onBack: () -> Unit, onPairAgain: () -> Unit) {
    val backend = remember(api) { ApiPrinterBackend(api) }
    val apiKey = System.identityHashCode(api).toString()
    val vm = viewModel(key = apiKey) { ManualMapViewModel(ApiManualMapBackend(api), id) }
    val name = viewModel(key = apiKey) { PrinterViewModel(backend, id) }.state.collectAsState()
    ManualMapScreen(vm, name.value.printer?.name, onBack = onBack, onPairAgain = onPairAgain)
}
