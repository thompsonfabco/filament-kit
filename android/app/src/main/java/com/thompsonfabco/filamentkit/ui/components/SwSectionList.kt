package com.thompsonfabco.filamentkit.ui.components

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.min
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The test tag of a section's row in [SwSectionList]. */
internal const val SECTION_ROW_TAG = "section-row"

/** The test tag of the icon tile of a section's row. */
internal const val SECTION_TILE_TAG = "section-tile"

/** The test tag of the hairline between two rows of a group. */
internal const val SECTION_DIVIDER_TAG = "section-divider"

/** The two groups of the list (02-components 2.3, foundations 8): Everyday, then System, which on Android is Settings. */
internal val SECTION_GROUPS: List<Pair<Int, List<Tab>>> = listOf(
    R.string.nav_everyday to listOf(Tab.Home, Tab.Spools, Tab.Printers, Tab.Recent),
    R.string.nav_system to listOf(Tab.Settings),
)

/** The width of the section pane of a window [available] wide: `min(--list-w, 40%)` like the web's shell column. */
internal fun sectionPaneWidth(listW: Dp, available: Dp): Dp = min(listW, available * 0.4f)

/**
 * The section list of `NavStyle.List` (Panes; 02-components 2.3, 08-platform-mapping 10.1): the navigation as a list
 * of grouped blocks on the `bg` ground, each a heading (`--fs-xs`, uppercase, `muted`) over a `surface` block with the
 * `r` corners and a 1 dp `border`. A row is a `ListItem` at least `--s7 + --s1` high: an icon in a tile (`--s5 + --s1`,
 * `surface3`), the section's name (`--fs-b` at the label weight), its summary line when [summaries] has one (`--fs-s`,
 * `muted`) and a chevron; `border` hairlines between rows start where the name starts. The current section's row has
 * the `surface3` ground and its icon tile `accent` with `onAccent` (the one use of `accent` the foundations give
 * navigation). A row is a tab (selected when current); the row of [settingsUpdate] is named "Settings, update
 * available". [focusOn] takes focus to that section's row when the list appears (Back from a section on a phone).
 * [modifier] sizes the list; it scrolls inside.
 */
@Composable
internal fun SwSectionList(
    selected: Tab?,
    onSelect: (Tab) -> Unit,
    modifier: Modifier = Modifier,
    summaries: Map<Tab, String> = emptyMap(),
    settingsUpdate: Boolean = false,
    focusOn: Tab? = null,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val shape = SpoolwardenTheme.shapes.r
    val requesters = remember { Tab.entries.associateWith { FocusRequester() } }
    if (focusOn != null) LaunchedEffect(focusOn) { requesters.getValue(focusOn).requestFocus() }
    Column(
        modifier.background(colors.bg).verticalScroll(rememberScrollState()).padding(start = space.s3, end = space.s3, top = space.s3, bottom = space.s5),
    ) {
        SECTION_GROUPS.forEach { (title, tabs) ->
            Text(
                stringResource(title).uppercase(),
                Modifier.padding(start = space.s3, end = space.s3, top = space.s3, bottom = space.s2).semantics { heading() },
                color = colors.muted, style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 0.05.em),
            )
            Column(
                Modifier.fillMaxWidth().clip(shape).background(colors.surface, shape)
                    .border(SpoolwardenTheme.sizes.hairline, colors.border, shape),
            ) {
                tabs.forEachIndexed { i, tab ->
                    if (i > 0) {
                        // the hairline starts where the name starts: the ListItem's 16 dp, the icon tile and the 16 dp after it
                        HorizontalDivider(
                            Modifier.padding(start = space.s4 * 2 + space.s5 + space.s1).testTag(SECTION_DIVIDER_TAG),
                            thickness = SpoolwardenTheme.sizes.hairline, color = colors.border,
                        )
                    }
                    SectionRow(
                        tab, current = tab == selected, summary = summaries[tab], update = tab == Tab.Settings && settingsUpdate,
                        onClick = { onSelect(tab) }, modifier = Modifier.focusRequester(requesters.getValue(tab)),
                    )
                }
            }
        }
    }
}

@Composable
private fun SectionRow(tab: Tab, current: Boolean, summary: String?, update: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val name = stringResource(tab.label)
    val updateName = stringResource(R.string.nav_settings_update)
    val ground = if (current) colors.surface3 else colors.surface
    ListItem(
        headlineContent = {
            Text(
                name, maxLines = 2, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyLarge.copy(fontWeight = MaterialTheme.typography.labelLarge.fontWeight),
            )
        },
        supportingContent = summary?.let { text ->
            { Text(text, style = MaterialTheme.typography.bodySmall, color = colors.muted) }
        },
        leadingContent = {
            val tile = Modifier.size(space.s5 + space.s1).testTag(SECTION_TILE_TAG)
                .background(if (current) colors.accent else colors.surface3, SpoolwardenTheme.shapes.rS).padding(space.s1)
            val tint = if (current) colors.onAccent else colors.text
            if (update) {
                BadgedBox(badge = { Box(Modifier.size(space.s2).background(colors.accentText, CircleShape)) }) {
                    SwIcon(tab.icon, null, tile, tint = tint)
                }
            } else {
                SwIcon(tab.icon, null, tile, tint = tint)
            }
        },
        trailingContent = { SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted) },
        colors = ListItemDefaults.colors(
            containerColor = ground, headlineColor = colors.text, supportingColor = colors.muted,
            leadingIconColor = colors.text, trailingIconColor = colors.muted,
        ),
        modifier = modifier.heightIn(min = space.s7 + space.s1).testTag(SECTION_ROW_TAG)
            .selectable(selected = current, role = Role.Tab, onClick = onClick)
            .then(if (update) Modifier.semantics { contentDescription = updateName } else Modifier),
    )
}

