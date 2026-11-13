package com.thompsonfabco.filamentkit.net

import com.thompsonfabco.filamentkit.ui.add.IntakeApi
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Test

/** Screens ask for the current client at each call, so a new client reaches a view model that is already alive. */
class ClientProviderTest {
    private val first = MockWebServer().apply { start() }
    private val second = MockWebServer().apply { start() }

    @After fun tearDown() {
        first.close()
        second.close()
    }

    private fun api(server: MockWebServer) = Api(OkHttpClient(), { server.ipUrl("/").toString().trimEnd('/') }, { "tok" })

    @Test fun theNextCallUsesTheClientThatIsCurrentThen() = runBlocking {
        first.enqueue(MockResponse.Builder().body("""{"locations":["Old Hub shelf"]}""").build())
        second.enqueue(MockResponse.Builder().body("""{"locations":["New Hub shelf"]}""").build())
        var current = api(first)
        val intake = IntakeApi.of { current }

        assertEquals(listOf("Old Hub shelf"), intake.locations())
        current = api(second)
        assertEquals(listOf("New Hub shelf"), intake.locations())
        assertEquals(1, first.requestCount)
        assertEquals(1, second.requestCount)
    }
}
