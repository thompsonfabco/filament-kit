package com.thompsonfabco.filamentkit.ui.printers

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/**
 * The texts of Clear slot and the guided add (EV7b) that are not in the string catalogue yet. Only the catalogue step
 * (EV2) opens `strings/en.json`; each text here has a proposed key in the EV7b report and moves there with it.
 * "Unload", "Cancel", "Back", "Add printer" and "Waiting for the spool to load" are catalogue texts already.
 */
object PrinterTexts {
    const val CLEAR_SLOT = "Clear slot"

    /** An older Hub has no such call (404): said, not hidden, because the button is on every slot. */
    const val CLEAR_UPDATE_HUB = "Update the Hub to clear a slot."

    /** What Unload adds when a spool that was waiting for the slot is waiting no more. */
    const val UNLOAD_WAITING_ENDED = "The spool waiting for this slot is not waiting any more."

    /** The guided add (R82 section 5). "Add a printer", "Use this printer", "Looking…" and "Back" are catalogue texts. */
    const val GUIDE_FOUND = "Found on your network"
    const val GUIDE_NONE = "None found. Type its address in the next step."
    const val GUIDE_BY_ADDRESS = "Type its address"
    const val MAP_TITLE = "Map its slots now?"
    const val MAP_BODY = "Mapping tells the Hub which slot is which. Nothing heats or moves."
    const val MAP_NOW = "Map slots"
    const val MAP_LATER = "Later"

    private const val CLEAR_WAITING_ENDED = "The spool that was waiting for it is not waiting any more."
    private const val CLEAR_PRINTER_CLEARED = "The slot's setting on the printer is cleared too."
    private const val PREVIOUS_PLACE = "its previous place"

    fun clearTitle(label: String): String = "Clear slot $label?"

    /**
     * The question after its title: what the Hub forgets and, only with a recorded [spool], where it goes back to
     * ([place] blank: its previous place).
     */
    fun clearBody(spool: String?, place: String?): String {
        val forgets = "The Hub forgets the spool recorded here."
        if (spool == null) return forgets
        return "$forgets $spool goes back to ${place?.ifBlank { null } ?: PREVIOUS_PLACE}."
    }

    /** The whole question as one text: "Clear slot A1? The Hub forgets ... goes back to Shelf B." */
    fun clearQuestion(label: String, spool: String?, place: String?): String = "${clearTitle(label)} ${clearBody(spool, place)}"

    /** The result of the real call. [spool] and [place] are what the question said. */
    fun clearDone(label: String, spool: String?, place: String?, waitingEnded: Boolean, printerCleared: Boolean): String =
        listOfNotNull(
            "Cleared slot $label.",
            spool?.let { "$it is back on ${place?.ifBlank { null } ?: PREVIOUS_PLACE}." },
            CLEAR_WAITING_ENDED.takeIf { waitingEnded },
            CLEAR_PRINTER_CLEARED.takeIf { printerCleared },
        ).joinToString(" ")

    /** A spool view (`inventory.spool_view`) as a person names it: brand and name, else "spool #id". */
    fun spoolName(view: JsonObject): String {
        fun text(key: String) = (view[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull?.trim()?.ifBlank { null }
        val named = listOfNotNull(text("vendor"), text("name")).joinToString(" ")
        if (named.isNotBlank()) return named
        val id = (view["id"] as? JsonPrimitive)?.let { it.intOrNull?.toString() ?: it.contentOrNull }
        return if (id.isNullOrBlank()) "The spool" else "Spool #$id"
    }
}
