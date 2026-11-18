package com.thompsonfabco.filamentkit.alerts

import kotlinx.serialization.Serializable

/** `alerts`: the Alerts list (raised conditions, then the alert events of 7 days), on the stack of the selected tab. */
@Serializable data object AlertsRoute

/** Settings > Alerts. */
@Serializable data object SettingsAlertsRoute
