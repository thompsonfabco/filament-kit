package com.thompsonfabco.filamentkit.data

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import java.io.File
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
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

    private val config = ServerConfig(listOf("kit.local", "192.168.1.5"), 8710, "ab".repeat(32), "tok-123", "Workshop server")

    @Test fun emptyByDefault() = runBlocking {
        assertNull(settings().server.first())
    }

    @Test fun saveRoundTrips() = runBlocking {
        val s = settings()
        s.save(config)
        assertEquals(config, s.server.first())
    }

    @Test fun theFingerprintCheckIsOnUntilTheUserSkipsIt() = runBlocking {
        val s = settings()
        assertFalse(s.skipsFingerprintCheck())
        s.setSkipFingerprintCheck(true)
        assertTrue(s.skipsFingerprintCheck())
        s.setSkipFingerprintCheck(false)
        assertFalse(s.skipsFingerprintCheck())
    }

    @Test fun forgettingAServerLeavesTheChoiceAboutTheCheck() = runBlocking {
        val s = settings()
        s.save(config)
        s.setSkipFingerprintCheck(true)
        s.clear()
        assertNull(s.server.first())
        assertTrue(s.skipsFingerprintCheck())
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

    @Test fun anUnknownStoredAppearanceIsSystem() = runBlocking {
        val store = PreferenceDataStoreFactory.create(scope = scope) { File(dir, "u.preferences_pb") }
        val s = Settings(store)
        for (bad in listOf("sepia", "Dark", "")) {
            store.edit { it[stringPreferencesKey("appearance")] = bad }
            assertEquals(bad, Appearance.System, s.appearance.first())
        }
    }

    @Test fun anUnreadableStoreGivesSystemAndUnpaired() = runBlocking {
        val broken = object : DataStore<Preferences> {
            override val data: Flow<Preferences> = flow { throw IOException("unreadable") }
            override suspend fun updateData(transform: suspend (Preferences) -> Preferences): Preferences = throw IOException("unreadable")
        }
        val s = Settings(broken)
        assertEquals(Appearance.System, s.appearance.first())
        assertNull(s.server.first())
    }

    @Test fun appearanceIsSystemUntilChosenAndKeepsTheChoice() = runBlocking {
        val s = settings()
        assertEquals(Appearance.System, s.appearance.first())
        s.setAppearance(Appearance.Dark)
        assertEquals(Appearance.Dark, s.appearance.first())
        s.setAppearance(Appearance.Light)
        assertEquals(Appearance.Light, s.appearance.first())
        s.setAppearance(Appearance.System)
        assertEquals(Appearance.System, s.appearance.first())
    }
}
