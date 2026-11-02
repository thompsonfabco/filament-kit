package com.thompsonfabco.filamentkit.ui.search

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SearchViewModelTest {
    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() = Dispatchers.resetMain()

    private val calls = mutableListOf<Pair<String, Boolean>>()
    private var error: Exception? = null
    private val results = listOf(buildJsonObject { put("id", 4) })
    private val vm = SearchViewModel { q, sealed ->
        calls += q to sealed
        error?.let { throw it }
        results
    }

    @Test fun searchPassesQueryAndSealedFlag() {
        vm.setQuery("  grey petg ")
        vm.setSealedOnly(true)
        vm.search()
        assertEquals(listOf("grey petg" to true), calls)
        assertEquals(results, vm.state.value.results)
        assertTrue(vm.state.value.searched)
        assertFalse(vm.state.value.busy)
    }

    @Test fun blankQueryDoesNotCallTheServer() {
        vm.setQuery("   ")
        vm.search()
        assertTrue(calls.isEmpty())
    }

    @Test fun errorsBecomePlainMessages() {
        vm.setQuery("x")
        error = ApiError(0, "offline", "gone")
        vm.search()
        assertEquals("Could not reach the server. Check that you are on the same network.", vm.state.value.error)
        error = IllegalStateException("boom")
        vm.search()
        assertEquals("Unexpected response from the server", vm.state.value.error)
        error = null
        vm.search()
        assertNull(vm.state.value.error)
    }

    @Test fun mismatchGetsItsOwnState() {
        vm.setQuery("x")
        error = FingerprintMismatch("aa", "bb")
        vm.search()
        assertEquals("aa" to "bb", vm.state.value.mismatch)
        assertEquals(emptyList<JsonObject>(), vm.state.value.results)
    }

    @Test fun unauthorizedIsFlagged() {
        vm.setQuery("x")
        error = ApiError(401, "unauthorized", "nope")
        vm.search()
        assertTrue(vm.state.value.unauthorized)
    }
}
