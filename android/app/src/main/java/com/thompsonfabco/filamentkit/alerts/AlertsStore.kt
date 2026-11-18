package com.thompsonfabco.filamentkit.alerts

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/**
 * What this phone keeps for alerts (R80 E4: the switch is stored on the device, the Hub stores nothing about it): the
 * switch "Alerts on this phone", the last event the watching service has seen, and the banners this phone dismissed.
 * Its own DataStore, so the pairing's store is never touched.
 */
class AlertsStore(private val store: DataStore<Preferences>) : CursorStore {
    /** Off until the person turns it on. */
    val on: Flow<Boolean> = store.data.catch { if (it is IOException) emit(androidx.datastore.preferences.core.emptyPreferences()) else throw it }
        .map { it[ON] ?: false }

    suspend fun isOn(): Boolean = try {
        on.first()
    } catch (_: IOException) {
        false
    }

    /** Any change of the switch forgets the cursor: the next watch starts from "now", with no old alerts. */
    suspend fun setOn(on: Boolean) {
        store.edit {
            it[ON] = on
            it.remove(LAST_SEEN)
        }
    }

    override suspend fun lastSeen(): Long? = try {
        store.data.first()[LAST_SEEN]
    } catch (_: IOException) {
        null
    }

    override suspend fun setLastSeen(id: Long) {
        store.edit { it[LAST_SEEN] = id }
    }

    /** The banners dismissed here, by key. */
    val dismissed: Flow<Map<String, Dismissed>> = store.data
        .catch { if (it is IOException) emit(androidx.datastore.preferences.core.emptyPreferences()) else throw it }
        .map { prefs -> decode(prefs[DISMISSED].orEmpty()) }

    suspend fun dismiss(key: String, severity: AlertSeverity, eventId: Long) {
        store.edit { prefs ->
            val all = decode(prefs[DISMISSED].orEmpty()).toMutableMap()
            all[key] = Dismissed(severity, eventId)
            // the newest few only: a dismissal older than every banner the Hub still shows is of no use
            val kept = all.entries.sortedByDescending { it.value.eventId }.take(MAX_DISMISSED)
            prefs[DISMISSED] = kept.map { "${it.key}$SEP${it.value.severity.name}$SEP${it.value.eventId}" }.toSet()
        }
    }

    companion object {
        private const val SEP = "\t"
        private const val MAX_DISMISSED = 100
        private val ON = booleanPreferencesKey("alerts_on")
        private val LAST_SEEN = longPreferencesKey("last_seen_event")
        private val DISMISSED = stringSetPreferencesKey("dismissed")

        internal fun decode(entries: Set<String>): Map<String, Dismissed> = entries.mapNotNull { line ->
            val parts = line.split(SEP)
            if (parts.size != 3) return@mapNotNull null
            val severity = AlertSeverity.entries.firstOrNull { it.name == parts[1] } ?: return@mapNotNull null
            val id = parts[2].toLongOrNull() ?: return@mapNotNull null
            parts[0] to Dismissed(severity, id)
        }.toMap()

        private val Context.dataStore by preferencesDataStore("alerts")

        fun create(context: Context): AlertsStore = AlertsStore(context.applicationContext.dataStore)
    }
}
