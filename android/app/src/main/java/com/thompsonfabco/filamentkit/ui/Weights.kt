package com.thompsonfabco.filamentkit.ui

/** A weight in grams the app will send or store: finite and above zero (no NaN, no Infinity). */
fun isValidWeight(grams: Double): Boolean = grams.isFinite() && grams > 0

/** Parses typed grams; null for blank, junk, zero, negative or non-finite text ("NaN", "Infinity", "1e400"). */
fun parseWeight(text: String): Double? = text.trim().toDoubleOrNull()?.takeIf(::isValidWeight)

/** Why Update weight can't be tapped yet; null when it can. */
fun weightHint(text: String): String? = when {
    parseWeight(text) != null -> null
    text.isBlank() -> "Type the weight on the scale to update it."
    else -> "Type a weight in grams, more than 0."
}

const val TARE_PROBLEM = "Empty spool weight must be more than 0 g"

/** The inline message for a typed empty-spool weight (tare); null when blank (unknown) or above 0 g. */
fun tareProblem(text: String): String? = if (text.isBlank() || parseWeight(text) != null) null else TARE_PROBLEM
