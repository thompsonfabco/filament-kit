package com.thompsonfabco.filamentkit.session

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.data.Settings
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.Discovery
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** Activity-wide state: settings, the one [ServerSession], the pairing router and the drafts on disk. */
class AppViewModel(app: Application) : AndroidViewModel(app) {
    val settings: Settings = Settings.create(app)
    val router = PairRouter()
    val discovery = Discovery(app)
    val session = ServerSession(viewModelScope, settings.server, settings::save, discovery::hosts, router)
    val drafts = DraftStore(File(app.filesDir, "drafts"))

    private val _draftList = MutableStateFlow<List<Draft>>(emptyList())
    val draftList: StateFlow<List<Draft>> = _draftList.asStateFlow()

    /** The last [PairRouter.requests] value the navigation host acted on (survives rotation). */
    var handledPairRequests = 0

    /** True when a server is paired (start on Home), false to start on Pair. */
    suspend fun isPaired(): Boolean = settings.server.first() != null

    fun refreshDrafts() {
        viewModelScope.launch(Dispatchers.IO) {
            _draftList.value = try {
                drafts.list().filter { it.photos.isNotEmpty() }.sortedByDescending { it.created }
            } catch (_: Exception) {
                emptyList()
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
