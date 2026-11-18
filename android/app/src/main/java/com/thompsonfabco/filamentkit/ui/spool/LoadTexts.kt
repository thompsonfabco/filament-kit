package com.thompsonfabco.filamentkit.ui.spool

/**
 * The texts of the load result that are not in the string catalogue yet (EV7b). Only the catalogue step (EV2) opens
 * `strings/en.json`; each text here has a proposed key in the EV7b report and moves there with it. "Waiting for the
 * spool to load" (the slot rows) is a catalogue text already (`slot_waiting`).
 */
object LoadTexts {
    /** The result of a load the printer has not carried out yet; [slot] is the slot's label. */
    fun waitingIn(slot: String): String = "Waiting for the spool to load in $slot."
}
