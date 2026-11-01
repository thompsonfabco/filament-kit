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
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.update.UpdateUi
import java.text.DateFormat
import java.util.Date

/**
 * The start screen: server name with a connection dot, the update banner, Add spools / Search / Printers /
 * Settings, and the unfinished adds kept on the phone ([onResumeDraft] reopens one). [extra] is for debug tools.
 */
@Composable
fun HomeScreen(
    serverName: String,
    connection: Connection,
    drafts: List<Draft>,
    update: UpdateUi,
    onAddSpools: () -> Unit,
    onSearch: () -> Unit,
    onPrinters: () -> Unit,
    onSettings: () -> Unit,
    onResumeDraft: (id: String) -> Unit,
    onRetryConnection: () -> Unit,
    onReviewCertificate: () -> Unit,
    onInstallUpdate: () -> Unit,
    onConfirmInstall: () -> Unit,
    modifier: Modifier = Modifier,
    extra: @Composable () -> Unit = {},
) {
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("filament-kit", style = MaterialTheme.typography.headlineSmall)
        ConnectionRow(serverName, connection, onRetryConnection, onReviewCertificate)
        UpdateBanner(update, onInstallUpdate, onConfirmInstall)

        Button(onClick = onAddSpools, modifier = Modifier.fillMaxWidth()) { Text("Add spools") }
        Button(onClick = onSearch, modifier = Modifier.fillMaxWidth()) { Text("Search") }
        Button(onClick = onPrinters, modifier = Modifier.fillMaxWidth()) { Text("Printers") }
        OutlinedButton(onClick = onSettings, modifier = Modifier.fillMaxWidth()) { Text("Settings") }

        if (drafts.isNotEmpty()) {
            Text("Unfinished adds", style = MaterialTheme.typography.titleMedium)
            drafts.forEach { d -> DraftRow(d) { onResumeDraft(d.id) } }
        }
        extra()
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
    if (update.available == null && !update.confirmPending) return
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Update available", style = MaterialTheme.typography.titleMedium)
            if (update.needsPermission) Text("Allow filament-kit to install apps, then tap Install again.")
            update.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (update.confirmPending) {
                Button(onClick = onConfirm) { Text("Tap to install") }
            } else {
                Button(onClick = onInstall, enabled = !update.busy) { Text(if (update.busy) "Downloading…" else "Install") }
            }
        }
    }
}

@Composable
private fun DraftRow(draft: Draft, onClick: () -> Unit) {
    val photos = if (draft.photos.size == 1) "1 photo" else "${draft.photos.size} photos"
    val detail = listOfNotNull(photos, draft.hint.ifBlank { null }, draft.tag?.let { "tag $it" }).joinToString(" · ")
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(12.dp)) {
            Text(DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(draft.created)))
            Text(detail, style = MaterialTheme.typography.bodySmall)
        }
    }
}
