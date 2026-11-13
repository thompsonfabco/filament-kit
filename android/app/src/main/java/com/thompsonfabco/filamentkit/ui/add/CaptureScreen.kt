package com.thompsonfabco.filamentkit.ui.add

import android.Manifest
import android.app.Activity
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
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.openAppSettings
import com.thompsonfabco.filamentkit.ui.parseWeight
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Step 1 of adding spools (05-android-app 6.2): label photos (1 to 8), an optional tag (tapped while this screen is
 * open), "Still sealed" and the weight with spool, an optional note for the Label Reader, then "Read labels". While
 * the Hub reads, the camera and the photo controls give way to a panel with "Cancel reading". [camera] draws the
 * live camera and its button; a test passes a stand-in because a test has no camera.
 */
@Composable
fun CaptureScreen(
    state: AddUiState,
    vm: AddViewModel,
    onPairAgain: () -> Unit,
    onAddByHand: () -> Unit,
    modifier: Modifier = Modifier,
    camera: @Composable (photos: Int, onPhoto: (ByteArray) -> Unit) -> Unit = { n, onPhoto -> CameraCapture(n, onPhoto) },
) {
    val reading = state.stage == Stage.Reading
    val space = SpoolwardenTheme.space
    val wide = SpoolwardenTheme.window != WindowClass.Phone
    val showCamera = state.photos.size < AddViewModel.MAX_PHOTOS && !reading
    AddPage(
        AddStep.Photos, state, modifier,
        bar = {
            state.error?.let { AddErrorNotice(it, vm, onPairAgain, onAddByHand, kept = state.draftId != null) }
            if (reading) {
                SwButton(
                    stringResource(R.string.add_photos_cancel_reading), vm::cancelRead, Modifier.fillMaxWidth(),
                )
            } else {
                if (state.photos.isEmpty()) {
                    Text(
                        stringResource(R.string.add_photos_need_photo), style = MaterialTheme.typography.bodySmall,
                        color = SpoolwardenTheme.colors.muted,
                    )
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                    if (state.items.isNotEmpty()) {
                        SwButton(stringResource(R.string.add_back_to_check), vm::showReview, Modifier.weight(1f))
                    }
                    SwButton(
                        pluralStringResource(R.plurals.add_photos_read, state.photos.size, state.photos.size), vm::read,
                        Modifier.weight(1f), kind = SwButtonKind.Main, enabled = state.photos.isNotEmpty(),
                    )
                }
            }
        },
    ) {
        Text(stringResource(R.string.add_photos_intro), style = MaterialTheme.typography.bodyMedium)
        if (reading) {
            AddPanel {
                Column(Modifier.padding(space.s4)) {
                    AddBusy(pluralStringResource(R.plurals.add_photos_reading, state.photos.size, state.photos.size))
                }
            }
            return@AddPage
        }
        // from medium width the camera sits on the left (up to `previewMax`) and the other controls on the right
        if (wide && showCamera) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s4)) {
                Column(Modifier.weight(1f).widthIn(max = SpoolwardenTheme.sizes.previewMax)) {
                    camera(state.photos.size, vm::addPhoto)
                }
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(space.s3)) { Controls(state, vm) }
            }
        } else {
            if (showCamera) camera(state.photos.size, vm::addPhoto)
            Controls(state, vm)
        }
    }
}

/** The photo strip, the tag row, "Still sealed", the weight and the note. */
@Composable
private fun Controls(state: AddUiState, vm: AddViewModel) {
    PhotoStrip(state.photos, onRemove = vm::removePhoto)
    TagRow(state.tag, onClear = vm::clearTag)
    SealedRow(state.sealed, vm::setSealed)
    WeightField(state, vm)
    OutlinedTextField(
        value = state.hint, onValueChange = vm::setHint,
        label = { Text(stringResource(R.string.add_photos_note_label)) },
        placeholder = { Text(stringResource(R.string.add_photos_note_placeholder)) },
        minLines = 1, maxLines = 3,
        modifier = Modifier.fillMaxWidth(),
    )
}

