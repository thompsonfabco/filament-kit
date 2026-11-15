package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.background
import androidx.annotation.DrawableRes
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.PermanentDrawerSheet
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Tab as MaterialTab
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffoldLayout
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteType
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.collapse
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.expand
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.LayoutDirection
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.ui.theme.LocalNavStyle
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/**
 * The shell around the main graph (05-android-app 2.1, 2.3): the bottom bar on a phone, the rail on a wider window,
 * the same five [Tab]s in both. The `nav` profile of the look (02-components 2.3) changes only the wide form: `Sidebar`
 * (Workbench) is the rail on a tablet and a permanent drawer `sideW` wide on expanded width; `Pills` (Palette) leaves the wide form to [SwPills]. [selected] is the current destination, null while a screen outside the five is on top
 * (the bar is then [visible] = false). A dot on Settings tells that an app update is ready ([settingsUpdate]).
 *
 * The bar and the rail keep Material's own geometry (80 dp high, 80 dp wide at least); [content] gets a 1 dp
 * `border` hairline between it and them.
 */
@Composable
internal fun SwNav(
    selected: Tab?,
    visible: Boolean,
    onSelect: (Tab) -> Unit,
    modifier: Modifier = Modifier,
    settingsUpdate: Boolean = false,
    content: @Composable () -> Unit,
) {
    val colors = SpoolwardenTheme.colors
    val sizes = SpoolwardenTheme.sizes
    val window = SpoolwardenTheme.window
    val layout = navLayout(visible, window, LocalNavStyle.current)
    val labels = Tab.entries.map { stringResource(it.label) }
    val updateName = stringResource(R.string.nav_settings_update)
    val barColors = NavigationBarItemDefaults.colors(
        selectedIconColor = colors.accentText, selectedTextColor = colors.accentText, indicatorColor = colors.accentSoft,
        unselectedIconColor = colors.muted, unselectedTextColor = colors.muted,
    )
    val railColors = NavigationRailItemDefaults.colors(
        selectedIconColor = colors.accentText, selectedTextColor = colors.accentText, indicatorColor = colors.accentSoft,
        unselectedIconColor = colors.muted, unselectedTextColor = colors.muted,
    )
    val drawerColors = NavigationDrawerItemDefaults.colors(
        selectedContainerColor = colors.accentSoft, unselectedContainerColor = Color.Transparent,
        selectedIconColor = colors.accentText, selectedTextColor = colors.accentText,
        unselectedIconColor = colors.muted, unselectedTextColor = colors.text,
    )
    val space = SpoolwardenTheme.space
    val dotSize = space.s2
    val labelWeight = MaterialTheme.typography.titleMedium.fontWeight
    val labelStyle = MaterialTheme.typography.labelSmall
    // The icon, with the update dot on Settings; the item carries the name "Settings, update available".
    fun Modifier.named(tab: Tab): Modifier =
        if (tab == Tab.Settings && settingsUpdate) semantics { contentDescription = updateName } else this
    @Composable
    fun Icon(tab: Tab) {
        val withDot = tab == Tab.Settings && settingsUpdate
        if (withDot) {
            BadgedBox(badge = { Box(Modifier.size(dotSize).background(colors.accentText, CircleShape)) }) {
                SwIcon(tab.icon, null)
            }
        } else {
            SwIcon(tab.icon, null)
        }
    }
    NavigationSuiteScaffoldLayout(
        navigationSuite = {
            when (layout) {
                NavigationSuiteType.NavigationRail -> NavigationRail(
                    containerColor = colors.surface,
                    contentColor = colors.muted,
                    // the product mark tops the rail (05-android-app 2.1)
                    header = { SwIcon(R.drawable.sw_ic_spoolwarden, null, size = SwIconSize.Large, tint = colors.accentText) },
                ) {
                    Tab.entries.forEachIndexed { i, tab ->
                        val current = tab == selected
                        NavigationRailItem(
                            selected = current,
                            onClick = { onSelect(tab) },
                            icon = { Icon(tab) },
                            modifier = Modifier.named(tab).drawWithContent {
                                drawContent()
                                // the current item: a mark at the outer edge (08-platform-mapping 10.1)
                                if (current) {
                                    val width = sizes.navMark.toPx()
                                    val x = if (layoutDirection == LayoutDirection.Ltr) 0f else size.width - width
                                    drawRect(colors.accentText, Offset(x, 0f), Size(width, size.height))
                                }
                            },
                            label = { Text(labels[i], style = labelStyle, fontWeight = if (current) labelWeight else null) },
                            alwaysShowLabel = true,
                            colors = railColors,
                        )
                    }
                }
                NavigationSuiteType.NavigationDrawer -> PermanentDrawerSheet(
                    Modifier.width(sizes.sideW),
                    drawerContainerColor = colors.surface,
                    drawerContentColor = colors.muted,
                ) {
                    SwIcon(
                        R.drawable.sw_ic_spoolwarden, null, size = SwIconSize.Large, tint = colors.accentText,
                        modifier = Modifier.padding(space.s4),
                    )
                    Tab.entries.forEachIndexed { i, tab ->
                        val current = tab == selected
                        NavigationDrawerItem(
                            label = { Text(labels[i], style = MaterialTheme.typography.labelLarge, fontWeight = if (current) labelWeight else null) },
                            selected = current,
                            onClick = { onSelect(tab) },
                            // `--ctl` high (02-components 2.3), in a slot of the 48 dp a touch needs
                            modifier = Modifier.named(tab).padding(NavigationDrawerItemDefaults.ItemPadding).minimumInteractiveComponentSize()
                                .height(sizes.control).drawWithContent {
                                drawContent()
                                // the current item: the same mark as the rail's, at the outer edge
                                if (current) {
                                    val width = sizes.navMark.toPx()
                                    val x = if (layoutDirection == LayoutDirection.Ltr) 0f else size.width - width
                                    drawRect(colors.accentText, Offset(x, 0f), Size(width, size.height))
                                }
                            },
                            icon = { Icon(tab) },
                            shape = SpoolwardenTheme.shapes.r,
                            colors = drawerColors,
                        )
                    }
                }
                NavigationSuiteType.NavigationBar -> NavigationBar(containerColor = colors.surface, contentColor = colors.muted) {
                    Tab.entries.forEachIndexed { i, tab ->
                        val current = tab == selected
                        NavigationBarItem(
                            selected = current,
                            onClick = { onSelect(tab) },
                            icon = { Icon(tab) },
                            modifier = Modifier.named(tab),
                            label = { Text(labels[i], style = labelStyle, fontWeight = if (current) labelWeight else null) },
                            alwaysShowLabel = true,
                            colors = barColors,
                        )
                    }
                }
                else -> Unit
            }
        },
        layoutType = layout,
    ) {
        Box(modifier.background(colors.bg).hairlineToward(layout, colors.border, sizes.hairline.value)) { content() }
    }
}

