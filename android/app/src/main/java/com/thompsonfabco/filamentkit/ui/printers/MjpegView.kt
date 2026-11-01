package com.thompsonfabco.filamentkit.ui.printers

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.job
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import kotlin.coroutines.coroutineContext

/**
 * Splits a `multipart/x-mixed-replace` body into JPEG frames. Bytes may arrive in any split; [feed] returns every
 * frame completed by the new bytes. Parts with `Content-Length` are cut by length (the server always sends it);
 * parts without it end at the next boundary. A frame or header larger than the limits throws [IOException].
 */
class MjpegParser(boundary: String, private val maxFrameBytes: Int = 8 * 1024 * 1024) {
    private val dashBoundary = "--$boundary".toByteArray(Charsets.US_ASCII)
    private val crlfBoundary = "\r\n--$boundary".toByteArray(Charsets.US_ASCII)
    private var buf = ByteArray(64 * 1024)
    private var len = 0

    fun feed(chunk: ByteArray, count: Int = chunk.size): List<ByteArray> {
        append(chunk, count)
        val frames = mutableListOf<ByteArray>()
        while (true) {
            val start = indexOf(dashBoundary, 0)
            if (start < 0) {
                // keep only a tail that could be the start of a boundary
                consume(maxOf(0, len - dashBoundary.size))
                break
            }
            val headerEnd = indexOf(HEADER_END, start + dashBoundary.size)
            if (headerEnd < 0) {
                if (len - start > MAX_HEADER_BYTES) throw IOException("Camera stream part header too long")
                consume(start)
                break
            }
            val bodyStart = headerEnd + HEADER_END.size
            val length = contentLength(String(buf, start, headerEnd - start, Charsets.US_ASCII))
            if (length != null) {
                if (length < 0 || length > maxFrameBytes) throw IOException("Camera frame too large ($length bytes)")
                if (len - bodyStart < length) {
                    consume(start)
                    break
                }
                frames += buf.copyOfRange(bodyStart, bodyStart + length)
                consume(bodyStart + length)
            } else {
                val next = indexOf(crlfBoundary, bodyStart)
                if (next < 0) {
                    if (len - bodyStart > maxFrameBytes) throw IOException("Camera frame too large")
                    consume(start)
                    break
                }
                frames += buf.copyOfRange(bodyStart, next)
                consume(next + 2)
            }
        }
        return frames
    }

    private fun append(chunk: ByteArray, count: Int) {
        if (len + count > buf.size) buf = buf.copyOf(maxOf(buf.size * 2, len + count))
        System.arraycopy(chunk, 0, buf, len, count)
        len += count
    }

    /** Drops the first [n] bytes. */
    private fun consume(n: Int) {
        if (n <= 0) return
        System.arraycopy(buf, n, buf, 0, len - n)
        len -= n
    }

    private fun indexOf(pattern: ByteArray, from: Int): Int {
        var i = from
        val last = len - pattern.size
        outer@ while (i <= last) {
            for (j in pattern.indices) if (buf[i + j] != pattern[j]) { i++; continue@outer }
            return i
        }
        return -1
    }

    private fun contentLength(headers: String): Int? = headers.lineSequence()
        .map { it.trim() }
        .firstOrNull { it.startsWith("content-length:", ignoreCase = true) }
        ?.substringAfter(':')?.trim()?.toIntOrNull()

    companion object {
        private val HEADER_END = "\r\n\r\n".toByteArray(Charsets.US_ASCII)
        private const val MAX_HEADER_BYTES = 16 * 1024

        /** The `boundary` parameter of a multipart content type, or null. */
        fun boundaryOf(contentType: String): String? = contentType.split(';')
            .map { it.trim() }
            .firstOrNull { it.startsWith("boundary=", ignoreCase = true) }
            ?.substringAfter('=')?.trim('"')?.ifBlank { null }
    }
}

/**
 * Shows the printer's MJPEG stream from [url], fetched with the app's pinned [client] and [headers] (the Bearer
 * header). The connection is closed when this leaves composition; a failure is shown over the view in plain words.
 */
@Composable
fun MjpegView(client: OkHttpClient, url: String, headers: Map<String, String>, modifier: Modifier = Modifier) {
    var frame by remember(url) { mutableStateOf<Bitmap?>(null) }
    var error by remember(url) { mutableStateOf<String?>(null) }
    LaunchedEffect(url) {
        error = try {
            streamFrames(client, url, headers) { frame = it }
            "The camera stream ended."
        } catch (e: CancellationException) {
            throw e
        } catch (e: CameraHttpError) {
            PrinterHelp.cameraFix(e.code)
        } catch (e: Exception) {
            "The camera stream was interrupted. Leave this screen and come back to try again."
        }
    }
    Box(modifier, contentAlignment = Alignment.Center) {
        frame?.let {
            Image(it.asImageBitmap(), contentDescription = "Printer camera", modifier = Modifier.fillMaxWidth(),
                contentScale = ContentScale.FillWidth)
        }
        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
        }
    }
}

/** A non-2xx camera response; [code] is the server's error code (`camera_unavailable`, `not_configured`, ...). */
class CameraHttpError(val status: Int, val code: String) : IOException("camera HTTP $status $code")

private suspend fun streamFrames(
    client: OkHttpClient,
    url: String,
    headers: Map<String, String>,
    onFrame: (Bitmap) -> Unit,
) = withContext(Dispatchers.IO) {
    val req = Request.Builder().url(url).apply { headers.forEach { (k, v) -> header(k, v) } }.build()
    // an MJPEG stream never ends on its own: no read/call timeout, closed by cancelling the call
    val call = client.newBuilder().readTimeout(java.time.Duration.ofSeconds(30)).callTimeout(java.time.Duration.ZERO)
        .build().newCall(req)
    val cancel = coroutineContext.job.invokeOnCompletion { call.cancel() }
    try {
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                val code = try {
                    (Json.parseToJsonElement(resp.body.string()) as? JsonObject)?.get("error")?.jsonPrimitive?.content
                } catch (_: Exception) {
                    null
                }
                throw CameraHttpError(resp.code, code ?: "http_${resp.code}")
            }
            val boundary = MjpegParser.boundaryOf(resp.header("Content-Type").orEmpty()) ?: "frame"
            val parser = MjpegParser(boundary)
            val chunk = ByteArray(16 * 1024)
            val input = resp.body.byteStream()
            while (true) {
                coroutineContext.ensureActive()
                val n = input.read(chunk)
                if (n < 0) break
                // decode only the newest frame of each read
                parser.feed(chunk, n).lastOrNull()?.let { jpeg ->
                    BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)?.let { bmp -> withContext(Dispatchers.Main) { onFrame(bmp) } }
                }
            }
        }
    } finally {
        cancel.dispose()
    }
}
