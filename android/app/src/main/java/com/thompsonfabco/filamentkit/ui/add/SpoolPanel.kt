package com.thompsonfabco.filamentkit.ui.add

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.input.KeyboardType
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.VendorChoice
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.components.SwMenu
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.parseWeight
import com.thompsonfabco.filamentkit.ui.profile.ParentField
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/** How sure the Label Reader is of one field (05-android-app 6.3); a field read from the label has no mark. */
internal enum class Mark { Estimated, NotOnLabel }

/** The fields of a read that can carry a mark (the ones the Label Reader fills from the label). */
private val MARKABLE = listOf("vendor", "name", "line", "material", "color_hex", "net", "tare", "density")

/**
 * The confidence marks of one item: "Estimated" for a field in the read's `estimates`, "Not on the label" for a field
 * the reader left empty. Editing a field removes its mark; a hand add has none.
 */
internal fun marksOf(item: JsonObject, manual: Boolean): Map<String, Mark> {
    if (manual) return emptyMap()
    val estimates = (item["estimates"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.toSet()
    val touched = (item[AddViewModel.TOUCHED] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.toSet()
    return buildMap {
        for (key in MARKABLE) {
            when {
                key in estimates -> put(key, Mark.Estimated)
                key !in touched && item.isEmptyField(key) -> put(key, Mark.NotOnLabel)
            }
        }
    }
}

private fun JsonObject.isEmptyField(key: String): Boolean {
    val v = this[key] as? JsonPrimitive ?: return true
    return v.contentOrNull.isNullOrBlank()
}

/** The labels of the item keys the Check step names ("Spool 2 still needs: Material, Net weight."). */
internal val FIELD_LABELS = mapOf(
    "vendor" to R.string.common_field_brand, "name" to R.string.common_field_name,
    "material" to R.string.common_field_material, "net" to R.string.common_field_net_weight,
    "tare" to R.string.common_field_empty_spool_weight, "density" to R.string.common_field_density,
    "count" to R.string.common_field_spools,
)

@Composable
internal fun fieldNames(keys: List<String>): String =
    keys.map { k -> FIELD_LABELS[k]?.let { stringResource(it) } ?: k }.joinToString(", ")

/** What a spool panel needs to draw its fields and answer the person. */
internal class PanelContext(
    val index: Int,
    val item: JsonObject,
    val manual: Boolean,
    val enabled: Boolean,
    /** The Hub's complaint per item key, shown at that field until an edit. */
    val serverErrors: Map<String, String>,
    /** The key to focus when the panel opens (from "Fix" or "Show"). */
    val focusKey: String?,
    val onFocused: () -> Unit,
    val marks: Map<String, Mark>,
    val onPickVendor: (VendorChoice) -> Unit,
)

/**
 * One proposed spool (05-android-app 6.3): a header that always shows (swatch, name, count, what Spoolman has, one status,
 * the chevron and "More actions") and, when [expanded], the fields in the add-form groups.
 */
@Composable
internal fun SpoolPanel(
    state: AddUiState,
    index: Int,
    expanded: Boolean,
    onToggle: () -> Unit,
    focusKey: String?,
    onFocused: () -> Unit,
    vm: AddViewModel,
    onRemove: () -> Unit,
    onAddCatalogLine: (vendor: String, line: String, material: String) -> Unit,
) {
    val item = state.items[index]
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    val editable = state.stage == Stage.Review
    val marks = marksOf(item, state.manual)
    val missing = state.missing.getOrNull(index).orEmpty()
    val estimated = marks.values.count { it == Mark.Estimated }
    val name = "${item.str("vendor").orEmpty()} ${item.str("name").orEmpty()}".trim()
    val headline = name.ifBlank { stringResource(R.string.add_new_filament) }
    val count = item.int("count")
    val existing = item.int("existing_filament_id") ?: item.int(AddViewModel.FROM_FILAMENT)
    val existingSpools = item.int(AddViewModel.FROM_SPOOLS)
    var menu by remember { mutableStateOf(false) }
    val state1 = stringResource(if (expanded) R.string.add_review_expanded else R.string.add_review_collapsed)

    AddPanel {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Row(
                Modifier.weight(1f).defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
                    .semantics(mergeDescendants = true) { stateDescription = state1 }
                    .clickable(role = Role.Button, onClick = onToggle)
                    .padding(start = space.s3, top = space.s2, bottom = space.s2),
                horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.Top,
            ) {
                ColorSwatch(
                    item.str("color_hex"),
                    Modifier.semantics { contentDescription = "" },
                    head = true,
                )
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(space.s1)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
                        Text(headline, Modifier.weight(1f, fill = false), style = MaterialTheme.typography.titleSmall)
                        if (count != null && count > 1) {
                            Text(stringResource(R.string.add_review_count, count), style = SpoolwardenTheme.type.dataSmall, color = colors.muted)
                        }
                    }
                    Text(
                        when {
                            existing != null && existingSpools != null ->
                                pluralStringResource(R.plurals.add_review_existing, existingSpools, existing, existingSpools)
                            existing != null -> stringResource(R.string.add_existing_filament, existing)
                            else -> stringResource(R.string.add_new_filament)
                        },
                        style = MaterialTheme.typography.bodySmall, color = colors.muted,
                    )
                    when {
                        missing.isNotEmpty() ->
                            AddStatusLine(AddStatus.Bad, stringResource(R.string.add_review_needs, fieldNames(missing)))
                        estimated > 0 ->
                            AddStatusLine(AddStatus.Warn, stringResource(R.string.add_review_estimated, estimated))
                        else -> AddStatusLine(AddStatus.Ok, stringResource(R.string.add_review_ready))
                    }
                    item.str("sealed_reason")?.let {
                        Text(
                            stringResource(R.string.add_review_reader_reason, it),
                            style = MaterialTheme.typography.bodySmall, color = colors.muted,
                        )
                    }
                }
                SwIcon(
                    R.drawable.sw_ic_chevron, null, Modifier.rotate(if (expanded) -90f else 90f), tint = colors.muted,
                )
            }
            Box {
                SwIconButton(
                    R.drawable.sw_ic_more, stringResource(R.string.common_more_actions_for, headline), { menu = true },
                )
                SwMenu(expanded = menu, onDismiss = { menu = false }) {
                    SwMenuItem(
                        stringResource(R.string.add_review_remove), { menu = false; onRemove() },
                        icon = R.drawable.sw_ic_trash, enabled = editable,
                    )
                    SwMenuItem(
                        stringResource(R.string.add_review_to_catalog),
                        {
                            menu = false
                            onAddCatalogLine(item.str("vendor").orEmpty(), item.str("line").orEmpty(), item.str("material").orEmpty())
                        },
                        icon = R.drawable.sw_ic_presets, enabled = editable,
                    )
                }
            }
        }
        if (expanded) {
            HorizontalDivider(color = colors.border)
            val ctx = PanelContext(
                index, item, state.manual, editable, state.fieldErrors[index].orEmpty(), focusKey, onFocused, marks,
                onPickVendor = { vm.pickVendor(index, it) },
            )
            Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s4)) {
                PanelFields(ctx, state, vm)
            }
        }
    }
}

