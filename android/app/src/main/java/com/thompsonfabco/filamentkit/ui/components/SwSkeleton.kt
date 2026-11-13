package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.Dp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * A block of the loading skeleton (02-components 10.3): `surface2` with `rS` corners, the height of what will arrive
 * (a row by default), no animation. It says nothing to TalkBack; the progress line under the top bar is the signal.
 */
@Composable
internal fun SwSkeleton(modifier: Modifier = Modifier, height: Dp = SpoolwardenTheme.sizes.row) {
    Box(
        modifier.fillMaxWidth().height(height).background(SpoolwardenTheme.colors.surface2, SpoolwardenTheme.shapes.rS)
            .clearAndSetSemantics { },
    )
}

/** [rows] skeleton rows one under the other, `gap` apart. */
@Composable
internal fun SwSkeletonRows(rows: Int = DEFAULT_SKELETON_ROWS, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.density.gap)) {
        repeat(rows) { SwSkeleton() }
    }
}

private const val DEFAULT_SKELETON_ROWS = 4
