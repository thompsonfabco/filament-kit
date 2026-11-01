package com.thompsonfabco.filamentkit.tags

/** Canonical tag UID: lowercase hex bytes joined by ':' with no padding (matches server `format_uid`). */
fun formatUid(uid: ByteArray): String = uid.joinToString(":") { (it.toInt() and 0xFF).toString(16) }
