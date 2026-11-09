package com.thompsonfabco.filamentkit.ui.printers

import androidx.annotation.OptIn
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.ui.PlayerView
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.LocalNetwork
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/**
 * Plays the printer's HLS camera stream from [url] through the app's pinned [client] with [headers] (the Bearer
 * header). The player is released when this leaves composition.
 */
@OptIn(UnstableApi::class)
@Composable
fun HlsPlayer(client: OkHttpClient, url: String, headers: Map<String, String>, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    var error by remember(url) { mutableStateOf<String?>(null) }
    var hasPicture by remember(url) { mutableStateOf(false) }
    val player = remember(url) {
        // the server waits for the stream to start before answering the first playlist request
        val http = client.newBuilder().readTimeout(30, TimeUnit.SECONDS).build()
        val source = OkHttpDataSource.Factory(http).setDefaultRequestProperties(headers)
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(HlsMediaSource.Factory(source))
            .build()
            .apply {
                volume = 0f
                setMediaItem(MediaItem.fromUri(url))
                playWhenReady = true
                prepare()
            }
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onRenderedFirstFrame() {
                hasPicture = true
            }

            override fun onPlayerError(e: PlaybackException) {
                if (e.errorCode == PlaybackException.ERROR_CODE_BEHIND_LIVE_WINDOW) {
                    player.seekToDefaultPosition()
                    player.prepare()
                } else {
                    error = cameraErrorText(e)
                }
            }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }
    Box(modifier, contentAlignment = Alignment.Center) {
        AndroidView(
            factory = { PlayerView(it).apply { useController = false } },
            update = { it.player = player },
            onRelease = { it.player = null },
            modifier = Modifier.fillMaxSize(),
        )
        if (!hasPicture && error == null) Text(PrinterHelp.CAMERA_WAITING, color = Color.White)
        error?.let { msg ->
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text(msg, color = MaterialTheme.colorScheme.error)
                OutlinedButton(onClick = {
                    error = null
                    player.prepare()
                }) { Text("Try again") }
            }
        }
    }
}

/** A plain-English text for a playback failure; the server's error code is read from an HTTP error body. */
@OptIn(UnstableApi::class)
private fun cameraErrorText(e: PlaybackException): String {
    var cause: Throwable? = e
    while (cause != null) {
        if (cause is HttpDataSource.InvalidResponseCodeException) {
            val code = try {
                (Json.parseToJsonElement(String(cause.responseBody, Charsets.UTF_8)) as? JsonObject)
                    ?.get("error")?.jsonPrimitive?.content
            } catch (_: Exception) {
                null
            }
            return PrinterHelp.cameraFix(code ?: if (cause.responseCode == 401) "unauthorized" else "http_${cause.responseCode}")
        }
        cause = cause.cause
    }
    return if (LocalNetwork.missing()) LOCAL_NETWORK_MESSAGE else "The camera stream was interrupted. Tap Try again."
}
