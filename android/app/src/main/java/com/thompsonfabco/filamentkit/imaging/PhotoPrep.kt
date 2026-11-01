package com.thompsonfabco.filamentkit.imaging

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import kotlin.math.max

private const val MAX_BYTES = 3 * 1024 * 1024
private const val MIN_QUALITY = 55

/**
 * Decodes any Android-decodable image, applies EXIF orientation, scales the longest side to at
 * most [maxSide] and encodes JPEG, stepping quality down by 10 (not below 55) until <= 3 MB.
 */
fun prepareJpeg(input: ByteArray, maxSide: Int = 1600, quality: Int = 85): ByteArray {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(input, 0, input.size, bounds)
    require(bounds.outWidth > 0 && bounds.outHeight > 0) { "unreadable image" }

    var sample = 1
    while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxSide) sample *= 2
    val decoded = BitmapFactory.decodeByteArray(
        input, 0, input.size, BitmapFactory.Options().apply { inSampleSize = sample },
    ) ?: throw IllegalArgumentException("unreadable image")

    val orientation = ExifInterface(ByteArrayInputStream(input))
        .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
    val matrix = Matrix()
    when (orientation) {
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
        ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
        ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.postRotate(90f); matrix.postScale(-1f, 1f) }
        ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
        ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.postRotate(270f); matrix.postScale(-1f, 1f) }
        ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
    }
    val longest = max(decoded.width, decoded.height)
    if (longest > maxSide) {
        val s = maxSide.toFloat() / longest
        matrix.postScale(s, s)
    }
    val bitmap = Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)

    var q = quality
    while (true) {
        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, q, out)
        if (out.size() <= MAX_BYTES) return out.toByteArray()
        if (q - 10 < MIN_QUALITY) throw IllegalArgumentException("photo too large")
        q -= 10
    }
}
