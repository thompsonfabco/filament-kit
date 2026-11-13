package com.thompsonfabco.filamentkit.nav

import androidx.annotation.StringRes
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.session.PairNotice
import com.thompsonfabco.filamentkit.session.isPaired
import com.thompsonfabco.filamentkit.ui.components.StatusKind

/** How the app stands with the Hub, as the connection chip and its sheet say it (05-android-app 2.4). */
internal enum class HubState(val badge: StatusKind?, @StringRes val sentence: Int) {
    /** Not known yet: the chip is a skeleton. */
    Checking(null, R.string.hub_state_checking),
    Connected(StatusKind.Connected, R.string.hub_state_connected),
    Offline(StatusKind.Offline, R.string.hub_state_offline),
    CertificateChanged(StatusKind.NeedsLook, R.string.hub_state_certificate),
    NoLongerPaired(StatusKind.NeedsLook, R.string.hub_state_unpaired),
    NeedsLocalNetwork(StatusKind.NeedsLook, R.string.hub_state_network),
}

/**
 * The state from the session's connection, the router's last reason to pair and the stored pairing. A 401 or a
 * certificate change never moves the user anywhere (05-android-app 2.7): it only changes this state.
 */
internal fun hubState(connection: Connection, notice: PairNotice?, config: ServerConfig?): HubState = when {
    config != null && !config.isPaired() -> HubState.NoLongerPaired
    notice is PairNotice.Unpaired -> HubState.NoLongerPaired
    notice is PairNotice.CertChanged || connection is Connection.CertChanged -> HubState.CertificateChanged
    else -> when (connection) {
        // nothing stored: no screen shows the chip; before the stored pairing reaches the session it is still unknown
        Connection.Unpaired -> HubState.Checking
        Connection.NeedsLocalNetwork -> HubState.NeedsLocalNetwork
        Connection.Checking -> HubState.Checking
        is Connection.Online -> HubState.Connected
        Connection.Offline -> HubState.Offline
        is Connection.CertChanged -> HubState.CertificateChanged
    }
}

/** Later checks keep the last known word on the chip while they run (05-android-app 2.4). */
internal fun keepLastKnown(previous: HubState?, now: HubState): HubState =
    if (now == HubState.Checking && previous != null) previous else now

/** `host:port` of the Hub as the sheet shows it: the host that answered, else the best stored one. */
fun hubAddress(connection: Connection, config: ServerConfig?): String {
    val cfg = config ?: return ""
    val host = (connection as? Connection.Online)?.host ?: cfg.endpoints.firstOrNull().orEmpty()
    return "${if (':' in host) "[$host]" else host}:${cfg.port}"
}

/**
 * Which Hub a pairing is: the certificate it is paired with. Addresses and port vary with how the pairing was made and
 * with DHCP; a reinstalled Hub has a new certificate. Pairing again with the same certificate is the same Hub. Null when
 * none is stored. (Trusting a new certificate is the same Hub by the user's say-so, not by this rule.)
 */
fun hubIdentity(config: ServerConfig?): String? = config?.fingerprint?.lowercase()
