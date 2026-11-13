package com.thompsonfabco.filamentkit.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * The paired server. [endpoints] are candidate hosts, best first (mDNS name, last good host, each pairing IP);
 * [fingerprint] is the pinned SHA-256 (lowercase hex, no colons); [token] is the bearer token.
 */
@Serializable
data class ServerConfig(
    val endpoints: List<String>,
    val port: Int,
    val fingerprint: String,
    val token: String,
    val name: String,
)

/** What the pairing screens need from [Settings]; lets JVM tests pass a fake. */
interface SettingsStore {
    suspend fun save(config: ServerConfig)
    suspend fun clear()

    /** The user chose to skip the fingerprint check when pairing with a new server by address. */
    suspend fun skipsFingerprintCheck(): Boolean = false
}

/**
 * The one paired server, in DataStore. The token lives in app-private storage (`allowBackup=false`).
 * The whole config is one JSON value so a save is atomic.
 */
class Settings(private val store: DataStore<Preferences>) : SettingsStore {
    private val json = Json { ignoreUnknownKeys = true }

    /** What is stored; an unreadable store reads as empty (System appearance, unpaired) so the splash is always released. */
    private val data: Flow<Preferences> = store.data.catch { e ->
        if (e is IOException) emit(emptyPreferences()) else throw e
    }

    /** The paired server, or null when unpaired (or the stored value is unreadable). */
    val server: Flow<ServerConfig?> = data.map { prefs ->
        prefs[KEY]?.let { text -> runCatching { json.decodeFromString<ServerConfig>(text) }.getOrNull() }
    }

    override suspend fun save(config: ServerConfig) {
        store.edit { it[KEY] = json.encodeToString(ServerConfig.serializer(), config) }
    }

    override suspend fun clear() {
        store.edit { it.remove(KEY) }
    }

    /** Off unless the user turned it on. It belongs to the phone, so forgetting a server leaves it as it is. */
    val skipFingerprintCheck: Flow<Boolean> = data.map { it[SKIP_FINGERPRINT] ?: false }

    override suspend fun skipsFingerprintCheck(): Boolean = skipFingerprintCheck.first()

    suspend fun setSkipFingerprintCheck(skip: Boolean) {
        store.edit { it[SKIP_FINGERPRINT] = skip }
    }

    /** Light, dark or follow the phone; System when nothing (or something unknown) is stored. */
    val appearance: Flow<Appearance> = data.map { prefs ->
        when (prefs[APPEARANCE]) {
            "light" -> Appearance.Light
            "dark" -> Appearance.Dark
            else -> Appearance.System
        }
    }

    suspend fun setAppearance(appearance: Appearance) {
        store.edit { it[APPEARANCE] = appearance.name.lowercase() }
    }

    companion object {
        private val KEY = stringPreferencesKey("server")
        private val APPEARANCE = stringPreferencesKey("appearance")
        private val SKIP_FINGERPRINT = booleanPreferencesKey("skip_fingerprint_check")

        private val Context.dataStore by preferencesDataStore("settings")

        fun create(context: Context): Settings = Settings(context.applicationContext.dataStore)
    }
}
