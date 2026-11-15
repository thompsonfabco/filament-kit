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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedCard
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalCollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The narrowest a card of the `Cards` grid is: `minmax(18rem, 1fr)` of 02-components 6.1, at 16 dp to the rem. */
internal val CARD_MIN_WIDTH = 288.dp

/** How many cards of at least [CARD_MIN_WIDTH] fit across [available] with [gap] between them; one at the least. */
internal fun cardColumns(available: Dp, gap: Dp): Int = maxOf(1, ((available + gap) / (CARD_MIN_WIDTH + gap)).toInt())

/**
 * The items of a collection (02-components 6.1), drawn as the `collection` profile of the look says: `Cards` (Workbench)
 * gives each item its own bordered card in a grid of [CARD_MIN_WIDTH] columns, `density.gap` apart (one column on a
 * phone); every other profile keeps the one bordered block with a hairline between the items (the table of Console, on
 * a phone the stacked rows). [ground] is the card's or block's ground; [inset] is the space at each side of an item that
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
    item: @Composable (index: Int, item: T) -> Unit,
) {
    if (LocalCollectionStyle.current == CollectionStyle.Cards) {
        val gap = SpoolwardenTheme.density.gap
        BoxWithConstraints(modifier.fillMaxWidth()) {
            val columns = cardColumns(maxWidth, gap)
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(gap)) {
                items.withIndex().chunked(columns).forEach { line ->
                    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(gap)) {
                        line.forEach { (i, entry) ->
                            CollectionCard(Modifier.weight(1f).fillMaxHeight(), ground, inset) { item(i, entry) }
                        }
                        // the last line keeps the width of a card for the places not filled
                        repeat(columns - line.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
            }
        }
    } else if (surface) {
        CollectionCard(modifier, ground, inset) {
            Column {
                items.forEachIndexed { i, entry ->
                    if (i > 0) CollectionDivider()
                    item(i, entry)
                }
            }
        }
    } else {
        Column(modifier.fillMaxWidth().collectionFrame(ground).padding(horizontal = inset)) {
            items.forEachIndexed { i, entry ->
                if (i > 0) CollectionDivider()
                item(i, entry)
            }
        }
    }
}

/** [SwCollection] for a long list: the same two forms, the items composed as they scroll into view. */
@Composable
internal fun <T> SwLazyCollection(
    items: List<T>,
    key: (T) -> Any,
    modifier: Modifier = Modifier,
    item: @Composable (item: T) -> Unit,
) {
    if (LocalCollectionStyle.current == CollectionStyle.Cards) {
        val gap = SpoolwardenTheme.density.gap
        LazyVerticalGrid(
            GridCells.Adaptive(CARD_MIN_WIDTH), modifier,
            horizontalArrangement = Arrangement.spacedBy(gap), verticalArrangement = Arrangement.spacedBy(gap),
        ) {
            items(items, key = key) { entry -> CollectionCard(Modifier, SpoolwardenTheme.colors.surface, 0.dp) { item(entry) } }
        }
    } else {
        Box(modifier.fillMaxWidth().collectionFrame(SpoolwardenTheme.colors.surface)) {
            LazyColumn {
                items(items, key = key) { entry ->
                    item(entry)
                    if (entry !== items.last()) CollectionDivider()
                }
            }
        }
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

@Composable
private fun CollectionDivider() {
    HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border)
}
