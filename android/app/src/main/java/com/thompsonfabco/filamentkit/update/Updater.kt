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

/** Whole percent of [total] done, or null when the server sent no length. */
fun percent(done: Long, total: Long): Int? =
    if (total <= 0) null else (done.coerceIn(0, total) * 100 / total).toInt()

/** Where updates come from; [of] adapts the real [Api]. */
interface UpdateSource {
    suspend fun info(): ServerInfo
    /** [onProgress]: (bytes so far, total or -1 when unknown). */
    suspend fun downloadApk(to: File, onProgress: (Long, Long) -> Unit)

    companion object {
        fun of(api: Api): UpdateSource = object : UpdateSource {
            override suspend fun info() = api.info()
            override suspend fun downloadApk(to: File, onProgress: (Long, Long) -> Unit) = api.downloadApk(to, onProgress)
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

    /** Why the last install failed; null when it did not. */
    val failure: Flow<UpdateFailure?>
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
    /** How much of the APK is downloaded, 0-100, while [busy]; null before the first bytes or with no known size. */
    val progress: Int? = null,
    val needsPermission: Boolean = false,
    /** The last failure in words (Home shows this); [failure] is the same thing as a value the update panel maps. */
    val error: String? = null,
    val failure: UpdateFailure? = null,
    /** The download is done and the system confirmation is waiting: Home shows "Tap to install". */
    val confirmPending: Boolean = false,
    /** The server speaks a newer API than [SUPPORTED_API]: Home asks the user to update the app. */
    val serverTooNew: Boolean = false,
    /** A check the person asked for is running ("Check for updates" says "Checking…"). */
    val checking: Boolean = false,
    /** The last check reached the Hub: only then is "This app is up to date." true. */
    val checked: Boolean = false,
    /** The install was handed to Android and its window has not been left yet: "Tap Install in the window Android shows." */
    val installing: Boolean = false,
    /** The download is done and the APK is being handed to Android: it cannot be cancelled any more. */
    val writing: Boolean = false,
)

/** The server API version (`/api/info` `api`) this app understands. */
const val SUPPORTED_API = 1

/**
 * Checks the server for a newer APK when created and every [checkEveryMs] after; [install] downloads it to
 * [apkFile] and hands it to [installer]. A revoked token or a changed certificate goes to [onProblem] (the global
 * pairing router); other failures never crash: a failed check just shows no banner. [words] puts a failure in words
 * for [UpdateUi.error].
 */
class Updater(
    private val source: UpdateSource,
    private val installer: ApkInstall,
    private val currentVersion: Int,
    private val apkFile: File,
    private val onProblem: (Throwable) -> Unit,
    private val words: (UpdateFailure) -> String,
    private val checkEveryMs: Long = DAY_MS,
) : ViewModel() {
    private val _state = MutableStateFlow(UpdateUi())
    val state: StateFlow<UpdateUi> = _state.asStateFlow()

    private var checkJob: Job? = null
    private var installJob: Job? = null
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
            installer.failure.collect { why -> if (why != null) _state.update { it.failed(why) } }
        }
    }

    /** Checks now (e.g. when the server becomes reachable again). */
    fun check() {
        if (checkJob?.isActive == true) return
        checkJob = viewModelScope.launch { runCheck() }
    }

    /** "Check for updates": like [check], and the screen shows "Checking…" and a failure of the check itself. */
    fun checkNow() {
        if (checkJob?.isActive == true) return
        _state.update {
            val keep = it.failure != null && it.failure !in CHECK_FAILURES
            it.copy(checking = true, error = if (keep) it.error else null, failure = it.failure.takeIf { keep })
        }
        checkJob = viewModelScope.launch {
            try {
                runCheck(asked = true)
            } finally {
                _state.update { it.copy(checking = false) }
            }
        }
    }

    /** "Cancel" while downloading; not once the APK is being handed to Android ([UpdateUi.writing]). */
    fun cancel() {
        if (_state.value.writing) return
        installJob?.cancel()
        _state.update { it.copy(busy = false, progress = null) }
    }

