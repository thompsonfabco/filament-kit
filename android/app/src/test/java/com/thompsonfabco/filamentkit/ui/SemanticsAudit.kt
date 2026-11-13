package com.thompsonfabco.filamentkit.ui

import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import com.thompsonfabco.filamentkit.ui.components.TOP_BAR_TAG

/**
 * The checks of AUT-8 (07-accessibility 15) on a semantics tree, as a list of findings (empty: the tree passes):
 * every clickable node has text or a content description (AND-1); the top app bar holds exactly one heading and it is
 * the screen's title, and every section title the test lists is a heading (AND-2; other headings are allowed); every
 * clickable is at least 48 x 48 dp (AND-6); no checkbox, switch or radio button has its own click handler inside a
 * row that has text (AND-5).
 */
internal object SemanticsAudit {
    private const val MIN_TARGET_DP = 48

    /** Material's smallest drawn control (a 40 dp button), which its minimum interactive size grows to 48 dp. */
    private const val MATERIAL_CONTROL_DP = 40

    /**
     * [merged] is the root of the merged tree, [unmerged] of the unmerged one; [density] is pixels per dp; [title] is
     * the top bar's title (null: the screen is drawn without a top bar); [sectionTitles] are the section titles the screen shows.
     */
    fun findings(
        merged: SemanticsNode,
        unmerged: SemanticsNode,
        density: Float,
        title: String?,
        sectionTitles: List<String> = emptyList(),
        /** False for the root of a dialog or sheet window: it has no top bar, only the controls rules apply. */
        screenRoot: Boolean = true,
    ): List<String> = buildList {
        val all = merged.flatten()
        all.filter { it.isClickable() }.forEach { node ->
            val name = node.name()
            if (name.isBlank()) add("clickable without text or content description at ${node.boundsInRoot}")
            // The clickable's own bounds count, not the box around it (outer padding is not touchable). Material's
            // minimum interactive size is the one exception: it grows a 40 or 44 dp button's layout slot to 48 dp
            // and the node itself stays smaller. (Compose widens the touch area of every pointer input to 48 dp, so
            // touch bounds cannot tell a small control from a large one.)
            if (!reaches(node.size.width / density, node.layoutInfo.width / density) ||
                !reaches(node.size.height / density, node.layoutInfo.height / density)
            ) {
                add("clickable \"$name\" is ${node.size.width / density}x${node.size.height / density} dp, under $MIN_TARGET_DP x $MIN_TARGET_DP")
            }
        }
        val all2 = unmerged.flatten()
        val bar = all2.firstOrNull { it.config.getOrNull(SemanticsProperties.TestTag) == TOP_BAR_TAG }
        val inBar = bar?.flatten().orEmpty().filter { it.isHeading() }
        when {
            !screenRoot -> Unit
            title == null -> if (bar != null) add("a top app bar where the screen has none")
            bar == null -> add("no top app bar in the screen")
            inBar.size != 1 -> add("expected exactly one heading in the top app bar, found ${inBar.size}")
            inBar[0].name() != title -> add("the top bar heading is \"${inBar[0].name()}\", not the title \"$title\"")
        }
        sectionTitles.forEach { section ->
            if (all2.none { it.isHeading() && it.name() == section }) add("section title \"$section\" is not a heading")
        }
        all.filter { it.isToggleWithoutRow() }.forEach { add("checkbox, switch or radio button with its own click beside text at ${it.boundsInRoot}") }
    }

    private fun reaches(node: Float, slot: Float) = node >= MIN_TARGET_DP || (slot >= MIN_TARGET_DP && node >= MATERIAL_CONTROL_DP)

    private fun SemanticsNode.isHeading() = config.getOrNull(SemanticsProperties.Heading) != null

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
