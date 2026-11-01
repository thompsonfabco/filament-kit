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
 * One printer. [state] is `connected`, `offline`, `wrong_code`, `needs_developer_mode` or `not_configured`;
 * [id] is the serial. The Access Code is never part of this.
 */
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
    val summary: PrinterSummary = PrinterSummary(),
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

@Serializable
data class AmsSlot(
    @Serializable(with = LenientInt::class) val slot: Int,
    val label: String = "",
    val type: String = "",
    @SerialName("color_hex") val colorHex: String = "",
    val active: Boolean = false,
    val spool: SlotSpool? = null,
)

/** [kind] is `ams` or `ams_ht`. */
@Serializable
data class AmsUnit(@Serializable(with = LenientInt::class) val unit: Int, val label: String = "", val kind: String = "ams", val slots: List<AmsSlot> = emptyList())

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
