package com.thompsonfabco.filamentkit.ui.search

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.ui.spool.HubFailure
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
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
        assertEquals("the chip searches again at once", listOf("grey petg" to true), calls)
        assertEquals(listOf(4), vm.state.value.results.map { it.id })
        assertEquals("grey petg", vm.state.value.searched)
        assertFalse(vm.state.value.busy)
    }

    @Test fun aPauseInTypingSearchesOnceForTheLastTextAfter300ms() {
        vm.setQuery("pe")
        scheduler.advanceTimeBy(200)
        vm.setQuery("petg")
        scheduler.advanceTimeBy(299)
        assertTrue(calls.isEmpty())
        scheduler.advanceTimeBy(2)
        assertEquals(listOf("petg" to false), calls)
        assertEquals(listOf(4), vm.state.value.results.map { it.id })
    }

    @Test fun oneTypedLetterDoesNotSearchByItself() {
        vm.setQuery("p")
        scheduler.advanceTimeBy(1_000)
        assertTrue(calls.isEmpty())
    }

    @Test fun theKeyboardsSearchKeySearchesAtOnceAndNotAgainAfterThePause() {
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
        assertNull(vm.state.value.searched)
        assertTrue(vm.state.value.results.isEmpty())
    }

    @Test fun theChipDoesNotSearchWhileNothingIsTyped() {
        vm.setSealedOnly(true)
        assertTrue(calls.isEmpty())
        vm.setQuery("petg")
        vm.search()
        vm.setSealedOnly(false)
        assertEquals(listOf("petg" to true, "petg" to false), calls)
    }

    @Test fun blankQueryDoesNotCallTheHub() {
        vm.setQuery("   ")
        vm.search()
        assertTrue(calls.isEmpty())
    }

    @Test fun theRowsOfTheLastAnswerStayUnderAFailure() {
        vm.setQuery("petg")
        vm.search()
        error = ApiError(0, "offline", "gone")
        vm.search()
        assertEquals(HubFailure.Unreachable, vm.state.value.failure)
        assertEquals(1, vm.state.value.results.size)
        error = null
        vm.search()
        assertNull(vm.state.value.failure)
    }

    @Test fun failuresAreSortedByTheRealApiErrorShapes() {
        vm.setQuery("x")
        error = IllegalStateException("boom")
        vm.search()
        assertEquals(HubFailure.Unexpected, vm.state.value.failure)
        error = ApiError(502, "internal", "The server returned an error (502)", noHubMessage = true)
        vm.search()
        assertEquals(HubFailure.Unexpected, vm.state.value.failure)
        error = ApiError(503, "spoolman_unreachable", "Spoolman is not reachable")
        vm.search()
        assertEquals(HubFailure.SpoolmanDown, vm.state.value.failure)
        error = FingerprintMismatch("aa", "bb")
        vm.search()
        assertEquals(HubFailure.CertificateChanged, vm.state.value.failure)
        error = ApiError(401, "unauthorized", "nope")
        vm.search()
        assertEquals(HubFailure.NotPaired, vm.state.value.failure)
    }
}
