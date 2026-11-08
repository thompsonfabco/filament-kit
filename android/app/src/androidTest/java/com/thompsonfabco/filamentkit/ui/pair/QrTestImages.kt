package com.thompsonfabco.filamentkit.ui.pair

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import java.io.ByteArrayOutputStream
import kotlin.math.PI
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.random.Random

/**
 * The fixed picture set for [QrDecoderComparisonTest]: a pairing QR code photographed badly, generated from fixed
 * seeds so every run sees the same pictures. Greyscale 1280x720 frames, like a camera's brightness plane.
 */
object QrTestImages {
    const val WIDTH = 1280
    const val HEIGHT = 720

    /** A pairing URI as server/filament_kit/pairing.py issue() writes it (urlencode, quote_plus). */
    val PAIR_URI = "fkit://pair?h=filament.local&p=8443&t=${token(11)}&fp=${hex(12)}&ip=192.168.1.20"

    /** A long one: long host name, two IPv4 and two IPv6 addresses (':' becomes %3A). */
    val PAIR_URI_LONG = "fkit://pair?h=filament-kit-workshop-server.local&p=8443&t=${token(21)}&fp=${hex(22)}" +
        "&ip=192.168.1.20&ip=10.0.0.5&ip=fd12%3A3456%3A789a%3A1%3A5054%3Aff%3Afe12%3A3456" +
        "&ip=2001%3Adb8%3A85a3%3A%3A8a2e%3A370%3A7334"

    /** How one picture is made. Defaults are a clean, square-on code with a full quiet zone. */
    data class Params(
        val text: String,
        val modulePx: Float = 4f,
        val rotation: Float = 0f,
        val tilt: Float = 0f,
        val tiltAxis: Int = 0, // 0 vertical axis, 1 horizontal, 2 diagonal
        val blur: Float = 0f, // gaussian sigma, px
        val noise: Float = 0f, // gaussian sigma, grey levels
        val dark: Int = 25,
        val light: Int = 230,
        val lighting: Float = 0f, // 0 even; 0.7 = the dark side gets 30 % of the light
        val glare: Float = 0f, // grey levels added at the centre of a bright band across the code
        val jpeg: Int = 0, // 0 = no JPEG round trip, else the quality
        val quietZone: Float = 4f, // modules of light margin; the background around it is cluttered
        val inverted: Boolean = false,
        val seed: Int = 0,
    ) {
        fun describe(): String = buildList {
            add(if (text == PAIR_URI) "uri=short" else "uri=long")
            add("module=$modulePx")
            if (rotation != 0f) add("rot=$rotation")
            if (tilt != 0f) add("tilt=$tilt/${"yxd"[tiltAxis]}")
            if (blur != 0f) add("blur=$blur")
            if (noise != 0f) add("noise=$noise")
            if (dark != 25 || light != 230) add("grey=$dark/$light")
            if (lighting != 0f) add("lighting=$lighting")
            if (glare != 0f) add("glare=$glare")
            if (jpeg != 0) add("jpeg=$jpeg")
            if (quietZone != 4f) add("quiet=$quietZone")
            if (inverted) add("inverted")
            add("seed=$seed")
        }.joinToString(" ")
    }

    data class Case(val id: Int, val category: String, val params: Params)