/** No tag, or the tag that was tapped (in `--mono`) with "Remove". */
@Composable
private fun TagRow(tag: String?, onClear: () -> Unit) {
    val space = SpoolwardenTheme.space
    Row(
        Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row),
        horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically,
    ) {
        SwIcon(R.drawable.sw_ic_tag, null, tint = SpoolwardenTheme.colors.muted)
        Column(Modifier.weight(1f)) {
            if (tag == null) {
                Text(stringResource(R.string.add_photos_tag_none), style = MaterialTheme.typography.bodyLarge)
                Text(
                    stringResource(R.string.add_photos_tag_hint), style = MaterialTheme.typography.bodySmall,
                    color = SpoolwardenTheme.colors.muted,
                )
            } else {
                Text(stringResource(R.string.common_tag, tag), style = SpoolwardenTheme.type.data)
                Text(
                    stringResource(R.string.add_photos_tag_linked_hint), style = MaterialTheme.typography.bodySmall,
                    color = SpoolwardenTheme.colors.muted,
                )
            }
        }
        if (tag != null) SwButton(stringResource(R.string.common_remove), onClear, kind = SwButtonKind.Quiet)
    }
}

/** "Still sealed (in its bag or box)", on by default; the whole row toggles. */
@Composable
internal fun SealedRow(sealed: Boolean, onChange: (Boolean) -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
            .toggleable(value = sealed, role = Role.Switch, onValueChange = onChange),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            stringResource(R.string.common_still_sealed), Modifier.weight(1f).padding(end = SpoolwardenTheme.space.s3),
            style = MaterialTheme.typography.bodyLarge,
        )
        Switch(checked = sealed, onCheckedChange = null)
    }
}

/** The weight with spool: only for one opened spool, so it is off while "Still sealed" is on. */
@Composable
private fun WeightField(state: AddUiState, vm: AddViewModel) {
    var text by remember(state.generation) { mutableStateOf(state.weight?.let(::grams).orEmpty()) }
    LaunchedEffect(state.sealed) { if (state.sealed) text = "" }
    val bad = text.isNotBlank() && parseWeight(text) == null
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it
            vm.setWeight(parseWeight(it))
        },
        enabled = !state.sealed,
        label = { Text(stringResource(R.string.common_field_weight_with_spool_optional)) },
        supportingText = {
            Text(
                stringResource(
                    when {
                        bad -> R.string.common_error_grams
                        state.sealed -> R.string.add_photos_weight_sealed
                        else -> R.string.add_photos_weight_hint
                    },
                ),
            )
        },
        isError = bad,
        singleLine = true,
        textStyle = SpoolwardenTheme.type.data,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = Modifier.fillMaxWidth(),
    )
}

/** Square thumbnails with a close button in the corner (48 dp to touch); the photos are numbered for TalkBack. */
@Composable
private fun PhotoStrip(photos: List<File>, onRemove: (Int) -> Unit) {
    if (photos.isEmpty()) return
    val side = SpoolwardenTheme.sizes.thumb
    LazyRow(horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2)) {
        itemsIndexed(photos, key = { _, f -> f.path }) { i, file ->
            Box(Modifier.size(side)) {
                Thumbnail(file, Modifier.size(side), stringResource(R.string.a11y_photo_draft, i + 1))
                SwIconButton(
                    R.drawable.sw_ic_close, stringResource(R.string.add_photo_remove, (i + 1).toString(), photos.size), { onRemove(i) },
                    Modifier.align(Alignment.TopEnd),
                )
            }
        }
    }
}

