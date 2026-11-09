package com.thompsonfabco.filamentkit.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
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

    /** The paired server, or null when unpaired (or the stored value is unreadable). */
    val server: Flow<ServerConfig?> = store.data.map { prefs ->
        prefs[KEY]?.let { text -> runCatching { json.decodeFromString<ServerConfig>(text) }.getOrNull() }
    }

    override suspend fun save(config: ServerConfig) {
        store.edit { it[KEY] = json.encodeToString(ServerConfig.serializer(), config) }
    }

    override suspend fun clear() {
        store.edit { it.remove(KEY) }
    }

    /** Off unless the user turned it on. It belongs to the phone, so forgetting a server leaves it as it is. */
    val skipFingerprintCheck: Flow<Boolean> = store.data.map { it[SKIP_FINGERPRINT] ?: false }

    override suspend fun skipsFingerprintCheck(): Boolean = skipFingerprintCheck.first()

    suspend fun setSkipFingerprintCheck(skip: Boolean) {
        store.edit { it[SKIP_FINGERPRINT] = skip }
    }

    companion object {
        private val KEY = stringPreferencesKey("server")
        private val SKIP_FINGERPRINT = booleanPreferencesKey("skip_fingerprint_check")

        private val Context.dataStore by preferencesDataStore("settings")

        fun create(context: Context): Settings = Settings(context.applicationContext.dataStore)
    }
}
