package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalCollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The items of a collection (02-components 6.1), drawn as the `collection` profile of the look says: `Cards` (Workbench)
 * gives each item its own bordered card, `density.gap` apart; every other profile keeps the one bordered block with a
 * hairline between the items (the table of Console, on a phone the stacked rows). [ground] is the card's or block's
 * ground; [inset] is the space at each side of an item that the item does not pad itself.
 */
@Composable
internal fun <T> SwCollection(
    items: List<T>,
    modifier: Modifier = Modifier,
    ground: Color = SpoolwardenTheme.colors.surface,
    inset: Dp = 0.dp,
    item: @Composable (index: Int, item: T) -> Unit,
) {
    if (LocalCollectionStyle.current == CollectionStyle.Cards) {
        Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.density.gap)) {
            items.forEachIndexed { i, entry -> Box(Modifier.collectionFrame(ground).padding(horizontal = inset)) { item(i, entry) } }
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
        LazyColumn(modifier, verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.density.gap)) {
            items(items, key = key) { entry -> Box(Modifier.collectionFrame(SpoolwardenTheme.colors.surface)) { item(entry) } }
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
private fun Modifier.collectionFrame(ground: Color): Modifier {
    val shape = SpoolwardenTheme.shapes.r
    return fillMaxWidth().clip(shape).background(ground, shape).border(SpoolwardenTheme.sizes.hairline, SpoolwardenTheme.colors.border, shape)
}

@Composable
private fun CollectionDivider() {
    HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border)
}
