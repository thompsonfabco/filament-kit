package com.thompsonfabco.filamentkit.ui

/** A weight in grams the app will send or store: finite and above zero (no NaN, no Infinity). */
fun isValidWeight(grams: Double): Boolean = grams.isFinite() && grams > 0

/** Parses typed grams; null for blank, junk, zero, negative or non-finite text ("NaN", "Infinity", "1e400"). */
fun parseWeight(text: String): Double? = text.trim().toDoubleOrNull()?.takeIf(::isValidWeight)