/**
 * The section list as the root page of a phone (02-components 2.3: `list` becomes the root page): the list fills the
 * window on the `bg` ground and, as a surface, keeps touches from the screen under it.
 */
@Composable
internal fun SwSectionPage(
    selected: Tab?,
    onSelect: (Tab) -> Unit,
    modifier: Modifier = Modifier,
    summaries: Map<Tab, String> = emptyMap(),
    settingsUpdate: Boolean = false,
    focusOn: Tab? = null,
) {
    Surface(modifier.fillMaxSize(), color = SpoolwardenTheme.colors.bg) {
        SwSectionList(selected, onSelect, Modifier.fillMaxSize(), summaries, settingsUpdate, focusOn)
    }
}

/**
 * The section pane beside the content on a tablet or expanded width (08-platform-mapping 10.1): the list, `min(--list-w,
 * 40%)` wide on a `bg` ground with a 1 dp `border` edge, under a strip of the top bar's height that carries the product
 * mark; [content] gets the rest. The pane keeps clear of [insets] (the cutout and the bars at the start and the bottom).
 */
@Composable
internal fun SwSectionPane(
    selected: Tab?,
    onSelect: (Tab) -> Unit,
    modifier: Modifier = Modifier,
    summaries: Map<Tab, String> = emptyMap(),
    settingsUpdate: Boolean = false,
    insets: WindowInsets = WindowInsets.safeDrawing.only(WindowInsetsSides.Start + WindowInsetsSides.Top + WindowInsetsSides.Bottom),
    content: @Composable () -> Unit,
) {
    val colors = SpoolwardenTheme.colors
    val sizes = SpoolwardenTheme.sizes
    BoxWithConstraints(modifier.fillMaxSize()) {
        val paneWidth = sectionPaneWidth(sizes.listW, maxWidth)
        Row(Modifier.fillMaxSize()) {
            Column(Modifier.width(paneWidth).fillMaxHeight().background(colors.bg).windowInsetsPadding(insets)) {
                Row(
                    Modifier.fillMaxWidth().heightIn(min = sizes.top).background(colors.surface).padding(horizontal = SpoolwardenTheme.space.s4),
                    horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s3), verticalAlignment = Alignment.CenterVertically,
                ) {
                    SwIcon(R.drawable.sw_ic_spoolwarden, null, size = SwIconSize.Large, tint = colors.accentText)
                }
                HorizontalDivider(thickness = sizes.hairline, color = colors.border)
                SwSectionList(selected, onSelect, Modifier.weight(1f).fillMaxWidth(), summaries, settingsUpdate)
            }
            // the edge between the pane and the page
            Box(Modifier.width(sizes.hairline).fillMaxHeight().background(colors.border))
            Box(Modifier.weight(1f).fillMaxHeight()) { content() }
        }
    }
}

/**
 * Where a phone in Panes is between the list of sections and a section (02-components 2.3: with `list` the navigation is
 * the root page, choosing an item drills in, and Back returns to the list). [open] is true while the list is the page;
 * [focus] is true after Back, so the list puts focus on the row of the section left.
 */
internal class SectionDrill(open: Boolean = true) {
    var open by mutableStateOf(open)
    var focus by mutableStateOf(false)

    /** The list is the page: the drill is [active] (Panes on a phone, navigation shown), the screen is the root of its section and the list is open. */
    fun showsPage(active: Boolean, atRoot: Boolean) = active && atRoot && open

    /** A section's root is the page, and Back goes to the list. */
    fun drilledIn(active: Boolean, atRoot: Boolean) = active && atRoot && !open

    companion object {
        val Saver = androidx.compose.runtime.saveable.Saver<SectionDrill, Boolean>(save = { it.open }, restore = { SectionDrill(it) })
    }
}

@Composable
internal fun rememberSectionDrill(): SectionDrill = rememberSaveable(saver = SectionDrill.Saver) { SectionDrill() }

/** What the screens under the list of a phone in Panes carry: out of reach of touch, focus and screen readers. */
internal fun Modifier.underSectionList(hidden: Boolean): Modifier =
    if (hidden) clearAndSetSemantics {}.focusProperties { canFocus = false } else this

/**
 * The drill-in of a phone in Panes over the screens: while [drill] shows the page, the section list covers [modifier]'s area
 * and choosing a section runs [onSelect] and opens it; while a section's root is the page, Back (the top bar's arrow too)
 * returns to the list, focus on that section's row; on the list Back runs [onLeave]. Composed after the screens, so its Back
 * handlers go before theirs. Nothing while the drill is not [active] (another look, a wider window, the navigation hidden).
 */
@Composable
internal fun SwSectionDrill(
    drill: SectionDrill,
    active: Boolean,
    atRoot: Boolean,
    selected: Tab?,
    onSelect: (Tab) -> Unit,
    onLeave: () -> Unit,
    modifier: Modifier = Modifier,
    summaries: Map<Tab, String> = emptyMap(),
    settingsUpdate: Boolean = false,
) {
    val page = drill.showsPage(active, atRoot)
    if (page) {
        SwSectionPage(
            selected, { chosen -> onSelect(chosen); drill.open = false; drill.focus = false }, modifier,
            summaries, settingsUpdate, focusOn = if (drill.focus) selected else null,
        )
    }
    BackHandler(enabled = drill.drilledIn(active, atRoot)) { drill.open = true; drill.focus = true }
    BackHandler(enabled = page) { onLeave() }
}
