package com.thompsonfabco.filamentkit.ui.profile

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.text.input.ImeAction
import com.thompsonfabco.filamentkit.net.ParentList

/**
 * The Bambu Studio parent. Once the PC has synced Bambu Studio's presets ([ParentList.synced]) the field is read-only
 * and only "Pick" sets it (a listed name, or Automatic = blank). Before that it is free text: [onType] per keystroke,
 * [onCommit] when the field loses focus or Done is pressed. [error] is shown under the field.
 */
@Composable
internal fun ParentField(
    value: String,
    parents: ParentList?,
    enabled: Boolean,
    onPick: (String) -> Unit,
    onType: (String) -> Unit = onPick,
    onCommit: () -> Unit = {},
    error: String? = null,
) {
    var open by remember { mutableStateOf(false) }
    val synced = parents?.synced == true
    val list = if (synced) parents.parents else emptyList()
    val note = when {
        error != null -> error
        synced -> "Pick from Bambu Studio's presets."
        parents != null -> "Bambu Studio's presets are not synced yet; type the name."
        else -> null
    }
    Box {
        OutlinedTextField(
            value = value, onValueChange = { if (!synced) onType(it) }, enabled = enabled, singleLine = true,
            readOnly = synced,
            isError = error != null,
            label = { Text("Bambu Studio parent") },
            placeholder = { Text("Blank = chosen automatically") },
            supportingText = note?.let { { Text(it) } },
            trailingIcon = if (synced) ({ TextButton(onClick = { open = true }, enabled = enabled) { Text("Pick") } }) else null,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { onCommit() }),
            modifier = Modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused) onCommit() },
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("Automatic") }, onClick = { onPick(""); open = false })
            list.forEach { p -> DropdownMenuItem(text = { Text(p) }, onClick = { onPick(p); open = false }) }
        }
    }
}
