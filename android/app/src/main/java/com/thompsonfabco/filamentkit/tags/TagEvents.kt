package com.thompsonfabco.filamentkit.tags

import android.app.Activity
import android.nfc.NfcAdapter
import android.nfc.Tag
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.dropWhile
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** Process-wide stream of tapped tag UIDs (canonical format). */
object TagEvents {
    private val _taps = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val taps: SharedFlow<String> = _taps.asSharedFlow()

    fun emit(uid: String) {
        _taps.tryEmit(uid)
    }

    private val appScope by lazy { CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate) }

    /**
     * Emits [uid] once the screen that is coming up listens: a tap held back by a screen that took it (the pick screen
     * during a load) is given on when that screen has left. Listening or not, it is emitted after [waitMs].
     */
    fun emitWhenListening(uid: String, scope: CoroutineScope = appScope, waitMs: Long = 1000L) {
        scope.launch {
            // the leaving screen's own collector goes first, then the next one's comes
            withTimeoutOrNull(waitMs) { _taps.subscriptionCount.dropWhile { it > 0 }.first { it > 0 } }
            emit(uid)
        }
    }
}

private const val READER_FLAGS = NfcAdapter.FLAG_READER_NFC_A or
    NfcAdapter.FLAG_READER_NFC_B or
    NfcAdapter.FLAG_READER_NFC_F or
    NfcAdapter.FLAG_READER_NFC_V or
    NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK

/** Starts NFC reader mode; each tag emits its UID on [TagEvents]. No-op without NFC. */
fun Activity.enableTagReader() {
    val adapter = NfcAdapter.getDefaultAdapter(this) ?: return
    adapter.enableReaderMode(this, { tag: Tag -> TagEvents.emit(formatUid(tag.id)) }, READER_FLAGS, null)
}

/** Stops NFC reader mode. No-op without NFC. */
fun Activity.disableTagReader() {
    NfcAdapter.getDefaultAdapter(this)?.disableReaderMode(this)
}
