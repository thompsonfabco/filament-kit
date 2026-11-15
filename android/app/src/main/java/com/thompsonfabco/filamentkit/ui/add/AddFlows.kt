package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.imaging.prepareJpeg
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch

/**
 * The adds that are open, one [AddViewModel] per draft, held by the app and not by a screen (05-android-app 6): a read or
 * an add goes on when the person leaves the screen, and the four steps (photos, check, preview, done) all talk to the
 * same flow. Every add, photo or hand, is a draft in [store] from the moment it starts. A flow is dropped by [release]
 * (after "Done", a discard, or when the person leaves an add with nothing in it).
 */
class AddFlows(
    private val scope: CoroutineScope,
    private val store: DraftStore,
    private val api: IntakeApi,
    private val io: CoroutineDispatcher = Dispatchers.IO,
    private val prepare: (ByteArray) -> ByteArray = { prepareJpeg(it) },
) {
    private class Open(val vm: AddViewModel, val job: Job)

    private val open = mutableMapOf<String, Open>()
    private val _readFinished = MutableSharedFlow<String>(extraBufferCapacity = 8)
    private val _addFinished = MutableSharedFlow<Pair<String, Boolean>>(extraBufferCapacity = 8)

    /** The draft whose read just ended with items. */
    val readFinished: SharedFlow<String> = _readFinished

    /** The draft whose real add just ended, and whether the spools were added. */
    val addFinished: SharedFlow<Pair<String, Boolean>> = _addFinished

    /** A new draft on the photo path or, with [manual], the hand path; returns its id. */
    fun start(manual: Boolean, tag: String? = null): String {
        val id = store.create(manual).id
        open(id, manual, tag)
        return id
    }

    /** The drafts whose flows are open now. */
    fun openIds(): Set<String> = synchronized(open) { open.keys.toSet() }

    /** The words for why an add that is open cannot be replaced right now ("Adding to Spoolman…"). */
    fun writingReason(id: String): Int =
        if (synchronized(open) { open[id]?.vm }?.state?.value?.stage == Stage.Adding) R.string.add_preview_adding
        else R.string.add_preview_checking

    /** The draft is on the phone (or its flow is open). */
    fun exists(id: String): Boolean = synchronized(open) { id in open } || store.get(id) != null

    /** Where a draft goes on resume: its first step. */
    fun stepOf(id: String): AddStep {
        val d = store.get(id)
        val items = d?.editedItems?.isNotEmpty() == true || d?.readResult != null
        return if (d?.manual == true || items) AddStep.Check else AddStep.Photos
    }

    /** The flow of draft [id]: the open one, or one restored from the draft. */
    fun get(id: String): AddViewModel = synchronized(open) { open[id]?.vm } ?: open(id, store.get(id)?.manual == true, null)

    private fun open(id: String, manual: Boolean, tag: String?): AddViewModel {
        val job = SupervisorJob(scope.coroutineContext[Job])
        val own = CoroutineScope(scope.coroutineContext + job)
        val vm = AddViewModel(
            api, store, taps = emptyFlow(), draftId = id, initialTag = tag, manual = manual, prepare = prepare, io = io, ownScope = own,
        )
        own.launch { vm.readDone.collect { _readFinished.emit(id) } }
        own.launch { vm.finished.collect { _addFinished.emit(id to it) } }
        synchronized(open) { open[id] = Open(vm, job) }
        return vm
    }

    /** Drops the flow (its draft stays on the phone unless a real add deleted it). */
    fun release(id: String) {
        val gone = synchronized(open) { open.remove(id) } ?: return
        gone.job.cancel()
    }

    /** The person left the add: a draft with nothing in it goes away; anything else stays on the phone. */
    fun leave(id: String) {
        val s = synchronized(open) { open[id]?.vm }?.state?.value ?: return
        if (isEmpty(s)) {
            release(id)
            store.delete(id)
        }
    }

    /**
     * A real add failed and was told to the person away from its screen, who did not open it: the flow is dropped and
     * its draft stays on the phone. An add that is writing again is left alone.
     */
    fun dropAfterFailure(id: String) {
        if (replaceRule(id) == AddReplace.Replace) release(id)
    }

    /** What may happen to the open add when a new one is asked for (05-android-app 2.5). */
    fun replaceRule(id: String): AddReplace =
        synchronized(open) { open[id]?.vm }?.let { addReplace(it.state.value) } ?: AddReplace.Replace

    /** "Add more": a new draft on the same path; the finished flow is dropped. */
    fun again(id: String): String {
        val manual = synchronized(open) { open[id]?.vm }?.state?.value?.manual == true
        release(id)
        return start(manual)
    }

    companion object {
        /** Nothing typed, photographed, tapped or read: leaving costs nothing. */
        internal fun isEmpty(s: AddUiState): Boolean =
            s.stage in setOf(Stage.Capture, Stage.Review) && s.photos.isEmpty() && s.items.isEmpty() && s.tag == null &&
                s.hint.isBlank() && s.weight == null && s.addedBefore == null
    }
}
