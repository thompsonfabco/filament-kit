package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * The filament-kit server's JSON API.
 *
 * [client] is ONE pinned client (from [pinnedClient]) built once per paired fingerprint by the caller and reused for
 * every request; never build a client per call. [baseUrl] (e.g. `https://kit.local:8443`) and [token] are read on
 * each call so a re-discovered address or a re-pair takes effect without a new [Api].
 *
 * Failures: [ApiError] for every server error (a 401 is always code `unauthorized`) and `ApiError(0, "offline")` when
 * the server cannot be reached — or `ApiError(0, "local_network")` when it could not be reached because the app lacks
 * the API 37 local network permission ([localNetworkMissing]). A failed write of the downloaded APK is
 * `ApiError(0, "storage")`. A [FingerprintMismatch] propagates unchanged so the UI can ask for a re-pair.
 */
class Api(
    /** Also used directly for the camera streams (Task 16), so they go through the same pinned TLS. */
    internal val client: OkHttpClient,
    private val baseUrl: () -> String,
    private val token: () -> String?,
    private val localNetworkMissing: () -> Boolean = { LocalNetwork.missing() },
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun info(): ServerInfo = decode(call(request("api", "info", auth = false).get()))

    suspend fun pair(code: String): String {
        val body = buildJsonObject { put("code", code) }
        return call(request("api", "pair", auth = false).post(body.toBody()))
            .jsonObject["token"]?.jsonPrimitive?.contentOrNull
            ?: throw ApiError(200, "bad_response", "The server did not return a token")
    }

    /** [photos] must already be prepared JPEGs. A read calls Claude, so it gets a long timeout. */
    suspend fun read(photos: List<ByteArray>, hint: String, tag: String?): ReadResult {
        val form = MultipartBody.Builder().setType(MultipartBody.FORM)
        photos.forEachIndexed { i, jpeg ->
            form.addFormDataPart("photo", "photo${i + 1}.jpg", jpeg.toRequestBody(JPEG))
        }
        form.addFormDataPart("hint", hint)
        if (tag != null) form.addFormDataPart("tag", tag)
        return decode(call(request("api", "intake", "read").post(form.build()), SLOW_READ_S))
    }

    suspend fun retry(readId: String): ReadResult =
        decode(call(request("api", "intake", "retry", readId).post(ByteArray(0).toRequestBody(null)), SLOW_READ_S))

    /** [items] are sent exactly as given (unknown fields included). */
    suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?): AddResult {
        val body = buildJsonObject {
            put("items", items)
            put("dry_run", dryRun)
            tag?.let { put("tag", it) }
        }
        return decode(call(request("api", "intake", "add").post(body.toBody())))
    }

    /** The spool linked to tag [uid] (format `4:77:90:e`), or null. */
    suspend fun tag(uid: String): JsonObject? {
        val spool = call(request("api", "tags", uid).get()).jsonObject["spool"]
        return if (spool == null || spool is JsonNull) null else spool.jsonObject
    }

    suspend fun link(
        spoolId: Int,
        tag: String,
        force: Boolean,
        dryRun: Boolean,
        gross: Double?,
        location: String?,
    ): JsonObject {
        val body = buildJsonObject {
            put("tag", tag)
            put("force", force)
            put("dry_run", dryRun)
            gross?.let { put("gross", it) }
            location?.let { put("location", it) }
        }
        return spool(call(request("api", "spools", spoolId.toString(), "link").post(body.toBody())))
    }

    /** Give at most one of [gross], [remaining] or [empty]; the server rejects a mix. */
    suspend fun update(
        spoolId: Int,
        gross: Double?,
        remaining: Double?,
        location: String?,
        empty: Boolean,
        dryRun: Boolean,
    ): JsonObject {
        val body = buildJsonObject {
            gross?.let { put("gross", it) }
            remaining?.let { put("remaining", it) }
            location?.let { put("location", it) }
            if (empty) put("empty", true)
            put("dry_run", dryRun)
        }
        return spool(call(request("api", "spools", spoolId.toString()).patch(body.toBody())))
    }

    suspend fun search(q: String, sealedOnly: Boolean): List<JsonObject> {
        val req = request("api", "spools") {
            addQueryParameter("q", q)
            if (sealedOnly) addQueryParameter("sealed", "1")
        }
        return call(req.get()).jsonObject["spools"]?.jsonArray.orEmpty().map { it.jsonObject }
    }

    /** Spoolman's filaments (also ones without spools) whose vendor, name or material hold every word of [q]. */
    suspend fun filaments(q: String): List<FilamentChoice> {
        val req = request("api", "filaments") { if (q.isNotBlank()) addQueryParameter("q", q.trim()) }
        return call(req.get()).jsonObject["filaments"]?.jsonArray.orEmpty().map { decode(it) }
    }

    suspend fun vendors(): List<VendorChoice> =
        call(request("api", "vendors").get()).jsonObject["vendors"]?.jsonArray.orEmpty().map { decode(it) }

    suspend fun locations(): List<String> =
        call(request("api", "locations").get()).jsonObject["locations"]?.jsonArray.orEmpty()
            .map { it.jsonPrimitive.content }

    /** Streams `/app.apk` into [to]; [to] is only replaced when the whole file arrived. */
    /** [onProgress] gets (bytes so far, total or -1 when the server sends no length) as the file is written. */
    suspend fun downloadApk(to: File, onProgress: (Long, Long) -> Unit = { _, _ -> }) {
        val part = File(to.parentFile, to.name + ".part")
        try {
            withContext(Dispatchers.IO) {
                execute(request("app.apk", auth = false).get().build(), DOWNLOAD_S).use { resp ->
                    if (!resp.isSuccessful) throw errorFor(resp.code, resp.body.string())
                    val total = resp.body.contentLength()
                    resp.body.byteStream().use { src -> copyToDisk(src, part) { done -> onProgress(done, total) } }
                }
                to.delete()
                if (!part.renameTo(to)) throw storageError("Could not write ${to.name}")
            }
        } finally {
            part.delete()
        }
    }

    // ---- printers (Task 16) ------------------------------------------------------------------------------

    suspend fun printers(): List<Printer> =
        call(request("api", "printers").get()).jsonObject["printers"]?.jsonArray.orEmpty().map { decode(it) }

    /** Sets up (or re-keys) a printer. [accessCode] goes only into this request body; it is never kept or logged. */
    suspend fun addPrinter(serial: String, accessCode: String, name: String?): Printer {
        val body = buildJsonObject {
            put("serial", serial)
            put("access_code", accessCode)
            name?.takeIf { it.isNotBlank() }?.let { put("name", it) }
        }
        val printer = call(request("api", "printers").post(body.toBody())).jsonObject["printer"]
            ?: throw ApiError(200, "bad_response", "The server did not return the printer")
        return decode(printer)
    }

    suspend fun printer(id: String): PrinterDetail = decode(call(request("api", "printers", id).get()))

    /** [action] is `pause`, `resume`, `stop`, `light_on` or `light_off`. */
    suspend fun command(id: String, action: String): CommandResult {
        val body = buildJsonObject { put("action", action) }
        return decode(call(request("api", "printers", id, "command").post(body.toBody())))
    }

    fun cameraHlsUrl(id: String): String = request("api", "printers", id, "camera", "index.m3u8").build().url.toString()

    fun cameraMjpegUrl(id: String): String = request("api", "printers", id, "camera.mjpeg").build().url.toString()

    /** The Bearer header for requests the app builds itself (camera streams). */
    fun authHeaders(): Map<String, String> = token()?.let { mapOf("Authorization" to "Bearer $it") }.orEmpty()

    // ---- bridge part 2 -------------------------------------------------------------------------------------

    /** Starts the slot test + calibration job; 409 `already_running` while one runs. */
    suspend fun startMap(id: String): String =
        call(request("api", "printers", id, "map").post(ByteArray(0).toRequestBody(null)))
            .jsonObject["job_id"]?.jsonPrimitive?.contentOrNull
            ?: throw ApiError(200, "bad_response", "The server did not return a job")

    suspend fun mapStatus(id: String): MapStatus = decode(call(request("api", "printers", id, "map").get()))

    suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
        val body = buildJsonObject {
            put("spool_id", spoolId)
            put("dry_run", dryRun)
        }
        return decode(call(request("api", "printers", id, "slots", label, "load").post(body.toBody())))
    }

    suspend fun unload(id: String, label: String, dryRun: Boolean): UnloadResult {
        val body = buildJsonObject { put("dry_run", dryRun) }
        return decode(call(request("api", "printers", id, "slots", label, "unload").post(body.toBody())))
    }

    /** Newest first (the server's order). */
    suspend fun usage(id: String, days: Int = 7): List<UsageEntry> {
        val req = request("api", "printers", id, "usage") { addQueryParameter("days", days.toString()) }
        return call(req.get()).jsonObject["entries"]?.jsonArray.orEmpty().map { decode(it) }
    }

    suspend fun undoUsage(entryId: String): UsageEntry {
        val entry = call(request("api", "usage", entryId, "undo").post(ByteArray(0).toRequestBody(null)))
            .jsonObject["entry"] ?: throw ApiError(200, "bad_response", "The server did not return the entry")
        return decode(entry)
    }

    // ---- stage 4: profiles and the spec library ---------------------------------------------------------------

    suspend fun profileStatus(): ProfileStatus = decode(call(request("api", "profiles", "status").get()))

    suspend fun profileLines(): List<ProfileLine> =
        call(request("api", "profiles", "lines").get()).jsonObject["lines"]?.jsonArray.orEmpty().map { decode(it) }

    /** Bambu Studio parents for [material]; [ParentList.synced] false before the PC uploaded the system presets. */
    suspend fun parents(material: String): ParentList {
        val req = request("api", "profiles", "parents") { addQueryParameter("material", material) }
        return decode(call(req.get()))
    }

    /** The line and parent the server would use for these values (nothing is saved). */
    suspend fun propose(vendor: String, line: String, material: String): Proposal {
        val body = buildJsonObject {
            put("vendor", vendor)
            put("line", line)
            put("material", material)
        }
        return decode(call(request("api", "profiles", "propose").post(body.toBody())))
    }

    /** 400 `unknown_parent` when the PC has synced and Bambu Studio has no such preset; 404 `not_found`. */
    suspend fun setLineParent(lineId: String, parent: String): ProfileLine {
        val body = buildJsonObject { put("bambu_parent", parent) }
        val line = call(request("api", "profiles", "lines", lineId).patch(body.toBody())).jsonObject["line"]
            ?: throw ApiError(200, "bad_response", "The server did not return the line")
        return decode(line)
    }

    /** Saves one of the owner's own library entries; 400 `invalid_entry` carries `problems` in [ApiError.extra]. */
    suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult =
        decode(call(request("api", "library", "local").post(entry.toBody())))

    // ---- end printers --------------------------------------------------------------------------------------

    // --- plumbing ---

    private fun request(
        vararg segments: String,
        auth: Boolean = true,
        query: (HttpUrl.Builder.() -> Unit)? = null,
    ): Request.Builder {
        val url = baseUrl().toHttpUrl().newBuilder().apply {
            segments.forEach { addPathSegment(it) }
            query?.invoke(this)
        }.build()
        val b = Request.Builder().url(url)
        if (auth) token()?.let { b.header("Authorization", "Bearer $it") }
        return b
    }

    private suspend fun call(req: Request.Builder, timeoutS: Long? = null): JsonElement = withContext(Dispatchers.IO) {
        val request = req.build()
        execute(request, timeoutS).use { resp ->
            val text = try {
                resp.body.string()
            } catch (e: IOException) {
                throw offline("The connection to the server was lost: ${e.message}")
            }
            if (!resp.isSuccessful) throw errorFor(resp.code, text, request.header("Authorization"))
            try {
                json.parseToJsonElement(text)
            } catch (_: Exception) {
                throw ApiError(resp.code, "bad_response", "The server sent a reply the app could not read")
            }
        }
    }

    /** Runs the call; connection failures become `offline`, a [FingerprintMismatch] is rethrown as-is. */
    private fun execute(req: Request, timeoutS: Long?): Response {
        val c = if (timeoutS == null) client else client.newBuilder()
            .readTimeout(timeoutS, TimeUnit.SECONDS)
            .callTimeout(timeoutS, TimeUnit.SECONDS)
            .build()
        try {
            return c.newCall(req).execute()
        } catch (e: FingerprintMismatch) {
            throw e
        } catch (e: IOException) {
            throw offline("Could not reach the server: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    /** A connection failure: `local_network` when the permission is missing (that is the real cause), else `offline`. */
    private fun offline(message: String): ApiError =
        if (localNetworkMissing()) ApiError(0, "local_network", LOCAL_NETWORK_MESSAGE) else ApiError(0, "offline", message)

    /** Network read errors are `offline`; errors writing [part] (disk full, no folder) are `storage`. */
    private fun copyToDisk(src: java.io.InputStream, part: File, onWritten: (Long) -> Unit) {
        try {
            part.outputStream().use { out ->
                val buf = ByteArray(64 * 1024)
                var done = 0L
                while (true) {
                    val n = try {
                        src.read(buf)
                    } catch (e: IOException) {
                        throw offline("The connection to the server was lost: ${e.message}")
                    }
                    if (n < 0) break
                    out.write(buf, 0, n)
                    done += n
                    onWritten(done)
                }
            }
        } catch (e: IOException) {
            throw storageError(e.message ?: e.javaClass.simpleName)
        }
    }

    private fun storageError(detail: String) =
        ApiError(0, "storage", "The update could not be saved on this phone (is there enough free space?): $detail")

    /** [auth] is the request's Authorization header; a 401 keeps its token in [ApiError.sentToken]. */
    private fun errorFor(status: Int, text: String, auth: String? = null): ApiError {
        val obj = try {
            json.parseToJsonElement(text) as? JsonObject
        } catch (_: Exception) {
            null
        }
        val code = if (status == 401) "unauthorized" else obj?.get("error")?.jsonPrimitive?.contentOrNull ?: genericCode(status)
        val message = obj?.get("message")?.jsonPrimitive?.contentOrNull ?: "The server returned an error ($status)"
        val extra = JsonObject(obj.orEmpty().filterKeys { it != "error" && it != "message" })
        val sent = if (status == 401) auth?.removePrefix("Bearer ")?.trim()?.ifBlank { null } else null
        return ApiError(status, code, message, extra, sent)
    }

    private fun genericCode(status: Int) = when {
        status == 400 -> "bad_request"
        status == 404 -> "not_found"
        status >= 500 -> "internal"
        else -> "http_$status"
    }

    private fun spool(body: JsonElement): JsonObject =
        body.jsonObject["spool"]?.jsonObject ?: throw ApiError(200, "bad_response", "The server did not return a spool")

    private inline fun <reified T> decode(body: JsonElement): T = json.decodeFromJsonElement(body)

    private fun JsonObject.toBody(): RequestBody = toString().toRequestBody(JSON)

    private companion object {
        val JPEG = "image/jpeg".toMediaType()
        val JSON = "application/json".toMediaType()
        const val SLOW_READ_S = 120L
        const val DOWNLOAD_S = 600L
    }
}
