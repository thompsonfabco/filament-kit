package com.thompsonfabco.filamentkit.session

import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.update.ApkInstall
import com.thompsonfabco.filamentkit.update.UpdateFailure
import com.thompsonfabco.filamentkit.update.UpdateSource
import com.thompsonfabco.filamentkit.update.Updater
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.isActive
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ApiOwnedTest {
    private val scheduler = TestCoroutineScheduler()
    private val dispatcher = StandardTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    /** Stands for one pinned client: counts the calls made through it. */
    private class Client(val fingerprint: String) : UpdateSource {
        var calls = 0
        override suspend fun info(): ServerInfo {
            calls++
            return ServerInfo("kit", "1", 1, "1")
        }
        override suspend fun downloadApk(to: File, onProgress: (Long, Long) -> Unit) = Unit
    }

    private object NoInstall : ApkInstall {
        override fun canInstall() = true
        override fun requestPermission() = Unit
        override suspend fun install(apk: File) = Unit
        override val confirmPending: Flow<Boolean> = flowOf(false)
        override fun showConfirm() = Unit
        override val failure: Flow<UpdateFailure?> = flowOf(null)
    }

    private val day = 24L * 60 * 60 * 1000

    @Test fun fingerprintChangeCancelsTheOldUpdaterAndNoCallUsesTheOldClient() {
        val old = Client("aa")
        val new = Client("bb")
        val apis = MutableStateFlow<Client?>(old)
        val owned = ApiOwned(CoroutineScope(dispatcher), apis, Updater::class) { client ->
            Updater(client, NoInstall, currentVersion = 1, apkFile = File("unused.apk"), onProblem = {}, words = { it.name })
        }
        scheduler.runCurrent()
        val first = owned.current.value!!
        assertEquals(1, old.calls)

        apis.value = new
        scheduler.runCurrent()
        val second = owned.current.value!!
        assertNotSame(first, second)
        assertFalse(first.viewModelScope.isActive)
        assertTrue(second.viewModelScope.isActive)

        scheduler.advanceTimeBy(3 * day)
        scheduler.runCurrent()
        assertEquals(1, old.calls) // the old daily loop is gone
        assertEquals(4, new.calls) // start + 3 daily checks, all on the new client
        first.check()
        scheduler.runCurrent()
        assertEquals(1, old.calls) // a cleared updater cannot call the old client
    }

    @Test fun forgettingTheServerClearsTheInstance() {
        val client = Client("aa")
        val apis = MutableStateFlow<Client?>(client)
        val owned = ApiOwned(CoroutineScope(dispatcher), apis, Updater::class) { c ->
            Updater(c, NoInstall, currentVersion = 1, apkFile = File("unused.apk"), onProblem = {}, words = { it.name })
        }
        scheduler.runCurrent()
        val first = owned.current.value!!
        apis.value = null
        scheduler.runCurrent()
        assertNull(owned.current.value)
        assertFalse(first.viewModelScope.isActive)
    }
}
