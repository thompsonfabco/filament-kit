package com.thompsonfabco.filamentkit.ui.add

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.thompsonfabco.filamentkit.ui.parseWeight
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.launch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Step 1 of adding spools: label photos (1–8), an optional tag (tapped while this screen is open), the weight on the
 * scale or "Sealed", an optional note for Claude, then Read.
 */
@Composable
fun CaptureScreen(
    state: AddUiState,
    vm: AddViewModel,
    onCancel: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val reading = state.stage == Stage.Reading
    Column(modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Add spools", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Photograph each label (several photos of one spool are fine). Nothing is saved until you check and add.",
            style = MaterialTheme.typography.bodyMedium,
        )
        if (state.photos.size < AddViewModel.MAX_PHOTOS && !reading) {
            CameraCapture(onPhoto = vm::addPhoto)
        }
        Text("Photos: ${state.photos.size} of ${AddViewModel.MAX_PHOTOS}", style = MaterialTheme.typography.labelLarge)
        PhotoStrip(state.photos, onRemove = vm::removePhoto, enabled = !reading)

        TagRow(state.tag, onClear = vm::clearTag, enabled = !reading)
        WeightFields(state, vm, enabled = !reading)
        OutlinedTextField(
            value = state.hint, onValueChange = vm::setHint, enabled = !reading,
            label = { Text("Note for Claude (optional)") },
            placeholder = { Text("e.g. 3 of the grey ones") },
            modifier = Modifier.fillMaxWidth(),
        )

        state.error?.let { ErrorCard(it, vm, onPairAgain, kept = state.draftId != null) }
        if (reading) {
            Busy("Claude is reading ${state.photos.size} photo${if (state.photos.size == 1) "" else "s"}… (up to a minute)")
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onCancel) { Text("Close") }
                if (state.items.isNotEmpty()) {
                    OutlinedButton(onClick = vm::showReview) { Text("Back to review") }
                }
                Button(onClick = vm::read, enabled = state.photos.isNotEmpty()) { Text("Read labels") }
            }
        }
    }
}

@Composable
private fun TagRow(tag: String?, onClear: () -> Unit, enabled: Boolean) {
    Card(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            if (tag == null) {
                Text("No tag. To link one, hold the spool's tag to the back of the phone (optional).", Modifier.weight(1f))
            } else {
                Text("Tag $tag", Modifier.weight(1f))
                TextButton(onClick = onClear, enabled = enabled) { Text("Remove tag") }
            }
        }
    }
}

@Composable
private fun WeightFields(state: AddUiState, vm: AddViewModel, enabled: Boolean) {
    var text by remember(state.generation) { mutableStateOf(state.weight?.let(::grams).orEmpty()) }
    LaunchedEffect(state.sealed) { if (state.sealed) text = "" }
    val bad = text.isNotBlank() && parseWeight(text) == null
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it
            vm.setWeight(parseWeight(it))
        },
        enabled = enabled && !state.sealed,
        label = { Text("Weight on the scale, with spool (g)") },
        supportingText = { Text(if (bad) "Enter grams, e.g. 812" else "Only used for one opened spool") },
        isError = bad,
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = Modifier.fillMaxWidth(),
    )
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("Sealed (still in its bag or box)", Modifier.weight(1f))
        Switch(
            checked = state.sealed, onCheckedChange = vm::setSealed, enabled = enabled,
            modifier = Modifier.semantics { contentDescription = "Sealed" },
        )
    }
}

@Composable
private fun PhotoStrip(photos: List<File>, onRemove: (Int) -> Unit, enabled: Boolean) {
    if (photos.isEmpty()) return
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        itemsIndexed(photos, key = { _, f -> f.path }) { i, file ->
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Thumbnail(file, Modifier.size(96.dp))
                TextButton(
                    onClick = { onRemove(i) }, enabled = enabled,
                    modifier = Modifier.semantics { contentDescription = "Remove photo ${i + 1}" },
                ) { Text("Remove") }
            }
        }
    }
}

@Composable
private fun Thumbnail(file: File, modifier: Modifier) {
    val bitmap by produceState<ImageBitmap?>(null, file) {
        value = withContext(Dispatchers.IO) { decodeThumbnail(file, 256) }
    }
    val b = bitmap
    if (b == null) {
        Box(modifier.background(MaterialTheme.colorScheme.surfaceVariant))
    } else {
        Image(b, contentDescription = "Photo ${file.nameWithoutExtension.removePrefix("photo")}", modifier, contentScale = ContentScale.Crop)
    }
}

private fun decodeThumbnail(file: File, maxSide: Int): ImageBitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.path, bounds)
    if (bounds.outWidth <= 0) return null
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxSide) sample *= 2
    return BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })?.asImageBitmap()
}

