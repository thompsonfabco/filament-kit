package com.thompsonfabco.filamentkit.ui.history

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistorySummary
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.printers.MismatchNotice
import com.thompsonfabco.filamentkit.ui.printers.UnpairedNotice
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Recently added: the list of intake records. */
@Composable
fun HistoryListEntry(api: Api, onOpen: (String) -> Unit, onPairAgain: () -> Unit) {
    val backend = remember(api) { HistoryBackend.of(api) }
    val list = viewModel(key = System.identityHashCode(api).toString()) { HistoryListViewModel(backend) }
    HistoryListScreen(list, onOpen = onOpen, onPairAgain = onPairAgain)
}

/**
 * One record. The list's view model belongs to [listOwner] (the list's own back stack entry), so the record shares the
 * list's data and the list refreshes when the person comes back.
 */
@Composable
fun HistoryRecordEntry(api: Api, id: String, listOwner: ViewModelStoreOwner, onBack: () -> Unit, onPairAgain: () -> Unit) {
    val backend = remember(api) { HistoryBackend.of(api) }
    val apiKey = System.identityHashCode(api).toString()
    val list = viewModel(viewModelStoreOwner = listOwner, key = apiKey) { HistoryListViewModel(backend) }
    val vm = viewModel(key = apiKey) { RecordViewModel(backend, id) }
    // A record can open with no list loaded (restored after process death): load it for the AI flag.
    LaunchedEffect(id) { list.ensureLoaded() }
    val ai = list.state.collectAsState().value.aiAvailable
    RecordScreen(vm, list, ai, onBack = { list.refresh(); onBack() }, onPairAgain = onPairAgain)
}

@Composable
private fun HistoryListScreen(vm: HistoryListViewModel, onOpen: (String) -> Unit, onPairAgain: () -> Unit) {
    val s by vm.state.collectAsState()
    LifecycleStartEffect(vm) {
        vm.refresh()
        onStopOrDispose { }
    }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        s.mismatch?.let { (e, a) -> MismatchNotice(e, a, onPairAgain); return@Column }
        if (s.unauthorized) { UnpairedNotice(onPairAgain); return@Column }
        s.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        val h = s.history
        when {
            h == null -> Text(if (s.loading) "Loading…" else "")
            h.keep == 0 && h.records.isEmpty() -> Text(HistoryTexts.KEEP_NONE)
            h.records.isEmpty() -> Text(HistoryTexts.EMPTY)
            else -> {
                Text("The last ${h.records.size} of up to ${h.keep} kept, newest first.", style = MaterialTheme.typography.bodySmall)
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(h.records, key = { it.id }) { r -> RecordRow(r, vm) { onOpen(r.id) } }
                }
            }
        }
    }
}

