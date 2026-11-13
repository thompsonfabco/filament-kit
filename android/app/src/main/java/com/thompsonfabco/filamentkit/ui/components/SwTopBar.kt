package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.RowScope
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarColors
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.TopAppBarScrollBehavior
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/** The semantics tag of the top bar, for the semantics tests (AUT-8). */
internal enum class SwTag { TopBar }

internal val TOP_BAR_TAG = SwTag.TopBar.name

/**
 * The top bar (05-android-app 2.2): the place as title, with the Hub's name under it where a screen gives one, the
 * back arrow when [onBack] is given, and [actions] at the end. The title is cut with an ellipsis before the actions
 * give way. `surface` ground with a 1 dp `border` hairline below.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SwTopBar(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    scrollBehavior: TopAppBarScrollBehavior? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    val colors = SpoolwardenTheme.colors
    val bar = TopAppBarColors(
        containerColor = colors.surface, scrolledContainerColor = colors.surface, navigationIconContentColor = colors.text,
        titleContentColor = colors.text, actionIconContentColor = colors.muted, subtitleContentColor = colors.muted,
    )
    Column(modifier.testTag(TOP_BAR_TAG)) {
        TopAppBar(
            title = {
                Column {
                    Text(
                        title, modifier = Modifier.semantics { heading() }, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        style = if (SpoolwardenTheme.window == WindowClass.Phone) {
                            MaterialTheme.typography.titleMedium
                        } else {
                            MaterialTheme.typography.titleLarge
                        },
                    )
                    if (subtitle != null) {
                        Text(
                            subtitle, maxLines = 1, overflow = TextOverflow.Ellipsis, color = colors.muted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            },
            navigationIcon = {
                if (onBack != null) {
                    // the drawing points right; the back arrow points left
                    SwIconButton(
                        R.drawable.sw_ic_chevron, stringResource(R.string.common_back), onBack,
                        iconModifier = Modifier.rotate(180f),
                    )
                }
            },
            actions = actions,
            expandedHeight = SpoolwardenTheme.sizes.top,
            colors = bar,
            scrollBehavior = scrollBehavior,
        )
        HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = colors.border)
    }
}
