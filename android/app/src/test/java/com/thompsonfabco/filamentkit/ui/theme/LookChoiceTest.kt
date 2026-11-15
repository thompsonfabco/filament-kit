package com.thompsonfabco.filamentkit.ui.theme

import com.thompsonfabco.filamentkit.net.ServerInfo
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** S6.3: which look the app draws (05-android-app 12.2, 08-platform-mapping 9). */
class LookChoiceTest {
    private val all = Look.entries

    @Test fun theStoredChoiceWinsOverTheHubsLook() {
        assertEquals(Look.Palette, resolveLook(chosen = Look.Palette, hub = Look.Workbench, built = all))
        assertEquals("even when the Hub's look is Console", Look.Panes, resolveLook(Look.Panes, Look.Console, all))
    }

    @Test fun withNoStoredChoiceTheHubsLookIsUsed() {
        assertEquals(Look.Workbench, resolveLook(chosen = null, hub = Look.Workbench, built = all))
    }

    @Test fun withNeitherTheLookIsConsole() {
        assertEquals("the Hub was never reached at first start", Look.Console, resolveLook(null, null, all))
        assertEquals(Look.Console, resolveLook(null, null))
    }

    @Test fun aLookWithNoBuiltLayoutIsNotDrawn() {
        assertEquals(listOf(Look.Console), BUILT_LOOKS)
        assertEquals(Look.Console, resolveLook(chosen = null, hub = Look.Palette))
        assertEquals(Look.Console, resolveLook(chosen = Look.Panes, hub = null))
        assertEquals("the Hub's look is the fallback of an unbuilt choice", Look.Workbench, resolveLook(Look.Panes, Look.Workbench, listOf(Look.Console, Look.Workbench)))
    }

    @Test fun lookNamesAreTheHubsWords() {
        assertEquals(listOf("console", "workbench", "palette", "panes"), all.map { it.wire })
        all.forEach { assertEquals(it, lookFromWire(it.wire)) }
        assertNull(lookFromWire(null))
        assertNull(lookFromWire(""))
        assertNull(lookFromWire("Console"))
        assertNull(lookFromWire("sepia"))
    }

    @Test fun theInfoAnswerCarriesTheHubsLook() {
        val json = Json { ignoreUnknownKeys = true }
        val info = json.decodeFromString<ServerInfo>("""{"name":"W","version":"0.5.3","api":1,"look":"palette"}""")
        assertEquals(Look.Palette, lookFromWire(info.look))
        val old = json.decodeFromString<ServerInfo>("""{"name":"W","version":"0.5.3","api":1}""")
        assertNull("an older Hub says nothing", lookFromWire(old.look))
    }
}
