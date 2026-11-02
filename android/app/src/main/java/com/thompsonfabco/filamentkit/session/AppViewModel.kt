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
        )
    }

    private val _draftList = MutableStateFlow<List<Draft>>(emptyList())
    val draftList: StateFlow<List<Draft>> = _draftList.asStateFlow()

    /** The last [PairRouter.requests] value the navigation host acted on (survives rotation). */
    var handledPairRequests = 0

    /** True when a server is stored with a usable token (start on Home); false (none, or revoked) starts on Pair. */
    suspend fun isPaired(): Boolean = settings.server.first().isPaired()

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

    /** Settings → Forget server. */
    fun forget(then: () -> Unit) {
        viewModelScope.launch {
            settings.clear()
            router.clear()
            then()
        }
    }
}
