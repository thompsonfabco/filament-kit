package com.thompsonfabco.filamentkit.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** `GET /api/info`. [apkVersion] is the integer versionCode the server offers, as text; null when no app is installed. */
@Serializable
data class ServerInfo(
    val name: String,
    val version: String,
    val api: Int,
    @SerialName("apk_version") val apkVersion: String? = null,
)

/**
 * `POST /api/intake/read` and `/retry`. [items] stays a [JsonArray] so fields the app does not know about (or the user
 * edited) go back to `add` exactly as received. [usage] is informational.
 */
@Serializable
data class ReadResult(
    val items: JsonArray = JsonArray(emptyList()),
    val questions: List<String> = emptyList(),
    val tag: String? = null,
    val usage: JsonObject? = null,
    @SerialName("read_id") val readId: String? = null,
)

/** `POST /api/intake/add`. [dry] is true for a preview (nothing written). */
@Serializable
data class AddResult(
    @SerialName("spool_ids") val spoolIds: List<Int> = emptyList(),
    val lines: List<String> = emptyList(),
    val dry: Boolean = true,
)

/** A failed call: the server's `{error, message, ...}` body, or `status` 0 / code `offline` when it could not be reached. */
class ApiError(
    val status: Int,
    val code: String,
    override val message: String,
    val extra: JsonObject = JsonObject(emptyMap()),
) : Exception(message)