/** The bar on a phone; wider, the rail, or the drawer of `Sidebar` on expanded width; none while [visible] is false. */
internal fun navLayout(visible: Boolean, window: WindowClass, style: NavStyle): NavigationSuiteType = when {
    !visible -> NavigationSuiteType.None
    window == WindowClass.Phone -> NavigationSuiteType.NavigationBar
    // the pills are a row under the top bar ([SwPills]), so no side navigation is left
    style == NavStyle.Pills -> NavigationSuiteType.None
    style == NavStyle.Sidebar && window == WindowClass.Desktop -> NavigationSuiteType.NavigationDrawer
    else -> NavigationSuiteType.NavigationRail
}

/**
 * One entry of the More menu of the pills: [current] when the screen shown belongs to it. An entry that stands for a whole
 * [tab] takes that tab's place in the row (a section is a pill or in More, never both). [section] is the section the
 * entry belongs to when that is not its own [label] (a page of Settings): More names it while the entry is current.
 */
internal class PillMore(
    val label: String,
    @DrawableRes val icon: Int,
    val current: Boolean,
    val tab: Tab? = null,
    val section: String? = null,
    val onClick: () -> Unit,
)

/**
 * What More holds in Palette: the System group of 02-components 2.3, which on Android is Settings. Settings itself comes
 * first (it is current at its root: [pages] are the ones of its pages, and while one of them is current it is that one),
 * then its [pages]; Settings is no pill then.
 */
