package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * Developer (05-android-app 12.6, debug builds only): type a tag ID (e.g. `4:77:90:e`) and [onSimulate] hands it to the
 * app as if the tag had been tapped (2.6).
 */
@Composable
internal fun DeveloperSettings(onSimulate: (String) -> Unit, modifier: Modifier = Modifier) {
    val example = stringResource(R.string.settings_developer_tag_example)
    var tagId by rememberSaveable { mutableStateOf(example) }
    SettingsPage(modifier) {
        OutlinedTextField(
            value = tagId, onValueChange = { tagId = it }, label = { Text(stringResource(R.string.settings_developer_tag_id)) },
            singleLine = true, textStyle = SpoolwardenTheme.type.data, modifier = Modifier.fillMaxWidth(),
        )
        SwButton(
            stringResource(R.string.settings_developer_simulate), { onSimulate(tagId.trim()) },
            Modifier.fillMaxWidth(), enabled = tagId.isNotBlank(),
        )
    }
}
