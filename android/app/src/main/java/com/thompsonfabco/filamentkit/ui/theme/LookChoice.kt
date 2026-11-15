package com.thompsonfabco.filamentkit.ui.theme

/** The name a look has in `GET api/info` and in the settings store: `console`, `workbench`, `palette`, `panes`. */
val Look.wire: String get() = name.lowercase()

/** The look named [text] by the Hub or the store; null when it is missing or not one of the four. */
fun lookFromWire(text: String?): Look? = Look.entries.firstOrNull { it.wire == text }

/**
 * The looks whose layouts the app has built (08-platform-mapping 9: a look is drawn only when the screens can): all four.
 */
internal val BUILT_LOOKS: List<Look> = Look.entries

/**
 * The look to draw: the phone's own choice wins; a phone that has not chosen follows the Hub's default (the answer of
 * `GET api/info`, kept from the last time); with neither, or when the one named is not built, Console.
 */
internal fun resolveLook(chosen: Look?, hub: Look?, built: List<Look> = BUILT_LOOKS): Look =
    chosen?.takeIf { it in built } ?: hub?.takeIf { it in built } ?: Look.Console
