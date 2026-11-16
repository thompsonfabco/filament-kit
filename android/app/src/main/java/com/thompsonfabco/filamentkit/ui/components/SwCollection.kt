package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedCard
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalCollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The test tag of the hairline between two rows of `CollectionStyle.Rows`. */
internal const val ROW_DIVIDER_TAG = "rows-divider"

/** The narrowest a card of the `Cards` grid is at font scale 1: `minmax(18rem, 1fr)` of 02-components 6.1, at 16 dp to the rem. */
internal val CARD_MIN_WIDTH = 288.dp

/** The narrowest a tile of the `Tiles` grid is at font scale 1: `minmax(14rem, 1fr)` of 02-components 6.1, at 16 dp to the rem. */
internal val TILE_MIN_WIDTH = 224.dp

/** How many columns of at least [min] fit across [available] with [gap] between them; one at the least. */
private fun columnsOf(available: Dp, gap: Dp, min: Dp): Int = maxOf(1, ((available + gap) / (min + gap)).toInt())

/** How many cards of at least [min] fit across [available] with [gap] between them; one at the least. */
internal fun cardColumns(available: Dp, gap: Dp, min: Dp = CARD_MIN_WIDTH): Int = columnsOf(available, gap, min)

/**
 * How many tiles of at least [min] fit across [available] with [gap] between them, one at the least: the rule of the
 * web's `repeat(auto-fill, minmax(14rem, 1fr))` at every window width (a phone is one column until two tiles fit).
 */
internal fun tileColumns(available: Dp, gap: Dp, min: Dp = TILE_MIN_WIDTH): Int = columnsOf(available, gap, min)

/**
 * [base] (dp at font scale 1, 16 dp to the rem) as rem: the rem is a 16 sp text size, so the width grows with the font
 * scale like the web's `rem` does and a column keeps its words.
 */
@Composable
private fun remWidth(base: Dp): Dp = with(LocalDensity.current) { 16.sp.toDp() * (base / 16.dp) }

/** The columns of the grid forms (`Cards`, `Tiles`) across [available]; 0 for the forms that are not a grid. */
private fun gridColumns(style: CollectionStyle, available: Dp, gap: Dp, cardMin: Dp, tileMin: Dp): Int = when (style) {
    CollectionStyle.Cards -> cardColumns(available, gap, cardMin)
    CollectionStyle.Tiles -> tileColumns(available, gap, tileMin)
    else -> 0
}

private fun isGrid(style: CollectionStyle) = style == CollectionStyle.Cards || style == CollectionStyle.Tiles

/**
 * The items of a collection (02-components 6.1), drawn as the `collection` profile of the look says: `Cards` (Workbench)
 * gives each item its own bordered card in a grid of [CARD_MIN_WIDTH] columns, `density.gap` apart (one column on a
 * phone); `Tiles` (Palette) the same in [TILE_MIN_WIDTH] columns, where an item gives its [tile] (a [SwTile]; without one
 * the item is drawn in a plain card). Both widths are rem: they grow with the font scale. Every other profile keeps the
 * one bordered block with a hairline between the items (the table of Console, on a phone the stacked rows); `Rows` (Panes)
 * is that block with every row at least `--row` high, its content `--s4` from the edge, and the hairlines inset by the
 * [visual]'s width (the width of the item's swatch, photo or ring with the gap after it; 0 for an item without one).
 * [ground] is the card's or block's ground; [inset] is the space at each side of an item that
 * the item does not pad itself. [surface] makes the block a Surface (one traversal group that also stops touches reaching
 * what lies behind it, as a card does); the cards always are.
 *
 * The grid here is built from rows rather than a `LazyVerticalGrid`, which cannot sit in the scrolling column the
 * screens put their lists in; [SwLazyCollection] is the lazy grid.
 */