@Composable
private fun PanelFields(ctx: PanelContext, state: AddUiState, vm: AddViewModel) {
    val space = SpoolwardenTheme.space
    val item = ctx.item
    val i = ctx.index
    val count = item.int("count")
    val sealed = item.bool("sealed") == true
    val gramsUnit = stringResource(R.string.common_unit_grams)
    val errGrams = stringResource(R.string.common_error_grams)
    val errWhole = stringResource(R.string.add_review_error_whole)
    val errDensity = stringResource(R.string.add_review_error_density)
    val errDegrees = stringResource(R.string.add_review_error_degrees)
    val vendors = state.vendors
    val locations = state.locations
    val picked = item.bool(AddViewModel.PICKED) == true
    val parent = item.str("bambu_parent").orEmpty()
    val parentProblem = intakeTextProblem(parent)

    Group(R.string.common_group_identity) {
        FieldPair(
            {
                BrandField(ctx, vendors) { vm.setText(i, "vendor", it) }
            },
            { TextRow(ctx, "name", R.string.common_field_name) { vm.setText(i, "name", it) } },
        )
        FieldPair(
            {
                TextRow(
                    ctx, "line", R.string.common_field_line, hint = stringResource(R.string.add_review_line_hint),
                    check = {
                        when (intakeTextProblem(it)) {
                            TextProblem.TooLong -> stringResource(R.string.add_review_line_limit)
                            TextProblem.HasAt -> stringResource(R.string.add_review_error_at)
                            null -> null
                        }
                    },
                ) { vm.setText(i, "line", it) }
            },
            { TextRow(ctx, "material", R.string.common_field_material) { vm.setText(i, "material", it) } },
        )
        ColourRow(ctx) { vm.setText(i, "color_hex", it) }
    }
    Group(R.string.add_group_amount) {
        FieldPair(
            {
                NumberRow(ctx, "count", R.string.common_field_spools, whole = true, problem = errWhole) { vm.setCount(i, it?.toInt()) }
            },
            {
                NumberRow(
                    ctx, "net", R.string.common_field_net_weight, suffix = gramsUnit, problem = errGrams,
                    hint = stringResource(R.string.add_review_net_weight_hint),
                ) { vm.setNumber(i, "net", it) }
            },
        )
        NumberRow(ctx, "tare", R.string.common_field_empty_spool_weight, suffix = gramsUnit, problem = errGrams) {
            vm.setNumber(i, "tare", it)
        }
    }
    Group(R.string.add_group_state) {
        Row(
            Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
                .toggleable(value = sealed, enabled = ctx.enabled, role = Role.Checkbox) { vm.setItemSealed(i, it) },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(checked = sealed, onCheckedChange = null, enabled = ctx.enabled)
            Text(
                stringResource(R.string.common_still_sealed), Modifier.padding(start = space.s2),
                style = MaterialTheme.typography.bodyLarge,
            )
        }
        if (count == 1 && !sealed) {
            NumberRow(
                ctx, "gross", R.string.common_field_weight_with_spool_optional, suffix = gramsUnit, problem = errGrams,
                hint = stringResource(R.string.common_hint_leave_empty_full),
            ) { vm.setNumber(i, "gross", it) }
        }
    }
    Group(R.string.add_group_print) {
        // a read asks for the density only when the Hub says so; by hand it is always there
        if (state.manual || "density" in ctx.serverErrors) {
            val guess = defaultDensity(item.str("material"))
            NumberRow(
                ctx, "density", R.string.common_field_density, suffix = stringResource(R.string.common_unit_density),
                problem = errDensity, hint = stringResource(R.string.common_hint_leave_empty_auto),
                placeholder = guess?.let(::grams),
            ) { vm.setNumber(i, "density", it) }
        }
        if (state.manual) {
            FieldPair(
                {
                    NumberRow(
                        ctx, "nozzle", R.string.common_field_nozzle_optional, suffix = stringResource(R.string.common_unit_celsius),
                        problem = errDegrees,
                    ) { vm.setNumber(i, "nozzle", it) }
                },
                {
                    NumberRow(
                        ctx, "bed", R.string.common_field_bed_optional, suffix = stringResource(R.string.common_unit_celsius),
                        problem = errDegrees,
                    ) { vm.setNumber(i, "bed", it) }
                },
            )
        }
        ParentField(
            parent, item.str("material")?.let { state.parents[it] }, ctx.enabled,
            onPick = { vm.setParent(i, it) },
            onType = { vm.typeParent(i, it) },
            onCommit = { vm.commitParent(i) },
            error = state.parentError?.takeIf { picked }
                ?: parentProblem?.let { if (it == TextProblem.TooLong) stringResource(R.string.add_review_line_limit) else stringResource(R.string.add_review_error_at) }
                ?: ctx.serverErrors["bambu_parent"],
        )
    }
    Group(R.string.add_group_storage) {
        LocationField(ctx, locations) { vm.setLocation(i, it) }
    }
    // complaints that name no field of this panel are bad lines at its bottom
    ctx.serverErrors.filterKeys { it !in SHOWN_KEYS }.values.forEach { NoticeCard(NoticeKind.Bad, it) }
}

