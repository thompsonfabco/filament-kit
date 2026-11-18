package com.thompsonfabco.filamentkit.alerts

import com.thompsonfabco.filamentkit.net.Api
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody

/** A Hub that answers from [handler] without a network: what was asked, and with which read timeout, is recorded. */
internal class FakeHub(var handler: (Request) -> Pair<Int, String> = { 200 to "{}" }) {
    val requests = mutableListOf<Request>()
    val readTimeoutsMs = mutableListOf<Int>()

    private val client = OkHttpClient.Builder().addInterceptor { chain ->
        val request = chain.request()
        requests += request
        readTimeoutsMs += chain.readTimeoutMillis()
        val (code, body) = handler(request)
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(code).message("fake")
            .body(body.toResponseBody("application/json".toMediaType())).build()
    }.build()

    fun api(token: String? = "tok-123"): Api = Api(client, { "https://hub.test:8443" }, { token }, localNetworkMissing = { false })

    fun query(i: Int, name: String): String? = requests[i].url.queryParameter(name)
}

/** A sample events answer: one raised condition (a paused print), one moment, a cleared condition, a test. */
internal const val SAMPLE_EVENTS = """
{
  "events": [
    {"id": 12, "at": "2026-11-17T04:12:09Z", "kind": "print.runout", "severity": "warn",
     "subject": {"type": "printer", "id": "p-3", "name": "Workshop X1"}, "actor": {"type": "hub", "id": "", "name": ""},
     "data": {"job": "bracket.3mf"}, "condition": {"key": "print-paused:p-3", "state": "raised"}, "alert": true,
     "title": "Filament ran out on Workshop X1", "text": "bracket.3mf is paused at 41 %.", "action": {"place": "printer", "id": "p-3"}, "future": 1},
    {"id": 13, "at": "2026-11-17T04:20:00Z", "kind": "print.failed", "severity": "bad", "condition": null, "alert": true,
     "title": "Print stopped on Workshop X1", "text": "bracket.3mf stopped at 70 %.", "action": {"place": "printer", "id": "p-3"}},
    {"id": 14, "at": "2026-11-17T04:25:00Z", "kind": "print.resumed", "severity": "ok",
     "condition": {"key": "print-paused:p-3", "state": "cleared"}, "alert": false, "title": "", "text": "", "action": {}}
  ],
  "next": 14,
  "conditions": [],
  "oldest": 1,
  "gap": false
}
"""
