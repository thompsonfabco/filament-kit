package com.thompsonfabco.filamentkit.nav

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.session.PairNotice
import com.thompsonfabco.filamentkit.ui.components.StatusKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The connection state the chip and its sheet show, from what the session and the router know. */
class HubStateTest {
    private val paired = ServerConfig(listOf("192.0.2.10"), 8710, "ab", "token", "Workshop hub")
    private val revoked = paired.copy(token = "")

    private fun state(connection: Connection, notice: PairNotice? = null, config: ServerConfig? = paired) =
        hubState(connection, notice, config)

    @Test fun eachConnectionHasItsWordAndShape() {
        assertEquals(HubState.Connected, state(Connection.Online("192.0.2.10")))
        assertEquals(StatusKind.Connected, HubState.Connected.badge)
        assertEquals(R.string.status_connected, StatusKind.Connected.word)
        assertEquals(R.drawable.sw_st_filled, StatusKind.Connected.shape)

        assertEquals(HubState.Offline, state(Connection.Offline))
        assertEquals(StatusKind.Offline, HubState.Offline.badge)
        assertEquals(R.string.status_offline, StatusKind.Offline.word)
        assertEquals(R.drawable.sw_st_hollow, StatusKind.Offline.shape)

        assertEquals(HubState.CertificateChanged, state(Connection.CertChanged("a", "b")))
        assertEquals(HubState.NeedsLocalNetwork, state(Connection.NeedsLocalNetwork))
        for (needsALook in listOf(HubState.CertificateChanged, HubState.NoLongerPaired, HubState.NeedsLocalNetwork)) {
            assertEquals(StatusKind.NeedsLook, needsALook.badge)
        }
        assertEquals(R.string.status_needs_look, StatusKind.NeedsLook.word)
        assertEquals(R.drawable.sw_st_triangle, StatusKind.NeedsLook.shape)
    }

    @Test fun beforeTheFirstAnswerThereIsNoWordAndNoShape() {
        assertEquals(HubState.Checking, state(Connection.Checking))
        assertNull(HubState.Checking.badge)
        assertEquals("nothing stored yet is not a state to show", HubState.Checking, state(Connection.Unpaired, config = null))
    }

    @Test fun a401OrAChangedCertificateOnlyChangesTheState() {
        assertEquals(HubState.NoLongerPaired, state(Connection.Online("192.0.2.10"), PairNotice.Unpaired("token")))
        assertEquals(HubState.NoLongerPaired, state(Connection.Online("192.0.2.10"), config = revoked))
        assertEquals(HubState.CertificateChanged, state(Connection.Online("192.0.2.10"), PairNotice.CertChanged("a", "b")))
        assertEquals("a new pairing clears the notice", HubState.Connected, state(Connection.Online("192.0.2.10"), null))
    }

    @Test fun aLaterCheckKeepsTheLastKnownWord() {
        assertEquals(HubState.Offline, keepLastKnown(HubState.Offline, HubState.Checking))
        assertEquals(HubState.Connected, keepLastKnown(HubState.Offline, HubState.Connected))
        assertEquals("the first check has nothing to keep", HubState.Checking, keepLastKnown(HubState.Checking, HubState.Checking))
        assertEquals(HubState.Checking, keepLastKnown(null, HubState.Checking))
    }

    @Test fun theAddressIsTheHostThatAnsweredWithItsPort() {
        assertEquals("192.0.2.77:8710", hubAddress(Connection.Online("192.0.2.77"), paired))
        assertEquals("192.0.2.10:8710", hubAddress(Connection.Offline, paired))
        assertEquals("[2001:db8::1]:8710", hubAddress(Connection.Online("2001:db8::1"), paired))
        assertEquals("", hubAddress(Connection.Offline, null))
    }
}