/** Keys with their own field in the panel (other complaints are listed under it). */
private val SHOWN_KEYS = setOf(
    "vendor", "name", "line", "material", "color_hex", "count", "net", "tare", "density", "nozzle", "bed", "gross",
    "location", "bambu_parent",
)

@Composable
private fun Group(title: Int, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s3)) {
        GroupTitle(stringResource(title))
        content()
    }
}

/** What goes under a field: the Hub's complaint, else our check, else the hint; then the confidence mark. */
@Composable
private fun Supporting(error: String?, hint: String?, mark: Mark?): (@Composable () -> Unit)? {
    if (error == null && hint == null && mark == null) return null
    return {
        Column {
            (error ?: hint)?.let { Text(it) }
            when (mark) {
                Mark.Estimated -> AddStatusLine(AddStatus.Warn, stringResource(R.string.add_review_mark_estimated))
                Mark.NotOnLabel -> AddStatusLine(AddStatus.Muted, stringResource(R.string.add_review_mark_not_on_label))
                null -> Unit
            }
        }
    }
}

@Composable
private fun markWord(mark: Mark?): String? = when (mark) {
    Mark.Estimated -> stringResource(R.string.add_review_mark_estimated)
    Mark.NotOnLabel -> stringResource(R.string.add_review_mark_not_on_label)
    null -> null
}

