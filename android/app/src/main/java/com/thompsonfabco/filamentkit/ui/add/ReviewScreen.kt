package com.thompsonfabco.filamentkit.ui.add

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.VendorChoice
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.TARE_PROBLEM
import com.thompsonfabco.filamentkit.ui.parseWeight
import com.thompsonfabco.filamentkit.ui.tareProblem
import com.thompsonfabco.filamentkit.ui.profile.ParentField
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/**
 * Step 2: what Claude read (questions on top), one editable card per proposed spool, then a preview (dry run) and
 * Add. Ends with the new spool ids. A manual add ([AddUiState.manual]) shows the filament picker on top instead and
 * offers [onClose] (Cancel) where the photo flow goes back to its photos.
 */
@Composable
fun ReviewScreen(
    state: AddUiState,
    vm: AddViewModel,
    onDone: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    onClose: () -> Unit = {},
) {
    Column(modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (state.stage == Stage.Done) {
            DoneSection(state, vm, onDone)
            return@Column
        }
        Text(if (state.manual) "Add spool" else "Check the spools", style = MaterialTheme.typography.headlineSmall)
        val editable = state.stage == Stage.Review || state.stage == Stage.Preview
        if (state.manual) FilamentPicker(state, vm, editable)
        if (state.questions.isNotEmpty()) {
            Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer)) {
                Column(Modifier.padding(12.dp)) {
                    Text("Claude asks", fontWeight = FontWeight.Bold)
                    state.questions.forEach { Text("• $it") }
                }
            }
        }
        state.notices.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
        state.tag?.let {
            Text(
                "Tag $it will be linked when you add exactly one opened spool.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
        if (state.items.isEmpty()) {
            Text(
                if (state.manual) "Pick a filament above, or tap New filament."
                else "No spools to add. Go back to the photos and read again.",
            )
        }

        state.items.forEachIndexed { i, item ->
            key(state.generation, i) {
                ItemCard(
                    i, item, state.locations, state.parents, state.parentError, vm, editable,
                    vendors = if (state.manual) state.vendors else emptyList(),
                    fieldErrors = state.fieldErrors[i].orEmpty(),
                    showFilamentFields = state.manual,
                )
            }
        }

        state.error?.let { ErrorCard(it, vm, onPairAgain, kept = state.draftId != null) }
        state.addedBefore?.let { before ->
            Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                Column(Modifier.padding(12.dp)) {
                    Text(before.note, fontWeight = FontWeight.Bold)
                    Text("Check Spoolman before adding these spools again.", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        if (state.askAddAgain) AddAgainDialog(state.addedBefore, vm)
        when (state.stage) {
            Stage.Previewing -> Busy("Checking…")
            Stage.Adding -> Busy("Adding to Spoolman…")
            Stage.Preview -> {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("Preview (nothing saved yet)", fontWeight = FontWeight.Bold)
                        state.previewLines.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                    }
                }
                val total = state.items.sumOf { it.int("count") ?: 0 }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    BackButton(state.manual, vm, onClose)
                    Button(onClick = vm::confirm) { Text("Add $total spool${if (total == 1) "" else "s"}") }
                }
            }
            else -> {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    BackButton(state.manual, vm, onClose)
                    Button(
                        onClick = vm::preview,
                        enabled = state.items.isNotEmpty() && state.countsValid && state.taresValid && state.complete,
                    ) { Text("Preview") }
                }
                if (!state.countsValid) Text("Enter a spool count for every item.", style = MaterialTheme.typography.bodySmall)
                if (!state.taresValid) Text(TARE_PROBLEM, style = MaterialTheme.typography.bodySmall)
                if (!state.complete) {
                    state.missing.forEachIndexed { i, keys ->
                        if (keys.isNotEmpty()) {
                            Text(
                                "Spool ${i + 1} still needs: ${keys.joinToString { FIELD_NAMES[it] ?: it }}.",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            }
        }
    }
}

/** The real add after one that may already have written spools: only after an explicit "I checked". */
@Composable
private fun AddAgainDialog(before: AddedBefore?, vm: AddViewModel) {
    AlertDialog(
        onDismissRequest = vm::cancelAddAgain,
        title = { Text("Add these spools again?") },
        text = {
            Text(
                (before?.note?.let { "$it\n\n" } ?: "") +
                    "Adding again can create duplicate spools. Check Spoolman first and only continue if they are missing.",
            )
        },
        confirmButton = { Button(onClick = vm::addAgain) { Text("I checked — add again") } },
        dismissButton = { TextButton(onClick = vm::cancelAddAgain) { Text("Cancel") } },
    )
}

@Composable
private fun DoneSection(state: AddUiState, vm: AddViewModel, onDone: () -> Unit) {
    Text("Spools added", style = MaterialTheme.typography.headlineSmall)
    Text(
        if (state.spoolIds.isEmpty()) "No new spool ids were returned."
        else "New spool${if (state.spoolIds.size == 1) "" else "s"}: ${state.spoolIds.joinToString { "#$it" }}",
    )
    state.resultLines.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = vm::startOver) { Text("Add more") }
        Button(onClick = onDone) { Text("Done") }
    }
}

/** Manual add: Cancel leaves the flow; the photo flow goes back to its photos. */
@Composable
private fun BackButton(manual: Boolean, vm: AddViewModel, onClose: () -> Unit) {
    if (manual) OutlinedButton(onClick = onClose) { Text("Cancel") }
    else OutlinedButton(onClick = vm::backToPhotos) { Text("Back to photos") }
}

/** Manual add: search Spoolman's filaments (tap one to add a spool of it) or start a new filament. */
@Composable
private fun FilamentPicker(state: AddUiState, vm: AddViewModel, enabled: Boolean) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(
                value = state.filamentQuery, onValueChange = vm::setFilamentQuery, enabled = enabled, singleLine = true,
                label = { Text("Find a filament in Spoolman") }, placeholder = { Text("e.g. sunlu petg") },
                modifier = Modifier.fillMaxWidth(),
            )
            when {
                state.filamentsError != null -> Text(state.filamentsError, color = MaterialTheme.colorScheme.error)
                state.filamentsLoading && state.filaments.isEmpty() -> Text("Looking…", style = MaterialTheme.typography.bodySmall)
                state.filaments.isEmpty() -> Text("No filament matches. Use New filament.", style = MaterialTheme.typography.bodySmall)
            }
            state.filaments.take(MAX_FILAMENTS_SHOWN).forEach { f ->
                Row(
                    Modifier.fillMaxWidth().clickable(enabled = enabled) { vm.pickFilament(f) }.padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Swatch(f.colorHex)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        listOfNotNull(
                            "${f.vendor} ${f.name.orEmpty()}".trim(),
                            f.material?.ifBlank { null },
                            if (f.spools == 1) "1 spool" else "${f.spools} spools",
                        ).joinToString(" · "),
                        modifier = Modifier.weight(1f),
                    )
                }
            }
            if (state.filaments.size > MAX_FILAMENTS_SHOWN) {
                Text(
                    "${state.filaments.size - MAX_FILAMENTS_SHOWN} more: type more of the name to narrow it down.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            OutlinedButton(onClick = vm::newFilament, enabled = enabled) { Text("New filament") }
        }
    }
}