    /** Every picture in the set, by degradation category. */
    fun cases(): List<Case> {
        val out = mutableListOf<Case>()
        fun add(category: String, p: Params) { out += Case(out.size, category, p.copy(seed = out.size)) }
        val uris = listOf(PAIR_URI, PAIR_URI_LONG)
        val modules = mapOf(PAIR_URI to moduleCount(PAIR_URI), PAIR_URI_LONG to moduleCount(PAIR_URI_LONG))

        for (u in uris) for (m in listOf(2f, 2.5f, 3f, 4f, 5f, 6f, 7f, 8f)) add("module size", Params(u, modulePx = m))
        // The symbol's side as a share of the frame height.
        for (u in uris) for (f in listOf(0.15f, 0.2f, 0.3f, 0.4f, 0.5f, 0.6f, 0.7f, 0.8f)) {
            add("frame fill", Params(u, modulePx = f * HEIGHT / modules.getValue(u)))
        }
        for (u in uris) for (m in listOf(3f, 5f)) for (r in listOf(0f, 15f, 45f, 90f, 180f, 270f)) {
            add("rotation", Params(u, modulePx = m, rotation = r))
        }
        for (u in uris) for (axis in 0..2) for (t in listOf(10f, 20f, 25f, 30f, 35f)) {
            add("tilt", Params(u, modulePx = 4f, tilt = t, tiltAxis = axis))
        }
        for (u in uris) for (m in listOf(3f, 5f)) for (b in listOf(0.5f, 1f, 1.5f, 2f, 2.5f, 3f)) {
            add("blur", Params(u, modulePx = m, blur = b))
        }
        for (u in uris) for (m in listOf(3f, 5f)) for (n in listOf(8f, 16f, 24f, 32f, 48f)) {
            add("noise", Params(u, modulePx = m, noise = n))
        }
        for (u in uris) for (m in listOf(3f, 5f)) {
            for ((d, l) in listOf(60 to 110, 80 to 120, 100 to 135, 110 to 140, 120 to 145)) {
                add("low contrast", Params(u, modulePx = m, dark = d, light = l))
            }
        }
        for (u in uris) for (m in listOf(3f, 5f)) {
            for ((lit, gl) in listOf(0.6f to 0f, 0.8f to 0f, 0f to 120f, 0f to 200f, 0.6f to 160f)) {
                add("lighting/glare", Params(u, modulePx = m, lighting = lit, glare = gl))
            }
        }
        for (u in uris) for (m in listOf(2.5f, 4f)) for (q in listOf(5, 10, 15, 25, 40)) {
            add("jpeg", Params(u, modulePx = m, jpeg = q))
        }
        for (u in uris) for (m in listOf(3f, 5f)) for (qz in listOf(2f, 1f, 0.5f, 0f)) {
            add("quiet zone", Params(u, modulePx = m, quietZone = qz))
        }
        for (u in uris) for (m in listOf(2.5f, 3f, 4f, 6f)) for (r in listOf(0f, 30f)) {
            add("inverted", Params(u, modulePx = m, rotation = r, inverted = true))
        }
        // Mixed: several milder faults at once, as a real phone photo has.
        val mix = Random(2026)
        repeat(40) { i ->
            add(
                "mixed",
                Params(
                    uris[i % 2],
                    modulePx = 2.5f + mix.nextFloat() * 4f,
                    rotation = mix.nextFloat() * 360f,
                    tilt = mix.nextFloat() * 25f,
                    tiltAxis = mix.nextInt(3),
                    blur = mix.nextFloat() * 1.5f,
                    noise = mix.nextFloat() * 20f,
                    dark = 25 + mix.nextInt(50),
                    light = 230 - mix.nextInt(70),
                    lighting = mix.nextFloat() * 0.5f,
                    glare = if (mix.nextInt(4) == 0) 60f + mix.nextFloat() * 80f else 0f,
                    jpeg = if (mix.nextBoolean()) 30 + mix.nextInt(60) else 0,
                    quietZone = if (mix.nextInt(4) == 0) 1f + mix.nextFloat() * 2f else 4f,
                    inverted = mix.nextInt(10) == 0,
                ),
            )
        }
        return out
    }

    fun moduleCount(text: String): Int = encode(text).width

