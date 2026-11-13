package com.thompsonfabco.filamentkit.ui.printers

import androidx.annotation.OptIn
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
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
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.LocalNetwork
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/**
 * Plays the printer's HLS camera stream from [url] through the app's pinned [client] with [headers] (the Bearer
 * header). The player is released when this leaves composition; a failure is shown in place of the picture
 * (05-android-app 9.4).
 */
@OptIn(UnstableApi::class)
@Composable
fun HlsPlayer(
    client: OkHttpClient,
    url: String,
    headers: Map<String, String>,
    printerName: String,
    modifier: Modifier = Modifier,
    onPairAgain: () -> Unit = {},
) {
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
                    error = cameraErrorCode(e)
                }
            }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }
    val live = stringResource(R.string.a11y_camera, printerName)
    Box(modifier.semantics { contentDescription = live }, contentAlignment = Alignment.Center) {
        AndroidView(
            factory = { PlayerView(it).apply { useController = false } },
            update = { it.player = player },
            onRelease = { it.player = null },
            modifier = Modifier.fillMaxSize(),
        )
        if (!hasPicture && error == null) CameraWaiting()
        error?.let { code ->
            CameraFailure(code, onTryAgain = {
                error = null
                player.prepare()
            }, onPairAgain = onPairAgain)
        }
    }
}

/** The failure of a playback as a code of [cameraErrorText]: the Hub's error code read from an HTTP error body. */
@OptIn(UnstableApi::class)
private fun cameraErrorCode(e: PlaybackException): String {
    var cause: Throwable? = e
    while (cause != null) {
        if (cause is HttpDataSource.InvalidResponseCodeException) {
            if (cause.responseCode == UNAUTHORIZED_STATUS) return CAMERA_UNAUTHORIZED
            return try {
                (Json.parseToJsonElement(String(cause.responseBody, Charsets.UTF_8)) as? JsonObject)
                    ?.get("error")?.jsonPrimitive?.content ?: CAMERA_INTERRUPTED
            } catch (_: Exception) {
                CAMERA_INTERRUPTED
            }
        }
        cause = cause.cause
    }
    return if (LocalNetwork.missing()) CAMERA_LOCAL_NETWORK else CAMERA_INTERRUPTED
}

private const val UNAUTHORIZED_STATUS = 401