@Composable
private fun Thumbnail(file: File, modifier: Modifier, description: String) {
    val bitmap by produceState<ImageBitmap?>(null, file) {
        value = withContext(Dispatchers.IO) { decodeThumbnail(file, 256) }
    }
    val colors = SpoolwardenTheme.colors
    val frame = modifier.clip(SpoolwardenTheme.shapes.r).border(SpoolwardenTheme.sizes.hairline, colors.border, SpoolwardenTheme.shapes.r)
    val b = bitmap
    if (b == null) {
        Box(frame.background(colors.surface2).semantics { contentDescription = description })
    } else {
        Image(b, contentDescription = description, modifier = frame, contentScale = ContentScale.Crop)
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

/**
 * The live camera (3:4, `r` corners, 1 dp `border`) with "Take photo" and the count "2 of 8" in `--mono`. Without the
 * camera permission a panel stands in its place: "Allow camera", or, when Android will not ask again, "Open app
 * settings". Each shot is saved to a cache file (EXIF orientation kept) and handed on.
 */
@Composable
internal fun CameraCapture(photos: Int, onPhoto: (ByteArray) -> Unit) {
    val context = LocalContext.current
    val space = SpoolwardenTheme.space
    var granted by remember { mutableStateOf(hasCamera(context)) }
    var noAsk by remember { mutableStateOf(false) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        granted = it
        // denied and Android will not show its question again: only the app's settings can allow it
        val activity = context as? Activity
        noAsk = !it && activity != null && !ActivityCompat.shouldShowRequestPermissionRationale(activity, Manifest.permission.CAMERA)
    }
    LaunchedEffect(Unit) { if (!granted) ask.launch(Manifest.permission.CAMERA) }
    if (!granted) {
        AddPanel {
            Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s2)) {
                Text(
                    stringResource(if (noAsk) R.string.add_photos_camera_no_ask else R.string.add_photos_camera_needed),
                    style = MaterialTheme.typography.bodyMedium,
                )
                SwButton(
                    stringResource(if (noAsk) R.string.common_open_app_settings else R.string.add_photos_camera_allow),
                    { if (noAsk) context.openAppSettings() else ask.launch(Manifest.permission.CAMERA) },
                    Modifier.fillMaxWidth(),
                    // "Read labels" is the main action once there is a photo
                    kind = if (photos == 0) SwButtonKind.Main else SwButtonKind.Plain,
                )
            }
        }
        return
    }

    val lifecycleOwner = LocalLifecycleOwner.current
    val capture = remember { ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build() }
    val previewView = remember { PreviewView(context) }
    var problem by remember { mutableStateOf(false) }
    var shotFailed by remember { mutableStateOf(false) }
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
            problem = false
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            problem = true
        }
    }
    DisposableEffect(lifecycleOwner) {
        onDispose {
            provider?.unbindAll()
        }
    }

    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(space.s2)) {
        AndroidView(
            { previewView },
            Modifier.fillMaxWidth().aspectRatio(3f / 4f).clip(SpoolwardenTheme.shapes.r)
                .border(SpoolwardenTheme.sizes.hairline, SpoolwardenTheme.colors.border, SpoolwardenTheme.shapes.r),
        )
        if (problem) NoticeCard(NoticeKind.Bad, stringResource(R.string.add_photos_camera_error))
        if (shotFailed) NoticeCard(NoticeKind.Bad, stringResource(R.string.add_photos_photo_failed))
        SwButton(
            stringResource(if (shooting) R.string.add_photos_taking else R.string.add_photos_take),
            {
                shooting = true
                shotFailed = false
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
                        shotFailed = true
                    } finally {
                        shooting = false
                    }
                }
            },
            Modifier.fillMaxWidth(),
            // "Read labels" becomes the main action once there is a photo
            kind = if (photos == 0) SwButtonKind.Main else SwButtonKind.Plain,
            enabled = !shooting && !problem,
            icon = R.drawable.sw_ic_camera,
            trailing = stringResource(R.string.add_photos_count, photos, AddViewModel.MAX_PHOTOS),
        )
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

