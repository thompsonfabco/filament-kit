package com.thompsonfabco.filamentkit.ui.pair

import android.content.ContextWrapper
import android.graphics.ImageFormat
import android.graphics.Rect
import android.util.Log
import androidx.camera.core.ImageInfo
import androidx.camera.core.ImageProxy
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.common.sdkinternal.MlKitContext
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.io.File
import java.lang.reflect.Proxy
import java.nio.ByteBuffer
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

private const val TAG = "QrCompare"

/**
 * The gate for dropping ML Kit: decodes every picture of [QrTestImages] with ML Kit (the scanner the app used to
 * ship) and with the app's [QrDecoder] (zxing-cpp), fed the picture's brightness as a YUV camera frame, the way
 * the scanner gets it. zxing-cpp must read at least as many, and every text it returns must be the exact URI.
 * Results go to logcat (tag QrCompare) as CSV and a per-category summary, and to files/qr-compare.csv of the app
 * under test.
 */
@RunWith(AndroidJUnit4::class)
class QrDecoderComparisonTest {
    private class Row(val case: QrTestImages.Case, val mlkit: String?, val zxing: String?) {
        val expected get() = case.params.text
        val mlkitOk get() = mlkit == expected
        val zxingOk get() = zxing == expected
    }

    @Test
    fun zxingCppReadsAtLeastAsManyAsMlKit() {
        // ML Kit normally starts from its content provider, which only runs in the app's own APK, not the test APK.
        // Its components are declared in the test APK's manifest, so start it on that context (which has no
        // application context of its own, hence the wrapper).
        val testContext = object : ContextWrapper(InstrumentationRegistry.getInstrumentation().context) {
            override fun getApplicationContext() = this
        }
        MlKitContext.initializeIfNeeded(testContext)
        val scanner = BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build(),
        )
        val decoder = QrDecoder()
        val nanos = LongArray(2) // ML Kit, QrDecoder
        val rows = QrTestImages.cases().map { case ->
            val bitmap = QrTestImages.render(case.params)
            val w = bitmap.width
            val h = bitmap.height
            var t = System.nanoTime()
            val mlkit = Tasks.await(scanner.process(InputImage.fromBitmap(bitmap, 0)))
                .firstNotNullOfOrNull { it.rawValue }
            nanos[0] += System.nanoTime() - t
            val frame = yuvFrame(QrTestImages.luma(bitmap), w, h)
            bitmap.recycle()
            t = System.nanoTime()
            val zxing = decoder.decode(frame)
            nanos[1] += System.nanoTime() - t
            Row(case, mlkit, zxing)
        }
        scanner.close()

        val csv = buildList {
            add("id,category,params,mlkit,zxing_cpp,zxing_text_ok")
            rows.forEach { r ->
                add("${r.case.id},${r.case.category},${r.case.params.describe()},${r.mlkitOk.pf()},${r.zxingOk.pf()}," +
                    "${r.zxing == null || r.zxingOk}")
            }
        }
        csv.forEach { Log.i(TAG, "csv $it") }
        val target = InstrumentationRegistry.getInstrumentation().targetContext
        File(target.filesDir, "qr-compare.csv").writeText(csv.joinToString("\n", postfix = "\n"))

        Log.i(TAG, "summary category,images,mlkit,zxing_cpp")
        for ((cat, list) in rows.groupBy { it.case.category } + ("ALL" to rows)) {
            Log.i(TAG, "summary $cat,${list.size},${list.count { it.mlkitOk }},${list.count { it.zxingOk }}")
        }
        Log.i(TAG, "ms per image: mlkit ${nanos[0] / 1_000_000 / rows.size}, zxing_cpp ${nanos[1] / 1_000_000 / rows.size}")
        rows.filter { it.mlkitOk && !it.zxingOk }.forEach {
            Log.i(TAG, "mlkit-only ${it.case.id} ${it.case.category} ${it.case.params.describe()}")
        }
        rows.filter { !it.mlkitOk && it.zxingOk }.forEach {
            Log.i(TAG, "zxing-only ${it.case.id} ${it.case.category} ${it.case.params.describe()}")
        }

        val wrong = rows.filter { it.zxing != null && !it.zxingOk }
        assertTrue("zxing-cpp returned wrong text for ${wrong.map { it.case.id }}", wrong.isEmpty())
        val ml = rows.count { it.mlkitOk }
        val zx = rows.count { it.zxingOk }
        assertTrue("zxing-cpp read $zx of ${rows.size}, ML Kit $ml", zx >= ml)
    }

    /**
     * A YUV_420_888 camera frame whose Y plane is [luma] (in a direct buffer, rows padded like a camera's), with
     * flat chroma. Only what zxing-cpp's read(ImageProxy) uses is real; ImageProxy has members that are internal
     * to CameraX, hence a dynamic proxy rather than a class.
     */
    private fun yuvFrame(luma: ByteArray, w: Int, h: Int): ImageProxy {
        val stride = w + 64
        val y = ByteBuffer.allocateDirect(stride * h)
        for (row in 0 until h) {
            y.position(row * stride)
            y.put(luma, row * w, w)
        }
        y.rewind()
        val chroma = ByteBuffer.allocateDirect(w * h / 2).apply { while (hasRemaining()) put(0x80.toByte()); rewind() }
        fun plane(buf: ByteBuffer, rowStride: Int, pixelStride: Int) =
            proxy<ImageProxy.PlaneProxy> { name ->
                when (name) {
                    "getBuffer" -> buf
                    "getRowStride" -> rowStride
                    "getPixelStride" -> pixelStride
                    else -> null
                }
            }
        val planes = arrayOf(plane(y, stride, 1), plane(chroma, w, 2), plane(chroma, w, 2))
        val info = proxy<ImageInfo> { name ->
            when (name) {
                "getRotationDegrees" -> 0
                "getTimestamp" -> 0L
                else -> null
            }
        }
        return proxy { name ->
            when (name) {
                "getFormat" -> ImageFormat.YUV_420_888
                "getWidth" -> w
                "getHeight" -> h
                "getCropRect" -> Rect(0, 0, w, h)
                "getPlanes" -> planes
                "getImageInfo" -> info
                else -> null // close(), setCropRect(), getImage()
            }
        }
    }

    private inline fun <reified T> proxy(crossinline answer: (String) -> Any?): T =
        Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { self, method, args ->
            when (method.name) {
                "hashCode" -> System.identityHashCode(self)
                "equals" -> self === args?.get(0)
                "toString" -> "fake ${T::class.java.simpleName}"
                else -> answer(method.name)
            }
        } as T

    private fun Boolean.pf() = if (this) "pass" else "fail"
}
