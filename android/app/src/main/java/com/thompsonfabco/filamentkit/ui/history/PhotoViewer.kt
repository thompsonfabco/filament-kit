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
    val colors = SpoolwardenTheme.colors
    val total = s.record?.photos ?: 0
    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Box(Modifier.fillMaxSize().background(colors.bg)) {
            var page by remember { mutableIntStateOf(start.coerceAtLeast(1) - 1) }
            var zoomed by remember { mutableStateOf(false) }
            if (total > 0) {
                val pager = rememberPagerState(initialPage = page.coerceIn(0, total - 1)) { total }
                LaunchedEffect(pager.currentPage) {
                    page = pager.currentPage
                    zoomed = false
                }
                HorizontalPager(pager, Modifier.fillMaxSize(), userScrollEnabled = !zoomed) { p ->
                    PhotoPage(list, id, p + 1, total, onZoom = { zoomed = it })
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
                        stringResource(R.string.photo_position, page + 1, total),
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
private fun PhotoPage(list: HistoryListViewModel, id: String, n: Int, total: Int, onZoom: (Boolean) -> Unit) {
    var attempt by remember { mutableIntStateOf(0) }
    var load by remember { mutableStateOf<PhotoLoad>(PhotoLoad.Loading) }
    LaunchedEffect(id, n, attempt) {
        load = PhotoLoad.Loading
        val bytes = list.photo(id, n)
        val bitmap = bytes?.let { withContext(Dispatchers.Default) { decode(it, FULL_PX) } }
        load = if (bitmap == null) PhotoLoad.Failed else PhotoLoad.Loaded(bitmap)
    }
    val colors = SpoolwardenTheme.colors
    when (val l = load) {
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
