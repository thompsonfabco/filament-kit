package com.thompsonfabco.filamentkit.ui.pair

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsBottomHeight
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.windowInsetsTopHeight
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Surface
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.openAppSettings
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The scanner (05-android-app 4.4): the camera preview full screen under a hint chip, the close button and a square
 * viewfinder, the system bars on a `scrim` band. Reports the first QR code it sees through [onResult] with a short
 * haptic tick. Asks for the camera permission itself. Decodes with zxing-cpp ([QrDecoder]), so no Google Play services
 * are needed. [onClose] is the same as Back; [onEnterAddress] leaves for the address step.
 */
@Composable
fun QrScanner(
    onResult: (String) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    onEnterAddress: () -> Unit = onClose,
) {
    val context = LocalContext.current
    val haptic = LocalHapticFeedback.current
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
    // back from the app's settings page with the camera allowed
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            granted = true
        }
    }
    // Once Android will not ask again, "Try again" can only send the person to the app's settings page.
    val tryAgain = {
        if (context.activity()?.shouldShowRequestPermissionRationale(Manifest.permission.CAMERA) == false) {
            context.openAppSettings()
        } else {
            launcher.launch(Manifest.permission.CAMERA)
        }
    }

    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Box(modifier.fillMaxSize().background(colors.bg)) {
        if (granted && !cameraFailed) {
            CameraPreview(
                onResult = { text ->
                    haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                    onResult(text)
                },
                onFailed = { cameraFailed = true },
            )
            Box(
                Modifier.align(Alignment.Center).fillMaxWidth(VIEWFINDER_FRACTION).aspectRatio(1f)
                    .border(space.s1 / 2, colors.borderStrong),
            )
        }
        when {
            cameraFailed -> ScanProblem(false, onEnterAddress, onEnterAddress, Modifier.align(Alignment.Center))
            granted -> Unit
            denied -> ScanProblem(true, tryAgain, onEnterAddress, Modifier.align(Alignment.Center))
        }
        // the system bars stay visible over a scrim band
        Box(Modifier.align(Alignment.TopCenter).fillMaxWidth().windowInsetsTopHeight(WindowInsets.statusBars).background(colors.scrim))
        Box(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().windowInsetsBottomHeight(WindowInsets.navigationBars)
                .background(colors.scrim),
        )
        Column(
            Modifier.align(Alignment.TopCenter).fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars).padding(space.s2),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(space.s2),
        ) {
            Box(Modifier.align(Alignment.Start).clip(CircleShape).background(colors.surface)) {
                SwIconButton(R.drawable.sw_ic_close, stringResource(R.string.pair_scan_close), onClose)
            }
            if (granted && !cameraFailed) {
                Surface(shape = SpoolwardenTheme.shapes.r, color = colors.surface, contentColor = colors.text) {
                    Text(
                        stringResource(R.string.pair_scan_hint), Modifier.padding(horizontal = space.s3, vertical = space.s2),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }
    }
}

/** What stands in place of the preview: the camera is refused ([denied]) or could not start (4.4). */
@Composable
internal fun ScanProblem(denied: Boolean, onPrimary: () -> Unit, onEnterAddress: () -> Unit, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    OutlinedCard(
        modifier.padding(space.s4).widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s3)) {
            Text(
                stringResource(if (denied) R.string.pair_scan_denied else R.string.pair_scan_failed),
                style = MaterialTheme.typography.bodyMedium,
            )
            if (denied) {
                SwButton(stringResource(R.string.common_try_again), onPrimary, Modifier.fillMaxWidth(), kind = SwButtonKind.Main)
                SwButton(stringResource(R.string.pair_start_enter_address), onEnterAddress, Modifier.fillMaxWidth())
            } else {
                SwButton(stringResource(R.string.pair_start_enter_address), onEnterAddress, Modifier.fillMaxWidth(), kind = SwButtonKind.Main)
            }
        }
    }
}

private const val VIEWFINDER_FRACTION = 0.6f

private fun Context.activity(): Activity? {
    var c = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

@Composable
private fun CameraPreview(onResult: (String) -> Unit, onFailed: () -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val gate = remember {
        val decoder = QrDecoder()
        QrFrameGate<ImageProxy>(decoder::decode)
    }
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
                // Decodes on the executor; frames that arrive meanwhile are dropped (KEEP_ONLY_LATEST and the gate).
                analysis.setAnalyzer(executor) { proxy ->
                    gate.offer(proxy, proxy::close)?.let { text ->
                        ContextCompat.getMainExecutor(context).execute { currentOnResult(text) }
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
