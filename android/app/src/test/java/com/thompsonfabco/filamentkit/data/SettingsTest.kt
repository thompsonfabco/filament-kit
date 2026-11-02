package com.thompsonfabco.filamentkit.data

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class SettingsTest {
    private lateinit var dir: File
    private lateinit var scope: CoroutineScope

    @Before fun setUp() {
        dir = kotlin.io.path.createTempDirectory("settings").toFile()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }

    @After fun tearDown() {
        scope.cancel()
        dir.deleteRecursively()
    }

    private fun settings(): Settings {
        val store = PreferenceDataStoreFactory.create(scope = scope) { File(dir, "s.preferences_pb") }
        return Settings(store)
    }

    private val config = ServerConfig(listOf("pat.local", "192.168.1.5"), 8710, "ab".repeat(32), "tok-123", "Workshop server")

    @Test fun emptyByDefault() = runBlocking {
        assertNull(settings().server.first())
    }

    @Test fun saveRoundTrips() = runBlocking {
        val s = settings()
        s.save(config)
        assertEquals(config, s.server.first())
    }

    @Test fun saveReplacesAndClearRemoves() = runBlocking {
        val s = settings()
        s.save(config)
        val changed = config.copy(endpoints = listOf("other.local"), token = "new")
        s.save(changed)
        assertEquals(changed, s.server.first())
        s.clear()
        assertNull(s.server.first())
    }
}
