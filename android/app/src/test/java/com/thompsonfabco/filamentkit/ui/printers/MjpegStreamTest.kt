package com.thompsonfabco.filamentkit.ui.printers

import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** A raw socket server so the test controls exactly when (if ever) bytes are sent. */
class MjpegStreamTest {
    private val server = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
    private val accepted = CountDownLatch(1)
    @Volatile private var socket: Socket? = null

    @After fun tearDown() {
        socket?.close()
        server.close()
    }

    private val uncaught = CopyOnWriteArrayList<Throwable>()
    private val handler = CoroutineExceptionHandler { _, e -> uncaught += e }

    private fun url() = "http://127.0.0.1:${server.localPort}/api/printers/X/camera.mjpeg"

    /** Answers one request with a 200 multipart header, then [body], then stays silent with the socket open. */
    private fun serve(body: ByteArray = ByteArray(0)) = Thread {
        val s = server.accept()
        socket = s
        val input = s.getInputStream()
        // read the request head
        var last4 = 0
        while (last4 != 0x0D0A0D0A) last4 = (last4 shl 8) or input.read()
        s.getOutputStream().apply {
            write(("HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n" +
                "Cache-Control: no-cache\r\n\r\n").toByteArray())
            write(body)
            flush()
        }
        accepted.countDown()
    }.apply { isDaemon = true; start() }

    @Test fun cancellingClosesTheConnectionPromptlyWhileTheServerIsSilent() = runBlocking {
        serve()
        val job = CoroutineScope(Dispatchers.Default + handler).launch {
            streamMjpeg(OkHttpClient(), url(), mapOf("Authorization" to "Bearer t")) { }
        }
        assertTrue(accepted.await(5, TimeUnit.SECONDS))
        Thread.sleep(200) // the client is now blocked reading a body that never comes
        val t0 = System.nanoTime()
        job.cancel()
        withTimeout(2000) { job.join() }
        // the server side sees the connection closed (EOF or reset), not a 30 s read timeout
        val s = socket!!
        s.soTimeout = 2000
        val closed = try {
            s.getInputStream().read() == -1
        } catch (_: SocketTimeoutException) {
            false
        } catch (_: java.io.IOException) {
            true
        }
        assertTrue("connection still open after cancel", closed)
        assertTrue("cancelling must not end the job with an error: $uncaught", uncaught.isEmpty())
        assertTrue(System.nanoTime() - t0 < TimeUnit.SECONDS.toNanos(3))
    }

    @Test fun deliversFrames() = runBlocking {
        val jpeg = byteArrayOf(1, 2, 3, 4)
        serve("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\n".toByteArray() + jpeg + "\r\n".toByteArray())
        val got = CopyOnWriteArrayList<ByteArray>()
        val job = CoroutineScope(Dispatchers.Default + handler).launch {
            streamMjpeg(OkHttpClient(), url(), emptyMap()) { got += it }
        }
        withTimeout(5000) { while (got.isEmpty()) kotlinx.coroutines.delay(20) }
        job.cancel()
        withTimeout(2000) { job.join() }
        assertTrue("$uncaught", uncaught.isEmpty())
        assertEquals(1, got.size)
        assertArrayEquals(jpeg, got[0])
    }
}
