package com.thompsonfabco.filamentkit.ui.history

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The photo viewer (05-android-app 10.5) on photo [n] of record [id]: full screen over the record, `bg` ground, a close
 * button and "Photo 1 of 2" at the top, a pager across the record's photos, pinch and double-tap zoom. The record and
 * the list belong to their own back stack entries ([recordOwner], [listOwner]); the photos come from the list's cache.
 */
@Composable
fun HistoryPhotoEntry(
    current: () -> Api,
    id: String,
    n: Int,
    recordOwner: ViewModelStoreOwner,
    listOwner: ViewModelStoreOwner,
    onClose: () -> Unit,
) {
    val list = viewModel(viewModelStoreOwner = listOwner) { HistoryListViewModel(HistoryBackend.of(current)) }
    val record = viewModel(viewModelStoreOwner = recordOwner, key = recordKey(id)) { RecordViewModel(HistoryBackend.of(current), id) }
    PhotoViewer(list, record, id, n, onClose)
}

@Composable
internal fun PhotoViewer(list: HistoryListViewModel, record: RecordViewModel, id: String, start: Int, onClose: () -> Unit) {
    val s by record.state.collectAsState()
    LaunchedEffect(record) { record.ensureLoaded() }
    // the photo's number within its record is stable, and the shown one is kept across an Activity recreation
    var current by rememberSaveable { mutableIntStateOf(start.coerceAtLeast(1)) }
    PhotoViewerDialog((1..(s.record?.photos ?: 0)).toList(), current, { current = it }, onClose) { n -> list.photo(id, n) }
}

/**
 * The viewer's own part, shared by the Hub photos and the Add spools draft photos: the photos [keys] (each photo's own
 * stable identity, in order), opening on [current], which the viewer reports through [onCurrent] as the page changes;
 * each fetched by [load] (null when it could not be had). The pages and the counter follow the photo by its key, so
 * a photo added or removed elsewhere in the list neither moves the shown page nor changes which photo Try again loads.
 */
@Composable
internal fun <K : Any> PhotoViewerDialog(
    keys: List<K>, current: K, onCurrent: (K) -> Unit, onClose: () -> Unit, load: suspend (K) -> ByteArray?,
) {
    val colors = SpoolwardenTheme.colors
    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Box(Modifier.fillMaxSize().background(colors.bg)) {
            var zoomed by remember { mutableStateOf(false) }
            val total = keys.size
            if (total > 0) {
                val pager = rememberPagerState(initialPage = keys.indexOf(current).coerceAtLeast(0)) { keys.size }
                val shown = rememberUpdatedState(keys)
                val now = rememberUpdatedState(current)
                // the pager follows the photo: when the list changes, return to the current photo's new slot
                LaunchedEffect(keys) {
                    val at = keys.indexOf(current)
                    if (at >= 0 && at != pager.currentPage) pager.scrollToPage(at)
                }
                LaunchedEffect(pager) {
                    snapshotFlow { pager.currentPage }.collect { p ->
                        shown.value.getOrNull(p)?.let { if (it != now.value) onCurrent(it) }
                        zoomed = false
                    }
                }
                HorizontalPager(pager, Modifier.fillMaxSize(), userScrollEnabled = !zoomed, key = { keys[it] }) { p ->
                    PhotoPage(keys[p], keys.indexOf(keys[p]) + 1, total, load, onZoom = { zoomed = it })
                }
            }
            Row(
                Modifier.statusBarsPadding().padding(SpoolwardenTheme.space.s2),
                horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                SwIconButton(R.drawable.sw_ic_close, stringResource(R.string.recent_photo_close), onClose)
                if (total > 0) {
                    Text(
                        stringResource(R.string.photo_position, keys.indexOf(current).coerceAtLeast(0) + 1, total),
                        style = SpoolwardenTheme.type.data, color = colors.text,
                    )
                }
            }
        }
    }
}

private sealed interface PhotoLoad {
    data object Loading : PhotoLoad
    data object Failed : PhotoLoad
    data class Loaded(val bitmap: Bitmap) : PhotoLoad
}

/** One photo, large: "Loading photo…", or "The photo could not be loaded." with "Try again". */
@Composable
private fun <K : Any> PhotoPage(key: K, n: Int, total: Int, load: suspend (K) -> ByteArray?, onZoom: (Boolean) -> Unit) {
    var attempt by remember { mutableIntStateOf(0) }
    var state by remember { mutableStateOf<PhotoLoad>(PhotoLoad.Loading) }
    LaunchedEffect(key, attempt) {
        state = PhotoLoad.Loading
        val bytes = load(key)
        val bitmap = bytes?.let { withContext(Dispatchers.Default) { decode(it, FULL_PX) } }
        state = if (bitmap == null) PhotoLoad.Failed else PhotoLoad.Loaded(bitmap)
    }
    val colors = SpoolwardenTheme.colors
    when (val l = state) {
        PhotoLoad.Loading -> Centered {
            Text(stringResource(R.string.recent_photo_loading), Modifier.semantics { liveRegion = LiveRegionMode.Polite }, color = colors.muted)
        }
        PhotoLoad.Failed -> Centered {
            Text(stringResource(R.string.recent_photo_failed), Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            SwButton(stringResource(R.string.common_try_again), { attempt++ })
        }
        is PhotoLoad.Loaded -> ZoomableImage(l.bitmap, stringResource(R.string.a11y_photo_record, n, total), onZoom)
    }
}

@Composable
private fun Centered(content: @Composable () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(SpoolwardenTheme.space.s4),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s3, Alignment.CenterVertically),
    ) { content() }
}

/** The photo with pinch and double-tap zoom; at normal size one finger belongs to the pager, zoomed in it pans. */
@Composable
private fun ZoomableImage(bitmap: Bitmap, description: String, onZoom: (Boolean) -> Unit) {
    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    var box by remember { mutableStateOf(IntSize.Zero) }
    fun clamp(o: Offset, s: Float): Offset {
        val x = box.width * (s - 1f) / 2f
        val y = box.height * (s - 1f) / 2f
        return Offset(o.x.coerceIn(-x, x), o.y.coerceIn(-y, y))
    }
    Image(
        bitmap.asImageBitmap(), contentDescription = description, contentScale = ContentScale.Fit,
        modifier = Modifier.fillMaxSize().onSizeChanged { box = it }
            .pointerInput(Unit) {
                detectTapGestures(onDoubleTap = {
                    scale = if (scale > 1f) 1f else DOUBLE_TAP_SCALE
                    offset = Offset.Zero
                    onZoom(scale > 1f)
                })
            }
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown(requireUnconsumed = false)
                    do {
                        val event = awaitPointerEvent()
                        if (event.changes.size > 1 || scale > 1f) {
                            scale = (scale * event.calculateZoom()).coerceIn(1f, MAX_SCALE)
                            offset = if (scale <= 1f) Offset.Zero else clamp(offset + event.calculatePan(), scale)
                            onZoom(scale > 1f)
                            event.changes.forEach { if (it.positionChanged()) it.consume() }
                        }
                    } while (event.changes.any { it.pressed })
                }
            }
            .graphicsLayer(scaleX = scale, scaleY = scale, translationX = offset.x, translationY = offset.y),
    )
}

private const val DOUBLE_TAP_SCALE = 2f
private const val MAX_SCALE = 5f
