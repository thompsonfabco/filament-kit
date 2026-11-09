package com.thompsonfabco.filamentkit.ui.printers

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewmodel.compose.viewModel
import com.thompsonfabco.filamentkit.net.Api

/** The Printers section: the list, and one printer's screen when opened (Back returns to the list). */
@Composable
fun PrintersEntry(api: Api, onPairAgain: () -> Unit) {
    val backend = remember(api) { ApiPrinterBackend(api) }
    val apiKey = System.identityHashCode(api)
    var openId by rememberSaveable { mutableStateOf<String?>(null) }
    val id = openId
    var manualFor by rememberSaveable { mutableStateOf<String?>(null) }
    // each visit gets its own view model: a finished session's summary is never restarted by coming back to it
    var manualVisit by rememberSaveable { mutableIntStateOf(0) }
    if (id == null) {
        val vm = viewModel(key = "printers-$apiKey") { PrintersViewModel(backend) }
        PrintersScreen(vm, onOpen = { openId = it }, onPairAgain = onPairAgain)
    } else if (manualFor == id) {
        val vm = viewModel(key = "manual-$apiKey-$id-$manualVisit") { ManualMapViewModel(ApiManualMapBackend(api), id) }
        val name = viewModel(key = "printer-$apiKey-$id") { PrinterViewModel(backend, id) }.state.collectAsState()
        ManualMapScreen(vm, name.value.printer?.name, onBack = { manualFor = null }, onPairAgain = onPairAgain)
    } else {
        BackHandler { openId = null }
        val vm = viewModel(key = "printer-$apiKey-$id") { PrinterViewModel(backend, id) }
        val tools = viewModel(key = "printer-tools-$apiKey-$id") { PrinterToolsViewModel(backend, id) }
        val camera = remember(api, id) {
            CameraSource(api.client, api.cameraHlsUrl(id), api.cameraMjpegUrl(id), api.authHeaders())
        }
        PrinterScreen(vm, tools, camera, onBack = { openId = null }, onPairAgain = onPairAgain,
            onManualMap = {
            manualVisit++
            manualFor = id
        })
    }
}
