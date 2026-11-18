package com.thompsonfabco.filamentkit.alerts

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AlertsFeedHubTest {
    private lateinit var dir: File
    private lateinit var scope: CoroutineScope
    private lateinit var store: AlertsStore

    @Before fun setUp() {
        dir = kotlin.io.path.createTempDirectory("alerts-hub").toFile()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        store = AlertsStore(PreferenceDataStoreFactory.create(scope = scope) { File(dir, "alerts.preferences_pb") })
    }

    @After fun tearDown() {
        scope.cancel()
        dir.deleteRecursively()
    }

    @Test fun withTheSwitchOffAnotherPairedHubForgetsTheDismissalsAndTheSameHubKeepsThem() = runBlocking {
        assertFalse(store.isOn())
        store.useHub("aa")
        store.dismiss("storage-low", AlertSeverity.Warn, 5)
        val hub = MutableStateFlow<String?>("aa")
        val feed = AlertsFeed(scope, { null }, store, hub = hub)
        withTimeout(5_000) { feed.state.first { it.dismissed.size == 1 } }
        hub.value = null
        hub.value = "aa"
        assertEquals("the same Hub keeps them", 1, store.dismissed.first().size)
        hub.value = "bb"
        withTimeout(5_000) { feed.state.first { it.dismissed.isEmpty() } }
        assertEquals(emptyMap<String, Dismissed>(), store.dismissed.first())
    }
}
