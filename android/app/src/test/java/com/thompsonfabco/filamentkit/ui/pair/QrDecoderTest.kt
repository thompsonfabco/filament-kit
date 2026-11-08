package com.thompsonfabco.filamentkit.ui.pair

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

// QrDecoder itself is native (zxing-cpp) and is checked on a device by QrDecoderComparisonTest; this covers the
// frame handling around it.
class QrDecoderTest {
    private val uri = "fkit://pair?h=kit.local&p=8443&t=tok&fp=" + "0f".repeat(32)

    @Test
    fun reportsTheFirstTextOnceAndClosesEveryFrame() {
        val frames = listOf(null, uri, "fkit://pair?other", uri)
        var decoded = 0
        var closed = 0
        val gate = QrFrameGate<String?> { decoded++; it }

        val results = frames.map { gate.offer(it) { closed++ } }

        assertEquals(listOf(null, uri, null, null), results)
        assertEquals("frames after the find are not decoded", 2, decoded)
        assertEquals(4, closed)
    }

    @Test
    fun dropsFramesWhileOneIsDecoding() {
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val gate = QrFrameGate<String> { frame ->
            if (frame == "slow") {
                started.countDown()
                release.await(5, TimeUnit.SECONDS)
                null
            } else {
                frame
            }
        }
        var slowClosed = false
        val worker = thread { gate.offer("slow") { slowClosed = true } }
        assertTrue(started.await(5, TimeUnit.SECONDS))

        var droppedClosed = false
        assertNull("busy: dropped unread", gate.offer(uri) { droppedClosed = true })
        assertTrue(droppedClosed)

        release.countDown()
        worker.join(5000)
        assertTrue(slowClosed)
        assertEquals("free again after the slow frame", uri, gate.offer(uri) {})
    }

    @Test
    fun aFailingDecodeStillClosesTheFrame() {
        var closed = false
        val gate = QrFrameGate<String> { if (it == "bad") error("boom") else it }
        runCatching { gate.offer("bad") { closed = true } }
        assertTrue(closed)
        assertEquals("not stuck busy", uri, gate.offer(uri) {})
    }
}
