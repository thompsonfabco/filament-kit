package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.compose.LifecycleStartEffect
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * Printer settings (05-android-app 9.9): one row per setting with its current value, each opening a dialog (a bottom
 * sheet on a phone), then "Forget printer" apart below. [printerVm] only loads the printer (no polling); a change's
 * result is the line at the top; a forgotten printer goes back to the list with [onForgotten] (it shows the toast).
 */
@Composable
fun PrinterSettingsScreen(
    printerVm: PrinterViewModel,
    edit: PrinterEditViewModel?,
    onPairAgain: () -> Unit,
    onForgotten: (name: String) -> Unit,
    /** Open the Replace Access Code dialog on arrival (a row whose code was refused). */
    openAccessCode: Boolean = false,
) {
    val state by printerVm.state.collectAsState()
    val editState = edit?.state?.collectAsState()?.value
    LifecycleStartEffect(printerVm) {
        printerVm.retry()
        onStopOrDispose { }
    }
    // the two view models tell each other when a request succeeded; the edit one exists only once the family is known
    LaunchedEffect(printerVm, edit) {
        printerVm.onHubOk = { edit?.clearHubNotice() }
        edit?.onHubOk = printerVm::clearHubNotice
    }
    // a refused Access Code opens here with Replace Access Code already open (05 9.1), once
    var asked by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(edit, state.printer, openAccessCode) {
        val p = state.printer
        if (openAccessCode && !asked && edit != null && p != null) {
            asked = true
            if (EditField.ACCESS_CODE in edit.fields(p)) edit.open(EditField.ACCESS_CODE)
        }
    }
    val printer = state.printer
    LaunchedEffect(editState?.forgotten) {
        if (editState?.forgotten == true && printer != null) onForgotten(printer.name)
    }
    val space = SpoolwardenTheme.space
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
        verticalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        HubNotices(
            unauthorized = state.unauthorized || editState?.unauthorized == true,
            mismatch = state.mismatch != null || editState?.mismatch != null,
            onPairAgain = onPairAgain,
        )
        editState?.note?.let { ResultLine(it) }
        editState?.hubNote?.let { NoticeCard(NoticeKind.Info, it) }
        ScreenState(
            loaded = printer != null && edit != null,
            loading = printer == null && state.problem == null,
            error = state.problem?.let { problemText(it) },
            onTryAgain = printerVm::retry,
        ) {
            if (printer == null || edit == null || editState == null) return@ScreenState
            PrinterPanel(title = null, padded = false) {
                val fields = edit.fields(printer)
                fields.forEachIndexed { i, field ->
                    if (i > 0) PanelDivider()
                    SettingRow(field, printer) { edit.open(field) }
                }
            }
            SwButton(
                stringResource(R.string.printers_forget), edit::askForget, kind = SwButtonKind.Destructive,
                enabled = !editState.busy,
            )
        }
    }
    if (printer != null && edit != null && editState != null) {
        editState.dialog?.let { EditFieldDialog(printer, it, edit, onPairAgain) }
        if (editState.confirmForget) ForgetDialog(printer, editState, edit)
    }
}

@Composable
private fun settingLabel(field: EditField): String = stringResource(
    when (field) {
        EditField.NAME -> R.string.common_field_name
        EditField.ADDRESS -> R.string.common_address
        EditField.ACCESS_CODE -> R.string.common_field_access_code
        EditField.API_KEY -> R.string.printer_set_row_api_key
        EditField.TRUST_CERT -> R.string.printers_fact_certificate
    },
)

/** The setting's current value as the row's supporting line; null where the Hub does not tell (a Klipper API key). */
@Composable
private fun settingValue(field: EditField, p: Printer): String? = when (field) {
    EditField.NAME -> p.name
    EditField.ADDRESS -> (if (p.family == "klipper") p.host else null) ?: p.ip
    EditField.ACCESS_CODE -> stringResource(accessCodeValue(p))
    EditField.TRUST_CERT -> stringResource(R.string.printers_cert_pinned_short)
    EditField.API_KEY -> null
}

/** "Set" once the Hub holds an Access Code for the printer, "Not set" until then (05 9.9). */
@androidx.annotation.StringRes
internal fun accessCodeValue(p: Printer): Int =
    if (p.configured) R.string.status_set else R.string.status_not_set