private const val MAX_FILAMENTS_SHOWN = 20

/** Field names for the "still needs" line. */
private val FIELD_NAMES = mapOf(
    "vendor" to "vendor", "name" to "name", "material" to "material", "net" to "net weight",
    "tare" to "empty spool weight", "density" to "density", "count" to "spool count",
)

@Composable
private fun ItemCard(
    index: Int,
    item: JsonObject,
    locations: List<String>,
    parents: Map<String, ParentList>,
    parentError: String?,
    vm: AddViewModel,
    enabled: Boolean,
    vendors: List<VendorChoice> = emptyList(),
    /** The server's complaint per item key (shown at that field). */
    fieldErrors: Map<String, String> = emptyMap(),
    /** Manual add: also density, nozzle and bed (used for a new filament). */
    showFilamentFields: Boolean = false,
) {
    val estimates = (item["estimates"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.toSet()
    fun label(text: String, key: String) = if (key in estimates) "$text (estimated)" else text
    val count = item.int("count")
    val sealed = item.bool("sealed") == true
    val err = fieldErrors::get

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Swatch(item.str("color_hex"))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        "${item.str("vendor").orEmpty()} ${item.str("name").orEmpty()}".ifBlank { "New filament" },
                        fontWeight = FontWeight.Bold,
                    )
                    item.str("match")?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    item.int(AddViewModel.FROM_FILAMENT)?.let { id ->
                        val n = item.int(AddViewModel.FROM_SPOOLS) ?: 0
                        Text(
                            "In Spoolman as filament #$id ($n spool${if (n == 1) "" else "s"}). A different vendor " +
                                "or name makes a new filament.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                TextButton(onClick = { vm.removeItem(index) }, enabled = enabled) { Text("Remove") }
            }
            item.str("sealed_reason")?.let { Text("Claude: $it", style = MaterialTheme.typography.bodySmall) }

            VendorField(label("Vendor", "vendor"), item.str("vendor"), vendors, enabled, err("vendor"),
                onPick = { vm.pickVendor(index, it) }) { vm.setText(index, "vendor", it) }
            TextField(label("Name", "name"), item.str("name"), enabled, error = err("name")) { vm.setText(index, "name", it) }
            TextField(label("Line", "line"), item.str("line"), enabled, check = ::intakeTextProblem, error = err("line")) {
                vm.setText(index, "line", it)
            }
            TextField(label("Material", "material"), item.str("material"), enabled, error = err("material")) {
                vm.setText(index, "material", it)
            }
            val parent = item.str("bambu_parent").orEmpty()
            val picked = item.bool(AddViewModel.PICKED) == true
            ParentField(
                parent, item.str("material")?.let { parents[it] }, enabled,
                onPick = { vm.setParent(index, it) },
                onType = { vm.typeParent(index, it) },
                onCommit = { vm.commitParent(index) },
                error = parentError?.takeIf { picked } ?: intakeTextProblem(parent) ?: err("bambu_parent"),
            )
            if (item.bool("line_exists") == true) {
                Text("The Bambu Studio parent applies to every colour of this line.", style = MaterialTheme.typography.bodySmall)
            }
            TextField(label("Colour (hex)", "color_hex"), item.str("color_hex"), enabled, error = err("color_hex")) {
                vm.setText(index, "color_hex", it)
            }
            NumberField(label("Spools", "count"), item.num("count"), enabled, whole = true, error = err("count")) {
                vm.setCount(index, it?.toInt())
            }
            NumberField(label("Net weight (g)", "net"), item.num("net"), enabled, error = err("net")) {
                vm.setNumber(index, "net", it)
            }
            NumberField(label("Empty spool (g)", "tare"), item.num("tare"), enabled, problem = ::tareProblem, error = err("tare")) {
                vm.setNumber(index, "tare", it)
            }
            if (showFilamentFields || "density" in fieldErrors) {
                val guess = defaultDensity(item.str("material"))
                NumberField(
                    label("Density (g/cm³)", "density"), item.num("density"), enabled, error = err("density"),
                    problem = { "Enter a density above 0" },
                    placeholder = guess?.let { "Blank = $it" },
                ) { vm.setNumber(index, "density", it) }
            }
            if (showFilamentFields) {
                NumberField("Nozzle °C (optional)", item.num("nozzle"), enabled, error = err("nozzle"),
                    problem = { "Enter degrees above 0" }) { vm.setNumber(index, "nozzle", it) }
                NumberField("Bed °C (optional)", item.num("bed"), enabled, error = err("bed"),
                    problem = { "Enter degrees above 0" }) { vm.setNumber(index, "bed", it) }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = sealed, onCheckedChange = { vm.setItemSealed(index, it) }, enabled = enabled,
                    modifier = Modifier.semantics { contentDescription = "Still sealed" },
                )
                Text("Still sealed (in its bag or box)")
            }
            if (count == 1 && !sealed) {
                NumberField("Weight with spool (g, blank = full)", item.num("gross"), enabled, error = err("gross")) {
                    vm.setNumber(index, "gross", it)
                }
            }
            LocationField(item.str("location"), locations, enabled, err("location")) { vm.setLocation(index, it) }
            fieldErrors.filterKeys { it !in SHOWN_KEYS }.values.forEach {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

/** Keys with their own field in the card (other field errors are listed under it). */
private val SHOWN_KEYS = setOf(
    "vendor", "name", "line", "material", "color_hex", "count", "net", "tare", "density", "nozzle", "bed", "gross",
    "location", "bambu_parent",
)

/** Free text with the server's vendors as suggestions; picking one also fills a blank empty-spool weight. */
@Composable
private fun VendorField(
    label: String,
    initial: String?,
    vendors: List<VendorChoice>,
    enabled: Boolean,
    error: String?,
    onPick: (VendorChoice) -> Unit,
    onChange: (String) -> Unit,
) {
    if (vendors.isEmpty()) {
        TextField(label, initial, enabled, error = error, onChange = onChange)
        return
    }
    var text by remember { mutableStateOf(initial.orEmpty()) }
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedTextField(
            value = text, onValueChange = { text = it; onChange(it) }, enabled = enabled, singleLine = true,
            isError = error != null, supportingText = error?.let { { Text(it) } },
            label = { Text(label) },
            trailingIcon = { TextButton(onClick = { open = true }, enabled = enabled) { Text("Pick") } },
            modifier = Modifier.fillMaxWidth(),
        )
        val typed = text.trim().lowercase()
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            vendors.filter { typed.isEmpty() || typed in it.name.lowercase() }.ifEmpty { vendors }.forEach { v ->
                DropdownMenuItem(
                    text = { Text(v.name + (v.tare?.let { " · ${grams(it)} g spool" } ?: "")) },
                    onClick = { text = v.name; onPick(v); open = false },
                )
            }
        }
    }
}

@Composable
private fun Swatch(hex: String?) {
    val known = hex?.takeIf { HEX.matches(it) }
    ColorSwatch(known, 28.dp, Modifier.semantics { contentDescription = if (known != null) "Colour #$hex" else "No colour" })
}

@Composable
private fun TextField(
    label: String,
    initial: String?,
    enabled: Boolean,
    check: ((String) -> String?)? = null,
    /** The server's complaint about this field. */
    error: String? = null,
    onChange: (String) -> Unit,
) {
    var text by remember { mutableStateOf(initial.orEmpty()) }
    val problem = check?.invoke(text) ?: error
    OutlinedTextField(
        value = text, onValueChange = { text = it; onChange(it) }, enabled = enabled, singleLine = true,
        isError = problem != null, supportingText = problem?.let { { Text(it) } },
        label = { Text(label) }, modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
/**
 * [whole]: a count (whole number, 0 allowed so the user sees the error). Otherwise grams: finite and above 0.
 * [problem] replaces the generic message for bad text (null = fine). [error] is the server's complaint.
 */
private fun NumberField(
    label: String,
    initial: Double?,
    enabled: Boolean,
    whole: Boolean = false,
    problem: ((String) -> String?)? = null,
    error: String? = null,
    placeholder: String? = null,
    onChange: (Double?) -> Unit,
) {
    var text by remember { mutableStateOf(initial?.let(::grams).orEmpty()) }
    fun parse(t: String): Double? = if (whole) {
        t.trim().toDoubleOrNull()?.takeIf { it.isFinite() && it >= 0 && it == Math.floor(it) && it <= Int.MAX_VALUE }
    } else parseWeight(t)
    val bad = text.isNotBlank() && parse(text) == null
    val badText = (problem?.invoke(text) ?: if (whole) "Enter a whole number" else "Enter grams above 0")
        .takeIf { bad } ?: error
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it
            val v = parse(it)
            if (it.isBlank() || v != null) onChange(v)
        },
        enabled = enabled, singleLine = true, isError = badText != null,
        supportingText = badText?.let { { Text(it) } },
        placeholder = placeholder?.let { { Text(it) } },
        keyboardOptions = KeyboardOptions(keyboardType = if (whole) KeyboardType.Number else KeyboardType.Decimal),
        label = { Text(label) }, modifier = Modifier.fillMaxWidth(),
    )
}

/** Free text with the server's known locations as suggestions; blank = the server places it. */
@Composable
private fun LocationField(
    initial: String?,
    locations: List<String>,
    enabled: Boolean,
    error: String?,
    onChange: (String) -> Unit,
) {
    var text by remember { mutableStateOf(initial.orEmpty()) }
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedTextField(
            value = text, onValueChange = { text = it; onChange(it) }, enabled = enabled, singleLine = true,
            isError = error != null, supportingText = error?.let { { Text(it) } },
            label = { Text("Location") }, placeholder = { Text("Blank = automatic") },
            trailingIcon = if (locations.isNotEmpty()) ({ TextButton(onClick = { open = true }, enabled = enabled) { Text("Pick") } }) else null,
            modifier = Modifier.fillMaxWidth(),
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("Automatic") }, onClick = { text = ""; onChange(""); open = false })
            locations.forEach { loc ->
                DropdownMenuItem(text = { Text(loc) }, onClick = { text = loc; onChange(loc); open = false })
            }
        }
    }
}

private val HEX = Regex("[0-9A-Fa-f]{6}")

private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
private fun JsonObject.num(key: String): Double? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toDoubleOrNull()
private fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.intOrNull
private fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull
