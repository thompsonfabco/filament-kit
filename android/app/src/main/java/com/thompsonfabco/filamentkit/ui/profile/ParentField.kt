package com.thompsonfabco.filamentkit.ui.profile

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The Bambu Studio parent of a line (05-android-app 6.3). Once the PC has synced Bambu Studio's presets
 * ([ParentList.synced]) it is a drop-down with "Automatic" first and only a listed name can be picked ([onPick]; blank
 * is Automatic). Before that it is a plain text field: [onType] per keystroke, [onCommit] when it loses focus or Done is
 * pressed, with the note that the presets are not synced to the Hub yet. "Applies to every colour of this line." is
 * always under it. [error] (the Hub's own words, or ours) replaces the notes under the field.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ParentField(
    value: String,
    parents: ParentList?,
    enabled: Boolean,
    onPick: (String) -> Unit,
    onType: (String) -> Unit = onPick,
    onCommit: () -> Unit = {},
    error: String? = null,
    modifier: Modifier = Modifier,
) {
    val synced = parents?.synced == true
    val unsynced = stringResource(R.string.common_bambu_parent_unsynced)
    val leaveEmpty = stringResource(R.string.common_hint_leave_empty_auto)
    val applies = stringResource(R.string.common_bambu_parent_applies)
    val note = listOfNotNull(
        error,
        unsynced.takeIf { error == null && parents != null && !synced },
        leaveEmpty.takeIf { error == null && !synced },
        applies,
    ).joinToString(" ")
    val label: @Composable () -> Unit = { Text(stringResource(R.string.common_field_bambu_parent)) }
    val supporting: @Composable () -> Unit = { Text(note) }
    if (!synced) {
        OutlinedTextField(
            value = value, onValueChange = onType, enabled = enabled, singleLine = true,
            isError = error != null, label = label, supportingText = supporting,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { onCommit() }),
            modifier = modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused) onCommit() },
        )
        return
    }
    var open by remember { mutableStateOf(false) }
    val automatic = stringResource(R.string.common_option_automatic)
    ExposedDropdownMenuBox(expanded = open && enabled, onExpandedChange = { open = it }, modifier = modifier) {
        OutlinedTextField(
            value = value.ifEmpty { automatic }, onValueChange = {}, readOnly = true, enabled = enabled,
            singleLine = true, isError = error != null, label = label, supportingText = supporting,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = open && enabled, onDismissRequest = { open = false },
            containerColor = SpoolwardenTheme.colors.surface, shape = SpoolwardenTheme.shapes.r,
        ) {
            SwMenuItem(automatic, { onPick(""); open = false }, checked = value.isEmpty())
            parents?.parents.orEmpty().forEach { p -> SwMenuItem(p, { onPick(p); open = false }, checked = p == value) }
        }
    }
}