    /** "Open settings": the system page where this app is allowed to install apps. */
    fun openPermissionSettings() = installer.requestPermission()

    /** The server became reachable: check again only if the last check failed (no duplicate startup check). */
    fun onOnline() {
        if (!lastCheckOk) check()
    }

    /**
     * Back on screen: drop the "allow, then tap Install" reminder once the permission is there, and treat Android's
     * install window as left: if it still waits for an answer, the panel offers "Tap to install".
     */
    fun onResumed() {
        if (_state.value.needsPermission && installer.canInstall()) _state.update { it.copy(needsPermission = false) }
        if (_state.value.installing) _state.update { it.copy(installing = false) }
    }

    /** "Tap to install": opens the waiting system confirmation. */
    fun confirmInstall() = installer.showConfirm()

    fun install() {
        val s = _state.value
        if (s.busy || s.available == null) return
        if (!installer.canInstall()) {
            _state.update { it.copy(needsPermission = true, error = null, failure = null) }
            installer.requestPermission()
            return
        }
        _state.update {
            it.copy(busy = true, progress = null, needsPermission = false, error = null, failure = null, installing = false)
        }
        // a cancelled download may still be unwinding; this one starts when it has finished with the files
        val previous = installJob
        installJob = viewModelScope.launch {
            previous?.join()
            try {
                apkFile.parentFile?.mkdirs()
                source.downloadApk(apkFile) { done, total ->
                    val pct = percent(done, total)
                    if (pct != _state.value.progress) _state.update { it.copy(progress = pct) }
                }
                _state.update { it.copy(writing = true) }
                installer.install(apkFile)
                _state.update { it.copy(busy = false, progress = null, installing = true, writing = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                onProblem(e)
                _state.update { it.failed(failureFor(e, checking = false)).copy(busy = false, progress = null, writing = false) }
            } finally {
                // the session holds its own copy once committed; a partial or failed download is no use either
                apkFile.delete()
            }
        }
    }

    private suspend fun runCheck(asked: Boolean = false) {
        try {
            val info = source.info()
            val offered = info.apkVersion?.trim()?.toIntOrNull()
            _state.update {
                it.copy(
                    available = if (isNewer(info.apkVersion, currentVersion)) offered else null,
                    offeredVersion = info.version,
                    serverTooNew = info.api > SUPPORTED_API,
                    checked = true,
                    // the Hub answered: a failure of reaching it is over (an install failure stays until the next try)
                    failure = it.failure?.takeUnless { f -> f in CHECK_FAILURES },
                    error = if (it.failure in CHECK_FAILURES) null else it.error,
                )
            }
            lastCheckOk = true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            lastCheckOk = false
            onProblem(e)
            if (asked) _state.update { it.failed(failureFor(e, checking = true)) }
        }
    }

    private fun UpdateUi.failed(why: UpdateFailure) = copy(failure = why, error = words(why), installing = false)

    private fun failureFor(e: Exception, checking: Boolean): UpdateFailure = when {
        e is ApiError && e.code == "local_network" -> UpdateFailure.LocalNetwork
        e is ApiError && e.code == "offline" -> UpdateFailure.HubUnreachable
        e is ApiError && e.code == "not_found" -> UpdateFailure.NoUpdate
        e is ApiError && e.code == "storage" -> UpdateFailure.Storage
        e is FingerprintMismatch -> UpdateFailure.CertificateChanged
        checking -> UpdateFailure.CheckFailed
        else -> UpdateFailure.Generic
    }

    private companion object {
        /** The failures a later check that reaches the Hub puts right. */
        val CHECK_FAILURES = setOf(
            UpdateFailure.HubUnreachable, UpdateFailure.LocalNetwork, UpdateFailure.CheckFailed, UpdateFailure.CertificateChanged,
        )

        const val DAY_MS = 24L * 60 * 60 * 1000
    }
}
