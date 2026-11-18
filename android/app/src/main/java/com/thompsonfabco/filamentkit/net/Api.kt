package com.thompsonfabco.filamentkit.net

import com.thompsonfabco.filamentkit.BuildConfig
import com.thompsonfabco.filamentkit.alerts.AlertParsing
import com.thompsonfabco.filamentkit.alerts.AlertsConfig
import com.thompsonfabco.filamentkit.alerts.EventsAnswer
import com.thompsonfabco.filamentkit.alerts.EventsQuery
import com.thompsonfabco.filamentkit.alerts.LowSpools
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
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

/** What the client says for an error reply that carries no `message` of its own ([ApiError.notFromHub] knows it). */
internal fun apiStandIn(status: Int) = "The Hub returned an error ($status)"

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
    /** The app's version, sent on every call as `X-Spoolwarden-Client: android/<version>` so the Hub can list it in Devices. */
    private val clientVersion: String = BuildConfig.VERSION_NAME,
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun info(): ServerInfo = decode(call(request("api", "info", auth = false).get()))

    suspend fun pair(code: String): String {
        val body = buildJsonObject { put("code", code) }
        return call(request("api", "pair", auth = false).post(body.toBody()))
            .jsonObject["token"]?.jsonPrimitive?.contentOrNull
            ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return a token")
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

    /**
     * [items] are sent exactly as given (unknown fields included). [readId]: the label read the items came from, so the
     * server's intake record keeps its photos (null: added by hand).
     */
    suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?, readId: String? = null): AddResult {
        val body = buildJsonObject {
            put("items", items)
            put("dry_run", dryRun)
            tag?.let { put("tag", it) }
            readId?.let { put("read_id", it) }
        }
        return decode(call(request("api", "intake", "add").post(body.toBody())))
    }

    // ---- intake history ----

    private fun history(vararg rest: String) = request("api", "intake", "history", *rest)

    suspend fun intakeHistory(): IntakeHistory = decode(call(history().get()))

    suspend fun intakeRecord(id: String): HistoryRecord = decode(call(history(id).get()))

    /** Photo [n] (1-based) of record [id], as JPEG bytes; 404 `not_found` when there is none. */
    suspend fun intakePhoto(id: String, n: Int): ByteArray = withContext(Dispatchers.IO) {
        val request = history(id, "photos", n.toString()).get().build()
        execute(request, null).use { resp ->
            if (!resp.isSuccessful) throw errorFor(resp.code, resp.body.string(), request.header("Authorization"))
            try {
                resp.body.bytes()
            } catch (e: IOException) {
                throw offline("The connection to the Hub was lost: ${e.message}")
            }
        }
    }

    /** Asks the AI again with the record's photos and [note]; writes nothing. 409 `ai_off`, 429 `daily_cap`. */
    suspend fun reviseIntake(id: String, note: String, item: Int?): RevisionProposal {
        val body = buildJsonObject {
            put("note", note)
            item?.let { put("item", it) }
        }
        return decode(call(history(id, "revise").post(body.toBody()), SLOW_READ_S))
    }

    /** Accepts an AI proposal as shown; 409 `stale` when the record changed since. */
    suspend fun applyProposal(id: String, proposal: String): HistoryRecord =
        decode(call(history(id, "apply").post(buildJsonObject { put("proposal", proposal) }.toBody())))

    /** Edits by hand: [values] is any subset of the item's fields; [spoolIds] null = every spool of the item. */
    suspend fun applyValues(id: String, item: Int, values: JsonObject, spoolIds: List<Int>? = null): HistoryRecord {
        val body = buildJsonObject {
            put("item", item)
            put("values", values)
            spoolIds?.let { ids -> put("spool_ids", JsonArray(ids.map { JsonPrimitive(it) })) }
        }
        return decode(call(history(id, "apply").post(body.toBody())))
    }

    /** Undoes [revision], the newest not undone yet; 409 `not_latest` otherwise. */
    suspend fun undoIntake(id: String, revision: Int): HistoryRecord =
        decode(call(history(id, "undo").post(buildJsonObject { put("revision", revision) }.toBody())))

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

    /** One spool by its number (`GET api/spools/{id}`); 404 `not_found` when the Hub has none. */
    suspend fun spoolById(id: Int): JsonObject = spool(call(request("api", "spools", id.toString()).get()))

    suspend fun search(q: String, sealedOnly: Boolean): List<JsonObject> {
        val req = request("api", "spools") {
            addQueryParameter("q", q)
            if (sealedOnly) addQueryParameter("sealed", "1")
        }
        return call(req.get()).jsonObject["spools"]?.jsonArray.orEmpty().map { it.jsonObject }
    }

    // ---- events and alerts (R80 section 8, E4) ----

    /**
     * `GET api/events`: waits up to `q.waitS` seconds (at most 55) for an event after the cursor, so the call's timeout is
     * longer than the wait. 404 `not_found` is a Hub without alerts; 401 is a revoked token.
     */
    suspend fun events(q: EventsQuery): EventsAnswer {
        val req = request("api", "events") {
            q.since?.let { addQueryParameter("since", it.toString()) }
            q.sinceAt?.let { addQueryParameter("since_at", it) }
            addQueryParameter("wait", q.waitS.toString())
            if (q.alertOnly) addQueryParameter("alert", "1")
            q.limit?.let { addQueryParameter("limit", it.toString()) }
        }
        return AlertParsing.events(call(req.get(), if (q.waitS > 0) q.waitS + EVENTS_EXTRA_S else null))
    }

    suspend fun alertsConfig(): AlertsConfig = AlertParsing.alerts(call(request("api", "alerts").get()))

    /** Stores nothing: the Hub gives this phone one test alert in its next events answer, within 60 seconds. */
    suspend fun sendTestAlert() {
        call(request("api", "alerts", "test").post(ByteArray(0).toRequestBody(null)))
    }

    suspend fun lowSpools(): LowSpools = AlertParsing.lowSpools(call(request("api", "spools", "low").get()))

    /** Spoolman's filaments (also ones without spools) whose vendor, name or material hold every word of [q]. */
    suspend fun filaments(q: String): List<FilamentChoice> {
        val req = request("api", "filaments") { if (q.isNotBlank()) addQueryParameter("q", q.trim()) }
        return call(req.get()).jsonObject["filaments"]?.jsonArray.orEmpty().map { decode(it) }
    }

    /** The first [limit] filaments for [q] and the number that match in all (the picker says how many more there are). */
    suspend fun filamentPage(q: String, limit: Int): FilamentPage {
        val req = request("api", "filaments") {
            if (q.isNotBlank()) addQueryParameter("q", q.trim())
            addQueryParameter("limit", limit.toString())
        }
        val body = call(req.get()).jsonObject
        val rows = body["filaments"]?.jsonArray.orEmpty().map { decode<FilamentChoice>(it) }
        return FilamentPage(rows, body["total"]?.jsonPrimitive?.intOrNull ?: rows.size)
    }

    suspend fun vendors(): List<VendorChoice> =
        call(request("api", "vendors").get()).jsonObject["vendors"]?.jsonArray.orEmpty().map { decode(it) }

    suspend fun locations(): List<String> =
        call(request("api", "locations").get()).jsonObject["locations"]?.jsonArray.orEmpty()
            .map { it.jsonPrimitive.content }

    /** `GET api/storage`: the locations with how full each is; null when the Hub has no such call (an older Hub, 404). */
    suspend fun storage(): StorageAnswer? = try {
        StorageWire.parse(call(request("api", "storage").get()))
    } catch (e: ApiError) {
        if (e.status == 404) null else throw e
    }

    /** The storage answer, or for an older Hub the names of `GET api/locations` alone. */
    suspend fun locationList(): StorageAnswer = storage() ?: StorageAnswer.ofNames(locations())

    /**
     * Streams `/app.apk` into [to]; [to] is only replaced when the whole file arrived. [onProgress] gets (bytes so
     * far, total or -1 when the server sends no length) as the file is written.
     */
    suspend fun downloadApk(to: File, onProgress: (Long, Long) -> Unit = { _, _ -> }) {
        val part = File(to.parentFile, to.name + ".part")
        try {
            withContext(Dispatchers.IO) {
                execute(request("app.apk", auth = false).get().build(), DOWNLOAD_S).use { resp ->
                    if (!resp.isSuccessful) throw errorFor(resp.code, resp.body.string())
                    val total = resp.body.contentLength()
                    resp.body.byteStream().use { src ->
                        copyToDisk(src, part, check = { ensureActive() }) { done -> onProgress(done, total) }
                    }
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
            ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return the printer")
        return decode(printer)
    }

    /** Adds a Klipper printer by the address of its Moonraker; the API key is set afterwards, from the printer's own screen. */
    suspend fun addKlipperPrinter(host: String, port: Int, name: String?): Printer {
        val body = buildJsonObject {
            put("family", "klipper")
            put("host", host)
            put("port", port)
            name?.takeIf { it.isNotBlank() }?.let { put("name", it) }
        }
        val printer = call(request("api", "printers").post(body.toBody())).jsonObject["printer"]
            ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return the printer")
        return decode(printer)
    }

    /**
     * The Hub's scan for Moonraker on [subnet] (its own /24 when null or blank). A refusal (a bad or too large network,
     * a scan already running, the Klipper module off) is an [ApiError] with the Hub's own message.
     */
    suspend fun scanKlipper(subnet: String?): List<KlipperFound> {
        val body = buildJsonObject { subnet?.trim()?.takeIf { it.isNotEmpty() }?.let { put("subnet", it) } }
        return call(request("api", "printers", "scan").post(body.toBody()), SLOW_READ_S).jsonObject["found"]?.jsonArray.orEmpty()
            .map { decode(it) }
    }

    suspend fun printer(id: String): PrinterDetail = decode(call(request("api", "printers", id).get()))

    /**
     * Changes a printer: [changes] holds one or more of name, address, port, access_code, api_key, unpin. A secret in
     * it goes only into this request body; it is never kept or logged.
     */
    suspend fun editPrinter(id: String, changes: JsonObject): PrinterEditResult =
        decode(call(request("api", "printers", id).patch(changes.toBody())))

    /** Forgets a printer (its entry and connection). */
    suspend fun removePrinter(id: String) {
        call(request("api", "printers", id).delete())
    }

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
            ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return a job")

    suspend fun mapStatus(id: String): MapStatus = decode(call(request("api", "printers", id, "map").get()))

    /** Builds a printer report now (Bambu printers; refused for a Klipper one); the server keeps a copy too. */
    suspend fun printerReport(id: String): PrinterReport =
        decode(call(request("api", "printers", id, "report").post(buildJsonObject { }.toBody())))

    // ---- map by loading filament ----

    private fun manual(id: String, vararg rest: String) = request("api", "printers", id, "manual-map", *rest)

    /** Opens the session, or joins the one already open (another device or the setup page). */
    suspend fun manualStart(id: String): ManualMapState =
        decode(call(manual(id, "start").post(buildJsonObject { }.toBody())))

    /** 404 `none` when no session was started for this printer since the server started. */
    suspend fun manualState(id: String): ManualMapState = decode(call(manual(id).get()))

    /** 409 `stale` when the session moved on (another device answered, or the load no longer shows). */
    suspend fun manualConfirm(id: String, session: String, position: String, reported: JsonObject, nozzle: String?,
                              byHand: Boolean): ManualMapState {
        val body = buildJsonObject {
            put("session", session)
            put("position", position)
            put("reported", reported)
            if (nozzle != null) put("nozzle", nozzle) else put("nozzle", JsonNull)
            if (byHand) put("by_hand", true)
        }
        return decode(call(manual(id, "confirm").post(body.toBody())))
    }

    suspend fun manualSkip(id: String, session: String, position: String): ManualMapState = decode(call(
        manual(id, "skip").post(buildJsonObject { put("session", session); put("position", position) }.toBody())))

    suspend fun manualStop(id: String, session: String): ManualMapState =
        decode(call(manual(id, "stop").post(buildJsonObject { put("session", session) }.toBody())))

    suspend fun manualOffer(id: String, share: Boolean): ManualOfferAnswer =
        decode(call(manual(id, "offer").post(buildJsonObject { put("share", share) }.toBody())))

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

    /**
     * Clears a slot: the Hub forgets which spool is in it (R83 section 3). [dryRun] says what would happen and changes
     * nothing. Offered on every slot, whether a spool is recorded there or not.
     */
    suspend fun clearSlot(printerId: String, label: String, dryRun: Boolean): ClearResult {
        val body = buildJsonObject { put("dry_run", dryRun) }
        return KitWire.clear(call(request("api", "printers", printerId, "slots", label, "clear").post(body.toBody())))
    }

    /** Newest first (the server's order). */
    suspend fun usage(id: String, days: Int = 7): List<UsageEntry> {
        val req = request("api", "printers", id, "usage") { addQueryParameter("days", days.toString()) }
        return call(req.get()).jsonObject["entries"]?.jsonArray.orEmpty().map { decode(it) }
    }

    suspend fun undoUsage(entryId: String): UsageEntry {
        val entry = call(request("api", "usage", entryId, "undo").post(ByteArray(0).toRequestBody(null)))
            .jsonObject["entry"] ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return the entry")
        return decode(entry)
    }

    // ---- stage 4: profiles and the spec library ---------------------------------------------------------------

    suspend fun profileStatus(): ProfileStatus = decode(call(request("api", "profiles", "status").get()))

    /**
     * Asks the server for a preset build (`POST /api/sync/rebuild`, 202). The server refuses with 409 `other_pc` while
     * another paired PC is the sync PC; the setup page's Build now has no such rule.
     */
    suspend fun requestBuild() {
        call(request("api", "sync", "rebuild").post(JsonObject(emptyMap()).toBody()))
    }

    suspend fun profileLines(): List<ProfileLine> =
        call(request("api", "profiles", "lines").get()).jsonObject["lines"]?.jsonArray.orEmpty().map { decode(it) }

    /** Bambu Studio parents for [material]; [ParentList.synced] false before the PC uploaded the system presets. */
    suspend fun parents(material: String): ParentList {
        val req = request("api", "profiles", "parents") { addQueryParameter("material", material) }
        return decode(call(req.get()))
    }

    /** `GET /api/profiles/orca-parents`: the Orca Slicer parents whose name has every word of [material], at most 60. */
    suspend fun orcaParents(material: String): OrcaParentList {
        val req = request("api", "profiles", "orca-parents") { addQueryParameter("material", material) }
        return decode(call(req.get()))
    }

    /** `GET /api/profiles/updates`: the presets in the slicers a newer build would change. */
    suspend fun presetUpdates(): PresetUpdates = decode(call(request("api", "profiles", "updates").get()))

    /**
     * Accepts exactly [names] from the list of build [stamp] (`POST /api/profiles/updates/accept`); the PC sync writes
     * them at its next run. 409 `updates_changed` when a newer build came after that list: nothing was accepted.
     */
    suspend fun acceptPresetUpdates(stamp: String, names: List<String>): AcceptedUpdates {
        val body = buildJsonObject {
            put("stamp", stamp)
            put("names", JsonArray(names.map(::JsonPrimitive)))
        }
        return decode(call(request("api", "profiles", "updates", "accept").post(body.toBody())))
    }

    /** The next build brings back presets deleted in Bambu Studio, and a build is asked for. */
    suspend fun restoreDeletedPresets() {
        call(request("api", "profiles", "restore-deleted").post(JsonObject(emptyMap()).toBody()))
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
            ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return the line")
        return decode(line)
    }

    /** `GET /api/profiles/uncovered`: the filaments without a preset line. */
    suspend fun uncoveredFilaments(): List<UncoveredFilament> =
        call(request("api", "profiles", "uncovered").get()).jsonObject["uncovered_filaments"]?.jsonArray.orEmpty().map { decode(it) }

    /** `POST /api/profiles/lines/{line}/filaments`: puts [ids] in the line; 400 `bad_request` names the `field` it refused. */
    suspend fun addFilamentsToLine(line: String, ids: List<Int>): ProfileLine {
        val body = buildJsonObject { put("ids", JsonArray(ids.map(::JsonPrimitive))) }
        return decode(call(request("api", "profiles", "lines", line, "filaments").post(body.toBody())))
    }

    /** `POST /api/profiles/lines`: makes a line named [name] of [vendor] from [ids], on Bambu Studio parent [bsTemplate]. */
    suspend fun createLine(name: String, vendor: String, ids: List<Int>, bsTemplate: String, orcaParent: String? = null): ProfileLine {
        val body = buildJsonObject {
            put("name", name)
            put("vendor", vendor)
            put("ids", JsonArray(ids.map(::JsonPrimitive)))
            put("bs_template", bsTemplate)
            if (!orcaParent.isNullOrBlank()) put("orca_parent", orcaParent)
        }
        return decode(call(request("api", "profiles", "lines").post(body.toBody())))
    }

    /** `POST /api/profiles/build`: asks the Hub for a preset build now (no PC sync rule, unlike [requestBuild]). */
    suspend fun buildPresets(): BuildRequested =
        decode(call(request("api", "profiles", "build").post(JsonObject(emptyMap()).toBody())))

    /** Saves one of the owner's own library entries; 400 `invalid_entry` carries `problems` in [ApiError.extra]. */
    suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult =
        decode(call(request("api", "library", "local").post(entry.toBody())))

    // ---- phase 3: the Hub at a glance, the owner's own catalog entries, spools (R83 section 10.1) ----

    /** `GET api/hub`; null when the Hub has no such call (an older Hub, 404), so the feature is hidden. */
    suspend fun hub(): HubAnswer? = try {
        KitWire.hub(call(request("api", "hub").get()))
    } catch (e: ApiError) {
        if (e.status == 404) null else throw e
    }

    /** `GET api/library/local`: the owner's own entries; 404 `not_found` from an older Hub. */
    suspend fun localLibrary(): LocalLibrary = KitWire.localLibrary(call(request("api", "library", "local").get()))

    /**
     * `POST api/library/local/form`: the Hub builds the entry from the form's [values] (brand, name, material and the
     * optional ones); the app sends values, never an entry's text. 400 `invalid_entry` carries `problems`
     * ([KitWire.problems]).
     */
    suspend fun addLocalEntryForm(values: JsonObject): LocalEntry {
        val entry = call(request("api", "library", "local", "form").post(values.toBody())).jsonObject["entry"]
        return KitWire.localEntry(entry ?: JsonNull)
            ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return the entry")
    }

    /** `DELETE api/library/local/{id}`; 404 `not_found` when the Hub has no such entry. */
    suspend fun removeLocalEntry(id: String) {
        call(request("api", "library", "local", id).delete())
    }

    /** `GET api/spools`: [filter] is one of [SpoolFilter] (null: every spool that is not empty). */
    suspend fun spools(q: String, filter: String?): SpoolsAnswer {
        val req = request("api", "spools") {
            if (q.isNotBlank()) addQueryParameter("q", q.trim())
            filter?.let { addQueryParameter("filter", it) }
        }
        return KitWire.spools(call(req.get()))
    }

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
        val b = Request.Builder().url(url).header(CLIENT_HEADER, "android/$clientVersion")
        if (auth) token()?.let { b.header("Authorization", "Bearer $it") }
        return b
    }

    private suspend fun call(req: Request.Builder, timeoutS: Long? = null): JsonElement = withContext(Dispatchers.IO) {
        val request = req.build()
        execute(request, timeoutS).use { resp ->
            val text = try {
                resp.body.string()
            } catch (e: IOException) {
                throw offline("The connection to the Hub was lost: ${e.message}")
            }
            if (!resp.isSuccessful) throw errorFor(resp.code, text, request.header("Authorization"))
            try {
                json.parseToJsonElement(text)
            } catch (_: Exception) {
                throw ApiError(resp.code, ApiError.BAD_RESPONSE, "The Hub sent a reply the app could not read")
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
            throw offline("Could not reach the Hub: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    /** A connection failure: `local_network` when the permission is missing (that is the real cause), else `offline`. */
    private fun offline(message: String): ApiError =
        if (localNetworkMissing()) ApiError(0, "local_network", LOCAL_NETWORK_MESSAGE) else ApiError(0, "offline", message)

    /**
     * Network read errors are `offline`; errors writing [part] (disk full, no folder) are `storage`. [check] runs before
     * each chunk and throws when the caller has cancelled, so a cancelled download stops at the next chunk.
     */
    private fun copyToDisk(src: java.io.InputStream, part: File, check: () -> Unit = {}, onWritten: (Long) -> Unit) {
        try {
            part.outputStream().use { out ->
                val buf = ByteArray(64 * 1024)
                var done = 0L
                while (true) {
                    check()
                    val n = try {
                        src.read(buf)
                    } catch (e: IOException) {
                        throw offline("The connection to the Hub was lost: ${e.message}")
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
        val message = obj?.get("message")?.jsonPrimitive?.contentOrNull ?: apiStandIn(status)
        val extra = JsonObject(obj.orEmpty().filterKeys { it != "error" && it != "message" })
        val sent = if (status == 401) auth?.removePrefix("Bearer ")?.trim()?.ifBlank { null } else null
        return ApiError(status, code, message, extra, sent, noHubMessage = obj?.get("message") == null)
    }

    private fun genericCode(status: Int) = when {
        status == 400 -> "bad_request"
        status == 404 -> "not_found"
        status >= 500 -> "internal"
        else -> "http_$status"
    }

    private fun spool(body: JsonElement): JsonObject =
        body.jsonObject["spool"]?.jsonObject ?: throw ApiError(200, ApiError.BAD_RESPONSE, "The Hub did not return a spool")

    private inline fun <reified T> decode(body: JsonElement): T = json.decodeFromJsonElement(body)

    private fun JsonObject.toBody(): RequestBody = toString().toRequestBody(JSON)

    private companion object {
        val JPEG = "image/jpeg".toMediaType()
        val JSON = "application/json".toMediaType()
        const val SLOW_READ_S = 120L
        const val DOWNLOAD_S = 600L
        const val EVENTS_EXTRA_S = 10L
        const val CLIENT_HEADER = "X-Spoolwarden-Client"
    }
}
