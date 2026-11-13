package com.thompsonfabco.filamentkit.ui

import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull

/**
 * The checks of AUT-8 (07-accessibility 15) on a semantics tree, as a list of findings (empty: the tree passes):
 * every clickable node has text or a content description (AND-1); the tree has exactly one heading, the top bar's
 * title (AND-2); every clickable is at least 48 x 48 dp (AND-6); no checkbox, switch or radio button has its own
 * click handler inside a row that has text (AND-5).
 */
internal object SemanticsAudit {
    private const val MIN_TARGET_DP = 48

    /** [merged] is the root of the merged tree, [unmerged] of the unmerged one; [density] is pixels per dp. */
    fun findings(merged: SemanticsNode, unmerged: SemanticsNode, density: Float): List<String> = buildList {
        val all = merged.flatten()
        all.filter { it.isClickable() }.forEach { node ->
            val name = node.name()
            if (name.isBlank()) add("clickable without text or content description at ${node.boundsInRoot}")
            // the layout slot of the control: Material's minimum interactive size grows a 40 or 44 dp button to 48 dp
            // there while the drawn button stays smaller; a bare `clickable` gets no such slot (Compose widens the
            // touch area of every pointer input to 48 dp, so touch bounds cannot tell a small control from a large one)
            val widthDp = node.layoutInfo.width / density
            val heightDp = node.layoutInfo.height / density
            if (widthDp < MIN_TARGET_DP || heightDp < MIN_TARGET_DP) {
                add("clickable \"$name\" is ${widthDp}x$heightDp dp, under $MIN_TARGET_DP x $MIN_TARGET_DP")
            }
        }
        val headings = unmerged.flatten().filter { it.config.getOrNull(SemanticsProperties.Heading) != null }
        if (headings.size != 1) add("expected exactly one heading, found ${headings.size}")
        all.filter { it.isToggleWithoutRow() }.forEach { add("checkbox, switch or radio button with its own click beside text at ${it.boundsInRoot}") }
    }

    /** How many clickable nodes the tree holds (a test that audits none has audited nothing). */
    fun clickableCount(merged: SemanticsNode): Int = merged.flatten().count { it.isClickable() }

    private fun SemanticsNode.flatten(): List<SemanticsNode> = listOf(this) + children.flatMap { it.flatten() }

    private fun SemanticsNode.isClickable() = config.contains(SemanticsActions.OnClick)

    /** The words a screen reader gives the node: its text, else its content description. */
    private fun SemanticsNode.name(): String {
        val text = config.getOrNull(SemanticsProperties.Text)?.joinToString(" ") { it.text }.orEmpty()
        val description = config.getOrNull(SemanticsProperties.ContentDescription)?.joinToString(" ").orEmpty()
        val typed = config.getOrNull(SemanticsProperties.EditableText)?.text.orEmpty()
        return listOf(text, description, typed).filter { it.isNotBlank() }.joinToString(" ")
    }

    /** A toggle that answers taps itself, has no words of its own, and sits in a parent that has text (AND-5). */
    private fun SemanticsNode.isToggleWithoutRow(): Boolean {
        val role = config.getOrNull(SemanticsProperties.Role)
        val toggle = role == Role.Checkbox || role == Role.Switch || role == Role.RadioButton
        if (!toggle || !isClickable() || name().isNotBlank()) return false
        val row = parent ?: return false
        return row.flatten().any { it !== this && it.name().isNotBlank() }
    }
}
