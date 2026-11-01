package com.thompsonfabco.filamentkit.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
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

// ---- printer models (Task 16) ------------------------------------------------------------------------
// Mirrors the server's printer routes (`api.py` `_printer_view`, `bridge/status.py` `summarize`).

/** `camera.kind`: `hls`, `mjpeg`, or null when the app cannot show this model's camera. */
@Serializable
data class PrinterCamera(val kind: String? = null)

/** The list's condensed status. */
@Serializable
data class PrinterSummary(
    @SerialName("gcode_state") val gcodeState: String = "UNKNOWN",
    val percent: Int = 0,
    @SerialName("remaining_min") val remainingMin: Int = 0,
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
data class Temp(val current: Int? = null, val target: Int? = null)

@Serializable
data class Temps(val nozzle: List<Temp> = emptyList(), val bed: Temp? = null, val chamber: Temp? = null)

@Serializable
data class SlotSpool(
    val id: Int? = null,
    val name: String = "",
    val material: String = "",
    @SerialName("color_hex") val colorHex: String = "",
    @SerialName("remaining_weight") val remainingWeight: Double? = null,
)

@Serializable
data class AmsSlot(
    val slot: Int,
    val label: String = "",
    val type: String = "",
    @SerialName("color_hex") val colorHex: String = "",
    val active: Boolean = false,
    val spool: SlotSpool? = null,
)

/** [kind] is `ams` or `ams_ht`. */
@Serializable
data class AmsUnit(val unit: Int, val label: String = "", val kind: String = "ams", val slots: List<AmsSlot> = emptyList())

@Serializable
data class HmsAlert(val code: String, val text: String = "")

/** `GET /api/printers/{id}` `status`. [eta] is ISO-8601 to the minute or null; [light] `on`/`off`/null. */
@Serializable
data class PrinterStatus(
    @SerialName("gcode_state") val gcodeState: String = "UNKNOWN",
    val stage: String = "",
    val job: String = "",
    val percent: Int = 0,
    val layer: Int? = null,
    @SerialName("total_layers") val totalLayers: Int? = null,
    @SerialName("remaining_min") val remainingMin: Int = 0,
    val eta: String? = null,
    val temps: Temps = Temps(),
    val ams: List<AmsUnit> = emptyList(),
    val hms: List<HmsAlert> = emptyList(),
    val light: String? = null,
    val updated: Long? = null,
)

/** [status] is null while the server has no connection to the printer. */
@Serializable
data class PrinterDetail(val printer: Printer, val status: PrinterStatus? = null)

/** `POST /api/printers/{id}/command`; [reply] is the server's `{ok, reply}` result for the printer's answer. */
@Serializable
data class CommandResult(val ok: Boolean = false, val reply: JsonElement? = null)
// ---- end printer models ------------------------------------------------------------------------------
