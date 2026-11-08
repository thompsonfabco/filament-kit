package com.thompsonfabco.filamentkit.ui.pair

import android.content.ContextWrapper
import android.graphics.Rect
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.common.sdkinternal.MlKitContext
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.ReaderException
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import zxingcpp.BarcodeReader

private const val TAG = "QrCompare"

/**
 * The gate for dropping ML Kit: decodes every picture of [QrTestImages] with ML Kit (the scanner the app used to
 * ship) and with [QrDecoder] fed the same brightness plane the camera path gives it. ZXing must read at least as
 * many, and every text it returns must be the exact URI. Results go to logcat (tag QrCompare) as CSV and a
 * per-category summary, and to files/qr-compare.csv of the app under test.
 *
 * "zxing_basic" is ZXing with only the hybrid binariser and TRY_HARDER, i.e. [QrDecoder] without its fallbacks.
 * "zxing_cpp" is the C++ port of ZXing (zxing-cpp, Apache-2.0), fed the same grey picture; reported, not asserted.
 */
@RunWith(AndroidJUnit4::class)
class QrDecoderComparisonTest {
    private class Row(
        val case: QrTestImages.Case,
        val mlkit: String?,
        val basic: String?,
        val zxing: String?,
        val cpp: String?,
    ) {
        val expected get() = case.params.text
        val mlkitOk get() = mlkit == expected
        val basicOk get() = basic == expected
        val zxingOk get() = zxing == expected
        val cppOk get() = cpp == expected
    }

    @Test
    fun zxingReadsAtLeastAsManyAsMlKit() {
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
        val cpp = BarcodeReader().apply {
            options.formats = setOf(BarcodeReader.Format.QR_CODE)
            options.tryHarder = true
            options.tryInvert = true
            options.tryRotate = true
            options.tryDownscale = true
        }
        val nanos = LongArray(3) // ML Kit, QrDecoder, zxing-cpp
        val rows = QrTestImages.cases().map { case ->
            val bitmap = QrTestImages.render(case.params)
            val w = bitmap.width
            val h = bitmap.height
            var t = System.nanoTime()
            val mlkit = Tasks.await(scanner.process(InputImage.fromBitmap(bitmap, 0)))
                .firstNotNullOfOrNull { it.rawValue }
            nanos[0] += System.nanoTime() - t
            val luma = QrTestImages.luma(bitmap)
            t = System.nanoTime()
            val zxing = decoder.decode(luma, w, h)
            nanos[1] += System.nanoTime() - t
            t = System.nanoTime()
            val cppText = cpp.read(bitmap, Rect(0, 0, w, h), 0).firstNotNullOfOrNull { it.text }
            nanos[2] += System.nanoTime() - t
            bitmap.recycle()
            Row(case, mlkit, basicZxing(luma, w, h), zxing, cppText)
        }
        scanner.close()

        val csv = buildList {
            add("id,category,params,mlkit,zxing_basic,zxing,zxing_cpp,zxing_text_ok")
            rows.forEach { r ->
                add("${r.case.id},${r.case.category},${r.case.params.describe()},${r.mlkitOk.pf()},${r.basicOk.pf()}," +
                    "${r.zxingOk.pf()},${r.cppOk.pf()},${r.zxing == null || r.zxingOk}")
            }
        }
        csv.forEach { Log.i(TAG, "csv $it") }
        val target = InstrumentationRegistry.getInstrumentation().targetContext
        File(target.filesDir, "qr-compare.csv").writeText(csv.joinToString("\n", postfix = "\n"))

        Log.i(TAG, "summary category,images,mlkit,zxing_basic,zxing,zxing_cpp")
        for ((cat, list) in rows.groupBy { it.case.category } + ("ALL" to rows)) {
            Log.i(
                TAG,
                "summary $cat,${list.size},${list.count { it.mlkitOk }},${list.count { it.basicOk }}," +
                    "${list.count { it.zxingOk }},${list.count { it.cppOk }}",
            )
        }
        Log.i(TAG, "ms per image: mlkit ${nanos[0] / 1_000_000 / rows.size}, zxing ${nanos[1] / 1_000_000 / rows.size}, " +
            "zxing_cpp ${nanos[2] / 1_000_000 / rows.size}")
        rows.filter { it.mlkitOk && !it.zxingOk }.forEach {
            Log.i(TAG, "mlkit-only ${it.case.id} ${it.case.category} ${it.case.params.describe()}")
        }
        rows.filter { !it.mlkitOk && it.zxingOk }.forEach {
            Log.i(TAG, "zxing-only ${it.case.id} ${it.case.category} ${it.case.params.describe()}")
        }

        val wrong = rows.filter { it.zxing != null && !it.zxingOk }
        assertTrue("ZXing returned wrong text for ${wrong.map { it.case.id }}", wrong.isEmpty())
        val ml = rows.count { it.mlkitOk }
        val zx = rows.count { it.zxingOk }
        assertTrue("ZXing read $zx of ${rows.size}, ML Kit $ml", zx >= ml)
    }

    private fun basicZxing(luma: ByteArray, w: Int, h: Int): String? = try {
        val source = PlanarYUVLuminanceSource(luma, w, h, 0, 0, w, h, false)
        QRCodeReader().decode(BinaryBitmap(HybridBinarizer(source)), mapOf(DecodeHintType.TRY_HARDER to true)).text
    } catch (_: ReaderException) {
        null
    }

    private fun Boolean.pf() = if (this) "pass" else "fail"
}