/** Focuses the field when "Fix" or "Show" asked for it. */
@Composable
private fun focusOn(ctx: PanelContext, key: String): FocusRequester {
    val requester = remember { FocusRequester() }
    if (ctx.focusKey == key) {
        LaunchedEffect(ctx.focusKey) {
            withFrameNanos { }
            runCatching { requester.requestFocus() }
            ctx.onFocused()
        }
    }
    return requester
}

/** A text field of the panel: shows its check after it loses focus, the Hub's complaint until an edit. */
@Composable
private fun TextRow(
    ctx: PanelContext,
    key: String,
    @androidx.annotation.StringRes label: Int,
    modifier: Modifier = Modifier,
    mono: Boolean = false,
    hint: String? = null,
    check: @Composable (String) -> String? = { null },
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    extra: String? = null,
    onChange: (String) -> Unit,
) {
    var text by remember { mutableStateOf(ctx.item.str(key).orEmpty()) }
    var seen by remember { mutableStateOf(false) }
    var shown by remember { mutableStateOf(false) }
    val requester = focusOn(ctx, key)
    val mark = ctx.marks[key]
    val problem = if (shown) check(text) else null
    val error = ctx.serverErrors[key] ?: problem
    val words = markWord(mark)
    OutlinedTextField(
        value = text, onValueChange = { text = it; onChange(it) }, enabled = ctx.enabled, singleLine = true,
        isError = error != null,
        label = { Text(stringResource(label)) },
        supportingText = Supporting(error, hint ?: extra, mark),
        leadingIcon = leading, trailingIcon = trailing,
        textStyle = if (mono) SpoolwardenTheme.type.data else SpoolwardenTheme.type.input,
        modifier = modifier.fillMaxWidth().focusRequester(requester)
            .onFocusChanged { if (it.isFocused) seen = true else if (seen) shown = true }
            .then(if (words != null) Modifier.semantics { stateDescription = words } else Modifier),
    )
}

/** The colour as six hex digits, with the live swatch at the leading end. */
@Composable
private fun ColourRow(ctx: PanelContext, onChange: (String) -> Unit) {
    var live by remember { mutableStateOf(ctx.item.str("color_hex")) }
    val wrong = stringResource(R.string.add_review_colour_error, EXAMPLE_HEX)
    TextRow(
        ctx, "color_hex", R.string.add_review_colour_label, mono = true,
        check = { if (it.isNotBlank() && !HEX.matches(it.trim().removePrefix("#"))) wrong else null },
        leading = { ColorSwatch(live, Modifier.padding(start = SpoolwardenTheme.space.s3)) },
    ) {
        live = it.trim().removePrefix("#")
        onChange(it)
    }
}

private val HEX = Regex("[0-9A-Fa-f]{6}")

/** The example in "Enter 6 hex digits, e.g. 2B2B2E." (05-android-app 6.3). */
private const val EXAMPLE_HEX = "2B2B2E"

/** Grams, degrees or a count: shows its check after it loses focus. [whole]: a whole number (0 shows the error). */
@Composable
private fun NumberRow(
    ctx: PanelContext,
    key: String,
    @androidx.annotation.StringRes label: Int,
    modifier: Modifier = Modifier,
    whole: Boolean = false,
    suffix: String? = null,
    problem: String,
    hint: String? = null,
    placeholder: String? = null,
    onChange: (Double?) -> Unit,
) {
    var text by remember { mutableStateOf(ctx.item.num(key)?.let(::grams).orEmpty()) }
    var seen by remember { mutableStateOf(false) }
    var shown by remember { mutableStateOf(false) }
    val requester = focusOn(ctx, key)
    fun parse(t: String): Double? = if (whole) {
        t.trim().toDoubleOrNull()?.takeIf { it.isFinite() && it >= 0 && it == Math.floor(it) && it <= Int.MAX_VALUE }
    } else parseWeight(t)
    // a count of 0 is accepted as text so the person sees why Preview stays off
    val bad = text.isNotBlank() && parse(text) == null || (whole && text.isNotBlank() && parse(text) == 0.0)
    val mark = ctx.marks[key]
    val error = ctx.serverErrors[key] ?: problem.takeIf { shown && bad }
    val words = markWord(mark)
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it
            val v = parse(it)
            if (it.isBlank() || v != null) onChange(v)
        },
        enabled = ctx.enabled, singleLine = true, isError = error != null,
        label = { Text(stringResource(label)) },
        supportingText = Supporting(error, hint, mark),
        suffix = suffix?.let { { Text(it) } },
        placeholder = placeholder?.let { { Text(it) } },
        textStyle = SpoolwardenTheme.type.data,
        keyboardOptions = KeyboardOptions(keyboardType = if (whole) KeyboardType.Number else KeyboardType.Decimal),
        modifier = modifier.fillMaxWidth().focusRequester(requester)
            .onFocusChanged { if (it.isFocused) seen = true else if (seen) shown = true }
            .then(if (words != null) Modifier.semantics { stateDescription = words } else Modifier),
    )
}

