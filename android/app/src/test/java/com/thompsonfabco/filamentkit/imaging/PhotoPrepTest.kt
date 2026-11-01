package com.thompsonfabco.filamentkit.imaging

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.exifinterface.media.ExifInterface
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode
import java.io.ByteArrayOutputStream
import java.io.File
import kotlin.random.Random

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class PhotoPrepTest {
    private fun bounds(bytes: ByteArray): Pair<Int, Int> {
        val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
        return o.outWidth to o.outHeight
    }

    private fun encode(w: Int, h: Int, format: Bitmap.CompressFormat): ByteArray {
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        bmp.eraseColor(0xFF336699.toInt())
        return ByteArrayOutputStream().also { bmp.compress(format, 95, it) }.toByteArray()
    }

    @Test
    fun largePngBecomesJpegWithMaxSide1600() {
        val out = prepareJpeg(encode(4000, 3000, Bitmap.CompressFormat.PNG))
        assertEquals(0xFF, out[0].toInt() and 0xFF)
        assertEquals(0xD8, out[1].toInt() and 0xFF)
        assertEquals(0xFF, out[2].toInt() and 0xFF)
        assertEquals(1600 to 1200, bounds(out))
        assertTrue(out.size <= 3_145_728)
    }

    @Test
    fun exifOrientation6IsAppliedToPixels() {
        val jpeg = encode(400, 300, Bitmap.CompressFormat.JPEG)
        val f = File.createTempFile("rot", ".jpg")
        try {
            f.writeBytes(jpeg)
            ExifInterface(f.absolutePath).apply {
                setAttribute(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_ROTATE_90.toString())
                saveAttributes()
            }
            assertEquals(300 to 400, bounds(prepareJpeg(f.readBytes())))
        } finally {
            f.delete()
        }
    }

    @Test
    fun incompressibleImageThrowsPhotoTooLarge() {
        // Noise cannot compress below 3 MB even at quality 55 (3000x3000 px, maxSide 3000).
        val bmp = Bitmap.createBitmap(3000, 3000, Bitmap.Config.ARGB_8888)
        val rnd = Random(1)
        val px = IntArray(3000 * 3000) { rnd.nextInt() or (0xFF shl 24) }
        bmp.setPixels(px, 0, 3000, 0, 0, 3000, 3000)
        val png = ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        try {
            prepareJpeg(png, maxSide = 3000)
            fail("expected IllegalArgumentException")
        } catch (e: IllegalArgumentException) {
            assertEquals("photo too large", e.message)
        }
    }
}
