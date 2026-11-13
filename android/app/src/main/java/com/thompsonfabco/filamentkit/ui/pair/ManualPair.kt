package com.thompsonfabco.filamentkit.ui.pair

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.em
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

// The three manual steps of pairing (05-android-app 4.5 to 4.7): the address, the fingerprint check, the code.

/** 4.5: Back goes to the first screen; the typed address stays while the step is under another. */
@Composable
internal fun PairAddressScreen(ui: PairUi, onSubmit: (host: String, port: String) -> Unit, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    var host by rememberSaveable { mutableStateOf(ui.host) }
    var port by rememberSaveable { mutableStateOf(ui.port.toString()) }
    val space = SpoolwardenTheme.space
    PairPage {
        PairHeading(stringResource(R.string.pair_address_heading))
        OutlinedTextField(
            value = host,
            onValueChange = { host = it },
            label = { Text(stringResource(R.string.pair_address_label)) },
            placeholder = { Text(stringResource(R.string.pair_address_placeholder)) },
            supportingText = ui.error.takeIf { ui.errorField == PairField.Address }?.let { { Text(it.text()) } },
            isError = ui.errorField == PairField.Address,
            singleLine = true,
            enabled = !ui.busy,
            textStyle = SpoolwardenTheme.type.input,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false, imeAction = ImeAction.Next),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = port,
            onValueChange = { port = it },
            label = { Text(stringResource(R.string.pair_address_port_label)) },
            supportingText = ui.error.takeIf { ui.errorField == PairField.Port }?.let { { Text(it.text()) } },
            isError = ui.errorField == PairField.Port,
            singleLine = true,
            enabled = !ui.busy,
            textStyle = SpoolwardenTheme.type.input,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
            modifier = Modifier.width(SpoolwardenTheme.sizes.portField),
        )
        Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
            SwButton(
                stringResource(if (ui.busy) R.string.common_connecting else R.string.pair_address_connect),
                { onSubmit(host, port) }, Modifier.fillMaxWidth(), kind = SwButtonKind.Main, busy = ui.busy,
            )
            if (ui.errorField == null) ui.error?.let { NoticeCard(NoticeKind.Bad, it.text()) }
        }
    }
}

/** 4.6: compare the fingerprint the Hub presented with the one on the Hub page. */
@Composable
internal fun PairFingerprintScreen(ui: PairUi, onMatches: () -> Unit, onDiffers: () -> Unit, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    PairPage {
        PairHeading(stringResource(R.string.pair_fingerprint_heading))
        Text(stringResource(R.string.pair_fingerprint_text, ui.host), style = MaterialTheme.typography.bodyLarge)
        FingerprintBox(ui.fingerprint.orEmpty())
        PairButtons(
            stringResource(R.string.pair_fingerprint_matches), onMatches,
            stringResource(R.string.pair_fingerprint_differs), onDiffers,
        )
    }
}

/** 4.7: the six digits; Pair stays off until all six are typed, and the sixth does not submit by itself. */
@Composable
internal fun PairCodeScreen(ui: PairUi, onSubmit: (String) -> Unit, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    var code by remember { mutableStateOf("") } // not saved state: a secret, as the Access Code fields
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    val space = SpoolwardenTheme.space
    PairPage {
        PairHeading(stringResource(R.string.pair_code_heading))
        Text(stringResource(R.string.pair_code_text), style = MaterialTheme.typography.bodyLarge)
        OutlinedTextField(
            value = code,
            onValueChange = { code = it.filter(Char::isDigit).take(CODE_LENGTH) },
            label = { Text(stringResource(R.string.pair_code_label)) },
            singleLine = true,
            enabled = !ui.busy,
            textStyle = MaterialTheme.typography.titleLarge.copy(
                fontFamily = SpoolwardenTheme.type.data.fontFamily, letterSpacing = 0.05.em, textAlign = TextAlign.Start,
            ),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
            modifier = Modifier.fillMaxWidth().focusRequester(focus),
        )
        Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
            val complete = code.length == CODE_LENGTH
            SwButton(
                stringResource(if (ui.busy) R.string.pair_code_pairing else R.string.pair_code_pair),
                { onSubmit(code) }, Modifier.fillMaxWidth(), kind = SwButtonKind.Main, enabled = complete, busy = ui.busy,
            )
            if (!complete) {
                Text(
                    stringResource(R.string.pair_code_error_length), style = MaterialTheme.typography.bodySmall,
                    color = SpoolwardenTheme.colors.muted,
                )
            }
            ui.error?.let { NoticeCard(NoticeKind.Bad, it.text()) }
        }
    }
}

private const val CODE_LENGTH = 6
