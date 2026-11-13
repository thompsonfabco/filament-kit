package com.thompsonfabco.filamentkit.ui.printers

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.viewmodel.compose.viewModel
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.SlotSpool
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

// The Printers section, one entry per route: the list, one printer, its settings, the slot pick and the manual slot
// map. Each route has its own back stack entry, so its view models are its own and a visit starts fresh. Every entry
// takes `currentApi`, so a request goes to the session's client of that moment (a re-pair or a trusted certificate
// reaches the screen with its state intact); only the camera streams, which need the client itself, take an [Api].

/** The printers list; its calls go to whatever client [currentApi] returns at that moment. */
@Composable
fun PrintersListEntry(currentApi: () -> Api, onOpen: (String) -> Unit, onPairAgain: () -> Unit) {
    val vm = viewModel { PrintersViewModel(ApiPrinterBackend(currentApi)) }
    PrintersScreen(vm, onOpen = onOpen, onPairAgain = onPairAgain)
}

/** One printer's screen. [api] gives the camera its client and stream addresses. */
@Composable
fun PrinterEntry(
    api: Api,
    currentApi: () -> Api,
    id: String,
    onPairAgain: () -> Unit,
    onOpenSettings: () -> Unit,
    onMapByLoading: () -> Unit,
    onPickSlot: (String) -> Unit,
    onOpenSpool: (SlotSpool) -> Unit,
) {
    val backend = remember { ApiPrinterBackend(currentApi) }
    val vm = viewModel { PrinterViewModel(backend, id) }
    val tools = viewModel { PrinterToolsViewModel(backend, id) }
    val camera = remember(api, id) {
        CameraSource(api.client, api.cameraHlsUrl(id), api.cameraMjpegUrl(id), api.authHeaders())
    }
    // Hide / Show is remembered per printer on this phone; the camera is shown by default
    val prefs = LocalContext.current.getSharedPreferences(CAMERA_PREFS, Context.MODE_PRIVATE)
    var shown by remember(id) { mutableStateOf(prefs.getBoolean(id, true)) }
    PrinterScreen(
        vm, tools, camera,
        onPairAgain = onPairAgain,
        onOpenSettings = onOpenSettings,
        onMapByLoading = onMapByLoading,
        onPickSlot = onPickSlot,
        onOpenSpool = onOpenSpool,
        cameraShown = shown,
        onCameraShown = {
            shown = it
            prefs.edit().putBoolean(id, it).apply()
        },
    )
}

private const val CAMERA_PREFS = "printer_camera"

/** Printer settings; [onForgotten] runs after the printer is forgotten, with its name (for the toast). */
@Composable
fun PrinterSettingsEntry(currentApi: () -> Api, id: String, onPairAgain: () -> Unit, onForgotten: (String) -> Unit) {
    val backend = remember { ApiPrinterBackend(currentApi) }
    val vm = viewModel { PrinterViewModel(backend, id) }
    val family = vm.state.collectAsState().value.printer?.family
    // made once the printer's family is known (it decides the rows); kept for the visit
    val edit = family?.let { f -> viewModel(key = f) { PrinterEditViewModel(backend, id, f, vm::showPrinter) } }
    PrinterSettingsScreen(vm, edit, onPairAgain, onForgotten)
}

/** Map a printer's slots by loading filament by hand. */
@Composable
fun ManualMapEntry(currentApi: () -> Api, id: String, onBack: () -> Unit, onPairAgain: () -> Unit) {
    val vm = viewModel { ManualMapViewModel(ApiManualMapBackend(currentApi), id) }
    ManualMapScreen(vm, PrinterTitles.name(id), onBack = onBack, onPairAgain = onPairAgain)
}

/** Pick a spool for slot [slot] of a printer; [onLoaded] says whether the printer already shows the load. */
@Composable
fun PickSpoolEntry(currentApi: () -> Api, id: String, slot: String, onLoaded: (printerName: String, confirmed: Boolean) -> Unit, onPairAgain: () -> Unit) {
    val backend = remember { ApiPrinterBackend(currentApi) }
    val printer = viewModel { PrinterViewModel(backend, id) }
    LaunchedEffect(printer) { printer.retry() }
    val name = printer.state.collectAsState().value.printer?.name ?: PrinterTitles.name(id)
    val vm = viewModel { PickSpoolViewModel(ApiPickBackend(currentApi), id, slot) }
    PickSpoolScreen(vm, name, slot, onLoaded = { confirmed -> onLoaded(name.orEmpty(), confirmed) }, onPairAgain = onPairAgain)
}

/** A slot's spool in the shape of a search result, so the spool card opens on it (until the spool has its own screen, 7.2). */
fun slotSpoolJson(sp: SlotSpool): JsonObject = buildJsonObject {
    sp.id?.let { put("id", it) }
    put("filament", buildJsonObject {
        put("name", sp.name)
        put("material", sp.material)
        put("color_hex", sp.colorHex)
    })
    sp.remainingWeight?.let { put("remaining_weight", it) }
}
