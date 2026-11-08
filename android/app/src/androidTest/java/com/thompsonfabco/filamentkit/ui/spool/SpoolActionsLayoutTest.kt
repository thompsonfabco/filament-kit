package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The spool card's actions at the widths the card really gets: the dialog leaves about 288 dp of content on a
 * 411 dp phone and about 248 dp on a 360 dp phone (240 dp checked for margin), at font scale 1.0 and 1.3.
 * Every label must stay on one line, unclipped, inside the card.
 */
@RunWith(AndroidJUnit4::class)
class SpoolActionsLayoutTest {
    @get:Rule val rule = createComposeRule()

    private var widthDp by mutableStateOf(288)
    private var fontScale by mutableStateOf(1f)

    @Test
    fun everyLabelStaysOnOneLine() {
        rule.setContent {
            val base = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
                MaterialTheme {
                    Box(Modifier.width(widthDp.dp)) { SpoolActions(canUpdate = true, onUpdate = {}, onMove = {}, onMarkEmpty = {}) }
                }
            }
        }
        for (w in listOf(288, 248, 240)) for (scale in listOf(1f, 1.3f)) {
            widthDp = w
            fontScale = scale
            rule.waitForIdle()
            val limit = with(rule.density) { w.dp.toPx() } + 0.5f
            for (label in listOf("Update weight", "Move", "Mark empty")) {
                val button = rule.onNodeWithText(label).fetchSemanticsNode()            // merged: the button
                val textNode = rule.onNodeWithText(label, useUnmergedTree = true).fetchSemanticsNode()
                val layouts = mutableListOf<TextLayoutResult>()
                textNode.config[SemanticsActions.GetTextLayoutResult].action?.invoke(layouts)
                val text = layouts.single()
                val where = "'$label' at $w dp, font x$scale"
                assertEquals("$where: lines", 1, text.lineCount)
                // The words end inside the space the text was given (not cut off by a squeezed button). Not
                // hasVisualOverflow: with softWrap off it reports overflow whenever the text is narrower than
                // its constraints.
                val inked = text.getLineRight(0)
                assertTrue("$where: clipped ($inked > ${text.size.width})", inked <= text.size.width + 0.5f)
                assertFalse("$where: clipped vertically", text.didOverflowHeight)
                assertTrue("$where: outside the card (${button.boundsInRoot.right} > $limit)", button.boundsInRoot.right <= limit)
            }
        }
    }
}
