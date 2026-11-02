package com.thompsonfabco.filamentkit.pairing

import java.net.URI
import java.net.URISyntaxException
import java.net.URLDecoder

/** What the server's pairing QR carries: `fkit://pair?h=<host>.local&p=<port>&t=<token>&fp=<sha256 hex>&ip=<ipv4>...`. */
data class PairingPayload(val host: String, val port: Int, val token: String, val fingerprint: String, val ips: List<String>)

private val FINGERPRINT = Regex("[0-9a-fA-F]{64}")

/**
 * Parses the pairing QR text. Values are form-encoded (the server builds them with `urlencode(..., doseq=True)`),
 * `ip` may repeat 0..n times; every other field must appear exactly once.
 *
 * @throws IllegalArgumentException if this is not a filament-kit pairing code or a field is missing or malformed.
 */
fun parsePairingUri(uri: String): PairingPayload {
    val parsed = try {
        URI(uri.trim())
    } catch (e: URISyntaxException) {
        throw IllegalArgumentException("Not a filament-kit pairing code", e)
    }
    require(parsed.scheme.equals("fkit", ignoreCase = true) && parsed.host.equals("pair", ignoreCase = true)) {
        "Not a filament-kit pairing code"
    }

    val params = (parsed.rawQuery ?: "").split('&').filter { it.isNotEmpty() }.map { pair ->
        val i = pair.indexOf('=')
        val key = if (i < 0) pair else pair.substring(0, i)
        val value = if (i < 0) "" else pair.substring(i + 1)
        decode(key) to decode(value)
    }

    fun single(key: String): String {
        val values = params.filter { it.first == key }.map { it.second }
        require(values.size <= 1) { "The pairing code has more than one '$key' value" }
        val value = values.firstOrNull()
        require(!value.isNullOrEmpty()) { "The pairing code is missing '$key'" }
        return value
    }

    val host = single("h")
    val port = single("p").toIntOrNull()
    require(port != null && port in 1..65535) { "The pairing code has an invalid port" }
    val token = single("t")
    val fingerprint = single("fp")
    require(FINGERPRINT.matches(fingerprint)) { "The pairing code has an invalid certificate fingerprint" }
    val ips = params.filter { it.first == "ip" && it.second.isNotEmpty() }.map { it.second }

    return PairingPayload(host, port, token, fingerprint.lowercase(), ips)
}

private fun decode(s: String): String = try {
    URLDecoder.decode(s, "UTF-8") // the Charset overload needs API 33
} catch (e: IllegalArgumentException) {
    throw IllegalArgumentException("The pairing code is not correctly encoded", e)
}
