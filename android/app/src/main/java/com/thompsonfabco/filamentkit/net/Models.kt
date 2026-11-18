package com.thompsonfabco.filamentkit.net

import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.descriptors.nullable
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/**
 * `GET /api/info`. [apkVersion] is the integer versionCode the server offers, as text; null when no app is installed.
 * [modules] are the modules that are on; null from an older server that does not list them (it always reads labels).
 */
@Serializable
data class ServerInfo(
    val name: String,
    val version: String,
    val api: Int,
    @SerialName("apk_version") val apkVersion: String? = null,
    val modules: List<String>? = null,
    /** The Hub's default theme for devices that have not chosen (`console`, `workbench`, `palette`, `panes`); null from an older Hub. */
    val look: String? = null,
) {
    /** The label-photo add flow is offered: `ai_intake` is on (or the server is too old to say). */
    val labelReading: Boolean get() = modules == null || AI_INTAKE in modules

    /** The Printers Feature is on (Bambu or Klipper; or the server is too old to say). */
    val printersOn: Boolean get() = modules == null || PRINTERS in modules || KLIPPER in modules

    companion object {
        const val AI_INTAKE = "ai_intake"
        const val PRINTERS = "printers"
        const val KLIPPER = "klipper"
    }
}

/** One of `GET /api/filaments`; the field names are an add item's, so a pick copies them into a new item. */
@Serializable
data class FilamentChoice(
    @Serializable(with = LenientNullableInt::class) val id: Int? = null,
    val vendor: String = "",
    val name: String? = null,
    val material: String? = null,
    @Serializable(with = LenientDouble::class) val density: Double? = null,
    @Serializable(with = LenientDouble::class) val net: Double? = null,
    @Serializable(with = LenientDouble::class) val tare: Double? = null,
    @SerialName("color_hex") val colorHex: String? = null,
    @Serializable(with = LenientDouble::class) val nozzle: Double? = null,
    @Serializable(with = LenientDouble::class) val bed: Double? = null,
    @Serializable(with = LenientInt::class) val spools: Int = 0,
)

/** One of `GET /api/vendors`; [tare] is the vendor's empty spool weight (a new filament's default). */
@Serializable
data class VendorChoice(
    @Serializable(with = LenientNullableInt::class) val id: Int? = null,
    val name: String = "",
    @Serializable(with = LenientDouble::class) val tare: Double? = null,
)

/**
 * `POST /api/intake/read` and `/retry`. [items] stays a [JsonArray] so fields the app does not know about (or the user
 * edited) go back to `add` exactly as received. [usage] is informational.
 */
@Serializable
data class ReadResult(
    val items: JsonArray = JsonArray(emptyList()),
    val questions: List<String> = emptyList(),
    @Serializable(with = ReadTag::class) val tag: String? = null,
    val usage: JsonObject? = null,
    @SerialName("read_id") val readId: String? = null,
    /** Which reader answered: "local" or "cloud" (null: a server from before the local reader). */
    val reader: String? = null,
    /** The local reader's confidence 0..1 (its least sure item); null for Claude. */
    @Serializable(with = LenientDouble::class) val confidence: Double? = null,
    @Serializable(with = LenientBool::class) val unsure: Boolean = false,
    /** The local reader's tier ("cpu" or "gpu"). */
    val tier: String? = null,
    /** The local reader went on from its CPU tier to its GPU tier. */
    @Serializable(with = LenientBool::class) val escalated: Boolean = false,
    /** Why another reader answered, or an unsure answer was kept (e.g. "local reader: ..."). */
    val note: String? = null,
)

/**
 * `POST /api/intake/add`. [dry] is true for a preview (nothing written). [historyId]: the intake record the save made
 * (null for a preview, with retention 0, or from an older server).
 */
@Serializable
data class AddResult(
    @SerialName("spool_ids") val spoolIds: List<Int> = emptyList(),
    val lines: List<String> = emptyList(),
    val dry: Boolean = true,
    @SerialName("history_id") val historyId: String? = null,
    /** What the add does per item (index, new or existing filament, where the spools go, problems); older Hubs send none. */
    val items: JsonArray = JsonArray(emptyList()),
)

/** One page of `GET /api/filaments`: the rows and how many filaments match in all. */
data class FilamentPage(val filaments: List<FilamentChoice>, val total: Int)

// ---- intake history (2026-11-12-1031 handoff, API v1) ----------------------------------------------------

/** One spool of an intake record, as it is now. */
@Serializable
data class HistorySpool(
    @Serializable(with = LenientNullableInt::class) @SerialName("spool_id") val spoolId: Int? = null,
    @Serializable(with = LenientNullableInt::class) @SerialName("filament_id") val filamentId: Int? = null,
    val vendor: String? = null,
    val name: String? = null,
    val material: String? = null,
    @SerialName("color_hex") val colorHex: String? = null,
)

/**
 * A record of `GET /api/intake/history` (the summary). [state]: `detected` (as first saved), `revised_ai`, `edited`.
 * [source]: `phone`, `web`, `station` or `cli`. [photos]: how many photos it keeps (0: saved by hand).
 */
@Serializable
data class HistorySummary(
    val id: String,
    val at: String = "",
    val source: String = "",
    val state: String = "detected",
    @Serializable(with = LenientInt::class) val photos: Int = 0,
    val undoable: Boolean = false,
    val spools: List<HistorySpool> = emptyList(),
)

/** `GET /api/intake/history`. [ai]: label reading is on (the note box works). [photoBytes]: the photos' disk use. */
@Serializable
data class IntakeHistory(
    @Serializable(with = LenientInt::class) val keep: Int = 0,
    @Serializable(with = LenientInt::class) val count: Int = 0,
    @Serializable(with = LenientNullableLong::class) @SerialName("photo_bytes") val photoBytes: Long? = null,
    val ai: Boolean = false,
    val records: List<HistorySummary> = emptyList(),
)

/** What the read returned; null in a record saved by hand. */
@Serializable
data class HistoryRead(val items: List<JsonObject> = emptyList(), val hint: String? = null)