    /** Renders one picture as an ARGB bitmap (grey pixels). */
    fun render(p: Params): Bitmap {
        val rnd = Random(p.seed * 7919 + 17)
        val frame = Bitmap.createBitmap(WIDTH, HEIGHT, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(frame)
        canvas.drawColor(grey(110))
        // Desk clutter, so a short quiet zone really runs into other edges.
        val paint = Paint()
        repeat(40) {
            paint.color = grey(30 + rnd.nextInt(190))
            val x = rnd.nextInt(WIDTH).toFloat()
            val y = rnd.nextInt(HEIGHT).toFloat()
            canvas.drawRect(x, y, x + 20 + rnd.nextInt(300), y + 10 + rnd.nextInt(200), paint)
        }

        val matrix = encode(p.text)
        val n = matrix.width
        val scale = ceil(p.modulePx).toInt().coerceAtLeast(2) // card px per module; drawn down to modulePx
        val margin = (p.quietZone * scale).roundToInt()
        val side = n * scale + 2 * margin
        val (dark, light) = if (p.inverted) p.light to p.dark else p.dark to p.light
        val card = Bitmap.createBitmap(side, side, Bitmap.Config.ARGB_8888)
        val pixels = IntArray(side * side) { grey(light) }
        for (y in 0 until n) for (x in 0 until n) if (matrix[x, y]) {
            for (dy in 0 until scale) for (dx in 0 until scale) {
                pixels[(margin + y * scale + dy) * side + margin + x * scale + dx] = grey(dark)
            }
        }
        card.setPixels(pixels, 0, side, 0, 0, side, side)

        // Where the card lands: rotated in the image plane, tilted in 3D, seen by a ~70 degree lens.
        val size = side * p.modulePx / scale
        val half = size / 2f
        val slack = ((minOf(WIDTH, HEIGHT) - size * 1.45f) / 2f).coerceAtLeast(0f)
        val cx = WIDTH / 2f + (rnd.nextFloat() * 2 - 1) * minOf(slack, 150f)
        val cy = HEIGHT / 2f + (rnd.nextFloat() * 2 - 1) * minOf(slack, 80f)
        val f = 914f
        val dst = FloatArray(8)
        val corners = listOf(-half to -half, half to -half, half to half, -half to half)
        val rot = p.rotation * PI.toFloat() / 180f
        val tilt = p.tilt * PI.toFloat() / 180f
        val (ax, ay) = when (p.tiltAxis) { 0 -> 0f to 1f; 1 -> 1f to 0f; else -> (1f / sqrt(2f)) to (1f / sqrt(2f)) }
        corners.forEachIndexed { i, (x0, y0) ->
            val x1 = x0 * cos(rot) - y0 * sin(rot)
            val y1 = x0 * sin(rot) + y0 * cos(rot)
            // Rodrigues rotation about the in-plane axis (ax, ay, 0); z starts at 0.
            val dot = ax * x1 + ay * y1
            val c = cos(tilt)
            val s = sin(tilt)
            val x2 = x1 * c + ax * dot * (1 - c)
            val y2 = y1 * c + ay * dot * (1 - c)
            val z2 = (ax * y1 - ay * x1) * s
            val z = f + z2
            dst[i * 2] = cx + f * x2 / z
            dst[i * 2 + 1] = cy + f * y2 / z
        }
        val src = floatArrayOf(0f, 0f, side.toFloat(), 0f, side.toFloat(), side.toFloat(), 0f, side.toFloat())
        val m = Matrix().apply { setPolyToPoly(src, 0, dst, 0, 4) }
        canvas.drawBitmap(card, m, Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG))

        // Light, then optics, then sensor, then compression.
        val px = IntArray(WIDTH * HEIGHT)
        frame.getPixels(px, 0, WIDTH, 0, 0, WIDTH, HEIGHT)
        var lum = FloatArray(px.size) { (px[it] and 0xff).toFloat() }
        if (p.lighting > 0f) {
            for (y in 0 until HEIGHT) for (x in 0 until WIDTH) {
                lum[y * WIDTH + x] *= 1f - p.lighting * (1f - x.toFloat() / WIDTH)
            }
        }
        if (p.glare > 0f) {
            val angle = rnd.nextFloat() * PI.toFloat()
            val nx = cos(angle)
            val ny = sin(angle)
            val width = maxOf(size * 0.12f, 12f)
            for (y in 0 until HEIGHT) for (x in 0 until WIDTH) {
                val d = (x - cx) * nx + (y - cy) * ny
                lum[y * WIDTH + x] += p.glare * exp(-(d * d) / (2 * width * width))
            }
        }
        if (p.blur > 0f) lum = gaussian(lum, p.blur)
        if (p.noise > 0f) {
            val g = java.util.Random(p.seed.toLong() * 31 + 5)
            for (i in lum.indices) lum[i] += (g.nextGaussian() * p.noise).toFloat()
        }
        for (i in px.indices) px[i] = grey(lum[i].roundToInt().coerceIn(0, 255))
        frame.setPixels(px, 0, WIDTH, 0, 0, WIDTH, HEIGHT)
        if (p.jpeg == 0) return frame
        val bytes = ByteArrayOutputStream().also { frame.compress(Bitmap.CompressFormat.JPEG, p.jpeg, it) }.toByteArray()
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply {
            inPreferredConfig = Bitmap.Config.ARGB_8888
        })
    }

    /** The brightness plane a camera would deliver for [bitmap]: full-range BT.601 luma, one byte per pixel. */
    fun luma(bitmap: Bitmap): ByteArray {
        val px = IntArray(bitmap.width * bitmap.height)
        bitmap.getPixels(px, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        return ByteArray(px.size) {
            val c = px[it]
            (0.299f * Color.red(c) + 0.587f * Color.green(c) + 0.114f * Color.blue(c)).roundToInt().coerceIn(0, 255).toByte()
        }
    }

    private fun encode(text: String) = QRCodeWriter().encode(
        text, BarcodeFormat.QR_CODE, 0, 0,
        // qrencode's default level, which the server's terminal QR uses.
        mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.L, EncodeHintType.MARGIN to 0),
    )

    private fun gaussian(src: FloatArray, sigma: Float): FloatArray {
        val r = ceil(sigma * 3).toInt()
        val k = FloatArray(2 * r + 1) { exp(-((it - r) * (it - r)) / (2 * sigma * sigma)) }
        val sum = k.sum()
        for (i in k.indices) k[i] /= sum
        val tmp = FloatArray(src.size)
        for (y in 0 until HEIGHT) for (x in 0 until WIDTH) {
            var acc = 0f
            for (i in -r..r) acc += k[i + r] * src[y * WIDTH + (x + i).coerceIn(0, WIDTH - 1)]
            tmp[y * WIDTH + x] = acc
        }
        val out = FloatArray(src.size)
        for (y in 0 until HEIGHT) for (x in 0 until WIDTH) {
            var acc = 0f
            for (i in -r..r) acc += k[i + r] * tmp[(y + i).coerceIn(0, HEIGHT - 1) * WIDTH + x]
            out[y * WIDTH + x] = acc
        }
        return out
    }

    private fun grey(v: Int) = Color.rgb(v, v, v)

    private fun token(seed: Int): String {
        val abc = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        val r = Random(seed)
        return String(CharArray(43) { abc[r.nextInt(abc.length)] })
    }

    private fun hex(seed: Int): String {
        val r = Random(seed)
        return String(CharArray(64) { "0123456789abcdef"[r.nextInt(16)] })
    }
}
