package com.thompsonfabco.filamentkit.ui.history

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.addOutline
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement

/**
 * A panel (05-android-app 3.1, "Form group"): `surface` ground, 1 dp `border`, `r` corners, a header row at least
 * `row` high with the title, an optional [tag] after it and [actions] at the right, a body, and an optional footer.
 */
@Composable
internal fun RecentPanel(
    title: String,
    modifier: Modifier = Modifier,
    tag: String? = null,
    actions: (@Composable RowScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    OutlinedCard(
        modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(horizontal = space.s4, vertical = space.s2),
            horizontalArrangement = Arrangement.spacedBy(space.s2),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(title, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleMedium)
                if (tag != null) Text(tag, color = colors.muted, style = MaterialTheme.typography.bodySmall)
            }
            actions?.invoke(this)
        }
        Column(
            Modifier.fillMaxWidth().padding(start = space.s4, end = space.s4, bottom = space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
            content = content,
        )
    }
}

/** A shape and a word in one colour (02-components 7.1): never the shape alone, never the colour alone. */
@Composable
internal fun RecentStatusLine(@DrawableRes shape: Int, word: String, colour: Color, modifier: Modifier = Modifier, large: Boolean = false) {
    val space = SpoolwardenTheme.space
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(space.s1), verticalAlignment = Alignment.CenterVertically) {
        Icon(
            painterResource(shape), contentDescription = null,
            modifier = Modifier.size(if (large) space.s2 + space.s1 / 2 else space.s2), tint = colour,
        )
        Text(word, color = colour, style = MaterialTheme.typography.labelMedium)
    }
}

/** The record's state as a status (hollow circle, info circle or pencil) with its word. */
@Composable
internal fun IntakeStateLabel(wire: String, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val state = IntakeState.of(wire)
    if (state == null) {
        RecentStatusLine(R.drawable.sw_st_hollow, wire, colors.muted, modifier)
    } else {
        RecentStatusLine(state.shape, stringResource(state.word), if (state.info) colors.info else colors.muted, modifier)
    }
}

@Composable
internal fun sourceText(source: String, photos: Int): String {
    val label = sourceLabel(source, photos)
    return label.word?.let { stringResource(it) } ?: label.raw
}

/** A field's value with its unit after a space ("150 g"); null when the value is empty. */
@Composable
internal fun fieldValue(field: RecentField?, v: JsonElement?): String? {
    val text = RecentValues.text(v) ?: return null
    val unit = field?.unit ?: return text
    return stringResource(R.string.recent_value_unit, text, stringResource(unit))
}

/** The Hub's name of a field in words: the catalogue's label, else the Hub's own name. */
@Composable
internal fun fieldName(wire: String): String = RecentField.of(wire)?.let { stringResource(it.label) } ?: wire.replace('_', ' ')

/** "Empty spool weight 150 → 140 g", the unit once at the end. */
@Composable
internal fun changeText(wire: String, old: JsonElement?, new: JsonElement?): String {
    val field = RecentField.of(wire)
    val empty = stringResource(R.string.recent_value_empty)
    val from = RecentValues.text(old) ?: empty
    val to = RecentValues.text(new) ?: empty
    val unit = field?.unit
    return if (unit != null) {
        stringResource(R.string.recent_change_unit, fieldName(wire), from, to, stringResource(unit))
    } else {
        stringResource(R.string.recent_change, fieldName(wire), from, to)
    }
}

/** What a failed request says (05-android-app 3.5 and 6.2); the Hub's own message is shown as given. */
@Composable
internal fun failureText(f: RecentFailure): String = when (f) {
    RecentFailure.Offline -> stringResource(R.string.common_hub_unreachable)
    RecentFailure.Unexpected -> stringResource(R.string.common_hub_answer_unknown)
    RecentFailure.ReaderOff -> stringResource(R.string.recent_reader_off)
    RecentFailure.DailyLimit -> stringResource(R.string.add_read_limit)
    RecentFailure.ReaderBusy -> stringResource(R.string.add_read_busy)
    is RecentFailure.Hub -> f.message
}

/** A dashed `border` outline in [shape] (the box that stands for a photo that is not there). */
internal fun Modifier.dashedOutline(colour: Color, shape: Shape, dash: Dp, width: Dp): Modifier =
    drawBehind {
        val on = dash.toPx()
        drawPath(
            Path().apply { addOutline(shape.createOutline(size, layoutDirection, this@drawBehind)) }, colour,
            style = Stroke(width.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(on, on))),
        )
    }

/**
 * Photo [n] of record [id], fetched once per visit. [thumb] decodes it small and crops it square; a photo that is not
 * there yet (or could not be had) is a `surface2` block.
 */
@Composable
internal fun RecentPhoto(vm: HistoryListViewModel, id: String, n: Int, modifier: Modifier, description: String?, thumb: Boolean = true) {
    val bitmap by produceState<Bitmap?>(null, id, n, thumb) {
        val bytes = vm.photo(id, n) ?: return@produceState
        value = withContext(Dispatchers.Default) { decode(bytes, if (thumb) THUMB_PX else FULL_PX) }
    }
    val b = bitmap
    if (b == null) {
        Box(modifier.background(SpoolwardenTheme.colors.surface2).semantics { description?.let { contentDescription = it } })
    } else {
        Image(
            b.asImageBitmap(), contentDescription = description, modifier = modifier,
            contentScale = if (thumb) ContentScale.Crop else ContentScale.Fit,
        )
    }
}

/** Decodes a JPEG no larger than about [max] pixels on its long side (a full photo is not needed for a thumbnail). */
internal fun decode(bytes: ByteArray, max: Int): Bitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= max) sample *= 2
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
}

private const val THUMB_PX = 192
internal const val FULL_PX = 1600