/** CameraX preview with a shutter button. Each shot is saved to a cache file (EXIF orientation kept) and handed on. */
@Composable
private fun CameraCapture(onPhoto: (ByteArray) -> Unit) {
    val context = LocalContext.current
    var granted by remember { mutableStateOf(hasCamera(context)) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) { if (!granted) ask.launch(Manifest.permission.CAMERA) }
    if (!granted) {
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp)) {
                Text("The camera is needed to photograph labels.")
                TextButton(onClick = { ask.launch(Manifest.permission.CAMERA) }) { Text("Allow camera") }
            }
        }
        return
    }

    val lifecycleOwner = LocalLifecycleOwner.current
    val capture = remember { ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build() }
    val previewView = remember { PreviewView(context) }
    var problem by remember { mutableStateOf<String?>(null) }
    var shotError by remember { mutableStateOf<String?>(null) }
    var provider by remember { mutableStateOf<ProcessCameraProvider?>(null) }
    var shooting by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(lifecycleOwner) {
        try {
            val p = cameraProvider(context)
            provider = p
            val preview = Preview.Builder().build().also { it.setSurfaceProvider(previewView.surfaceProvider) }
            p.unbindAll()
            p.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, capture)
            problem = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            problem = "The camera could not be started: ${e.message ?: "no camera found"}"
        }
    }
    DisposableEffect(lifecycleOwner) {
        onDispose {
            provider?.unbindAll()
        }
    }

    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
        AndroidView({ previewView }, Modifier.fillMaxWidth().aspectRatio(3f / 4f))
        Spacer(Modifier.height(8.dp))
        (problem ?: shotError)?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(
            enabled = !shooting && problem == null,
            onClick = {
                shooting = true
                shotError = null
                scope.launch {
                    try {
                        val file = withContext(Dispatchers.IO) { File.createTempFile("shot", ".jpg", context.cacheDir) }
                        val bytes = try {
                            takePicture(capture, file, context)
                            withContext(Dispatchers.IO) { file.readBytes() }
                        } finally {
                            withContext(NonCancellable + Dispatchers.IO) { file.delete() }
                        }
                        onPhoto(bytes)
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        shotError = "The photo failed: ${e.message ?: "camera error"}. Try again."
                    } finally {
                        shooting = false
                    }
                }
            },
        ) { Text(if (shooting) "Taking photo…" else "Take photo") }
    }
}

/** Saves one shot into [file] (EXIF orientation set). Camera errors throw [ImageCaptureException]. */
private suspend fun takePicture(capture: ImageCapture, file: File, context: Context): Unit =
    suspendCancellableCoroutine { cont ->
        capture.takePicture(
            ImageCapture.OutputFileOptions.Builder(file).build(),
            ContextCompat.getMainExecutor(context),
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                    if (cont.isActive) cont.resume(Unit)
                }

                override fun onError(exception: ImageCaptureException) {
                    if (cont.isActive) cont.resumeWithException(exception)
                }
            },
        )
    }

private suspend fun cameraProvider(context: Context): ProcessCameraProvider = suspendCancellableCoroutine { cont ->
    val future = ProcessCameraProvider.getInstance(context)
    future.addListener({
        try {
            cont.resume(future.get())
        } catch (e: Exception) {
            cont.resumeWithException(e.cause ?: e)
        }
    }, ContextCompat.getMainExecutor(context))
}

private fun hasCamera(context: Context) =
    ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

/** A spinner with a line of text. */
@Composable
internal fun Busy(text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(Modifier.size(24.dp))
        Spacer(Modifier.width(12.dp))
        Text(text)
    }
}

/** The current problem, with the actions that fit it. */
@Composable
internal fun ErrorCard(error: AddError, vm: AddViewModel, onPairAgain: () -> Unit, kept: Boolean) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(error.message, color = MaterialTheme.colorScheme.onErrorContainer)
            if (error.expectedFingerprint != null && error.actualFingerprint != null) {
                Text("Paired certificate: ${groups(error.expectedFingerprint)}", style = MaterialTheme.typography.bodySmall)
                Text("Certificate now: ${groups(error.actualFingerprint)}", style = MaterialTheme.typography.bodySmall)
            }
            error.detail?.let { Text("Server says: $it", style = MaterialTheme.typography.bodySmall) }
            if (kept) Text("Your photos and edits are kept.", style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (error.canRetry) Button(onClick = vm::retry) { Text("Retry") }
                if (error.canDropTag) Button(onClick = vm::dropTagAndRetry) { Text("Add without the tag") }
                if (error.pairAgain) Button(onClick = onPairAgain) { Text("Pair again") }
                TextButton(onClick = vm::dismissError) { Text("OK") }
            }
        }
    }
}

private fun groups(fp: String) = fp.chunked(4).joinToString(" ")
