package com.thompsonfabco.filamentkit.ui.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.net.ParentList

/**
 * "Add profile": the owner's own spec values for a product line (saved on the server as a local library entry, from
 * which the presets are rebuilt). Vendor, product line and material are required.
 */
@Composable
fun AddProfileScreen(vm: AddProfileViewModel, onBack: () -> Unit, onPairAgain: () -> Unit, modifier: Modifier = Modifier) {
    val s by vm.state.collectAsStateWithLifecycle()
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Add profile", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Values from the maker's label or data sheet for one product line. They apply to every colour of the line.",
            style = MaterialTheme.typography.bodySmall,
        )
        ProfileField.entries.forEach { f ->
            if (f == ProfileField.Parent) {
                ParentField(s.values[f].orEmpty(), s.parents, !s.saving, onPick = { vm.set(f, it) })
            } else {
                OutlinedTextField(
                    value = s.values[f].orEmpty(),
                    onValueChange = { vm.set(f, it) },
                    enabled = !s.saving,
                    singleLine = f != ProfileField.Notes,
                    label = { Text(if (f.required) "${f.label} *" else f.label) },
                    keyboardOptions = if (f.number) KeyboardOptions(keyboardType = KeyboardType.Decimal) else KeyboardOptions.Default,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        if (s.lines.isNotEmpty()) {
            Text("Existing lines", style = MaterialTheme.typography.titleMedium)
            s.lines.forEach { line ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("${line.vendor} ${line.product} (${line.material})")
                        Text(
                            "Parent: ${line.bambuParent ?: "automatic"}",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Box {
                        TextButton(onClick = { vm.editParent(line) }) { Text("Change parent") }
                        val edit = s.editing?.takeIf { it.lineId == line.lineId }
                        DropdownMenu(expanded = edit != null, onDismissRequest = vm::cancelEditParent) {
                            val parents = edit?.parents
                            if (parents == null) {
                                DropdownMenuItem(text = { Text("Loading…") }, onClick = {}, enabled = false)
                            } else {
                                DropdownMenuItem(text = { Text("Automatic") }, onClick = { vm.setLineParent("") })
                                if (!parents.synced) {
                                    DropdownMenuItem(text = { Text("Presets not synced yet") }, onClick = {}, enabled = false)
                                }
                                parents.parents.forEach { p ->
                                    DropdownMenuItem(text = { Text(p) }, onClick = { vm.setLineParent(p) })
                                }
                            }
                        }
                    }
                }
            }
            s.lineError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
        if (s.problems.isNotEmpty()) {
            Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                Column(Modifier.padding(12.dp)) {
                    Text("The server could not use these values", fontWeight = FontWeight.Bold)
                    s.problems.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall) }
                }
            }
        }
        s.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (s.pairAgain) Button(onClick = onPairAgain) { Text("Pair again") }
        s.saved?.let { Text(it, fontWeight = FontWeight.Bold) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onBack) { Text(if (s.saved != null) "Done" else "Back") }
            Button(onClick = vm::save, enabled = s.canSave) { Text(if (s.saving) "Saving…" else "Save") }
        }
        if (!s.filled && !s.saving) Text("Fill in the fields marked *.", style = MaterialTheme.typography.bodySmall)
    }
}

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
