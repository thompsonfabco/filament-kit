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
) {
    /** The label-photo add flow is offered: `ai_intake` is on (or the server is too old to say). */
    val labelReading: Boolean get() = modules == null || AI_INTAKE in modules

    companion object {
        const val AI_INTAKE = "ai_intake"
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
)

/** `POST /api/intake/add`. [dry] is true for a preview (nothing written). */
@Serializable
data class AddResult(
    @SerialName("spool_ids") val spoolIds: List<Int> = emptyList(),
    val lines: List<String> = emptyList(),
    val dry: Boolean = true,
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
) : Exception(message)

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
) {
    /** What to show for the model: its name, else the code an older server sent, else null. */
    val shownModel: String? get() = modelName?.takeIf { it.isNotBlank() } ?: model?.takeIf { it.isNotBlank() }
}

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

/**
 * [say] is how the slot is spoken (`["external", "left"]`); [present] / [reading] are null when unknown. Older
 * servers send none of the three.
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
)

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

/** `GET /api/profiles/status`. [stale]: presets no longer generated, to delete in Bambu Studio. */
@Serializable
data class ProfileStatus(
    @Serializable(with = LenientInt::class) val lines: Int = 0,
    @Serializable(with = LenientInt::class) val presets: Int = 0,
    val build: BuildInfo? = null,
    @SerialName("last_attempt") val lastAttempt: BuildAttempt? = null,
    val installed: InstalledInfo? = null,
    val pc: PcInfo? = null,
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
