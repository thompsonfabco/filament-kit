package com.thompsonfabco.filamentkit.ui.search

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
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
    private val scheduler = TestCoroutineScheduler()

    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher(scheduler))
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

    @Test fun aPauseInTypingSearchesOnceForTheLastText() {
        vm.setQuery("pe")
        scheduler.advanceTimeBy(200)
        vm.setQuery("petg")
        scheduler.advanceTimeBy(399)
        assertTrue(calls.isEmpty())
        scheduler.advanceTimeBy(2)
        assertEquals(listOf("petg" to false), calls)
        assertEquals(results, vm.state.value.results)
    }

    @Test fun oneTypedLetterDoesNotSearch() {
        vm.setQuery("p")
        scheduler.advanceTimeBy(1_000)
        assertTrue(calls.isEmpty())
    }

    @Test fun theSearchButtonDoesNotSearchTwice() {
        vm.setQuery("petg")
        vm.search()
        scheduler.advanceTimeBy(1_000)
        assertEquals(listOf("petg" to false), calls)
    }

    @Test fun clearingTheBoxClearsTheResults() {
        vm.setQuery("petg")
        vm.search()
        vm.setQuery("")
        scheduler.advanceTimeBy(1_000)
        assertEquals(1, calls.size)
        assertFalse(vm.state.value.searched)
        assertTrue(vm.state.value.results.isEmpty())
    }

    @Test fun theSealedBoxSearchesAgainOnlyOnceSomethingWasSearched() {
        vm.setSealedOnly(true)
        assertTrue(calls.isEmpty())
        vm.setQuery("petg")
        vm.search()
        vm.setSealedOnly(false)
        assertEquals(listOf("petg" to true, "petg" to false), calls)
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
