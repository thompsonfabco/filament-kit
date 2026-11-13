package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.withStyle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * A text field of the printer forms (05-android-app 3.1): the label inside the outline, the hint under it, and an
 * error under it that starts with the octagon so colour is not the only sign. A [secret] field hides what is typed and
 * has the text button "Show" / "Hide" whose spoken name adds the field ("Show Access Code"); what is typed is kept
 * only as long as the form is on screen.
 */
@Composable
internal fun FormField(
    value: String,
    onChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    placeholder: String? = null,
    hint: String? = null,
    error: String? = null,
    enabled: Boolean = true,
    secret: Boolean = false,
    mono: Boolean = false,
    keyboard: KeyboardType = KeyboardType.Text,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    var shown by remember { mutableStateOf(false) }
    val hidden = secret && !shown
    val type = SpoolwardenTheme.type
    val toggleName = stringResource(if (shown) R.string.common_hide_named else R.string.common_show_named, label)
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        modifier = modifier.fillMaxWidth(),
        enabled = enabled,
        singleLine = true,
        isError = error != null,
        label = { Text(label) },
        placeholder = placeholder?.let { { Text(it) } },
        textStyle = if (mono) type.data else type.input,
        shape = SpoolwardenTheme.shapes.r,
        visualTransformation = if (hidden) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(
            keyboardType = if (secret) KeyboardType.Password else keyboard, autoCorrectEnabled = false,
        ),
        trailingIcon = if (secret) {
            {
                SwButton(
                    stringResource(if (shown) R.string.common_hide else R.string.common_show),
                    { shown = !shown },
                    Modifier.semantics { contentDescription = toggleName },
                    kind = SwButtonKind.Quiet,
                    enabled = enabled,
                )
            }
        } else {
            null
        },
        supportingText = if (error != null || hint != null) {
            {
                if (error != null) {
                    Row(horizontalArrangement = Arrangement.spacedBy(space.s1), verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            painterResource(NoticeKind.Bad.shape), contentDescription = null,
                            modifier = Modifier.size(NoticeKind.Bad.side(space)), tint = colors.bad,
                        )
                        Text(error, color = colors.bad)
                    }
                } else if (hint != null) {
                    Text(hint)
                }
            }
        } else {
            null
        },
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = colors.text, unfocusedTextColor = colors.text, disabledTextColor = colors.muted,
            errorTextColor = colors.text,
            focusedContainerColor = colors.surface, unfocusedContainerColor = colors.surface,
            disabledContainerColor = colors.surface2, errorContainerColor = colors.surface,
            focusedBorderColor = colors.focus, unfocusedBorderColor = colors.borderStrong,
            disabledBorderColor = colors.border, errorBorderColor = colors.bad,
            focusedLabelColor = colors.accentText, unfocusedLabelColor = colors.muted,
            disabledLabelColor = colors.muted, errorLabelColor = colors.bad,
            focusedPlaceholderColor = colors.muted, unfocusedPlaceholderColor = colors.muted,
            focusedSupportingTextColor = colors.muted, unfocusedSupportingTextColor = colors.muted,
            disabledSupportingTextColor = colors.muted, errorSupportingTextColor = colors.bad,
            cursorColor = colors.text, errorCursorColor = colors.text,
        ),
    )
}

/** The words for a [Problem], from the catalogue; the Hub's own message is shown as given. */
@Composable
internal fun problemText(problem: Problem): String = when (problem) {
    Problem.Unreachable -> stringResource(R.string.common_hub_unreachable)
    Problem.Unexpected -> stringResource(R.string.common_hub_answer_unknown)
    is Problem.HubSaid -> problem.text
    is Problem.FeatureOff -> stringResource(
        R.string.common_feature_off,
        when (problem.module) {
            "klipper" -> stringResource(R.string.common_klipper)
            "bambu" -> stringResource(R.string.common_bambu_lab)
            else -> problem.module
        },
    )
    is Problem.PrinterState -> stringResource(fixLine(problem.state) ?: R.string.common_hub_answer_unknown)
}

/** [text] with the first [part] in the mono face (serials and addresses, 05-android-app 15). */
@Composable
internal fun withMono(text: String, part: String): AnnotatedString = buildAnnotatedString {
    val at = text.indexOf(part).takeIf { part.isNotEmpty() }
    if (at == null || at < 0) {
        append(text)
        return@buildAnnotatedString
    }
    append(text.substring(0, at))
    withStyle(SpanStyle(fontFamily = SpoolwardenTheme.type.data.fontFamily)) { append(part) }
    append(text.substring(at + part.length))
}
