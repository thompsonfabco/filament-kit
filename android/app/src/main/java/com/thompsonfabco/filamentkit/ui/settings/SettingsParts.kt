package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.annotation.DrawableRes
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** A page of the Settings section: one scrolling column, no wider than a reading column. */
@Composable
internal fun SettingsPage(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val space = SpoolwardenTheme.space
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth().verticalScroll(rememberScrollState())
                .padding(space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
            content = content,
        )
    }
}

/** A group title (heading for TalkBack). */
@Composable
internal fun GroupTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text, modifier.semantics { heading() }, color = SpoolwardenTheme.colors.text,
        style = MaterialTheme.typography.titleMedium,
    )
}

/** A panel (05-android-app 3.1): `surface`, 1 dp `border`, `r` corners, `s4` padding. */
@Composable
internal fun SettingsPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val colors = SpoolwardenTheme.colors
    Surface(
        modifier.fillMaxWidth(), shape = SpoolwardenTheme.shapes.r, color = colors.surface, contentColor = colors.text,
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Column(Modifier.padding(SpoolwardenTheme.space.s4), verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s3), content = content)
    }
}

/**
 * A field row: the label in `muted` over the value. [mono] sets the value in the data face; [selectable] lets the
 * person select and copy it. One TalkBack node, read as "label, value".
 */
@Composable
internal fun FieldRow(label: String, value: String, modifier: Modifier = Modifier, mono: Boolean = false, selectable: Boolean = false) {
    Column(modifier.fillMaxWidth().semantics(mergeDescendants = true) { }) {
        Text(label, color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodySmall)
        val text: @Composable () -> Unit = {
            Text(value, style = if (mono) SpoolwardenTheme.type.data else MaterialTheme.typography.bodyMedium)
        }
        if (selectable) SelectionContainer { text() } else text()
    }
}

/**
 * A row of the Settings list (12.1): icon, title, one-line live summary, chevron. [selected] marks the open group on
 * a wide window; [dot] is the "update ready" dot. One TalkBack node that opens the group.
 */
@Composable
internal fun SettingsRow(
    @DrawableRes icon: Int,
    title: String,
    summary: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    dot: Boolean = false,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Row(
        modifier.fillMaxWidth()
            .background(if (selected) colors.accentSoft else colors.surface)
            .clickable(role = Role.Button, onClick = onClick)
            .heightIn(min = maxOf(SpoolwardenTheme.sizes.row, SpoolwardenTheme.density.control))
            .padding(horizontal = space.s4, vertical = space.s2)
            .semantics(mergeDescendants = true) { this.selected = selected },
        horizontalArrangement = Arrangement.spacedBy(space.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SwIcon(icon, null, tint = if (selected) colors.accentText else colors.muted)
        Column(Modifier.weight(1f)) {
            Text(
                title, color = if (selected) colors.accentText else colors.text,
                style = MaterialTheme.typography.bodyLarge, fontWeight = MaterialTheme.typography.titleMedium.fontWeight,
            )
            Text(
                summary, color = colors.muted, style = MaterialTheme.typography.bodySmall,
                maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
        }
        if (dot) Box(Modifier.size(space.s2).background(colors.accentText, CircleShape))
        SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

@Composable
internal fun SettingsDivider() {
    HorizontalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
}
