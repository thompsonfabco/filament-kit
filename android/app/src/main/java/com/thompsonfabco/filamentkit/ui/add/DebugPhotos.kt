package com.thompsonfabco.filamentkit.ui.add

import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow

/**
 * Debug builds only: label photos handed to the open add flow as if the camera had taken them (the emulator
 * end-to-end test uses it; an emulator has no real label to photograph). Buffered until the add flow collects.
 */
object DebugPhotos {
    private val channel = Channel<ByteArray>(capacity = 8)
    val photos: Flow<ByteArray> = channel.receiveAsFlow()

    fun emit(jpeg: ByteArray) {
        channel.trySend(jpeg)
    }
}