/** The brand, typed or picked from the Hub's vendors ("Pick a brand"); a pick also fills an empty "Empty spool weight". */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BrandField(ctx: PanelContext, vendors: List<VendorChoice>, onChange: (String) -> Unit) {
    if (vendors.isEmpty()) {
        TextRow(ctx, "vendor", R.string.common_field_brand, onChange = onChange)
        return
    }
    var text by remember { mutableStateOf(ctx.item.str("vendor").orEmpty()) }
    var open by remember { mutableStateOf(false) }
    val requester = focusOn(ctx, "vendor")
    val mark = ctx.marks["vendor"]
    val error = ctx.serverErrors["vendor"]
    val words = markWord(mark)
    ExposedDropdownMenuBox(expanded = open && ctx.enabled, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = text, onValueChange = { text = it; onChange(it) }, enabled = ctx.enabled, singleLine = true,
            isError = error != null, label = { Text(stringResource(R.string.common_field_brand)) },
            supportingText = Supporting(error, null, mark),
            trailingIcon = {
                SwIconButton(
                    R.drawable.sw_ic_chevron, stringResource(R.string.add_review_pick_brand), { open = true },
                    iconModifier = Modifier.rotate(90f),
                )
            },
            textStyle = SpoolwardenTheme.type.input,
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryEditable)
                .focusRequester(requester)
                .then(if (words != null) Modifier.semantics { stateDescription = words } else Modifier),
        )
        val typed = text.trim().lowercase()
        ExposedDropdownMenu(
            expanded = open && ctx.enabled, onDismissRequest = { open = false },
            containerColor = SpoolwardenTheme.colors.surface, shape = SpoolwardenTheme.shapes.r,
        ) {
            vendors.filter { typed.isEmpty() || typed in it.name.lowercase() }.ifEmpty { vendors }.forEach { v ->
                SwMenuItem(
                    v.tare?.let { stringResource(R.string.add_review_vendor_option, v.name, grams(it)) } ?: v.name,
                    {
                        text = v.name
                        open = false
                        ctx.onPickVendor(v)
                    },
                )
            }
        }
    }
}

/** The storage location: "Automatic" first, then the Hub's locations; a place that is typed in is kept as typed. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LocationField(ctx: PanelContext, locations: List<String>, onChange: (String) -> Unit) {
    var text by remember { mutableStateOf(ctx.item.str("location").orEmpty()) }
    var open by remember { mutableStateOf(false) }
    val requester = focusOn(ctx, "location")
    val error = ctx.serverErrors["location"]
    val automatic = stringResource(R.string.common_option_automatic)
    val hint = stringResource(R.string.common_hint_leave_empty_auto)
    if (locations.isEmpty()) {
        OutlinedTextField(
            value = text, onValueChange = { text = it; onChange(it) }, enabled = ctx.enabled, singleLine = true,
            isError = error != null, label = { Text(stringResource(R.string.common_field_location)) },
            supportingText = { Text(error ?: hint) },
            textStyle = SpoolwardenTheme.type.input,
            modifier = Modifier.fillMaxWidth().focusRequester(requester),
        )
        return
    }
    ExposedDropdownMenuBox(expanded = open && ctx.enabled, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = text, onValueChange = { text = it; onChange(it) }, enabled = ctx.enabled, singleLine = true,
            isError = error != null, label = { Text(stringResource(R.string.common_field_location)) },
            placeholder = { Text(automatic) },
            supportingText = { Text(error ?: hint) },
            trailingIcon = { androidx.compose.material3.ExposedDropdownMenuDefaults.TrailingIcon(open) },
            textStyle = SpoolwardenTheme.type.input,
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryEditable).focusRequester(requester),
        )
        ExposedDropdownMenu(
            expanded = open && ctx.enabled, onDismissRequest = { open = false },
            containerColor = SpoolwardenTheme.colors.surface, shape = SpoolwardenTheme.shapes.r,
        ) {
            SwMenuItem(automatic, { text = ""; onChange(""); open = false }, checked = text.isEmpty())
            locations.forEach { loc -> SwMenuItem(loc, { text = loc; onChange(loc); open = false }, checked = text == loc) }
        }
    }
}

internal fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
internal fun JsonObject.num(key: String): Double? =
    (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toDoubleOrNull()
internal fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.intOrNull
internal fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull
