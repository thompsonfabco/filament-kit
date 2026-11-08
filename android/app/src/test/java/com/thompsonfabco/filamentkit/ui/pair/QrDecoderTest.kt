package com.thompsonfabco.filamentkit.ui.pair

import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import java.awt.Color
import java.awt.RenderingHints
import java.awt.geom.AffineTransform
import java.awt.image.BufferedImage
import java.awt.image.DataBufferByte
import kotlin.random.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class QrDecoderTest {
    // What the server's pairing QR holds (server/filament_kit/pairing.py issue()).
    private val uri = "fkit://pair?h=kit.local&p=8443&t=Ab-_x9y2zQwErTyUiOpAsDfGhJkLzXcVbNm1234567&fp=" +
        "0f".repeat(32) + "&ip=192.168.1.20&ip=10.0.0.5"

    @Test
    fun readsCleanCode() {
        assertEquals(uri, decode(frame(uri)))
    }

    @Test
    fun readsRotatedCode() {
        for (deg in listOf(15.0, 45.0, 90.0, 180.0, 270.0)) {
            assertEquals("at $deg degrees", uri, decode(frame(uri, rotation = deg)))
        }
    }

    @Test
    fun readsInvertedCode() {
        assertEquals(uri, decode(frame(uri, inverted = true)))
    }

    @Test
    fun readsCodeInsideCropOfLargerRow() {
        val f = frame(uri)
        // The same picture with 64 junk bytes after each row and 10 junk rows on top, as a camera buffer can have.
        val stride = f.width + 64
        val junk = Random(7)
        val big = ByteArray(stride * (f.height + 10)) { junk.nextInt(256).toByte() }
        for (y in 0 until f.height) System.arraycopy(f.bytes, y * f.width, big, (y + 10) * stride, f.width)
        assertEquals(uri, QrDecoder().decode(big, stride, f.height + 10, left = 0, top = 10, width = f.width, height = f.height))
    }

    @Test
    fun noCodeGivesNull() {
        val noise = Random(1)
        val w = 640
        val h = 480
        assertNull(QrDecoder().decode(ByteArray(w * h) { noise.nextInt(256).toByte() }, w, h))
        assertNull(QrDecoder().decode(ByteArray(w * h) { 0x80.toByte() }, w, h))
    }

    private class Frame(val bytes: ByteArray, val width: Int, val height: Int)

    private fun decode(f: Frame) = QrDecoder().decode(f.bytes, f.width, f.height)

    /** A 640x480 grey frame with the code in the middle, 4 px per module, light grey background. */
    private fun frame(text: String, rotation: Double = 0.0, inverted: Boolean = false): Frame {
        val matrix = QRCodeWriter().encode(
            text, BarcodeFormat.QR_CODE, 0, 0,
            mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.L, EncodeHintType.MARGIN to 4),
        )
        val dark = if (inverted) Color(235, 235, 235) else Color(20, 20, 20)
        val light = if (inverted) Color(20, 20, 20) else Color(235, 235, 235)
        val module = 4
        val img = BufferedImage(640, 480, BufferedImage.TYPE_BYTE_GRAY)
        val g = img.createGraphics()
        g.color = Color(150, 150, 150)
        g.fillRect(0, 0, 640, 480)
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR)
        val side = matrix.width * module
        g.transform = AffineTransform().apply {
            translate(320.0, 240.0)
            rotate(Math.toRadians(rotation))
            translate(-side / 2.0, -side / 2.0)
        }
        g.color = light
        g.fillRect(0, 0, side, side)
        g.color = dark
        for (y in 0 until matrix.height) for (x in 0 until matrix.width) {
            if (matrix[x, y]) g.fillRect(x * module, y * module, module, module)
        }
        g.dispose()
        return Frame((img.raster.dataBuffer as DataBufferByte).data, 640, 480)
    }
}
