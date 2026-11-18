package com.thompsonfabco.filamentkit.ui.search

import com.thompsonfabco.filamentkit.alerts.LowSpool
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.ui.spool.HubFailure
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The Running low filter of Spools (R80 section 7). */
@OptIn(ExperimentalCoroutinesApi::class)
class SearchLowTest {
    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() = Dispatchers.resetMain()

    private var loads = 0
    private var error: Exception? = null
    private val low = listOf(
        LowSpool(7, "Prusament PLA", "PLA", "ff8800", 96.5, "Shelf A", inStock = 0, lastOne = true),
        LowSpool(9, "Polymaker PETG", "PETG", null, 140.0, null, inStock = 2, lastOne = false),
    )
    private val vm = SearchViewModel(loadLow = { loads++; error?.let { throw it }; low }) { _, _ -> emptyList() }

    @Test fun theChipLoadsTheListAndTurnsTheFilterOn() {
        vm.setLowOnly(true)
        val ui = vm.state.value
        assertTrue(ui.lowOnly)
        assertTrue(ui.lowLoaded)
        assertEquals(listOf(7, 9), ui.low.map { it.id })
        assertFalse(ui.busy)
        assertEquals(1, loads)
    }

    @Test fun aRowIsASpoolSummaryOfTheLowSpool() {
        val summary = low[0].toSummary()
        assertEquals(7, summary.id)
        assertEquals("Prusament PLA", summary.title)
        assertEquals("PLA", summary.material)
        assertEquals("Shelf A", summary.location)
        assertEquals(96.5, summary.remaining!!, 0.0)
    }

    @Test fun turningTheFilterOffReturnsToTheSearch() {
        vm.setLowOnly(true)
        vm.setLowOnly(false)
        assertFalse(vm.state.value.lowOnly)
        assertEquals("no second read", 1, loads)
    }

    @Test fun aFailureShowsTheHubNoticeAndTryAgainReadsAgain() {
        error = ApiError(0, "offline", "no")
        vm.setLowOnly(true)
        assertTrue(vm.state.value.failure is HubFailure)
        assertFalse(vm.state.value.lowLoaded)
        error = null
        vm.loadLowSpools()
        assertNull(vm.state.value.failure)
        assertTrue(vm.state.value.lowLoaded)
    }

    @Test fun withoutALowListNothingHappens() {
        val plain = SearchViewModel { _, _ -> emptyList() }
        plain.setLowOnly(true)
        assertFalse(plain.state.value.lowLoaded)
    }
}
