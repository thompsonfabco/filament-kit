package com.thompsonfabco.filamentkit.ui.pair

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Camera preview that reports the first QR code it sees through [onResult]. Asks for the camera permission itself.
 * Decodes with ZXing ([QrDecoder]) on the frames' brightness, so no Google Play services are needed.
 */
@Composable
fun QrScanner(
    onResult: (String) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    onEnterAddress: () -> Unit = onClose,
) {
    val context = LocalContext.current
    var granted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    var denied by remember { mutableStateOf(false) }
    var cameraFailed by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        granted = it
        denied = !it
    }
    LaunchedEffect(Unit) { if (!granted) launcher.launch(Manifest.permission.CAMERA) }

    Box(modifier.fillMaxSize()) {
        when {
            cameraFailed -> Column(
                Modifier.align(Alignment.Center).padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("The camera could not be started, so the pairing code can't be scanned. Enter the server's address instead.")
                Button(onClick = onEnterAddress) { Text("Enter address instead") }
            }
            granted -> CameraPreview(onResult, onFailed = { cameraFailed = true })
            denied -> Column(
                Modifier.align(Alignment.Center).padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("The camera is needed to scan the pairing code. You can allow it in the phone's app settings, or enter the address by hand instead.")
                Button(onClick = { launcher.launch(Manifest.permission.CAMERA) }) { Text("Try again") }
                OutlinedButton(onClick = onEnterAddress) { Text("Enter address instead") }
            }
        }
        OutlinedButton(onClick = onClose, modifier = Modifier.align(Alignment.BottomCenter).padding(24.dp)) {
            Text("Cancel")
        }
    }
}

@Composable
private fun CameraPreview(onResult: (String) -> Unit, onFailed: () -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val decoder = remember { QrDecoder() }
    val luma = remember { LumaCopy() }
    val reported = remember { AtomicBoolean(false) }
    val currentOnResult by rememberUpdatedState(onResult)
    val currentOnFailed by rememberUpdatedState(onFailed)
    val preview = remember { Preview.Builder().build() }
    val analysis = remember {
        ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
    }
    val disposed = remember { AtomicBoolean(false) }
    var provider by remember { mutableStateOf<ProcessCameraProvider?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            disposed.set(true)
            // Unbind only our own use cases; other screens (e.g. photo capture) may have theirs bound.
            provider?.unbind(preview, analysis)
            analysis.clearAnalyzer()
            executor.shutdown()
        }
    }

    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            val view = PreviewView(ctx)
            preview.surfaceProvider = view.surfaceProvider
            val future = ProcessCameraProvider.getInstance(ctx)
            future.addListener({
                if (disposed.get()) return@addListener
                // No camera, camera in use, or CameraX failed to start: offer typing the address instead of crashing.
                val cameraProvider = try {
                    future.get()
                } catch (_: Exception) {
                    currentOnFailed()
                    return@addListener
                }
                // Decodes on the executor; frames that arrive meanwhile are dropped (KEEP_ONLY_LATEST).
                analysis.setAnalyzer(executor) { proxy ->
                    proxy.use {
                        if (!reported.get()) {
                            val text = luma.copy(it)?.let { (bytes, w, h) -> decoder.decode(bytes, w, h) }
                            if (text != null && reported.compareAndSet(false, true)) {
                                ContextCompat.getMainExecutor(context).execute { currentOnResult(text) }
                            }
                        }
                    }
                }
                try {
                    cameraProvider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
                    provider = cameraProvider
                } catch (_: Exception) { // IllegalArgumentException (no back camera), IllegalStateException, ...
                    analysis.clearAnalyzer()
                    currentOnFailed()
                }
            }, ContextCompat.getMainExecutor(context))
            view
        },
    )
}

/** Copies the Y plane inside a frame's crop rectangle into one reused, tightly packed array. */
private class LumaCopy {
    private var bytes = ByteArray(0)

    /** The frame's brightness as (bytes, width, height), or null if the frame has no Y plane. */
    fun copy(proxy: ImageProxy): Triple<ByteArray, Int, Int>? {
        val plane = proxy.planes.firstOrNull() ?: return null
        val crop = proxy.cropRect
        val w = crop.width()
        val h = crop.height()
        if (w <= 0 || h <= 0) return null
        if (bytes.size != w * h) bytes = ByteArray(w * h)
        val buffer = plane.buffer
        val stride = plane.rowStride
        val step = plane.pixelStride // 1 for the Y plane of YUV_420_888 in practice; handled anyway
        for (y in 0 until h) {
            val rowStart = (crop.top + y) * stride + crop.left * step
            if (step == 1) {
                buffer.position(rowStart)
                buffer.get(bytes, y * w, w)
            } else {
                for (x in 0 until w) bytes[y * w + x] = buffer.get(rowStart + x * step)
            }
        }
        return Triple(bytes, w, h)
    }
}
