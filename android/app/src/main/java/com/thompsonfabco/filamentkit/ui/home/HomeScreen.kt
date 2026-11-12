package com.thompsonfabco.filamentkit.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.update.UpdateTexts
import com.thompsonfabco.filamentkit.update.UpdateUi
import java.text.DateFormat
import java.util.Date

/**
 * The start screen: server name with a connection dot, the update banner, Add spool (by hand), Add from label
 * photos (only when [labelPhotos]: the server reads labels, see [showLabelPhotos]) / Search / Printers /
 * Settings, and the unfinished adds kept on the phone ([onResumeDraft] reopens one). [extra] is for debug tools.
 */
@Composable
fun HomeScreen(
    serverName: String,
    connection: Connection,
    drafts: List<Draft>,
    update: UpdateUi,
    /** The small line directly under the title ([versionLine]). */
    version: String,
    onAddSpools: () -> Unit,
    onAddByHand: () -> Unit,
    onAddProfile: () -> Unit,
    onSearch: () -> Unit,
    onPrinters: () -> Unit,
    onSettings: () -> Unit,
    onResumeDraft: (id: String) -> Unit,
    /** Delete an unfinished add and its photos (asked to confirm first). */
    onDiscardDraft: (id: String) -> Unit,
    onRetryConnection: () -> Unit,
    onReviewCertificate: () -> Unit,
    onInstallUpdate: () -> Unit,
    onConfirmInstall: () -> Unit,
    modifier: Modifier = Modifier,
    /** The intake history (the last spools added, with their photos; revise and edit). */
    onHistory: () -> Unit = {},
    /** The Presets card; null while the status is unknown. [showPresets] false hides the card (not paired yet). */
    presets: ProfileStatus? = null,
    showPresets: Boolean = true,
    /** Offer the label-photo add flow ([showLabelPhotos]). */
    labelPhotos: Boolean = false,
    /** Shown while [connection] is [Connection.NeedsLocalNetwork] (explanation, Allow, Open app settings). */
    localNetworkPanel: @Composable () -> Unit = {},
    extra: @Composable () -> Unit = {},
) {
    Column(modifier.fillMaxSize()) {
    Column(
        Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column {
            Text("filament-kit", style = MaterialTheme.typography.headlineSmall)
            VersionLine(version)
        }
        ConnectionRow(serverName, connection, onRetryConnection, onReviewCertificate)
        if (connection == Connection.NeedsLocalNetwork) localNetworkPanel()
        UpdateBanner(update, onInstallUpdate, onConfirmInstall)

        Button(onClick = onAddByHand, modifier = Modifier.fillMaxWidth()) { Text("Add spool") }
        if (labelPhotos) {
            OutlinedButton(onClick = onAddSpools, modifier = Modifier.fillMaxWidth()) { Text("Add from label photos") }
        }
        OutlinedButton(onClick = onAddProfile, modifier = Modifier.fillMaxWidth()) { Text("Add profile") }
        Button(onClick = onSearch, modifier = Modifier.fillMaxWidth()) { Text("Search") }
        OutlinedButton(onClick = onHistory, modifier = Modifier.fillMaxWidth()) { Text("Intake history") }
        Button(onClick = onPrinters, modifier = Modifier.fillMaxWidth()) { Text("Printers") }
        OutlinedButton(onClick = onSettings, modifier = Modifier.fillMaxWidth()) { Text("Settings") }
        if (showPresets) PresetsCard(presets)

        if (drafts.isNotEmpty()) {
            Text("Unfinished adds", style = MaterialTheme.typography.titleMedium)
            drafts.forEach { d -> DraftRow(d, onClick = { onResumeDraft(d.id) }, onDiscard = { onDiscardDraft(d.id) }) }
        }
        extra()
    }
    }
}

@Composable
private fun ConnectionRow(name: String, connection: Connection, onRetry: () -> Unit, onReview: () -> Unit) {
    val (color, label) = when (connection) {
        is Connection.Online -> Color(0xFF2E7D32) to "Connected"
        Connection.Checking -> Color(0xFFF9A825) to "Connecting…"
        Connection.Offline -> Color(0xFFC62828) to "Can't reach the server"
        is Connection.CertChanged -> Color(0xFFC62828) to "The server's certificate changed"
        Connection.Unpaired -> Color.Gray to "Not paired"
        Connection.NeedsLocalNetwork -> Color(0xFFF9A825) to "Needs local network access"
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.size(12.dp).background(color, CircleShape))
        Column(Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.titleMedium)
            Text(label, style = MaterialTheme.typography.bodySmall)
        }
        when (connection) {
            Connection.Offline -> TextButton(onClick = onRetry) { Text("Retry") }
            is Connection.CertChanged -> TextButton(onClick = onReview) { Text("Review") }
            else -> Unit
        }
    }
}

@Composable
private fun UpdateBanner(update: UpdateUi, onInstall: () -> Unit, onConfirm: () -> Unit) {
    if (update.available == null && !update.confirmPending && !update.serverTooNew) return
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (update.serverTooNew) {
                Text("Update the app", style = MaterialTheme.typography.titleMedium)
                Text(
                    "The server is newer than this app, so some things may not work. " +
                        if (update.available != null || update.confirmPending) "Install the update below."
                        else "The server has no newer app to install yet: ask whoever runs the server for the latest filament-kit app.",
                )
            } else {
                Text(UpdateTexts.bannerTitle(update.offeredVersion), style = MaterialTheme.typography.titleMedium)
            }
            if (update.needsPermission) Text("Allow filament-kit to install apps, then tap Install again.")
            update.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            val refused = UpdateTexts.refused(update)
            if (refused) {
                val links = LocalUriHandler.current
                TextButton(onClick = {
                    // no browser on the phone: the sentence above still says what to do
                    runCatching { links.openUri(UpdateTexts.REFUSED_GUIDE_URL) }
                }) { Text(UpdateTexts.REFUSED_GUIDE_LABEL) }
            }
            if (update.confirmPending) {
                Button(onClick = onConfirm) { Text("Tap to install") }
            } else if (update.available != null) {
                val label = UpdateTexts.installLabel(update)
                if (refused) {
                    OutlinedButton(onClick = onInstall, enabled = !update.busy) { Text(label) }
                } else {
                    Button(onClick = onInstall, enabled = !update.busy) { Text(label) }
                }
            }
        }
    }
}

@Composable
private fun DraftRow(draft: Draft, onClick: () -> Unit, onDiscard: () -> Unit) {
    var confirming by remember { mutableStateOf(false) }
    val photos = if (draft.photos.size == 1) "1 photo" else "${draft.photos.size} photos"
    val detail = listOfNotNull(photos, draft.hint.ifBlank { null }, draft.tag?.let { "tag $it" }).joinToString(" · ")
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(12.dp)) {
            Text(DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(draft.created)))
            Text(detail, style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { confirming = true }) { Text("Discard") }
        }
    }
    if (confirming) {
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text("Discard this unfinished add?") },
            text = { Text("Its $photos will be deleted from this phone. Nothing is removed from the server.") },
            confirmButton = { TextButton(onClick = { confirming = false; onDiscard() }) { Text("Discard") } },
            dismissButton = { TextButton(onClick = { confirming = false }) { Text("Keep") } },
        )
    }
}

/** The label-photo add flow is offered only when the server says its `ai_intake` module is on ([info] null: unknown). */
fun showLabelPhotos(info: ServerInfo?): Boolean = info?.labelReading == true