@Composable
internal fun <T> SwCollection(
    items: List<T>,
    modifier: Modifier = Modifier,
    ground: Color = SpoolwardenTheme.colors.surface,
    inset: Dp = 0.dp,
    surface: Boolean = false,
    visual: Dp = 0.dp,
    tile: (@Composable (index: Int, item: T) -> Unit)? = null,
    isExpanded: ((T) -> Boolean)? = null,
    detail: (@Composable (index: Int, item: T) -> Unit)? = null,
    item: @Composable (index: Int, item: T) -> Unit,
) {
    val style = LocalCollectionStyle.current
    val rows = style == CollectionStyle.Rows
    val divider = if (rows) rowDividerStart(inset, visual) else 0.dp
    if (isGrid(style)) {
        val gap = SpoolwardenTheme.density.gap
        val cardMin = remWidth(CARD_MIN_WIDTH)
        val tileMin = remWidth(TILE_MIN_WIDTH)
        BoxWithConstraints(modifier.fillMaxWidth()) {
            val columns = gridColumns(style, maxWidth, gap, cardMin, tileMin)
            val expandCards = style == CollectionStyle.Cards && isExpanded != null && detail != null
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(gap)) {
                if (expandCards) {
                    val pending = mutableListOf<IndexedValue<T>>()
                    val flushPending: @Composable () -> Unit = {
                        if (pending.isNotEmpty()) {
                            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(gap)) {
                                pending.forEach { (idx, entry) ->
                                    CollectionCard(Modifier.weight(1f).fillMaxHeight(), ground, inset) { item(idx, entry) }
                                }
                                repeat(columns - pending.size) { Spacer(Modifier.weight(1f)) }
                            }
                            pending.clear()
                        }
                    }
                    items.withIndex().forEach { indexed ->
                        if (isExpanded(indexed.value)) {
                            flushPending()
                            CollectionCard(Modifier.fillMaxWidth(), ground, inset) {
                                Column(Modifier.fillMaxWidth()) {
                                    item(indexed.index, indexed.value)
                                    CollectionDivider()
                                    detail(indexed.index, indexed.value)
                                }
                            }
                        } else {
                            pending.add(indexed)
                            if (pending.size == columns) flushPending()
                        }
                    }
                    flushPending()
                } else {
                    items.withIndex().chunked(columns).forEach { line ->
                        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(gap)) {
                            line.forEach { (i, entry) ->
                                if (style == CollectionStyle.Tiles && tile != null) {
                                    Box(Modifier.weight(1f).fillMaxHeight()) { tile(i, entry) }
                                } else {
                                    CollectionCard(Modifier.weight(1f).fillMaxHeight(), ground, inset) { item(i, entry) }
                                }
                            }
                            // the last line keeps the width of a card for the places not filled
                            repeat(columns - line.size) { Spacer(Modifier.weight(1f)) }
                        }
                    }
                }
            }
        }
    } else if (surface) {
        CollectionCard(modifier, ground, inset) {
            Column {
                items.forEachIndexed { i, entry ->
                    if (i > 0) CollectionDivider(divider, rows)
                    CollectionRow(rows, inset) { item(i, entry) }
                }
            }
        }
    } else {
        Column(modifier.fillMaxWidth().collectionFrame(ground).padding(horizontal = inset)) {
            items.forEachIndexed { i, entry ->
                if (i > 0) CollectionDivider(divider, rows)
                CollectionRow(rows, inset) { item(i, entry) }
            }
        }
    }
}

