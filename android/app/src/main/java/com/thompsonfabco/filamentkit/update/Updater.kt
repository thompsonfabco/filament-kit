package com.thompsonfabco.filamentkit.update

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ServerInfo
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** True when the server offers an APK whose versionCode ([apkVersion], as text) is above [current]. */
fun isNewer(apkVersion: String?, current: Int): Boolean {
    val offered = apkVersion?.trim()?.toIntOrNull() ?: return false
    return offered > current
}

/** Where updates come from; [of] adapts the real [Api]. */
interface UpdateSource {
    suspend fun info(): ServerInfo
    suspend fun downloadApk(to: File)

    companion object {
        fun of(api: Api): UpdateSource = object : UpdateSource {
            override suspend fun info() = api.info()
            override suspend fun downloadApk(to: File) = api.downloadApk(to)
        }
    }
}

/** Installs a downloaded APK; [ApkInstaller] is the PackageInstaller implementation. */
interface ApkInstall {
    /** The user has allowed this app to install apps ("install unknown apps"). */
    fun canInstall(): Boolean

    /** Opens the system screen where the user allows it. */
    fun requestPermission()

    suspend fun install(apk: File)

    /** True while the system's install confirmation waits for the user (it may not have opened by itself). */
    val confirmPending: Flow<Boolean>

    /** Opens the waiting install confirmation. */
    fun showConfirm()

    /** Why the last install failed, in words for the user; null when it did not. */
    val failure: Flow<String?>
}

/**
 * [available] is the newer versionCode the server offers (the "Update available" banner), or null.
 * [needsPermission] means the user was sent to allow "install unknown apps" and should tap Install again.
 */
data class UpdateUi(
    val available: Int? = null,
    /** The server's release, which the update comes with (`/api/info` `version`). */
    val offeredVersion: String? = null,
    val busy: Boolean = false,
    val needsPermission: Boolean = false,
    val error: String? = null,
    /** The download is done and the system confirmation is waiting: Home shows "Tap to install". */
    val confirmPending: Boolean = false,
    /** The server speaks a newer API than [SUPPORTED_API]: Home asks the user to update the app. */
    val serverTooNew: Boolean = false,
)

/** The server API version (`/api/info` `api`) this app understands. */
const val SUPPORTED_API = 1

/**
 * Checks the server for a newer APK when created and every [checkEveryMs] after; [install] downloads it to
 * [apkFile] and hands it to [installer]. A revoked token or a changed certificate goes to [onProblem] (the global
 * pairing router); other failures never crash: a failed check just shows no banner.
 */
class Updater(
    private val source: UpdateSource,
    private val installer: ApkInstall,
    private val currentVersion: Int,
    private val apkFile: File,
    private val onProblem: (Throwable) -> Unit,
    private val checkEveryMs: Long = DAY_MS,
) : ViewModel() {
    private val _state = MutableStateFlow(UpdateUi())
    val state: StateFlow<UpdateUi> = _state.asStateFlow()

    private var checkJob: Job? = null
    private var lastCheckOk = false

    init {
        viewModelScope.launch {
            while (isActive) {
                check()
                delay(checkEveryMs)
            }
        }
        viewModelScope.launch {
            installer.confirmPending.collect { pending -> _state.update { it.copy(confirmPending = pending) } }
        }
        viewModelScope.launch {
            installer.failure.collect { why -> if (why != null) _state.update { it.copy(error = why) } }
        }
    }

    /** Checks now (e.g. when the server becomes reachable again). */
    fun check() {
        if (checkJob?.isActive == true) return
        checkJob = viewModelScope.launch { runCheck() }
    }

    /** The server became reachable: check again only if the last check failed (no duplicate startup check). */
    fun onOnline() {
        if (!lastCheckOk) check()
    }

    /** "Tap to install": opens the waiting system confirmation. */
    fun confirmInstall() = installer.showConfirm()

    fun install() {
        val s = _state.value
        if (s.busy || s.available == null) return
        if (!installer.canInstall()) {
            _state.update { it.copy(needsPermission = true, error = null) }
            installer.requestPermission()
            return
        }
        _state.update { it.copy(busy = true, needsPermission = false, error = null) }
        viewModelScope.launch {
            try {
                apkFile.parentFile?.mkdirs()
                source.downloadApk(apkFile)
                installer.install(apkFile)
                _state.update { it.copy(busy = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                onProblem(e)
                _state.update { it.copy(busy = false, error = messageFor(e)) }
            }
        }
    }

    private suspend fun runCheck() {
        try {
            val info = source.info()
            val offered = info.apkVersion?.trim()?.toIntOrNull()
            _state.update {
                it.copy(
                    available = if (isNewer(info.apkVersion, currentVersion)) offered else null,
                    offeredVersion = info.version,
                    serverTooNew = info.api > SUPPORTED_API,
                )
            }
            lastCheckOk = true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            lastCheckOk = false
            onProblem(e)
        }
    }

    private fun messageFor(e: Exception): String = when {
        e is ApiError && e.code == "offline" -> "Could not reach the server. Check that you are on the same network."
        e is ApiError && e.code == "not_found" -> "The server has no app update to download."
        e is ApiError -> e.message
        e is FingerprintMismatch -> "The server's certificate changed."
        else -> "The update could not be installed."
    }

    private companion object {
        const val DAY_MS = 24L * 60 * 60 * 1000
    }
}