/** One item as saved: [values] are the add's item fields (vendor, name, material, nozzle, ...). */
@Serializable
data class HistorySaved(
    @Serializable(with = LenientInt::class) val item: Int = 0,
    @SerialName("spool_ids") val spoolIds: List<Int> = emptyList(),
    val values: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class HistoryChange(
    @Serializable(with = LenientNullableInt::class) @SerialName("spool_id") val spoolId: Int? = null,
    val field: String = "",
    val old: JsonElement? = null,
    val new: JsonElement? = null,
)

/** A re-link: the spools moved from filament [from] to [to]; [orphaned] filaments are left with no spools. */
@Serializable
data class HistoryFilaments(
    @Serializable(with = LenientNullableInt::class) val from: Int? = null,
    @Serializable(with = LenientNullableInt::class) val to: Int? = null,
    val created: Boolean = false,
    val orphaned: List<Int> = emptyList(),
    /** After an undo: the copy of the filament the spools went to, and the filaments the undo left without spools. */
    @Serializable(with = LenientNullableInt::class) @SerialName("undo_to") val undoTo: Int? = null,
    @SerialName("orphaned_by_undo") val orphanedByUndo: List<Int> = emptyList(),
)

/** [by]: `ai` or `hand`. */
@Serializable
data class HistoryRevision(
    @Serializable(with = LenientInt::class) val n: Int = 0,
    val at: String = "",
    val by: String = "",
    val device: String? = null,
    val note: String? = null,
    val changes: List<HistoryChange> = emptyList(),
    val filaments: HistoryFilaments? = null,
    val undone: Boolean = false,
)

/** `GET /api/intake/history/{id}` and the reply of apply / undo: the summary plus the details. */
@Serializable
data class HistoryRecord(
    val id: String,
    val at: String = "",
    val source: String = "",
    val state: String = "detected",
    @Serializable(with = LenientInt::class) val photos: Int = 0,
    val undoable: Boolean = false,
    val spools: List<HistorySpool> = emptyList(),
    val read: HistoryRead? = null,
    val saved: List<HistorySaved> = emptyList(),
    @Serializable(with = LenientDouble::class) val weight: Double? = null,
    val tag: String? = null,
    val revisions: List<HistoryRevision> = emptyList(),
)

/** `POST .../revise`: the AI's proposal for [item], nothing written yet. [changes] are the fields that differ. */
@Serializable
data class RevisionProposal(
    val proposal: String,
    @Serializable(with = LenientInt::class) val item: Int = 0,
    val before: JsonObject = JsonObject(emptyMap()),
    val after: JsonObject = JsonObject(emptyMap()),
    val changes: List<String> = emptyList(),
    @SerialName("no_photo") val noPhoto: Boolean = false,
    /** Who read again: "local" or "cloud" (null: an older server), how sure (local), and the server's note. */
    val reader: String? = null,
    @Serializable(with = LenientDouble::class) val confidence: Double? = null,
    val note: String? = null,
)

/**
 * A failed call: the server's `{error, message, ...}` body, or `status` 0 / code `offline` when it could not be reached.
 * [sentToken] is the bearer token a rejected (401) request carried, so a late 401 for an old token can be told apart
 * from one for the current token; it is never part of the message.
 */
class ApiError(
    val status: Int,
    val code: String,
    override val message: String,
    val extra: JsonObject = JsonObject(emptyMap()),
    val sentToken: String? = null,
    /** The reply carried no `message` of the Hub's: an error page of some other service, so [message] is the app's own. */
    val noHubMessage: Boolean = false,
) : Exception(message) {
    /** The reply was not the Hub speaking: unreadable (`bad_response`) or an error page without the Hub's own `message`. */
    val notFromHub: Boolean get() = code == BAD_RESPONSE || noHubMessage || message.isBlank() || message == apiStandIn(status)

    companion object {
        const val BAD_RESPONSE = "bad_response"

        /** No Hub is paired, so there is no client to ask: the same answer as a Hub that cannot be reached. */
        fun noHubPaired() = ApiError(0, "offline", "No Hub is paired.")
    }
}

// ---- printer models (Task 16) ------------------------------------------------------------------------
// Mirrors the server's printer routes (`api.py` `_printer_view`, `bridge/status.py` `summarize`).

/** `camera.kind`: `hls`, `mjpeg`, or null when the app cannot show this model's camera. */
@Serializable
data class PrinterCamera(val kind: String? = null)

/** The list's condensed status. */
@Serializable
data class PrinterSummary(
    @SerialName("gcode_state") val gcodeState: String = "UNKNOWN",
    @Serializable(with = LenientInt::class) val percent: Int = 0,
    @Serializable(with = LenientInt::class) @SerialName("remaining_min") val remainingMin: Int = 0,
    val job: String? = null,
)

/**
 * One printer. [state] is `connected`, `offline`, `wrong_code`, `needs_developer_mode`, `cert_changed` (its TLS
 * certificate is not the one first seen; no Access Code is sent to it) or `not_configured`;
 * [id] is the serial. The Access Code is never part of this.
 */
/**
 * `PATCH /api/printers/{id}`: the printer as it is now (after a reconnect, the new connection's first state), which
 * keys changed, and the server's one line about a new address (null: nothing to say).
 */
@Serializable
data class PrinterEditResult(
    val printer: Printer,
    val changed: List<String> = emptyList(),
    val note: String? = null,
)

@Serializable
data class Printer(
    val id: String,
    val name: String,
    val model: String? = null,
    val serial: String,
    val ip: String? = null,
    val configured: Boolean = false,
    val state: String = "not_configured",
    val camera: PrinterCamera = PrinterCamera(),
    /** Null when the server could not summarise the printer's report; the list then shows the state only. */
    val summary: PrinterSummary? = null,
    /** The model's name ("H2D" for "O1D"); servers before 0.3 send only [model]. */
    @SerialName("model_name") val modelName: String? = null,
    /** `bambu` or `klipper`; servers before 0.4 send none (Bambu only then). */
    val family: String = "bambu",
    /** A certificate is pinned for it (never which); servers before the printer edit routes send none. */
    val pinned: Boolean = false,
    /** A Klipper printer's Moonraker host name or address; none for a Bambu printer. */
    val host: String? = null,
) {
    /** What to show for the model: its name, else the code an older server sent, else null. */
    val shownModel: String? get() = modelName?.takeIf { it.isNotBlank() } ?: model?.takeIf { it.isNotBlank() }

    /** The [state] codes the Home panel tells apart; the others all mean "needs a look". */
    companion object {
        const val STATE_CONNECTED = "connected"
        const val STATE_OFFLINE = "offline"
        const val STATE_WRONG_CODE = "wrong_code"
        const val STATE_NOT_CONFIGURED = "not_configured"
    }
}

/** One Moonraker the Hub's scan answered from (`POST /api/printers/scan`); [configured] when it is already a printer. */
@Serializable
data class KlipperFound(
    val id: String = "",
    val host: String,
    @Serializable(with = LenientInt::class) val port: Int = 7125,
    val name: String = "",
    val configured: Boolean = false,
)

@Serializable
data class Temp(
    @Serializable(with = LenientDouble::class) val current: Double? = null,
    @Serializable(with = LenientDouble::class) val target: Double? = null,
)

@Serializable
data class Temps(val nozzle: List<Temp> = emptyList(), val bed: Temp? = null, val chamber: Temp? = null)

@Serializable
data class SlotSpool(
    @Serializable(with = LenientNullableInt::class) val id: Int? = null,
    val name: String = "",
    val material: String = "",
    @SerialName("color_hex") val colorHex: String = "",
    @Serializable(with = LenientDouble::class) @SerialName("remaining_weight") val remainingWeight: Double? = null,
)

/** A spool assigned to an empty slot that waits to load there: [spoolId] is the Hub's spool, null when it sent none. */
@Serializable
data class SlotPending(
    @Serializable(with = LenientNullableInt::class) @SerialName("spool_id") val spoolId: Int? = null,
)

/** `pending`: an object is a waiting spool; absent, null or any other shape is none (older Hubs send none). */
@OptIn(ExperimentalSerializationApi::class)
internal object LenientPending : KSerializer<SlotPending?> {
    override val descriptor: SerialDescriptor = SlotPending.serializer().descriptor.nullable
    override fun deserialize(decoder: Decoder): SlotPending? {
        val d = decoder as? JsonDecoder ?: throw SerializationException("JSON only")
        val obj = d.decodeJsonElement() as? JsonObject ?: return null
        return SlotPending(spoolId = (obj["spool_id"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content?.toDoubleOrNull()?.roundToInt())
    }
    override fun serialize(encoder: Encoder, value: SlotPending?) =
        (encoder as JsonEncoder).encodeJsonElement(
            if (value == null) JsonNull else JsonObject(mapOf("spool_id" to (value.spoolId?.let(::JsonPrimitive) ?: JsonNull))),
        )
}

/**
 * [say] is how the slot is spoken (`["external", "left"]`); [present] / [reading] are null when unknown. Older
 * servers send none of the three. [pending] is a spool waiting to load into this empty slot.
 */
@Serializable
data class AmsSlot(
    @Serializable(with = LenientInt::class) val slot: Int,
    val label: String = "",
    val type: String = "",
    @SerialName("color_hex") val colorHex: String = "",
    val active: Boolean = false,
    val spool: SlotSpool? = null,
    @Serializable(with = SayWords::class) val say: List<String> = emptyList(),
    @Serializable(with = LenientNullableBool::class) val present: Boolean? = null,
    @Serializable(with = LenientNullableBool::class) val reading: Boolean? = null,
    @Serializable(with = LenientPending::class) val pending: SlotPending? = null,
)

/**
 * [kind] is an AMS type key (`ams`, `ams_ht`, `ams_2pro`, ...) or `ext`: an external spool holder, one slot labelled
 * `Ext`, `Ext-L` or `Ext-R`. [typeName] is the type for people (`AMS 2 Pro`); blank from older servers.
 */
@Serializable
data class AmsUnit(
    @Serializable(with = LenientInt::class) val unit: Int,
    val label: String = "",
    val kind: String = "ams",
    val slots: List<AmsSlot> = emptyList(),
    @SerialName("type_name") val typeName: String = "",
    @Serializable(with = SayWords::class) val say: List<String> = emptyList(),
)

/** `say`: a list of words, or one text (split at spaces); anything else is no words. */
internal object SayWords : KSerializer<List<String>> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("SayWords", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): List<String> {
        val el = (decoder as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement()
        val words = when (el) {
            is JsonArray -> el.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p !is JsonNull }?.content }
            is JsonPrimitive -> if (el is JsonNull) emptyList() else listOf(el.content)
            else -> emptyList()
        }
        return words.flatMap { it.split(' ') }.filter { it.isNotBlank() }
    }
    override fun serialize(encoder: Encoder, value: List<String>) =
        (encoder as JsonEncoder).encodeJsonElement(JsonArray(value.map(::JsonPrimitive)))
}

/** true / false; null or anything else reads as null (unknown). */
@OptIn(ExperimentalSerializationApi::class)
internal object LenientNullableBool : KSerializer<Boolean?> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("LenientNullableBool", PrimitiveKind.BOOLEAN).nullable
    override fun deserialize(decoder: Decoder): Boolean? {
        val el = (decoder as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement()
        return when ((el as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content) {
            "true" -> true
            "false" -> false
            else -> null
        }
    }
    override fun serialize(encoder: Encoder, value: Boolean?) =
        (encoder as JsonEncoder).encodeJsonElement(if (value == null) JsonNull else JsonPrimitive(value))
}

@Serializable
data class HmsAlert(val code: String, val text: String = "")

/** `GET /api/printers/{id}` `status`. [eta] is ISO-8601 to the minute or null; [light] `on`/`off`/null. */
@Serializable
data class PrinterStatus(
    @SerialName("gcode_state") val gcodeState: String = "UNKNOWN",
    val stage: String = "",
    val job: String = "",
    @Serializable(with = LenientInt::class) val percent: Int = 0,
    @Serializable(with = LenientNullableInt::class) val layer: Int? = null,
    @Serializable(with = LenientNullableInt::class) @SerialName("total_layers") val totalLayers: Int? = null,
    @Serializable(with = LenientInt::class) @SerialName("remaining_min") val remainingMin: Int = 0,
    val eta: String? = null,
    val temps: Temps = Temps(),
    val ams: List<AmsUnit> = emptyList(),
    val hms: List<HmsAlert> = emptyList(),
    val light: String? = null,
    @Serializable(with = LenientNullableLong::class) val updated: Long? = null,
)

/** [status] is null while the server has no connection to the printer. */
@Serializable
data class PrinterDetail(val printer: Printer, val status: PrinterStatus? = null)

/** `POST /api/printers/{id}/command`; [reply] is the server's `{ok, reply}` result for the printer's answer. */
@Serializable
data class CommandResult(val ok: Boolean = false, val reply: JsonElement? = null)

// ---- bridge part 2: slot mapping, loading, filament used (route-contract.md) ---------------------------

@Serializable
data class MapSlot(
    val label: String,
    @Serializable(with = LenientNullableInt::class) @SerialName("ams_id") val amsId: Int? = null,
    @Serializable(with = LenientNullableInt::class) @SerialName("tray_id") val trayId: Int? = null,
    @Serializable(with = LenientNullableInt::class) val global: Int? = null,
)

/**
 * `GET /api/printers/{id}/map`. [state] is `none`, `running`, `done` or `failed`; [observe]: usage is logged only.
 * [notes]: what a good result does not settle yet (not problems). [problemsOld]: the problems are from a job an earlier
 * server run finished (at [finished], epoch seconds), so they say what happened then, not what is wrong now.
 * [stale]: the printer's layout changed since the map was made. [suspect]: two prints in a row disagreed with the map.
 * [schemeUnsettled]: the loaded slots fit more than one numbering scheme (null: a server that does not say).
 * [outcome] and [reason] (v0.5.0 servers): the server's one reading of the flags and why a job stopped short of a
 * confirmed map; [outcomeText] and [nextStep] are its sentences for them. Null on an older server.
 * [reportWanted]: why a printer report would help (a code; null when it wouldn't), [reportWhy] the server's sentence.
 */
@Serializable
data class MapStatus(
    val state: String = "none",
    val step: String = "",
    val slots: List<MapSlot> = emptyList(),
    val calibrated: Boolean = false,
    val observe: Boolean = false,
    val problems: List<String> = emptyList(),
    val notes: List<String> = emptyList(),
    @SerialName("problems_old") val problemsOld: Boolean = false,
    val finished: Double? = null,
    val stale: Boolean = false,
    val suspect: Boolean = false,
    @SerialName("scheme_unsettled") val schemeUnsettled: Boolean? = null,
    val outcome: String? = null,
    val reason: String? = null,
    @SerialName("outcome_text") val outcomeText: String? = null,
    @SerialName("next_step") val nextStep: String? = null,
    @SerialName("report_wanted") val reportWanted: String? = null,
    @SerialName("report_why") val reportWhy: String? = null,
)

/** `POST /api/printers/{id}/report`: the printer report as XML text and the file name the server gave it. */
@Serializable
data class PrinterReport(val name: String, val xml: String)

@Serializable
data class LoadSlot(
    val label: String,
    @Serializable(with = LenientNullableInt::class) @SerialName("ams_id") val amsId: Int? = null,
    @Serializable(with = LenientNullableInt::class) @SerialName("tray_id") val trayId: Int? = null,
)

/** The owner's own Bambu Studio preset the slot is set to. */
@Serializable
data class PresetRef(@SerialName("filament_id") val filamentId: String = "", val name: String = "")

/**
 * `POST /api/printers/{id}/slots/{label}/load`. A dry run says what would happen ([confirmed] false, no [problems]);
 * after a real load [confirmed] is false while the printer has not reported the new setting yet.
 */
@Serializable
data class LoadResult(
    val spool: JsonObject? = null,
    val slot: LoadSlot,
    val preset: PresetRef? = null,
    @Serializable(with = LenientDouble::class) @SerialName("nozzle_mm") val nozzleMm: Double? = null,
    @SerialName("nozzle_assumed") val nozzleAssumed: Boolean = false,
    /** A dry run may send null here; read as false. */
    @Serializable(with = LenientBool::class) val confirmed: Boolean = false,
    val problems: List<String> = emptyList(),
    /** Spools now in that slot that go back to their previous place (not in the contract; shown when sent). */
    @SerialName("moved_back") val movedBack: List<MovedBack> = emptyList(),
    /** A Bambu Lab load that has not happened yet: the spool is assigned to the slot and waits for it (phase 3, R83 3.5). */
    @Serializable(with = LenientBool::class) val pending: Boolean = false,
)

@Serializable
data class MovedBack(@Serializable(with = LenientNullableInt::class) val id: Int? = null, val location: String = "")

/** true / false; null or anything else reads as false. */
internal object LenientBool : KSerializer<Boolean> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("LenientBool", PrimitiveKind.BOOLEAN)
    override fun deserialize(decoder: Decoder): Boolean {
        val el = (decoder as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement()
        return (el as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content == "true"
    }
    override fun serialize(encoder: Encoder, value: Boolean) = encoder.encodeBoolean(value)
}

/**
 * `POST /api/printers/{id}/slots/{label}/unload`; [location] is where the spool goes back to. [movedBack] lists every
 * spool that was at that slot's location and where each goes (usually just the one).
 */
@Serializable
data class UnloadResult(
    val spool: JsonObject? = null,
    val slot: LoadSlot,
    val location: String = "",
    @SerialName("moved_back") val movedBack: List<MovedBack> = emptyList(),
    /** A spool that was waiting for this slot is waiting no more (phase 3); false from an older Hub. */
    @Serializable(with = LenientBool::class) @SerialName("waiting_ended") val waitingEnded: Boolean = false,
)

/**
 * One line of `GET /api/printers/{id}/usage`. [id] may be sent as a number or a string; it is kept as text.
 * [observe]: only logged, nothing was taken off a spool. [error] is a code when the deduction could not be made.
 */
@Serializable
data class UsageEntry(
    @Serializable(with = TextId::class) val id: String,
    val at: String = "",
    val job: String? = null,
    @Serializable(with = LenientDouble::class) val grams: Double? = null,
    @Serializable(with = LenientNullableInt::class) @SerialName("spool_id") val spoolId: Int? = null,
    val slot: String? = null,
    val observe: Boolean = false,
    val undone: Boolean = false,
    val error: String? = null,
)

/** A JSON string or number, read as text. */
internal object TextId : KSerializer<String> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("TextId", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): String {
        val el = (decoder as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement()
        return (el as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content ?: throw SerializationException("id missing")
    }
    override fun serialize(encoder: Encoder, value: String) = encoder.encodeString(value)
}

// ---- end bridge part 2 ---------------------------------------------------------------------------------

/*
 * Printer numbers pass through from Bambu reports, which mix integers, decimals (`64.0`, `25.5`) and numeric strings
 * (`"28.5"`). These serializers accept any of them (and null); integer fields are rounded. An unreadable value
 * becomes null (or 0 for a non-null field) instead of failing the whole status.
 */
private fun JsonElement.number(): Double? =
    (this as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content?.toDoubleOrNull()?.takeIf { it.isFinite() }

private fun Decoder.number(): Double? =
    (this as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement().number()

@OptIn(ExperimentalSerializationApi::class)
internal abstract class LenientNullable<T : Number>(name: String, kind: PrimitiveKind, private val convert: (Double) -> T) :
    KSerializer<T?> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor(name, kind).nullable
    override fun deserialize(decoder: Decoder): T? = decoder.number()?.let(convert)
    override fun serialize(encoder: Encoder, value: T?) =
        (encoder as JsonEncoder).encodeJsonElement(if (value == null) JsonNull else JsonPrimitive(value))
}

internal object LenientDouble : LenientNullable<Double>("LenientDouble", PrimitiveKind.DOUBLE, { it })
internal object LenientNullableInt : LenientNullable<Int>("LenientNullableInt", PrimitiveKind.INT, { it.roundToInt() })
internal object LenientNullableLong : LenientNullable<Long>("LenientNullableLong", PrimitiveKind.LONG, { it.roundToLong() })

internal object LenientInt : KSerializer<Int> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("LenientInt", PrimitiveKind.INT)
    override fun deserialize(decoder: Decoder): Int = decoder.number()?.roundToInt() ?: 0
    override fun serialize(encoder: Encoder, value: Int) = encoder.encodeInt(value)
}
// ---- end printer models ------------------------------------------------------------------------------

/**
 * The tag a read was made with. The server echoes it as `{"nfc_id": uid}`; a bare string (older drafts) is accepted
 * too. Written back as the bare uid.
 */
@OptIn(ExperimentalSerializationApi::class)
internal object ReadTag : KSerializer<String?> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("ReadTag", PrimitiveKind.STRING).nullable
    override fun deserialize(decoder: Decoder): String? {
        val el = (decoder as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement()
        val value = (el as? JsonObject)?.get("nfc_id") ?: el
        return (value as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
    }
    override fun serialize(encoder: Encoder, value: String?) =
        (encoder as JsonEncoder).encodeJsonElement(if (value == null) JsonNull else JsonPrimitive(value))
}

// ---- stage 4: profiles, library and PC sync status (global-constraints "Sync and profiles API contract") ------

/** The newest good build: [presets] preset files, [problems] lines skipped or reported. [created] is a server time. */
@Serializable
data class BuildInfo(
    val stamp: String = "",
    @SerialName("live_hash") val liveHash: String? = null,
    @Serializable(with = LenientText::class) val created: String? = null,
    @Serializable(with = LenientInt::class) val presets: Int = 0,
    @Serializable(with = LenientInt::class) val problems: Int = 0,
)

/** The last build run; [error] says why it failed when [ok] is false. */
@Serializable
data class BuildAttempt(
    @Serializable(with = LenientText::class) val at: String? = null,
    @Serializable(with = LenientBool::class) val ok: Boolean = false,
    val error: String? = null,
)

/** The build the sync PC last installed into Bambu Studio. */
@Serializable
data class InstalledInfo(val stamp: String = "", @Serializable(with = LenientText::class) val at: String? = null)

/** Changed presets already in the slicers ([count] on [lines] lines, [accepted] of them already accepted). */
@Serializable
data class UpdatesInfo(
    @Serializable(with = LenientInt::class) val count: Int = 0,
    @Serializable(with = LenientInt::class) val lines: Int = 0,
    @Serializable(with = LenientInt::class) val accepted: Int = 0,
)

/** The paired PC that syncs Bambu Studio. */
@Serializable
data class PcInfo(
    @SerialName("device_id") val deviceId: String = "",
    @Serializable(with = LenientText::class) @SerialName("last_upload") val lastUpload: String? = null,
)

/** The spec library: [source] `bundled` or `updated`; [local] the owner's own additions. */
@Serializable
data class LibraryInfo(
    @Serializable(with = LenientText::class) val version: String? = null,
    val source: String = "bundled",
    @Serializable(with = LenientInt::class) val local: Int = 0,
    @SerialName("last_check") val lastCheck: BuildAttempt? = null,
)

/** One preset in the slicers a newer build would change ([keys]); [accepted]: the PC sync writes it at its next run. */
@Serializable
data class PresetUpdate(
    val name: String = "",
    /** The slicer: "bambu_studio" or "orca". */
    val target: String = "",
    @SerialName("line_id") val lineId: String? = null,
    val keys: List<String> = emptyList(),
    @Serializable(with = LenientBool::class) val accepted: Boolean = false,
)

/** `GET /api/profiles/updates` (FB-041): what a newer build would change, for the build [stamp]. */
@Serializable
data class PresetUpdates(
    val stamp: String? = null,
    @Serializable(with = LenientInt::class) val count: Int = 0,
    @Serializable(with = LenientInt::class) val accepted: Int = 0,
    val updates: List<PresetUpdate> = emptyList(),
    /** Presets never written over: the owner's own preset of that name in Bambu Studio. */
    val yours: List<String> = emptyList(),
) {
    /** What Accept takes: the updates not accepted yet, exactly as shown. */
    val waiting: List<PresetUpdate> get() = updates.filter { !it.accepted }
}

/** `POST /api/profiles/updates/accept`: the presets accepted (one object each). */
@Serializable
data class AcceptedUpdates(val stamp: String? = null, val accepted: List<JsonObject> = emptyList())

/** `GET /api/profiles/status`. [stale]: presets no longer generated, to delete in Bambu Studio. */
@Serializable
data class ProfileStatus(
    @Serializable(with = LenientInt::class) val lines: Int = 0,
    @Serializable(with = LenientInt::class) val presets: Int = 0,
    val build: BuildInfo? = null,
    @SerialName("last_attempt") val lastAttempt: BuildAttempt? = null,
    val installed: InstalledInfo? = null,
    val pc: PcInfo? = null,
    val updates: UpdatesInfo? = null,
    val library: LibraryInfo? = null,
    val stale: List<String> = emptyList(),
    val problems: List<String> = emptyList(),
)

/** One product line (`GET /api/profiles/lines`); [bambuParent] is null when no parent was found. */
@Serializable
data class ProfileLine(
    @SerialName("line_id") val lineId: String,
    val vendor: String = "",
    val product: String = "",
    val material: String = "",
    @SerialName("bambu_parent") val bambuParent: String? = null,
    @SerialName("parent_source") val parentSource: String = "none",
    @SerialName("spoolman_ids") val spoolmanIds: List<Int> = emptyList(),
    @Serializable(with = LenientInt::class) val presets: Int = 0,
)

/** Text where the Hub may send null (a Spoolman field left empty): null reads as "". */
internal object TextOrEmpty : KSerializer<String> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("TextOrEmpty", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): String {
        val el = (decoder as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement()
        return (el as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content.orEmpty()
    }
    override fun serialize(encoder: Encoder, value: String) = encoder.encodeString(value)
}

/** One Spoolman filament no preset line records (`GET /api/profiles/uncovered`); [linesForVendor]: the lines of its brand. */
@Serializable
data class UncoveredFilament(
    @Serializable(with = LenientInt::class) val id: Int = 0,
    @Serializable(with = TextOrEmpty::class) val vendor: String = "",
    @Serializable(with = TextOrEmpty::class) val name: String = "",
    @Serializable(with = TextOrEmpty::class) val material: String = "",
    @SerialName("lines_for_vendor") val linesForVendor: List<String> = emptyList(),
)

/** `POST /api/profiles/build`: [requested] true when the Hub took the request; [output] is the Hub's own text. */
@Serializable
data class BuildRequested(val requested: Boolean = false, val output: String = "")

/** `POST /api/profiles/propose`: the line and parent the server would use; [exists] when the line is known. */
@Serializable
data class Proposal(
    @SerialName("line_id") val lineId: String = "",
    val line: String = "",
    @SerialName("bambu_parent") val bambuParent: String? = null,
    @SerialName("parent_source") val parentSource: String = "none",
    val exists: Boolean = false,
)

/** `GET /api/profiles/parents`; [synced] false while the PC has not uploaded Bambu Studio's system presets. */
@Serializable
data class ParentList(val parents: List<String> = emptyList(), val synced: Boolean = false)

/** `GET /api/profiles/orca-parents`: the Orca Slicer parents of a material; empty until an Orca library is uploaded. */
@Serializable
data class OrcaParentList(@SerialName("orca_parents") val parents: List<String> = emptyList())

/** `POST /api/library/local` (201). */
@Serializable
data class LocalEntryResult(val entry: JsonObject = JsonObject(emptyMap()), @SerialName("line_id") val lineId: String = "")

/** A string or a number (times may be ISO text or epoch seconds), read as text; null stays null. */
@OptIn(ExperimentalSerializationApi::class)
internal object LenientText : KSerializer<String?> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("LenientText", PrimitiveKind.STRING).nullable
    override fun deserialize(decoder: Decoder): String? {
        val el = (decoder as? JsonDecoder ?: throw SerializationException("JSON only")).decodeJsonElement()
        return (el as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
    }
    override fun serialize(encoder: Encoder, value: String?) =
        (encoder as JsonEncoder).encodeJsonElement(if (value == null) JsonNull else JsonPrimitive(value))
}

// ---- end stage 4 -----------------------------------------------------------------------------------------------

// ---- map by loading filament (manual slot mapping API v2, 2026-11-09) ----------------------------------------

/** A position the owner can load from; [id] is its slot label. [status]: `pending`, `confirmed`, `by_hand`, `skipped`. */
@Serializable
data class ManualPosition(
    val id: String,
    val label: String,
    val status: String = "pending",
    @SerialName("reported_label") val reportedLabel: String? = null,
    val nozzle: String? = null,
)

/** What the printer now reports loaded; [reported] is opaque and goes back unchanged in a confirm. */
@Serializable
data class ManualSeen(
    val reported: JsonObject = JsonObject(emptyMap()),
    @SerialName("reported_label") val reportedLabel: String = "",
    val nozzle: String? = null,
    @SerialName("nozzle_reported") val nozzleReported: Boolean = false,
    val settled: Boolean = false,
)

@Serializable
data class ManualStepPosition(val id: String, val label: String)

/** The position asked now: [say] is the instruction, [ask] the question once a load has settled (null before). */
@Serializable
data class ManualStep(
    val position: ManualStepPosition,
    val say: String = "",
    val seen: ManualSeen? = null,
    val ask: String? = null,
)

/** A slot the owner can pick by hand when the printer reports no loads. */
@Serializable
data class ManualChoice(val reported: JsonObject = JsonObject(emptyMap()), val label: String)

/**
 * `GET /api/printers/{id}/manual-map`: one session per printer, shared with the setup page. [step] is null once every
 * position has an answer or the session is closed; [choices] comes with [reportsLoads] false; [offerReport]: the
 * one-time question whether to share the map in a printer report, after a closed session that confirmed something.
 */
@Serializable
data class ManualMapState(
    val session: String = "",
    val open: Boolean = false,
    @SerialName("dual_nozzle") val dualNozzle: Boolean = false,
    @SerialName("reports_loads") val reportsLoads: Boolean = true,
    val step: ManualStep? = null,
    val positions: List<ManualPosition> = emptyList(),
    val summary: String = "",
    @SerialName("offer_report") val offerReport: Boolean = false,
    val choices: List<ManualChoice> = emptyList(),
)

/** `POST .../manual-map/offer`: the server's sentence for the owner's answer. */
@Serializable
data class ManualOfferAnswer(val share: Boolean = false, val message: String = "")

// ---- phase 3 (R83 section 10.1): clear a slot, the Hub at a glance, the owner's own catalog entries, spools --------
// Read leniently: unknown keys are ignored and an absent or null optional part is its default, so an older or newer Hub
// never crashes the app.

/** `POST /api/printers/{id}/slots/{label}/clear`. A dry run only says what would happen ([dryRun] true). */
data class ClearResult(
    val slot: String,
    /** The spool that was recorded in the slot (its view), or null when none was. */
    val spool: JsonObject?,
    /** Where that spool goes back to. */
    val movedBack: String?,
    /** A spool that was waiting for this slot is waiting no more. */
    val waitingEnded: Boolean,
    /** The slot's setting on the printer was cleared too (Klipper, printer online). */
    val printerCleared: Boolean,
    val dryRun: Boolean,
    /** The Hub's own sentence about what the printer still shows (Bambu Lab, R83); absent on older answers. */
    val text: String? = null,
)

/** One row of Status: [state] is how the Hub rates it, [fix] the line that says what to do. */
data class HubCheck(val group: String, val state: HubCheckState, val text: String, val fix: String?)

/** A check's `state`: `ok`, `look` (needs a look), `note`, `off`; anything else reads as a note. */
enum class HubCheckState {
    Ok, Look, Note, Off;

    companion object {
        fun of(wire: String?): HubCheckState = when (wire) {
            "ok" -> Ok
            "look" -> Look
            "off" -> Off
            else -> Note
        }
    }
}

/** The Getting started counts of `GET /api/hub`. */
data class GettingStarted(val done: Int, val total: Int, val hidden: Boolean, val finished: Boolean)

data class HubFeature(val id: String, val name: String, val on: Boolean)

/** A device by name only (no addresses); [kind] is `phone`, `pc`, `station`, `web`, `reader` or `builtin`. */
data class HubDevice(
    val name: String,
    val kind: String,
    val version: String?,
    val lastSeen: String?,
    val outOfDate: Boolean,
    /** The device that asked. */
    val thisOne: Boolean,
)

data class HubNewest(val version: String, val checkedAt: String?)

data class HubCatalogFacts(val version: String?, val checkedAt: String?)

data class HubBackupFacts(val lastAt: String?, val nightly: Boolean)

/** The Label Reader: its engine, and whether a key is set (the key itself is never sent). */
data class HubReaderFacts(val engine: String, val keySet: Boolean)

/** `GET /api/hub`. The optional groups are null when the Hub left them out; [hubPage] and [spoolmanUrl] when unreachable. */
data class HubAnswer(
    val name: String,
    val version: String,
    val newest: HubNewest?,
    val updateAvailable: Boolean,
    val checks: List<HubCheck>,
    val gettingStarted: GettingStarted?,
    val features: List<HubFeature>,
    val catalog: HubCatalogFacts?,
    val backup: HubBackupFacts?,
    val reader: HubReaderFacts?,
    val devices: List<HubDevice>,
    val recordsKept: Long?,
    val spoolmanUrl: String?,
    val hubPage: String?,
)

/**
 * One of the owner's own Filament Catalog entries (`GET /api/library/local`). [added] is a plain date `YYYY-MM-DD` as the
 * Hub gives it (R83 section 10); `hubDay` reads that, ISO text and whole seconds since 1970.
 */
data class LocalEntry(val id: String, val brand: String, val name: String, val material: String, val added: String?)

/** `GET /api/library/local`: the entries and the materials the catalog knows ([materials] null: an older Hub sent none). */
data class LocalLibrary(val entries: List<LocalEntry>, val materials: List<String>?)

/** One refused field of the catalog form: 400 `invalid_entry`, `problems: [{field, text}]`. */
data class EntryProblem(val field: String, val text: String)

/** `GET /api/spools` with its `spoolman_url` (absent when Spoolman cannot be reached from where the phone is). */
data class SpoolsAnswer(val spools: List<JsonObject>, val spoolmanUrl: String?)

/** Where a spool is loaded: the `loaded` field of the spool view. */
data class SpoolLoaded(val printerId: String, val printer: String, val slot: String)

/** The `filter` values of `GET /api/spools`; one at a time, none = every spool that is not empty. */
object SpoolFilter {
    const val SEALED = "sealed"
    const val OPENED = "opened"
    const val LOADED = "loaded"
    const val LOW = "low"
}

object KitWire {
    fun clear(root: JsonElement): ClearResult {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        return ClearResult(
            slot = o.str("slot").orEmpty(),
            spool = o["spool"] as? JsonObject,
            movedBack = o.str("moved_back")?.takeIf { it.isNotBlank() },
            waitingEnded = o.bool("waiting_ended") ?: false,
            printerCleared = o.bool("printer_cleared") ?: false,
            dryRun = o.bool("dry_run") ?: true,
            text = o.str("text")?.takeIf { it.isNotBlank() },
        )
    }

    fun hub(root: JsonElement): HubAnswer {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        return HubAnswer(
            name = o.str("name").orEmpty(),
            version = o.str("version").orEmpty(),
            newest = (o["newest"] as? JsonObject)?.let { n ->
                n.str("version")?.takeIf { it.isNotBlank() }?.let { HubNewest(it, n.str("checked_at")) }
            },
            updateAvailable = o.bool("update_available") ?: false,
            checks = o.objects("checks").map { c ->
                HubCheck(c.str("group").orEmpty(), HubCheckState.of(c.str("state")), c.str("text").orEmpty(), c.str("fix")?.takeIf { it.isNotBlank() })
            },
            gettingStarted = (o["getting_started"] as? JsonObject)?.let { g ->
                GettingStarted(
                    done = g.long("done")?.toInt() ?: 0,
                    total = g.long("total")?.toInt() ?: 0,
                    hidden = g.bool("hidden") ?: false,
                    finished = g.bool("finished") ?: false,
                )
            },
            features = o.objects("features").map { HubFeature(it.str("id").orEmpty(), it.str("name").orEmpty(), it.bool("on") ?: false) },
            catalog = (o["catalog"] as? JsonObject)?.let { HubCatalogFacts(it.str("version"), it.str("checked_at")) },
            backup = (o["backup"] as? JsonObject)?.let { HubBackupFacts(it.str("last_at"), it.bool("nightly") ?: false) },
            reader = (o["reader"] as? JsonObject)?.let { HubReaderFacts(it.str("engine").orEmpty(), it.bool("key_set") ?: false) },
            devices = o.objects("devices").map { d ->
                HubDevice(
                    name = d.str("name").orEmpty(),
                    kind = d.str("kind").orEmpty(),
                    version = d.str("version"),
                    lastSeen = d.str("last_seen"),
                    outOfDate = d.bool("out_of_date") ?: false,
                    thisOne = d.bool("this") ?: false,
                )
            },
            recordsKept = o.long("records_kept"),
            spoolmanUrl = o.str("spoolman_url")?.takeIf { it.isNotBlank() },
            hubPage = o.str("hub_page")?.takeIf { it.isNotBlank() },
        )
    }

    fun localEntries(root: JsonElement): List<LocalEntry> =
        ((root as? JsonObject)?.get("entries") as? JsonArray).orEmpty().mapNotNull { localEntry(it) }

    /** The entries and, when the answer has a `materials` list, its non-blank names (an empty list stays empty). */
    fun localLibrary(root: JsonElement): LocalLibrary {
        val materials = ((root as? JsonObject)?.get("materials") as? JsonArray)?.mapNotNull {
            (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.contentOrNull?.trim()?.takeIf { s -> s.isNotEmpty() }
        }
        return LocalLibrary(localEntries(root), materials)
    }

    /** Null for an element without an id (it could not be removed). */
    fun localEntry(element: JsonElement): LocalEntry? {
        val o = element as? JsonObject ?: return null
        val id = o.str("id")?.takeIf { it.isNotBlank() } ?: return null
        return LocalEntry(id, o.str("brand").orEmpty(), o.str("name").orEmpty(), o.str("material").orEmpty(), o.str("added"))
    }

    /** The refused fields of a 400 `invalid_entry`; empty for any other error. */
    fun problems(e: ApiError): List<EntryProblem> =
        if (e.code != "invalid_entry") emptyList()
        else (e.extra["problems"] as? JsonArray).orEmpty().mapNotNull { p ->
            val o = p as? JsonObject ?: return@mapNotNull null
            EntryProblem(o.str("field").orEmpty(), o.str("text").orEmpty())
        }

    fun spools(root: JsonElement): SpoolsAnswer {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        return SpoolsAnswer(
            spools = (o["spools"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject },
            spoolmanUrl = o.str("spoolman_url")?.takeIf { it.isNotBlank() },
        )
    }

    /** The spool view of a row of `GET /api/spools`: its `view` object when it has one, else the row itself. */
    fun spoolView(row: JsonObject): JsonObject = row["view"] as? JsonObject ?: row

    /** The view's `loaded` (null when the spool is in no slot or the Hub is older). */
    fun spoolLoaded(row: JsonObject): SpoolLoaded? {
        val l = spoolView(row)["loaded"] as? JsonObject ?: return null
        val slot = l.str("slot")?.takeIf { it.isNotBlank() } ?: return null
        return SpoolLoaded(l.str("printer_id").orEmpty(), l.str("printer").orEmpty(), slot)
    }

    /** The view's `low`: running low. */
    fun spoolLow(row: JsonObject): Boolean = spoolView(row).bool("low") ?: false

    private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
    private fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.let { it.longOrNull ?: it.doubleOrNull?.toLong() }
    private fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull
    private fun JsonObject.objects(key: String): List<JsonObject> = (this[key] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
}

// ---- history and data (R84 section 9): events with undo, health, usage by month ----
// Parsed leniently like the rest of KitWire: a missing field is a default, so an older Hub never crashes the app.

/** Why the Hub refuses an undo (`why_not`, also the `error` of a 409 `POST api/events/{id}/undo`). */
object UndoWhyNot {
    const val CHANGED_SINCE = "changed_since"
    const val TOO_OLD = "too_old"
    const val ALREADY_UNDONE = "already_undone"
    const val NOT_UNDOABLE = "not_undoable"
}

/** An event's `undo`: [possible] with the time the Hub allows it until, or the [whyNot] it cannot be undone. */
data class UndoState(val possible: Boolean, val until: String?, val whyNot: String?)

/**
 * One event of `GET api/events?activity=1`. [who] is the actor's name (its type when it has none), [text] the Hub's
 * sentence for it. [undo] is null when the Hub sent none (an older Hub: nothing can be undone from the app).
 */
data class ActivityEvent(
    val id: Long,
    val at: String,
    val atMillis: Long?,
    val kind: String,
    val who: String,
    val text: String,
    val subject: String?,
    val undo: UndoState?,
    val undone: Boolean,
    val undoOf: Long?,
) {
    /** The row keeps Undo while the Hub allows it. */
    val canUndo: Boolean get() = undo?.possible == true && !undone
}

/** `POST api/events/{id}/undo` 200: [event] is the new event's id, [note] what the Hub adds (a load or unload). */
data class UndoAnswer(val undone: Boolean, val eventId: Long?, val note: String?)

/** One check of `GET api/health`: [now] is `ok`, `look` or `bad`. */
data class HealthCheck(val key: String, val group: String, val text: String, val now: String)

/** One change of state of a check: [from] and [to] are `ok`, `look` or `bad`. */
data class HealthChange(val at: String, val atMillis: Long?, val key: String, val text: String, val from: String, val to: String)

/** `GET api/health`: [since] is when history starts, when the Hub says (the days before it are empty). */
data class HealthAnswer(
    val from: String?,
    val to: String?,
    val since: String?,
    val checks: List<HealthCheck>,
    val changes: List<HealthChange>,
)

/** One month of `GET api/printers/{id}/usage?by=month`. */
data class UsageMonth(
    /** `2026-11`. */
    val month: String,
    val grams: Double,
    val prints: Int,
    val unfinishedPrints: Int,
    val topMaterial: String?,
)

object HistoryWire {
    fun event(element: JsonElement): ActivityEvent? {
        val o = element as? JsonObject ?: return null
        val id = o.long("id") ?: return null
        val actor = o["actor"] as? JsonObject
        val subject = o["subject"] as? JsonObject
        val subjectType = subject?.str("type")?.takeIf { it.isNotBlank() }
        val at = o.str("at").orEmpty()
        return ActivityEvent(
            id = id,
            at = at,
            atMillis = runCatching { java.time.Instant.parse(at).toEpochMilli() }.getOrNull(),
            kind = o.str("kind").orEmpty(),
            who = actor?.str("name")?.takeIf { it.isNotBlank() } ?: actor?.str("type").orEmpty(),
            text = o.str("text")?.takeIf { it.isNotBlank() } ?: o.str("title").orEmpty(),
            subject = subjectType?.let { t -> "$t:${subject.str("id").orEmpty()}" },
            undo = (o["undo"] as? JsonObject)?.let { u ->
                UndoState(u.bool("possible") ?: false, u.str("until")?.takeIf { it.isNotBlank() }, u.str("why_not")?.takeIf { it.isNotBlank() })
            },
            undone = o.bool("undone") ?: false,
            undoOf = o.long("undo_of"),
        )
    }

    /**
     * The events of an answer, newest first. An older Hub ignores `subject` and sends every event, so when [subject] is
     * given only the events that name it are kept.
     */
    fun events(root: JsonElement, subject: String? = null): List<ActivityEvent> =
        ((root as? JsonObject)?.get("events") as? JsonArray).orEmpty().mapNotNull(::event)
            .filter { subject == null || it.subject == subject }
            .sortedByDescending { it.id }

    fun undo(root: JsonElement): UndoAnswer {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        val ev = o["event"]
        return UndoAnswer(
            undone = o.bool("undone") ?: true,
            eventId = (ev as? JsonObject)?.long("id") ?: (ev as? JsonPrimitive)?.longOrNull,
            note = o.str("note")?.takeIf { it.isNotBlank() },
        )
    }

    fun health(root: JsonElement): HealthAnswer {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        return HealthAnswer(
            from = o.str("from"),
            to = o.str("to"),
            since = o.str("since")?.takeIf { it.isNotBlank() },
            checks = o.objects("checks").mapNotNull { c ->
                val key = c.str("key") ?: return@mapNotNull null
                HealthCheck(key, c.str("group").orEmpty(), c.str("text").orEmpty(), c.str("now") ?: "ok")
            },
            changes = o.objects("changes").mapNotNull { c ->
                val key = c.str("key") ?: return@mapNotNull null
                val at = c.str("at").orEmpty()
                HealthChange(
                    at, runCatching { java.time.Instant.parse(at).toEpochMilli() }.getOrNull(),
                    key, c.str("text").orEmpty(), c.str("from") ?: "ok", c.str("to") ?: "ok",
                )
            },
        )
    }

    /** The months of `usage?by=month`, newest first; a row without a month is dropped. */
    fun months(root: JsonElement): List<UsageMonth> =
        (root as? JsonObject)?.objects("months").orEmpty().mapNotNull { m ->
            val month = m.str("month")?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            UsageMonth(
                month = month,
                grams = (m["grams"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                prints = m.long("prints")?.toInt() ?: 0,
                unfinishedPrints = m.long("unfinished_prints")?.toInt() ?: 0,
                topMaterial = m.str("top_material")?.takeIf { it.isNotBlank() },
            )
        }.sortedByDescending { it.month }

    private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
    private fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.let { it.longOrNull ?: it.doubleOrNull?.toLong() }
    private fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull
    private fun JsonObject.objects(key: String): List<JsonObject> = (this[key] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
}
