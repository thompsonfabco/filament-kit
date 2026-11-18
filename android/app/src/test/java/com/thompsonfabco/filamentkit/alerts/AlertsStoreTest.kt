package com.thompsonfabco.filamentkit.alerts

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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AlertsStoreTest {
    private lateinit var dir: File
    private lateinit var scope: CoroutineScope
    private lateinit var store: AlertsStore

    @Before fun setUp() {
        dir = kotlin.io.path.createTempDirectory("alerts").toFile()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        store = AlertsStore(PreferenceDataStoreFactory.create(scope = scope) { File(dir, "alerts.preferences_pb") })
    }

    @After fun tearDown() {
        scope.cancel()
        dir.deleteRecursively()
    }

    @Test fun theSwitchIsOffUntilTheyTurnItOn() = runBlocking {
        assertFalse(store.isOn())
        store.setOn(true)
        assertTrue(store.isOn())
        store.setOn(false)
        assertFalse(store.on.first())
    }

    @Test fun theLastSeenEventIsKeptAndAnyChangeOfTheSwitchForgetsIt() = runBlocking {
        assertNull(store.lastSeen())
        store.setLastSeen(41)
        assertEquals(41L, store.lastSeen())
        store.setOn(true)
        assertNull("a new watch starts from now", store.lastSeen())
    }

    @Test fun dismissalsAreKeptWithTheirSeverityAndEvent() = runBlocking {
        store.dismiss("storage-low", AlertSeverity.Warn, 5)
        store.dismiss("event:9", AlertSeverity.Bad, 9)
        val d = store.dismissed.first()
        assertEquals(Dismissed(AlertSeverity.Warn, 5), d["storage-low"])
        assertEquals(Dismissed(AlertSeverity.Bad, 9), d["event:9"])
        store.dismiss("storage-low", AlertSeverity.Bad, 12)
        assertEquals(Dismissed(AlertSeverity.Bad, 12), store.dismissed.first()["storage-low"])
    }

    @Test fun onlyTheNewestHundredDismissalsStay() = runBlocking {
        for (i in 1L..105L) store.dismiss("event:$i", AlertSeverity.Warn, i)
        val d = store.dismissed.first()
        assertEquals(100, d.size)
        assertFalse("event:1" in d)
        assertTrue("event:105" in d)
    }
}