@Composable
private fun RecordRow(r: HistorySummary, vm: HistoryListViewModel, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            if (r.photos > 0) Photo(vm, r.id, 1, Modifier.size(64.dp), thumb = true)
            else ColorSwatch(r.spools.firstOrNull()?.colorHex, head = true)
            Column(Modifier.weight(1f)) {
                Text(HistoryTexts.spools(r.spools))
                Text("${HistoryTexts.state(r.state)} · ${HistoryTexts.source(r.source)}", style = MaterialTheme.typography.bodySmall)
                Text(HistoryTexts.time(r.at), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

/** A record's photo [n], fetched once per visit; [thumb] decodes it small. */
@Composable
private fun Photo(vm: HistoryListViewModel, id: String, n: Int, modifier: Modifier, thumb: Boolean = false) {
    val bitmap by produceState<Bitmap?>(null, id, n, thumb) {
        val bytes = vm.photo(id, n) ?: return@produceState
        value = withContext(Dispatchers.Default) { decode(bytes, if (thumb) 192 else 1600) }
    }
    val b = bitmap
    if (b == null) {
        Box(modifier.background(MaterialTheme.colorScheme.surfaceVariant))
    } else {
        Image(b.asImageBitmap(), contentDescription = "Photo $n", modifier = modifier,
            contentScale = if (thumb) ContentScale.Crop else ContentScale.Fit)
    }
}

/** Decodes a JPEG no larger than about [max] pixels on its long side (a full photo is not needed for a thumbnail). */
private fun decode(bytes: ByteArray, max: Int): Bitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= max) sample *= 2
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
}

@Composable
private fun RecordScreen(vm: RecordViewModel, list: HistoryListViewModel, ai: Boolean?, onBack: () -> Unit, onPairAgain: () -> Unit) {
    val s by vm.state.collectAsState()
    LaunchedEffect(vm) { vm.load() }
    var enlarged by rememberSaveable { mutableStateOf<Int?>(null) }
    var note by rememberSaveable { mutableStateOf("") }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Intake record", style = MaterialTheme.typography.headlineSmall)
        s.mismatch?.let { (e, a) -> MismatchNotice(e, a, onPairAgain); return@Column }
        if (s.unauthorized) { UnpairedNotice(onPairAgain); return@Column }
        val r = s.record
        if (r == null) {
            Text(s.message ?: "Loading…", color = if (s.messageIsError) MaterialTheme.colorScheme.error else Color.Unspecified)
            return@Column
        }
        Text("${HistoryTexts.state(r.state)} · ${HistoryTexts.source(r.source)} · ${HistoryTexts.time(r.at)}")
        listOfNotNull(r.weight?.let { "Weighed ${HistoryTexts.value(kotlinx.serialization.json.JsonPrimitive(it))} g" },
            r.tag?.let { "Tag read" }).takeIf { it.isNotEmpty() }?.let { Text(it.joinToString(" · "), style = MaterialTheme.typography.bodySmall) }

        if (r.photos > 0) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (1..r.photos).forEach { n ->
                    Photo(list, r.id, n, Modifier.size(96.dp).clickable { enlarged = n }, thumb = true)
                }
            }
            Text("Tap a photo to enlarge it.", style = MaterialTheme.typography.bodySmall)
        } else {
            Text("No photo: these spools were added by hand.", style = MaterialTheme.typography.bodySmall)
        }

        s.message?.let { Text(it, color = if (s.messageIsError) MaterialTheme.colorScheme.error else Color.Unspecified) }

        r.saved.forEach { item ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(if (item.spoolIds.size == 1) "Spool #${item.spoolIds.single()}" else
                        "${item.spoolIds.size} spools: " + item.spoolIds.joinToString(", ") { "#$it" },
                        style = MaterialTheme.typography.titleSmall)
                    HistoryTexts.FIELDS.filter { it in item.values }.forEach { f ->
                        Text("${HistoryTexts.label(f)}: ${HistoryTexts.value(item.values[f])}")
                    }
                    HistoryTexts.readLine(r, item.item)?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    OutlinedButton(onClick = { vm.openEdit(item.item) }) { Text(HistoryTexts.EDIT) }
                }
            }
        }

        // revise with AI: greyed with the reason when label reading is off
        Text("Revise with AI", style = MaterialTheme.typography.titleMedium)
        if (ai == false) Text(HistoryTexts.AI_OFF, style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(note, { note = it }, label = { Text(HistoryTexts.NOTE_LABEL) }, enabled = ai != false && !s.reviseBusy,
            modifier = Modifier.fillMaxWidth())
        if (ai != false) Text(HistoryTexts.NOTE_HELP, style = MaterialTheme.typography.bodySmall)
        s.noteError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(onClick = { vm.revise(note) }, enabled = ai != false && !s.reviseBusy) {
            Text(if (s.reviseBusy) HistoryTexts.ASKING else HistoryTexts.ASK)
        }

        s.undoTarget?.let { t ->
            OutlinedButton(onClick = vm::undo, enabled = !s.undoBusy) { Text(HistoryTexts.UNDO) }
            Text("Takes back: " + HistoryTexts.revision(t), style = MaterialTheme.typography.bodySmall)
        }

        if (r.revisions.isNotEmpty()) {
            Text("Changes", style = MaterialTheme.typography.titleMedium)
            r.revisions.asReversed().forEach { rev ->
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(HistoryTexts.revision(rev), style = MaterialTheme.typography.labelLarge)
                    HistoryTexts.changes(rev).forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                    HistoryTexts.filaments(rev)?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
            }
        }
    }

    val r = s.record
    enlarged?.let { n ->
        if (r != null) Dialog(onDismissRequest = { enlarged = null }) {
            Photo(list, r.id, n, Modifier.fillMaxWidth().clickable { enlarged = null })
        }
    }
    s.proposal?.let { p ->
        AlertDialog(
            onDismissRequest = { if (!s.applyBusy) vm.discard() },
            title = { Text("The AI proposes") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    com.thompsonfabco.filamentkit.ui.add.ReaderTexts.revisedBy(p)?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall)
                    }
                    if (p.noPhoto) Text(HistoryTexts.NO_PHOTO, style = MaterialTheme.typography.bodySmall)
                    if (p.changes.isEmpty()) Text(HistoryTexts.NO_CHANGE)
                    p.changes.forEach { f ->
                        Text("${HistoryTexts.label(f)}: ${HistoryTexts.value(p.before[f])} → ${HistoryTexts.value(p.after[f])}")
                    }
                }
            },
            confirmButton = {
                Button(onClick = vm::accept, enabled = p.changes.isNotEmpty() && !s.applyBusy) {
                    Text(if (s.applyBusy) "Saving…" else HistoryTexts.ACCEPT)
                }
            },
            dismissButton = { TextButton(onClick = vm::discard, enabled = !s.applyBusy) { Text(HistoryTexts.DISCARD) } },
        )
    }
    s.edit?.let { f -> if (r != null) EditDialog(r, f, vm) }
}

@Composable
private fun EditDialog(r: HistoryRecord, f: EditForm, vm: RecordViewModel) {
    val values = r.saved.firstOrNull { it.item == f.item }?.values ?: return
    val texts = remember(r.id, f.item) {
        mutableStateMapOf<String, String>().apply { HistoryTexts.FIELDS.forEach { put(it, HistoryTexts.formText(values[it])) } }
    }
    AlertDialog(
        onDismissRequest = vm::closeEdit,
        title = { Text(HistoryTexts.EDIT) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                HistoryTexts.FIELDS.forEach { field ->
                    OutlinedTextField(
                        texts[field].orEmpty(), { texts[field] = it }, singleLine = true, enabled = !f.busy,
                        label = { Text(HistoryTexts.label(field) + if (HistoryTexts.ranged(field)) " (e.g. 190-230)" else "") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                f.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { Button(onClick = { vm.saveEdit(texts.toMap()) }, enabled = !f.busy) { Text(if (f.busy) "Saving…" else "Save") } },
        dismissButton = { TextButton(onClick = vm::closeEdit, enabled = !f.busy) { Text("Cancel") } },
    )
}