internal fun paletteMore(selected: Tab?, settings: String, pages: List<PillMore>, onSettings: () -> Unit): List<PillMore> =
    listOf(
        PillMore(
            settings, Tab.Settings.icon, selected == Tab.Settings && pages.none { it.current }, tab = Tab.Settings, onClick = onSettings,
        ),
    ) + pages

/**
 * The sides of the display the content of the main scaffold keeps clear of (the status bar belongs to the top bar):
 * all of them while the navigation is hidden; on a phone the horizontal ones (the bar below takes the bottom); with
 * `Pills` the pill row under the top bar takes the top, and there is no rail, so the horizontal ones and the bottom; else
 * the end and the bottom (the rail takes the start).
 */
internal fun contentInsetSides(navVisible: Boolean, phone: Boolean, pills: Boolean): WindowInsetsSides = when {
    !navVisible -> WindowInsetsSides.Horizontal + WindowInsetsSides.Vertical
    phone -> WindowInsetsSides.Horizontal
    pills -> WindowInsetsSides.Horizontal + WindowInsetsSides.Bottom
    else -> WindowInsetsSides.End + WindowInsetsSides.Bottom
}

/**
 * The navigation of `NavStyle.Pills` (Palette) on a tablet or expanded width (02-components 2.3): the five [Tab]s as a
 * row of pills under the top bar, the current one `accentSoft` ground with `accentText`, each `--ctl` high with an icon
 * (`muted`, `accentText` when current) left of its label (`text`, `--fs-m` at the label weight). The trailing More tab
 * opens a menu of the [more] entries, the part of the app the row does not hold (the System group: a tab that an entry
 * stands for is no pill); while the screen is one of them it is the current pill and its name is "More, current:
 * <section>". It tells TalkBack that it opens a menu, and whether the menu is open. The row keeps clear of [insets] (the cutout and the bars at the
 * sides). Nothing is drawn on a phone (the bottom bar is there), for another profile, or while [visible] is false.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SwPills(
    selected: Tab?,
    visible: Boolean,
    onSelect: (Tab) -> Unit,
    modifier: Modifier = Modifier,
    settingsUpdate: Boolean = false,
    more: List<PillMore> = emptyList(),
    insets: WindowInsets = WindowInsets.safeDrawing.only(WindowInsetsSides.Horizontal),
) {
    if (!visible || LocalNavStyle.current != NavStyle.Pills || SpoolwardenTheme.window == WindowClass.Phone) return
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val updateName = stringResource(R.string.nav_settings_update)
    // the tabs that More holds are not pills, and the update dot of Settings moves with it
    val moreTabs = more.mapNotNull { it.tab }.toSet()
    val pillTabs = Tab.entries.filter { it !in moreTabs }
    val inMore = more.firstOrNull { it.current } ?: more.firstOrNull { it.tab != null && it.tab == selected }
    val moreUpdate = settingsUpdate && Tab.Settings in moreTabs
    val moreLabel = stringResource(R.string.nav_more)
    val moreName = when {
        inMore != null && moreUpdate -> stringResource(R.string.nav_more_current_update, inMore.section ?: inMore.label)
        inMore != null -> stringResource(R.string.nav_more_current, inMore.section ?: inMore.label)
        moreUpdate -> stringResource(R.string.nav_more_update)
        else -> moreLabel
    }
    var menu by remember { mutableStateOf(false) }
    val menuState = stringResource(if (menu) R.string.nav_more_expanded else R.string.nav_more_collapsed)
    @Composable
    fun Pill(
        current: Boolean, onClick: () -> Unit, name: String?, icon: Int, label: String, dot: Boolean,
        popup: Boolean = false, menuContent: (@Composable () -> Unit)? = null,
    ) {
        MaterialTab(
            selected = current,
            onClick = onClick,
            modifier = Modifier
                .padding(vertical = space.s1, horizontal = space.s1)
                .height(SpoolwardenTheme.sizes.control)
                .clip(SpoolwardenTheme.shapes.rL)
                .background(if (current) colors.accentSoft else Color.Transparent)
                .then(if (name != null) Modifier.semantics { contentDescription = name } else Modifier)
                .then(
                    // a button that opens a menu: its state and the action that toggles it (the has-popup and expanded of 02 2.3)
                    if (popup) {
                        Modifier.semantics {
                            stateDescription = menuState
                            if (menu) collapse { menu = false; true } else expand { menu = true; true }
                        }
                    } else {
                        Modifier
                    },
                ),
            selectedContentColor = colors.accentText,
            unselectedContentColor = colors.text,
        ) {
            Row(
                Modifier.padding(start = space.s3, end = space.s4),
                horizontalArrangement = Arrangement.spacedBy(space.s2),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val tint = if (current) colors.accentText else colors.muted
                if (dot) {
                    BadgedBox(badge = { Box(Modifier.size(space.s2).background(colors.accentText, CircleShape)) }) {
                        SwIcon(icon, null, tint = tint)
                    }
                } else {
                    SwIcon(icon, null, tint = tint)
                }
                Text(
                    label, style = MaterialTheme.typography.labelLarge,
                    color = if (current) colors.accentText else colors.text,
                )
                menuContent?.invoke()
            }
        }
    }
    Column(modifier.fillMaxWidth().background(colors.surface)) {
        Box(Modifier.windowInsetsPadding(insets)) {
            PrimaryScrollableTabRow(
                selectedTabIndex = if (inMore != null) pillTabs.size else pillTabs.indexOf(selected).coerceAtLeast(0),
                containerColor = Color.Transparent,
                contentColor = colors.muted,
                edgePadding = space.s4,
                indicator = {},
                divider = {},
            ) {
                pillTabs.forEach { tab ->
                    val withDot = tab == Tab.Settings && settingsUpdate
                    Pill(
                        tab == selected && inMore == null, { onSelect(tab) }, if (withDot) updateName else null,
                        tab.icon, stringResource(tab.label), withDot,
                    )
                }
                if (more.isNotEmpty()) {
                    Pill(inMore != null, { menu = true }, moreName, R.drawable.sw_ic_more, moreLabel, moreUpdate, popup = true) {
                        SwMenu(menu, onDismiss = { menu = false }) {
                            more.forEach { entry ->
                                SwMenuItem(entry.label, onClick = { menu = false; entry.onClick() }, icon = entry.icon, checked = entry === inMore)
                            }
                        }
                    }
                }
            }
        }
        HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = colors.border)
    }
}

/** The hairline between the content and the bar below it, or the rail or drawer before it. */
private fun Modifier.hairlineToward(layout: NavigationSuiteType, colour: Color, thickness: Float): Modifier =
    if (layout == NavigationSuiteType.None) {
        this
    } else {
        drawWithContent {
            drawContent()
            val line = thickness * density
            if (layout == NavigationSuiteType.NavigationRail || layout == NavigationSuiteType.NavigationDrawer) {
                val x = if (layoutDirection == LayoutDirection.Ltr) 0f else size.width - line
                drawRect(colour, Offset(x, 0f), Size(line, size.height))
            } else {
                drawRect(colour, Offset(0f, size.height - line), Size(size.width, line))
            }
        }
    }
