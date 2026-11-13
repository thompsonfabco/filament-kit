package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteDefaults
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffold
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
    val itemColors = NavigationSuiteDefaults.itemColors(navigationBarItemColors = barColors, navigationRailItemColors = railColors)
    val dotSize = SpoolwardenTheme.space.s2
    val dot: @Composable () -> Unit = { Box(Modifier.size(dotSize).background(colors.accentText, CircleShape)) }
    NavigationSuiteScaffold(
        navigationSuiteItems = {
            Tab.entries.forEachIndexed { i, tab ->
                val current = tab == selected
                val marked = rail && current
                val withDot = tab == Tab.Settings && settingsUpdate
                item(
                    selected = current,
                    onClick = { onSelect(tab) },
                    icon = { SwIcon(tab.icon, null) },
                    modifier = Modifier
                        .drawWithContent {
                            drawContent()
                            // the rail's current item: a mark at the outer edge (08-platform-mapping 10.1)
                            if (marked) {
                                val width = sizes.navMark.toPx()
                                val x = if (layoutDirection == LayoutDirection.Ltr) 0f else size.width - width
                                drawRect(colors.accentText, Offset(x, 0f), Size(width, size.height))
                            }
                        }
                        .semantics { if (withDot) contentDescription = updateName },
                    label = {
                        Text(
                            labels[i], style = MaterialTheme.typography.labelSmall,
                            fontWeight = if (current) MaterialTheme.typography.titleMedium.fontWeight else null,
                        )
                    },
                    badge = if (withDot) dot else null,
                    alwaysShowLabel = true,
                    colors = itemColors,
                )
            }
        },
        modifier = modifier,
        layoutType = layout,
        navigationSuiteColors = NavigationSuiteDefaults.colors(
            navigationBarContainerColor = colors.surface, navigationBarContentColor = colors.muted,
            navigationRailContainerColor = colors.surface, navigationRailContentColor = colors.muted,
        ),
        containerColor = colors.bg,
        contentColor = colors.text,
    ) {
        Box(Modifier.hairlineToward(layout, colors.border, sizes.hairline.value)) { content() }
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
