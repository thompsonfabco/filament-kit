package com.thompsonfabco.filamentkit.ui.pair

import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.ReaderException
import com.google.zxing.common.GlobalHistogramBinarizer
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader

/**
 * Finds a QR code in one greyscale frame (a camera frame's Y plane) with ZXing. Pure JVM code, so it is tested
 * without a device. Not thread-safe: use one per thread (the scanner decodes on a single executor).
 *
 * QR detection copes with any rotation by itself; what costs codes is binarisation. Each picture is tried with the
 * local (hybrid) binariser, inverted for light-on-dark codes, and with the global histogram binariser. If that
 * finds nothing, cheapest first: contrast boosted (dim codes), halved (noise), doubled (small modules), doubled
 * and boosted. Measured against ML Kit in QrDecoderComparisonTest.
 */
class QrDecoder {
    private val reader = QRCodeReader()
    private val hints = mapOf(DecodeHintType.TRY_HARDER to true, DecodeHintType.CHARACTER_SET to "UTF-8")

    /**
     * Decodes the [width] x [height] area at [left], [top] of [luma], one byte per pixel with rows [rowStride]
     * bytes apart. Returns the QR code's text, or null if there is none (or it can't be read).
     */
    fun decode(
        luma: ByteArray,
        rowStride: Int,
        rows: Int,
        left: Int = 0,
        top: Int = 0,
        width: Int = rowStride,
        height: Int = rows,
    ): String? {
        val img = Luma(luma, rowStride, rows, left, top, width, height)
        attempt(img)?.let { return it }
        val packed = img.packed()
        val boosted = packed.boosted()
        return attempt(boosted) ?: attempt(packed.halved()) ?: attempt(packed.doubled()) ?: attempt(boosted.doubled())
    }

    private fun attempt(img: Luma): String? {
        val source = PlanarYUVLuminanceSource(img.bytes, img.stride, img.rows, img.left, img.top, img.width, img.height, false)
        return tryDecode(BinaryBitmap(HybridBinarizer(source)))
            ?: tryDecode(BinaryBitmap(HybridBinarizer(source.invert())))
            ?: tryDecode(BinaryBitmap(GlobalHistogramBinarizer(source)))
            ?: tryDecode(BinaryBitmap(GlobalHistogramBinarizer(source.invert())))
    }

    private fun tryDecode(bitmap: BinaryBitmap): String? = try {
        reader.decode(bitmap, hints).text
    } catch (_: ReaderException) { // NotFound, Checksum, Format: no readable code in this picture
        null
    } finally {
        reader.reset()
    }

    /** A greyscale picture: the [width] x [height] area at [left], [top] of [bytes], rows [stride] apart. */
    private class Luma(
        val bytes: ByteArray,
        val stride: Int,
        val rows: Int,
        val left: Int,
        val top: Int,
        val width: Int,
        val height: Int,
    ) {
        private fun at(x: Int, y: Int) = bytes[(top + y) * stride + left + x].toInt() and 0xff

        /** Just the area, rows back to back. */
        fun packed(): Luma {
            if (left == 0 && top == 0 && stride == width && rows == height) return this
            val out = ByteArray(width * height)
            for (y in 0 until height) System.arraycopy(bytes, (top + y) * stride + left, out, y * width, width)
            return of(out, width, height)
        }

        /** Contrast times 2.5 around the mean, so a dim code clears the binarisers' minimum contrast. */
        fun boosted(): Luma {
            var sum = 0L
            for (b in bytes) sum += b.toInt() and 0xff
            val mean = (sum / bytes.size).toInt()
            val lut = ByteArray(256) { ((it - mean) * 5 / 2 + 128).coerceIn(0, 255).toByte() }
            return of(ByteArray(bytes.size) { lut[bytes[it].toInt() and 0xff] }, width, height)
        }

        /** Half size, each pixel the mean of 2x2: averages noise away. */
        fun halved(): Luma {
            val w = width / 2
            val h = height / 2
            val out = ByteArray(w * h)
            for (y in 0 until h) for (x in 0 until w) {
                val sum = at(2 * x, 2 * y) + at(2 * x + 1, 2 * y) + at(2 * x, 2 * y + 1) + at(2 * x + 1, 2 * y + 1)
                out[y * w + x] = ((sum + 2) / 4).toByte()
            }
            return of(out, w, h)
        }

        /** Double size, bilinear: gives the detector more pixels per module on small codes. */
        fun doubled(): Luma {
            val w = width * 2
            val h = height * 2
            val out = ByteArray(w * h)
            for (y in 0 until h) {
                val sy = ((y - 0.5f) / 2f).coerceIn(0f, height - 1f)
                val y0 = sy.toInt()
                val y1 = minOf(y0 + 1, height - 1)
                val fy = sy - y0
                for (x in 0 until w) {
                    val sx = ((x - 0.5f) / 2f).coerceIn(0f, width - 1f)
                    val x0 = sx.toInt()
                    val x1 = minOf(x0 + 1, width - 1)
                    val fx = sx - x0
                    val v = (at(x0, y0) * (1 - fx) + at(x1, y0) * fx) * (1 - fy) + (at(x0, y1) * (1 - fx) + at(x1, y1) * fx) * fy
                    out[y * w + x] = (v + 0.5f).toInt().toByte()
                }
            }
            return of(out, w, h)
        }

        companion object {
            fun of(bytes: ByteArray, width: Int, height: Int) = Luma(bytes, width, height, 0, 0, width, height)
        }
    }
}
