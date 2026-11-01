package com.thompsonfabco.filamentkit.ui.printers

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayOutputStream

class MjpegParserTest {
    private fun part(img: ByteArray, withLength: Boolean = true): ByteArray {
        val out = ByteArrayOutputStream()
        out.write("--frame\r\nContent-Type: image/jpeg\r\n".toByteArray())
        if (withLength) out.write("Content-Length: ${img.size}\r\n".toByteArray())
        out.write("\r\n".toByteArray())
        out.write(img)
        out.write("\r\n".toByteArray())
        return out.toByteArray()
    }

    // JPEG-like payloads that contain CR/LF and dashes, so a naive line parser would break
    private val a = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 13, 10, 45, 45, 1, 2, 3, 0xFF.toByte(), 0xD9.toByte())
    private val b = ByteArray(5000) { (it % 251).toByte() }
    private val c = byteArrayOf(9, 8, 7)

    @Test fun yieldsFramesFromOneRead() {
        val p = MjpegParser("frame")
        val frames = p.feed(part(a) + part(b) + part(c))
        assertEquals(3, frames.size)
        assertArrayEquals(a, frames[0])
        assertArrayEquals(b, frames[1])
        assertArrayEquals(c, frames[2])
    }

    @Test fun yieldsFramesWhenSplitAcrossReadsAtEveryOffset() {
        val stream = part(a) + part(b) + part(c)
        for (chunk in listOf(1, 2, 3, 7, 13, 64, 1000, 4097)) {
            val p = MjpegParser("frame")
            val got = mutableListOf<ByteArray>()
            var i = 0
            while (i < stream.size) {
                val n = minOf(chunk, stream.size - i)
                got += p.feed(stream.copyOfRange(i, i + n))
                i += n
            }
            assertEquals("chunk $chunk", 3, got.size)
            assertArrayEquals(a, got[0])
            assertArrayEquals(b, got[1])
            assertArrayEquals(c, got[2])
        }
    }

    @Test fun usesTheLengthParameterOfABuffer() {
        val p = MjpegParser("frame")
        val buf = part(c) + ByteArray(100)
        assertEquals(1, p.feed(buf, part(c).size).size)
    }

    @Test fun findsFramesWithoutContentLengthByTheNextBoundary() {
        val p = MjpegParser("frame")
        val stream = part(a, withLength = false) + part(c, withLength = false)
        val frames = mutableListOf<ByteArray>()
        stream.forEach { frames += p.feed(byteArrayOf(it)) }
        // the last part has no following boundary yet, so only the first is complete
        assertEquals(1, frames.size)
        assertArrayEquals(a, frames[0])
    }

    @Test fun boundaryComesFromTheContentType() {
        assertEquals("frame", MjpegParser.boundaryOf("multipart/x-mixed-replace; boundary=frame"))
        assertEquals("xyz", MjpegParser.boundaryOf("multipart/x-mixed-replace;boundary=\"xyz\""))
        assertNull(MjpegParser.boundaryOf("image/jpeg"))
    }

    @Test fun rejectsAnOversizedFrame() {
        val p = MjpegParser("frame", maxFrameBytes = 1000)
        assertThrows(java.io.IOException::class.java) { p.feed(part(b)) }
    }
}
