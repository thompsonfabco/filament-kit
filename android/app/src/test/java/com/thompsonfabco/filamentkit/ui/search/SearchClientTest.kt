package com.thompsonfabco.filamentkit.ui.search

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/** The view model keeps what was typed and asks for the current client at each search (a trusted certificate, a re-pair). */
@OptIn(ExperimentalCoroutinesApi::class)
class SearchClientTest {
    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() = Dispatchers.resetMain()

    @Test fun theSameViewModelUsesTheNewClientAndKeepsItsState() {
        val answers = mapOf("old" to buildJsonObject { put("id", 1) }, "new" to buildJsonObject { put("id", 2) })
        var client = "old"
        val seen = mutableListOf<String>()
        val vm = SearchViewModel { _, _ ->
            seen += client
            listOf<JsonObject>(answers.getValue(client))
        }
        vm.setQuery("grey petg")
        vm.setSealedOnly(true) // the chip searches at once
        assertEquals(listOf(1), vm.state.value.results.map { it.id })

        client = "new"
        vm.search()
        assertEquals(listOf("old", "new"), seen)
        assertEquals(listOf(2), vm.state.value.results.map { it.id })
        assertEquals("grey petg", vm.state.value.query)
        assertEquals(true, vm.state.value.sealedOnly)
    }
}
