package com.thompsonfabco.filamentkit.session

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.BuildConfig
import com.thompsonfabco.filamentkit.data.Settings
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.Discovery
import com.thompsonfabco.filamentkit.net.LocalNetwork
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.spool.ApiLoadBackend
import com.thompsonfabco.filamentkit.ui.spool.ApiSpoolBackend
import com.thompsonfabco.filamentkit.ui.spool.LoadViewModel
import com.thompsonfabco.filamentkit.ui.spool.SpoolViewModel
import com.thompsonfabco.filamentkit.update.ApkInstaller
import com.thompsonfabco.filamentkit.update.UpdateSource
import com.thompsonfabco.filamentkit.update.Updater
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** The two things read from the settings store before the first screen: the appearance and whether a Hub is paired. */
data class Startup(val appearance: Appearance, val paired: Boolean)

/** Activity-wide state: settings, the one [ServerSession], the pairing router and the drafts on disk. */
class AppViewModel(app: Application) : AndroidViewModel(app) {
    init {
        LocalNetwork.install(app) // before anything below can open a socket
    }

    val settings: Settings = Settings.create(app)
    val router = PairRouter()
    val discovery = Discovery(app)
    val session = ServerSession(
        viewModelScope, settings.server, settings::save, discovery::hosts, router,
        localNetworkGranted = { LocalNetwork.granted(app) },
    )
    val drafts = DraftStore(File(app.filesDir, "drafts"))

    /** The spool card, one per [ServerSession.api] (cleared when the pinned client changes or the server is forgotten). */
    val spool = ApiOwned(viewModelScope, session.api, SpoolViewModel::class) { SpoolViewModel(ApiSpoolBackend(it)) }

    /** "Load into printer" from the spool card, one per [ServerSession.api] like [spool]. */
    val load = ApiOwned(viewModelScope, session.api, LoadViewModel::class) { LoadViewModel(ApiLoadBackend(it)) }

    /** The update checker, one per [ServerSession.api]; its daily loop stops with the old client. */
    val updater = ApiOwned(viewModelScope, session.api, Updater::class) { api ->
        Updater(
            source = UpdateSource.of(api),
            installer = ApkInstaller(app),
            currentVersion = BuildConfig.VERSION_CODE,
            apkFile = File(app.cacheDir, "updates/filament-kit.apk"),
            onProblem = router::report,
            words = { app.getString(it.text) },
        )
    }

    private val _draftList = MutableStateFlow<List<Draft>>(emptyList())
    val draftList: StateFlow<List<Draft>> = _draftList.asStateFlow()

    init {
        purgeDrafts()
    }

    /** The last [PairRouter.pairAgainRequests] value the navigation host acted on (survives rotation). */
    var handledPairRequests = 0

    /** What the splash screen waits for: the stored pairing and appearance (null until both are read). */
    private val _startup = MutableStateFlow<Startup?>(null)
    val startup: StateFlow<Startup?> = _startup.asStateFlow()

    init {
        viewModelScope.launch {
            // a server is stored with a usable token: start on Home; none, or a revoked token: start on Pair
            _startup.value = Startup(settings.appearance.first(), settings.serverOrNull().isPaired())
        }
    }

    /** The user's choice from the top bar's appearance menu; applies at once. */
    fun setAppearance(appearance: Appearance) {
        viewModelScope.launch { settings.setAppearance(appearance) }
    }

    /** At start: delete expired, photo-less and unreadable drafts ([DraftStore.purge]), then show what is left. */
    private fun purgeDrafts() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { drafts.purge(DraftStore.MAX_AGE_MS) }
            refreshDrafts()
        }
    }

    /** Home → Discard (confirmed): delete the draft and its photos. */
    fun discardDraft(id: String) {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { drafts.delete(id) }
            refreshDrafts()
        }
    }

    fun refreshDrafts() {
        viewModelScope.launch(Dispatchers.IO) {
            _draftList.value = try {
                drafts.list().filter { it.photos.isNotEmpty() }.sortedByDescending { it.created }
            } catch (_: Exception) {
                emptyList()
            }
        }
    }

    override fun onCleared() {
        spool.close()
        load.close()
        updater.close()
    }

    /** Settings → Skip the fingerprint check for new servers. */
    fun setSkipFingerprintCheck(skip: Boolean) {
        viewModelScope.launch { settings.setSkipFingerprintCheck(skip) }
    }

    private val _trustFailed = MutableStateFlow(false)

    /** The last "Trust the new certificate" did not take effect; the notice that offered it says so. */
    val trustFailed: StateFlow<Boolean> = _trustFailed.asStateFlow()

    /** The notice that showed the failure is gone (or shows another certificate): the next one starts clean. */
    fun clearTrustFailed() {
        _trustFailed.value = false
    }

    /** Pair or a changed-certificate notice → Trust the new certificate; [then] runs only if the pin changed. */
    fun trustCertificate(expected: String, actual: String, then: () -> Unit = {}) {
        _trustFailed.value = false
        viewModelScope.launch {
            if (session.trustCertificate(expected, actual)) {
                router.clear()
                then()
            } else {
                _trustFailed.value = true
            }
        }
    }

    /** Settings → Forget server. */
    fun forget(then: () -> Unit) {
        viewModelScope.launch {
            settings.clear()
            router.clear()
            then()
        }
    }
}
