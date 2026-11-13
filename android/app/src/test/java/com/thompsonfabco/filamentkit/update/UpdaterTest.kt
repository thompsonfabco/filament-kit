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

    @Test fun aFailedInstallStaysOnTheBannerUntilTheNextTry() {
        val installer = FakeInstaller(allowed = true)
        val u = updater(FakeSource("7"), installer)
        scheduler.runCurrent()
        installer.failure.value = UpdateFailure.Signature
        scheduler.runCurrent()
        assertEquals(UpdateFailure.Signature, u.state.value.failure)
        assertEquals("Signature", u.state.value.error)
        u.install()
        assertNull("a new try starts clean", u.state.value.error)
        assertNull(u.state.value.failure)
        scheduler.runCurrent()
    }

    @Test fun theDownloadedApkIsDeletedOnceHandedToTheInstaller() {
        val installer = FakeInstaller(allowed = true)
        val u = updater(FakeSource("7"), installer)
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertEquals(1, installer.installed.size)
        assertFalse(installer.installed.single().exists())
    }

    @Test fun theOfferedReleaseComesFromTheServer() {
        val u = updater(FakeSource("7"), FakeInstaller(allowed = true))
        scheduler.runCurrent()
        assertEquals("1.0", u.state.value.offeredVersion)
    }

    private class FakeSource(var apkVersion: String?, var api: Int = 1) : UpdateSource {
        var infoCalls = 0
        var infoError: Exception? = null
        val downloads = mutableListOf<File>()
        var downloadError: Exception? = null
        /** Called with the number of the download (1, 2, ...); may suspend to keep a download running. */
        var downloadHook: (suspend (Int) -> Unit)? = null
        override suspend fun info(): ServerInfo {
            infoCalls++
            infoError?.let { throw it }
            return ServerInfo("kit", "1.0", api, apkVersion)
        }
        var steps: List<Pair<Long, Long>> = emptyList()
        val seen = mutableListOf<Int?>()
        var watch: (() -> Int?)? = null
        override suspend fun downloadApk(to: File, onProgress: (Long, Long) -> Unit) {
            downloads += to
            downloadError?.let { throw it }
            downloadHook?.invoke(downloads.size)
            steps.forEach { (d, t) -> onProgress(d, t); seen += watch?.invoke() }
            to.writeText("apk")
        }
    }

    private class FakeInstaller(var allowed: Boolean) : ApkInstall {
        var permissionRequests = 0
        val installed = mutableListOf<File>()
        override fun canInstall() = allowed
        override fun requestPermission() { permissionRequests++ }
        var installGate: (suspend () -> Unit)? = null
        override suspend fun install(apk: File) { installGate?.invoke(); installed += apk }
        val pending = MutableStateFlow(false)
        var confirmsShown = 0
        override val confirmPending: Flow<Boolean> = pending
        override fun showConfirm() { confirmsShown++ }
        override val failure = MutableStateFlow<UpdateFailure?>(null)
    }

    private fun updater(source: UpdateSource, installer: ApkInstall = FakeInstaller(true), router: PairRouter = PairRouter()) =
        Updater(source, installer, currentVersion = 5, apkFile = File(tmp.root, "update.apk"), onProblem = router::report, words = { it.name })

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

    @Test fun aServerWithANewerApiAsksForAnAppUpdate() {
        val u = updater(FakeSource("7", api = SUPPORTED_API + 1))
        scheduler.runCurrent()
        assertTrue(u.state.value.serverTooNew)
        assertEquals(7, u.state.value.available)

        val same = updater(FakeSource(null, api = SUPPORTED_API))
        scheduler.runCurrent()
        assertFalse(same.state.value.serverTooNew)
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
        assertTrue(router.notice.value is PairNotice.Unpaired)
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

    @Test fun theDownloadReportsWholePercentsAndClearsWhenDone() {
        val source = FakeSource("7")
        source.steps = listOf(0L to 1000L, 5L to 1000L, 420L to 1000L, 1000L to 1000L)
        val u = updater(source)
        source.watch = { u.state.value.progress }
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertEquals(listOf(0, 0, 42, 100), source.seen)
        assertNull("cleared after the install starts", u.state.value.progress)
        assertFalse(u.state.value.busy)
    }

    @Test fun noLengthMeansNoPercent() {
        val source = FakeSource("7")
        source.steps = listOf(500L to -1L)
        val u = updater(source)
        source.watch = { u.state.value.progress }
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertEquals(listOf<Int?>(null), source.seen)
    }

    @Test fun percentIsClampedAndWhole() {
        assertEquals(33, percent(1, 3))
        assertEquals(100, percent(5000, 1000))
        assertNull(percent(1, 0))
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

    @Test fun theReminderGoesWhenThePermissionIsGivenAndOnlyThen() {
        val installer = FakeInstaller(false)
        val u = updater(FakeSource("7"), installer)
        u.check()
        scheduler.runCurrent()
        u.install()
        u.onResumed()
        assertTrue(u.state.value.needsPermission)
        installer.allowed = true
        u.onResumed()
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

    @Test fun anAskedCheckSaysCheckingThenUpToDate() {
        val u = updater(FakeSource("5"))
        scheduler.runCurrent()
        assertTrue("the startup check reached the Hub", u.state.value.checked)
        u.checkNow()
        assertTrue(u.state.value.checking)
        scheduler.runCurrent()
        assertFalse(u.state.value.checking)
        assertNull(u.state.value.failure)
        assertTrue(u.state.value.checked)
    }

    @Test fun anAskedCheckThatCannotReachTheHubSaysSo() {
        val source = FakeSource("7")
        val u = updater(source)
        scheduler.runCurrent()
        source.infoError = ApiError(0, "offline", "gone")
        u.checkNow()
        scheduler.runCurrent()
        assertEquals(UpdateFailure.HubUnreachable, u.state.value.failure)
        assertFalse(u.state.value.checking)
        // the startup and daily checks stay quiet
        val quiet = updater(FakeSource("7").apply { infoError = ApiError(0, "offline", "gone") })
        scheduler.runCurrent()
        assertNull(quiet.state.value.failure)
        assertFalse(quiet.state.value.checked)
    }

    @Test fun eachDownloadFailureHasItsOwnLine() {
        val cases = listOf(
            ApiError(0, "offline", "x") to UpdateFailure.HubUnreachable,
            ApiError(404, "not_found", "x") to UpdateFailure.NoUpdate,
            ApiError(0, "storage", "x") to UpdateFailure.Storage,
            FingerprintMismatch("aa", "bb") to UpdateFailure.CertificateChanged,
            ApiError(500, "boom", "x") to UpdateFailure.Generic,
        )
        for ((error, expected) in cases) {
            val source = FakeSource("7").apply { downloadError = error }
            val u = updater(source)
            scheduler.runCurrent()
            u.install()
            scheduler.runCurrent()
            assertEquals(expected, u.state.value.failure)
            assertEquals(expected.name, u.state.value.error)
            assertFalse(u.state.value.busy)
        }
    }

    @Test fun cancelStopsTheDownloadAndGoesBackToTheOffer() {
        val installer = FakeInstaller(true)
        val u = updater(FakeSource("7"), installer)
        scheduler.runCurrent()
        u.install()
        assertTrue(u.state.value.busy)
        u.cancel()
        scheduler.runCurrent()
        assertFalse(u.state.value.busy)
        assertTrue("nothing was handed to Android", installer.installed.isEmpty())
        assertNull(u.state.value.failure)
        assertEquals(7, u.state.value.available)
    }

    @Test fun theInstallWindowIsOpenUntilTheAppIsBackOnScreen() {
        val u = updater(FakeSource("7"), FakeInstaller(true))
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertTrue(u.state.value.installing)
        u.onResumed()
        assertFalse(u.state.value.installing)
    }

    @Test fun aFailureEndsTheInstallingStep() {
        val installer = FakeInstaller(true)
        val u = updater(FakeSource("7"), installer)
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        installer.failure.value = UpdateFailure.Storage
        scheduler.runCurrent()
        assertFalse(u.state.value.installing)
        assertEquals(UpdateFailure.Storage, u.state.value.failure)
    }

    @Test fun cancelStopsADownloadThatIsRunning() {
        val events = mutableListOf<String>()
        val source = FakeSource("7").apply {
            downloadHook = { n ->
                events += "start$n"
                try { kotlinx.coroutines.awaitCancellation() } finally { events += "end$n" }
            }
        }
        val u = updater(source)
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertEquals(listOf("start1"), events)
        assertTrue(u.state.value.busy)
        u.cancel()
        scheduler.runCurrent()
        assertEquals(listOf("start1", "end1"), events)
        assertFalse(u.state.value.busy)
    }

    @Test fun installWhileACancelledDownloadUnwindsWaitsForIt() {
        val events = mutableListOf<String>()
        val source = FakeSource("7").apply {
            downloadHook = { n ->
                events += "start$n"
                if (n == 1) {
                    try { kotlinx.coroutines.awaitCancellation() } finally {
                        kotlinx.coroutines.withContext(kotlinx.coroutines.NonCancellable) { kotlinx.coroutines.yield() }
                        events += "end$n"
                    }
                }
            }
        }
        val u = updater(source)
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        u.cancel()
        u.install() // before the first one has finished unwinding
        scheduler.runCurrent()
        assertEquals(listOf("start1", "end1", "start2"), events)
        assertEquals(2, source.downloads.size)
    }

    @Test fun cancelIsRefusedWhileTheApkIsHandedToAndroid() {
        val gate = kotlinx.coroutines.CompletableDeferred<Unit>()
        val installer = FakeInstaller(true).apply { installGate = { gate.await() } }
        val u = updater(FakeSource("7"), installer)
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertTrue(u.state.value.writing)
        u.cancel()
        scheduler.runCurrent()
        assertTrue("the commit goes on", u.state.value.busy)
        gate.complete(Unit)
        scheduler.runCurrent()
        assertEquals(1, installer.installed.size)
        assertFalse(u.state.value.writing)
        assertTrue(u.state.value.installing)
    }

    @Test fun theLocalNetworkPermissionHasItsOwnLine() {
        val source = FakeSource("7").apply { downloadError = ApiError(0, "local_network", "x") }
        val u = updater(source)
        scheduler.runCurrent()
        u.install()
        scheduler.runCurrent()
        assertEquals(UpdateFailure.LocalNetwork, u.state.value.failure)
    }

    @Test fun aCheckThatFailsSaysTheCheckFailedNotTheInstall() {
        val source = FakeSource("7")
        val u = updater(source)
        scheduler.runCurrent()
        source.infoError = ApiError(500, "boom", "x")
        u.checkNow()
        scheduler.runCurrent()
        assertEquals(UpdateFailure.CheckFailed, u.state.value.failure)
        source.infoError = ApiError(0, "local_network", "x")
        u.checkNow()
        scheduler.runCurrent()
        assertEquals(UpdateFailure.LocalNetwork, u.state.value.failure)
    }

    @Test fun aCheckThatReachesTheHubClearsAFailureOfReachingIt() {
        val source = FakeSource("7")
        val u = updater(source)
        scheduler.runCurrent()
        source.infoError = ApiError(0, "offline", "gone")
        u.checkNow()
        scheduler.runCurrent()
        assertEquals(UpdateFailure.HubUnreachable, u.state.value.failure)
        source.infoError = null
        u.checkNow()
        scheduler.runCurrent()
        assertNull(u.state.value.failure)
        assertNull(u.state.value.error)
    }

    @Test fun anInstallFailureSurvivesALaterCheck() {
        val installer = FakeInstaller(true)
        val u = updater(FakeSource("7"), installer)
        scheduler.runCurrent()
        installer.failure.value = UpdateFailure.Signature
        scheduler.runCurrent()
        u.checkNow()
        scheduler.runCurrent()
        assertEquals(UpdateFailure.Signature, u.state.value.failure)
    }
}
