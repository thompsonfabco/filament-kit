package com.thompsonfabco.filamentkit.ui.search

/**
 * The text of the Spools screen's Open Spoolman item (EV7b) that is not in the string catalogue yet. Only the catalogue
 * step (EV2) opens `strings/en.json`; the text has a proposed key in the EV7b report and moves there with it.
 */
object SearchTexts {
    const val OPEN_SPOOLMAN = "Open Spoolman"
}

/**
 * The address of Spoolman's own page as the Hub gave it (`spoolman_url`, R83 section 7), or null when there is none or
 * it is not a web address: the item is then not offered. The app never builds the address itself.
 */
internal fun spoolmanLink(url: String?): String? {
    val link = url?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    return link.takeIf { it.startsWith("http://", ignoreCase = true) || it.startsWith("https://", ignoreCase = true) }
}
