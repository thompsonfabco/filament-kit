package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffoldLayout
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteType
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.LayoutDirection
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/**
 * The shell around the main graph (05-android-app 2.1, 2.3): the bottom bar on a phone, the rail on a wider window,
 * the same five [Tab]s in both. [selected] is the current destination, null while a screen outside the five is on top
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
    val rail = SpoolwardenTheme.window != WindowClass.Phone
    val layout = when {
        !visible -> NavigationSuiteType.None
        rail -> NavigationSuiteType.NavigationRail
        else -> NavigationSuiteType.NavigationBar
    }
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
    val dotSize = SpoolwardenTheme.space.s2
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

/** The hairline between the content and the bar below it, or the rail before it. */
private fun Modifier.hairlineToward(layout: NavigationSuiteType, colour: Color, thickness: Float): Modifier =
    if (layout == NavigationSuiteType.None) {
        this
    } else {
        drawWithContent {
            drawContent()
            val line = thickness * density
            if (layout == NavigationSuiteType.NavigationRail) {
                val x = if (layoutDirection == LayoutDirection.Ltr) 0f else size.width - line
                drawRect(colour, Offset(x, 0f), Size(line, size.height))
            } else {
                drawRect(colour, Offset(0f, size.height - line), Size(size.width, line))
            }
        }
    }