/** [SwCollection] for a long list: the same forms, the items composed as they scroll into view. */
@Composable
internal fun <T> SwLazyCollection(
    items: List<T>,
    key: (T) -> Any,
    modifier: Modifier = Modifier,
    visual: Dp = 0.dp,
    tile: (@Composable (item: T) -> Unit)? = null,
    isExpanded: ((T) -> Boolean)? = null,
    detail: (@Composable (item: T) -> Unit)? = null,
    item: @Composable (item: T) -> Unit,
) {
    val style = LocalCollectionStyle.current
    val rows = style == CollectionStyle.Rows
    if (isGrid(style)) {
        val gap = SpoolwardenTheme.density.gap
        val cells = if (style == CollectionStyle.Tiles) TileCells(gap, remWidth(TILE_MIN_WIDTH)) else GridCells.Adaptive(remWidth(CARD_MIN_WIDTH))
        val expandCards = style == CollectionStyle.Cards && isExpanded != null && detail != null
        LazyVerticalGrid(
            cells, modifier,
            horizontalArrangement = Arrangement.spacedBy(gap), verticalArrangement = Arrangement.spacedBy(gap),
        ) {
            if (expandCards) {
                items(
                    items,
                    key = key,
                    span = { entry -> GridItemSpan(if (isExpanded(entry)) maxLineSpan else 1) },
                ) { entry ->
                    CollectionCard(Modifier, SpoolwardenTheme.colors.surface, 0.dp) {
                        if (isExpanded(entry)) {
                            Column(Modifier.fillMaxWidth()) {
                                item(entry)
                                CollectionDivider()
                                detail(entry)
                            }
                        } else {
                            item(entry)
                        }
                    }
                }
            } else {
                items(items, key = key) { entry ->
                    if (style == CollectionStyle.Tiles && tile != null) {
                        tile(entry)
                    } else {
                        CollectionCard(Modifier, SpoolwardenTheme.colors.surface, 0.dp) { item(entry) }
                    }
                }
            }
        }
    } else {
        Box(modifier.fillMaxWidth().collectionFrame(SpoolwardenTheme.colors.surface)) {
            LazyColumn {
                items(items, key = key) { entry ->
                    CollectionRow(rows, 0.dp) { item(entry) }
                    if (entry !== items.last()) CollectionDivider(if (rows) rowDividerStart(0.dp, visual) else 0.dp, rows)
                }
            }
        }
    }
}

/** The columns of [tileColumns] for a lazy grid, which hands over its width in pixels. */
private class TileCells(private val gap: Dp, private val min: Dp) : GridCells {
    override fun Density.calculateCrossAxisCellSizes(availableSize: Int, spacing: Int): List<Int> {
        val columns = tileColumns(availableSize.toDp(), gap, min)
        val cell = (availableSize - spacing * (columns - 1)) / columns
        return List(columns) { cell }
    }
}

@Composable
private fun CollectionCard(modifier: Modifier, ground: Color, inset: Dp, content: @Composable () -> Unit) {
    val colors = SpoolwardenTheme.colors
    OutlinedCard(
        modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = ground, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Box(Modifier.padding(horizontal = inset)) { content() }
    }
}

@Composable
private fun Modifier.collectionFrame(ground: Color): Modifier {
    val shape = SpoolwardenTheme.shapes.r
    return fillMaxWidth().clip(shape).background(ground, shape).border(SpoolwardenTheme.sizes.hairline, SpoolwardenTheme.colors.border, shape)
}

/** Where the hairlines of `Rows` start, from the edge of the padded area: the content's `--s4` when [inset] gives none, then the [visual]. */
@Composable
private fun rowDividerStart(inset: Dp, visual: Dp): Dp = (if (inset > 0.dp) 0.dp else SpoolwardenTheme.space.s4) + visual

/**
 * One item of `Rows`: at least `--row` high, its content `--s4` from the block's edge (the items pad `--s3` themselves, so
 * `--s1` is added unless [inset] already sets the edge). Every other form draws the item as it is.
 */
@Composable
private fun CollectionRow(rows: Boolean, inset: Dp, content: @Composable () -> Unit) {
    if (!rows) {
        content()
        return
    }
    val pad = if (inset > 0.dp) 0.dp else SpoolwardenTheme.space.s1
    Box(Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(horizontal = pad)) { content() }
}

@Composable
private fun CollectionDivider(start: Dp = 0.dp, rows: Boolean = false) {
    HorizontalDivider(
        (if (rows) Modifier.padding(start = start).testTag(ROW_DIVIDER_TAG) else Modifier),
        thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border,
    )
}
