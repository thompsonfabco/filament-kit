package com.thompsonfabco.filamentkit.ui.pair

import androidx.camera.core.ImageProxy
import java.util.concurrent.atomic.AtomicBoolean
import zxingcpp.BarcodeReader

/**
 * Reads a QR code from a camera frame with zxing-cpp (the C++ port of ZXing, a native library). It reads the
 * frame's Y plane inside its crop rectangle and copes with rotation, tilt, inverted codes and small codes itself.
 * Measured against ML Kit in QrDecoderComparisonTest. Not thread-safe: use one per thread.
 */
class QrDecoder {
    // Created on first use: making it loads the native library, which only exists on a device.
    private val reader by lazy {
        BarcodeReader().apply {
            options.formats = setOf(BarcodeReader.Format.QR_CODE)
            options.tryHarder = true
            options.tryRotate = true
            options.tryInvert = true
            options.tryDownscale = true
        }
    }

    /** The QR code's text, or null if the frame has none that can be read. Doesn't close [frame]. */
    fun decode(frame: ImageProxy): String? =
        try {
            reader.read(frame).firstOrNull { it.error == null && it.text != null }?.text
        } catch (_: IllegalStateException) { // a frame format zxing-cpp doesn't take; the next frame may do
            null
        }
}

/**
 * Hands camera frames to [decode] one at a time and gives back the first text found, once. A frame that arrives
 * while another is being decoded, or after a code was found, is dropped unread. Every frame is closed.
 */
class QrFrameGate<F>(private val decode: (F) -> String?) {
    private val busy = AtomicBoolean(false)
    private val found = AtomicBoolean(false)

    /** Decodes [frame] unless busy or done, then calls [close]. Returns the text the first time one is found. */
    fun offer(frame: F, close: () -> Unit): String? {
        try {
            if (found.get() || !busy.compareAndSet(false, true)) return null
            try {
                val text = decode(frame) ?: return null
                return if (found.compareAndSet(false, true)) text else null
            } finally {
                busy.set(false)
            }
        } finally {
            close()
        }
    }
}
