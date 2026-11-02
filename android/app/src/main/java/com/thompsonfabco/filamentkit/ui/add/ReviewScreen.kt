package com.thompsonfabco.filamentkit.ui.add

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.net.ParentList
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
 * Add. Ends with the new spool ids.
 */
@Composable
fun ReviewScreen(
    state: AddUiState,
    vm: AddViewModel,
    onDone: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (state.stage == Stage.Done) {
            DoneSection(state, vm, onDone)
            return@Column
        }
        Text("Check the spools", style = MaterialTheme.typography.headlineSmall)
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
        if (state.items.isEmpty()) Text("No spools to add. Go back to the photos and read again.")

        val editable = state.stage == Stage.Review || state.stage == Stage.Preview
        state.items.forEachIndexed { i, item ->
            key(state.generation, i) {
                ItemCard(i, item, state.locations, state.parents, state.parentError, vm, editable)
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
                    OutlinedButton(onClick = vm::backToPhotos) { Text("Back to photos") }
                    Button(onClick = vm::confirm) { Text("Add $total spool${if (total == 1) "" else "s"}") }
                }
            }
            else -> {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = vm::backToPhotos) { Text("Back to photos") }
                    Button(
                        onClick = vm::preview,
                        enabled = state.items.isNotEmpty() && state.countsValid && state.taresValid,
                    ) { Text("Preview") }
                }
                if (!state.countsValid) Text("Enter a spool count for every item.", style = MaterialTheme.typography.bodySmall)
                if (!state.taresValid) Text(TARE_PROBLEM, style = MaterialTheme.typography.bodySmall)
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

@Composable
private fun ItemCard(
    index: Int,
    item: JsonObject,
    locations: List<String>,
    parents: Map<String, ParentList>,
    parentError: String?,
    vm: AddViewModel,
    enabled: Boolean,
) {
    val estimates = (item["estimates"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.toSet()
    fun label(text: String, key: String) = if (key in estimates) "$text (estimated)" else text
    val count = item.int("count")
    val sealed = item.bool("sealed") == true

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Swatch(item.str("color_hex"))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text("${item.str("vendor").orEmpty()} ${item.str("name").orEmpty()}", fontWeight = FontWeight.Bold)
                    item.str("match")?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
                TextButton(onClick = { vm.removeItem(index) }, enabled = enabled) { Text("Remove") }
            }
            item.str("sealed_reason")?.let { Text("Claude: $it", style = MaterialTheme.typography.bodySmall) }

            TextField(label("Vendor", "vendor"), item.str("vendor"), enabled) { vm.setText(index, "vendor", it) }
            TextField(label("Name", "name"), item.str("name"), enabled) { vm.setText(index, "name", it) }
            TextField(label("Line", "line"), item.str("line"), enabled, check = ::intakeTextProblem) { vm.setText(index, "line", it) }
            TextField(label("Material", "material"), item.str("material"), enabled) { vm.setText(index, "material", it) }
            val parent = item.str("bambu_parent").orEmpty()
            val picked = item.bool(AddViewModel.PICKED) == true
            ParentField(
                parent, item.str("material")?.let { parents[it] }, enabled,
                onPick = { vm.setParent(index, it) },
                onType = { vm.typeParent(index, it) },
                onCommit = { vm.commitParent(index) },
                error = parentError?.takeIf { picked } ?: intakeTextProblem(parent),
            )
            if (item.bool("line_exists") == true) {
                Text("The Bambu Studio parent applies to every colour of this line.", style = MaterialTheme.typography.bodySmall)
            }
            TextField(label("Colour (hex)", "color_hex"), item.str("color_hex"), enabled) { vm.setText(index, "color_hex", it) }
            NumberField(label("Spools", "count"), item.num("count"), enabled, whole = true) {
                vm.setCount(index, it?.toInt())
            }
            NumberField(label("Net weight (g)", "net"), item.num("net"), enabled) { vm.setNumber(index, "net", it) }
            NumberField(label("Empty spool (g)", "tare"), item.num("tare"), enabled, problem = ::tareProblem) {
                vm.setNumber(index, "tare", it)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = sealed, onCheckedChange = { vm.setItemSealed(index, it) }, enabled = enabled,
                    modifier = Modifier.semantics { contentDescription = "Still sealed" },
                )
                Text("Still sealed (in its bag or box)")
            }
            if (count == 1 && !sealed) {
                NumberField("Weight with spool (g, blank = full)", item.num("gross"), enabled) {
                    vm.setNumber(index, "gross", it)
                }
            }
            LocationField(item.str("location"), locations, enabled) { vm.setLocation(index, it) }
        }
    }
}

@Composable
private fun Swatch(hex: String?) {
    val color = hex?.takeIf { HEX.matches(it) }?.let { Color(0xFF000000 or it.toLong(16)) }
    Box(
        Modifier.size(28.dp).border(1.dp, MaterialTheme.colorScheme.outline, CircleShape)
            .background(color ?: Color.Transparent, CircleShape)
            .semantics { contentDescription = if (color != null) "Colour #$hex" else "No colour" },
    )
}

@Composable
private fun TextField(
    label: String,
    initial: String?,
    enabled: Boolean,
    check: ((String) -> String?)? = null,
    onChange: (String) -> Unit,
) {
    var text by remember { mutableStateOf(initial.orEmpty()) }
    val problem = check?.invoke(text)
    OutlinedTextField(
        value = text, onValueChange = { text = it; onChange(it) }, enabled = enabled, singleLine = true,
        isError = problem != null, supportingText = problem?.let { { Text(it) } },
        label = { Text(label) }, modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
/**
 * [whole]: a count (whole number, 0 allowed so the user sees the error). Otherwise grams: finite and above 0.
 * [problem] replaces the generic message for bad text (null = fine).
 */
private fun NumberField(
    label: String,
    initial: Double?,
    enabled: Boolean,
    whole: Boolean = false,
    problem: ((String) -> String?)? = null,
    onChange: (Double?) -> Unit,
) {
    var text by remember { mutableStateOf(initial?.let(::grams).orEmpty()) }
    fun parse(t: String): Double? = if (whole) {
        t.trim().toDoubleOrNull()?.takeIf { it.isFinite() && it >= 0 && it == Math.floor(it) && it <= Int.MAX_VALUE }
    } else parseWeight(t)
    val bad = text.isNotBlank() && parse(text) == null
    val badText = problem?.invoke(text) ?: if (whole) "Enter a whole number" else "Enter grams above 0"
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it
            val v = parse(it)
            if (it.isBlank() || v != null) onChange(v)
        },
        enabled = enabled, singleLine = true, isError = bad,
        supportingText = if (bad) ({ Text(badText) }) else null,
        keyboardOptions = KeyboardOptions(keyboardType = if (whole) KeyboardType.Number else KeyboardType.Decimal),
        label = { Text(label) }, modifier = Modifier.fillMaxWidth(),
    )
}

/** Free text with the server's known locations as suggestions; blank = the server places it. */
@Composable
private fun LocationField(initial: String?, locations: List<String>, enabled: Boolean, onChange: (String) -> Unit) {
    var text by remember { mutableStateOf(initial.orEmpty()) }
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedTextField(
            value = text, onValueChange = { text = it; onChange(it) }, enabled = enabled, singleLine = true,
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
