package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.net.ReadResult
import com.thompsonfabco.filamentkit.net.RevisionProposal
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlin.math.roundToInt

/**
 * Which label reader answered (the server's local reader or Claude) and how sure it was (local-intake handoff
 * 2026-11-12-1317). A server older than that sends no `reader`: the texts then say Claude, as before.
 */
object ReaderTexts {
    /** A field below this is "least sure" (the server's own threshold for an unsure item). */
    const val SURE = 0.78

    /** What the result screen keeps of a read: who answered, its summary line, and the server's note. */
    data class Info(val reader: String?, val line: String?, val note: String?) {
        val local: Boolean get() = reader == "local"
        /** The questions card's title and the prefix of the reader's own remarks. */
        val name: String get() = if (local) "The local reader" else "Claude"
    }

    fun info(r: ReadResult): Info = Info(r.reader, line(r), r.note?.takeIf { it.isNotBlank() })

    fun pct(c: Double): String = "${(c * 100).roundToInt()} %"

    /** "Read by the local reader (gpu tier, after the CPU tier), 86 % sure (unsure: check the fields)"; null: old server. */
    fun line(r: ReadResult): String? = when (r.reader) {
        "local" -> buildString {
            append("Read by the local reader (${r.tier ?: "?"} tier")
            if (r.escalated) append(", after the CPU tier")
            append(")")
            r.confidence?.let { append(", ${pct(it)} sure") }
            if (r.unsure) append(" (unsure: check the fields)")
        }
        "cloud" -> "Read by Claude"
        else -> null
    }

    /** One item's colour name and family, how sure, and its least sure fields; null when the reader gave none. */
    fun item(it: JsonObject): String? {
        val parts = mutableListOf<String>()
        val name = it.text("color_name")
        val family = it.text("color_family")
        if (name != null || family != null) {
            val shown = if (name != null && name != "unknown") name else "colour name not in the library"
            parts += "Colour: $shown" + (family?.let { f -> " ($f)" } ?: "")
        }
        it.num("confidence")?.let { c -> parts += "${pct(c)} sure" }
        val low = (it["field_confidence"] as? JsonObject).orEmpty()
            .filter { (_, v) -> ((v as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull() ?: 1.0) < SURE }.keys
        if (low.isNotEmpty()) parts += "least sure: " + low.joinToString(", ")
        return parts.takeIf { it.isNotEmpty() }?.joinToString(" · ")
    }

    /** The history proposal: "Read again by the local reader, 93 % sure (note)."; null from an older server. */
    fun revisedBy(p: RevisionProposal): String? {
        val who = when (p.reader) {
            "local" -> "the local reader"
            "cloud" -> "Claude"
            else -> return null
        }
        return "Read again by $who" + (p.confidence?.let { ", ${pct(it)} sure" } ?: "") +
            (p.note?.takeIf { it.isNotBlank() }?.let { " ($it)" } ?: "") + "."
    }

    /** The local reader's failures (`local_<kind>`), worded for the owner; null for any other code. */
    fun localError(code: String): String? = when (code) {
        "local_unreachable" -> "The server can't reach its local label reader. Check that it is running, then retry."
        "local_busy" -> "The local label reader is busy. Wait a moment, then retry."
        "local_refused" -> "The local label reader could not use these photos. Retry, or take different photos."
        "local_unauthorized" -> "The local label reader refused the server's token. Check the reader on the setup page, then retry."
        "local_version" -> "The local label reader does not match this server's version. Update it, then retry."
        "local_tier_unavailable" -> "The local label reader's tier (CPU or GPU) is not available. Change the tier on the setup page, then retry."
        "local_bad_answer" -> "The local label reader gave an answer the server could not use. Retry in a moment."
        "local_revise_unsupported" -> "This local label reader can't revise a reading. Edit by hand instead."
        else -> if (code.startsWith("local_")) "The local label reader could not read the labels this time. Retry in a moment." else null
    }

    private fun JsonObject.text(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()?.takeIf { it.isNotEmpty() }

    private fun JsonObject.num(key: String): Double? =
        (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toDoubleOrNull()
}
