package com.thompsonfabco.filamentkit.update

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.session.PairNotice
import com.thompsonfabco.filamentkit.session.PairRouter
import com.thompsonfabco.filamentkit.session.UNPAIRED_MESSAGE
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

@OptIn(ExperimentalCoroutinesApi::class)
class UpdaterTest {
    @get:Rule val tmp = TemporaryFolder()
    private val scheduler = TestCoroutineScheduler()

    @Before fun setUp() = Dispatchers.setMain(StandardTestDispatcher(scheduler))
    @After fun tearDown() = Dispatchers.resetMain()

    private class FakeSource(var apkVersion: String?) : UpdateSource {
        var infoCalls = 0
        var infoError: Exception? = null
        val downloads = mutableListOf<File>()
        override suspend fun info(): ServerInfo {
            infoCalls++
            infoError?.let { throw it }
            return ServerInfo("kit", "1.0", 1, apkVersion)
        }
        override suspend fun downloadApk(to: File) {
            downloads += to
            to.writeText("apk")
        }
    }

    private class FakeInstaller(var allowed: Boolean) : ApkInstall {
        var permissionRequests = 0
        val installed = mutableListOf<File>()
        override fun canInstall() = allowed
        override fun requestPermission() { permissionRequests++ }
        override suspend fun install(apk: File) { installed += apk }
        val pending = MutableStateFlow(false)
        var confirmsShown = 0
        override val confirmPending: Flow<Boolean> = pending
        override fun showConfirm() { confirmsShown++ }
    }

    private fun updater(source: UpdateSource, installer: ApkInstall = FakeInstaller(true), router: PairRouter = PairRouter()) =
        Updater(source, installer, currentVersion = 5, apkFile = File(tmp.root, "update.apk"), onProblem = router::report)

    @Test fun decidesOnNullEqualLowerHigherAndJunkVersions() {
        assertFalse(isNewer(null, 5))
        assertFalse(isNewer("5", 5))
        assertFalse(isNewer("4", 5))
        assertTrue(isNewer("6", 5))
        assertTrue(isNewer(" 12\n", 5))
        assertFalse(isNewer("six", 5))
        assertFalse(isNewer("", 5))
    }

    @Test fun noBannerWhenServerHasNoApk() {
        val u = updater(FakeSource(null))
        scheduler.runCurrent()
        assertNull(u.state.value.available)
    }

    @Test fun noBannerWhenServerHasSameVersion() {
        val u = updater(FakeSource("5"))
        scheduler.runCurrent()
        assertNull(u.state.value.available)
    }

    @Test fun bannerWhenServerHasHigherVersion() {
        val u = updater(FakeSource("7"))
        scheduler.runCurrent()
        assertEquals(7, u.state.value.available)
    }

    @Test fun checksOnStartAndAgainDaily() {
        val source = FakeSource("5")
        val u = updater(source)
        scheduler.runCurrent()
        assertEquals(1, source.infoCalls)
        source.apkVersion = "6"
        scheduler.advanceTimeBy(24 * 60 * 60 * 1000L + 1)
        scheduler.runCurrent()
        assertEquals(2, source.infoCalls)
        assertEquals(6, u.state.value.available)
    }

    @Test fun failedCheckShowsNoBannerAndDoesNotCrash() {
        val source = FakeSource("9").apply { infoError = ApiError(0, "offline", "Could not reach the server") }
        val router = PairRouter()
        val u = updater(source, router = router)
        scheduler.runCurrent()
        assertNull(u.state.value.available)
        assertNull(router.notice.value)
    }

    @Test fun unauthorizedFromUpdaterRoutesToPairWithMessage() {
        val source = FakeSource("9").apply { infoError = ApiError(401, "unauthorized", "Bad token") }
        val router = PairRouter()
        updater(source, router = router)
        scheduler.runCurrent()
        assertEquals(PairNotice.Unpaired, router.notice.value)
        assertEquals("This phone was unpaired from the server", UNPAIRED_MESSAGE)
        assertEquals(1, router.requests.value)
    }

    @Test fun mismatchFromUpdaterRoutesToPairWithBothFingerprints() {
        val source = FakeSource("9").apply { infoError = FingerprintMismatch("aa", "bb") }
        val router = PairRouter()
        updater(source, router = router)
        scheduler.runCurrent()
        assertEquals(PairNotice.CertChanged("aa", "bb"), router.notice.value)
    }

    @Test fun installAsksForUnknownAppsPermissionFirst() {
        val source = FakeSource("7")
        val installer = FakeInstaller(allowed = false)
        val u = updater(source, installer)
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertEquals(1, installer.permissionRequests)
        assertTrue(source.downloads.isEmpty())
        assertTrue(u.state.value.needsPermission)

        installer.allowed = true
        u.install()
        scheduler.runCurrent()
        assertEquals(1, installer.permissionRequests)
        assertEquals(listOf(File(tmp.root, "update.apk")), source.downloads)
        assertEquals(source.downloads, installer.installed)
        assertFalse(u.state.value.busy)
        assertFalse(u.state.value.needsPermission)
    }

    @Test fun startupCheckIsNotDuplicated() {
        val source = FakeSource("7")
        val u = updater(source)
        u.check()
        u.onOnline()
        scheduler.runCurrent()
        assertEquals(1, source.infoCalls)
        u.onOnline() // last check succeeded: nothing to do
        scheduler.runCurrent()
        assertEquals(1, source.infoCalls)
    }

    @Test fun comingOnlineRetriesAFailedCheck() {
        val source = FakeSource("7").apply { infoError = ApiError(0, "offline", "gone") }
        val u = updater(source)
        scheduler.runCurrent()
        assertNull(u.state.value.available)
        source.infoError = null
        u.onOnline()
        scheduler.runCurrent()
        assertEquals(2, source.infoCalls)
        assertEquals(7, u.state.value.available)
    }

    @Test fun waitingConfirmationShowsTapToInstall() {
        val installer = FakeInstaller(true)
        val u = updater(FakeSource("7"), installer)
        scheduler.runCurrent()
        assertFalse(u.state.value.confirmPending)
        installer.pending.value = true
        scheduler.runCurrent()
        assertTrue(u.state.value.confirmPending)
        u.confirmInstall()
        assertEquals(1, installer.confirmsShown)
        installer.pending.value = false
        scheduler.runCurrent()
        assertFalse(u.state.value.confirmPending)
    }
}