@Composable
private fun SettingRow(field: EditField, printer: Printer, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val value = settingValue(field, printer)
    val open = stringResource(R.string.a11y_action_open)
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(onClickLabel = open, onClick = onClick)
            .padding(horizontal = space.s4, vertical = space.s2),
        horizontalArrangement = Arrangement.spacedBy(space.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(settingLabel(field), style = MaterialTheme.typography.bodyLarge)
            if (value != null) {
                Text(
                    value, color = colors.muted,
                    style = if (field == EditField.ADDRESS) SpoolwardenTheme.type.data else MaterialTheme.typography.bodyMedium,
                )
            }
        }
        SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** One setting's dialog. What was typed stays while the Hub refuses; a secret lives only while the dialog is open. */
@Composable
private fun EditFieldDialog(printer: Printer, d: EditDialog, edit: PrinterEditViewModel, onPairAgain: () -> Unit) {
    val klipper = printer.family == "klipper"
    var value by if (d.field.secret) remember(d.field) { mutableStateOf("") } else rememberSaveable(d.field) {
        mutableStateOf(
            when (d.field) {
                EditField.NAME -> printer.name
                EditField.ADDRESS -> (if (klipper) printer.host else null) ?: printer.ip.orEmpty()
                else -> ""
            },
        )
    }
    var port by rememberSaveable(d.field) { mutableStateOf("") }
    var second by remember(d.field) { mutableStateOf("") }      // a secret: never in saved state
    val busyWords = if (d.field == EditField.NAME) R.string.common_saving else R.string.printer_set_connecting
    val action = when (d.field) {
        EditField.NAME -> R.string.common_rename
        EditField.ADDRESS -> R.string.printers_change_address
        EditField.ACCESS_CODE -> R.string.printers_replace_access_code
        EditField.API_KEY -> R.string.common_save_key
        EditField.TRUST_CERT -> R.string.printers_forget_cert
    }
    val title = when (d.field) {
        EditField.NAME -> stringResource(R.string.printers_rename_title)
        EditField.ADDRESS -> stringResource(R.string.printers_change_address_title, printer.name)
        EditField.ACCESS_CODE -> stringResource(R.string.printers_access_code_title, printer.name)
        EditField.API_KEY -> stringResource(R.string.printers_key_title, printer.name)
        EditField.TRUST_CERT -> stringResource(R.string.printers_forget_cert_title, printer.name)
    }
    val say = rememberBusySay()
    SwDialog(
        title = title,
        onClose = { if (d.busy) say() else edit.close() },
        confirm = SwDialogButton(
            label = stringResource(if (d.busy) busyWords else action),
            onClick = { edit.submit(value, port, second) },
            kind = if (d.field == EditField.TRUST_CERT) SwButtonKind.DestructiveFilled else SwButtonKind.Main,
            busy = d.busy,
        ),
        cancel = SwAction(stringResource(R.string.common_cancel), edit::close),
        cancelEnabled = !d.busy,
    ) {
        BusyBack(d.busy, say)
        @Composable fun error(which: FieldError, @androidx.annotation.StringRes words: Int) =
            if (d.error == which) stringResource(words) else null
        when (d.field) {
            EditField.NAME -> FormField(
                value, { value = it }, stringResource(R.string.printer_field_name), enabled = !d.busy,
                error = error(FieldError.Name, R.string.printer_error_name),
            )
            EditField.ADDRESS -> {
                FormField(
                    value, { value = it }, stringResource(R.string.common_address), enabled = !d.busy, mono = true,
                    hint = stringResource(R.string.printer_set_address_hint), keyboard = KeyboardType.Uri,
                    error = error(FieldError.Address, R.string.common_error_address),
                )
                if (klipper) {
                    FormField(
                        port, { port = it.filter(Char::isDigit).take(MAX_PORT_DIGITS) }, stringResource(R.string.printer_field_port),
                        enabled = !d.busy, mono = true, keyboard = KeyboardType.Number,
                        hint = stringResource(R.string.printer_set_port_hint),
                        error = error(FieldError.Port, R.string.common_error_port),
                    )
                    FormField(
                        second, { second = it }, stringResource(R.string.printers_key_optional), secret = true,
                        enabled = !d.busy, hint = stringResource(R.string.printer_moonraker_key_hint),
                    )
                } else {
                    FormField(
                        second, { second = it }, stringResource(R.string.common_field_access_code), secret = true, enabled = !d.busy,
                        hint = stringResource(R.string.printer_set_address_code_hint),
                        error = error(FieldError.AccessCode, R.string.common_error_access_code),
                    )
                }
            }
            EditField.ACCESS_CODE -> FormField(
                value, { value = it }, stringResource(R.string.common_field_access_code), secret = true, enabled = !d.busy,
                hint = stringResource(R.string.common_hint_access_code),
                error = error(FieldError.AccessCode, R.string.common_error_access_code),
            )
            EditField.API_KEY -> FormField(
                value, { value = it }, stringResource(R.string.common_moonraker_key), secret = true, enabled = !d.busy,
                hint = stringResource(R.string.printer_set_key_hint),
            )
            EditField.TRUST_CERT -> {
                Text(stringResource(R.string.printer_set_cert_text, printer.name), style = MaterialTheme.typography.bodyMedium)
                FormField(
                    value, { value = it }, stringResource(R.string.common_field_access_code), secret = true, enabled = !d.busy,
                    error = error(FieldError.AccessCode, R.string.common_error_access_code),
                )
            }
        }
        d.problem?.let { ProblemNotice(it, onPairAgain) }
    }
}

private const val MAX_PORT_DIGITS = 5

@Composable
private fun ForgetDialog(printer: Printer, s: PrinterEditUiState, edit: PrinterEditViewModel) {
    val say = rememberBusySay()
    SwDialog(
        title = stringResource(R.string.printers_forget_title, printer.name),
        onClose = { if (s.busy) say() else edit.cancelForget() },
        confirm = SwDialogButton(
            stringResource(R.string.printers_forget), edit::confirmForget, kind = SwButtonKind.DestructiveFilled, busy = s.busy,
        ),
        cancel = SwAction(stringResource(R.string.common_cancel), edit::cancelForget),
        cancelEnabled = !s.busy,
    ) {
        BusyBack(s.busy, say)
        Text(
            stringResource(
                if (printer.family == "klipper") R.string.printers_forget_body_klipper else R.string.printers_forget_body_bambu,
            ),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
