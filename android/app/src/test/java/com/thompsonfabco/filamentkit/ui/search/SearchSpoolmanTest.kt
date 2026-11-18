package com.thompsonfabco.filamentkit.ui.search

import com.thompsonfabco.filamentkit.net.ApiError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/** Open Spoolman (R83 section 7): offered only with the address the Hub gave. */
@OptIn(ExperimentalCoroutinesApi::class)
class SearchSpoolmanTest {
    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() = Dispatchers.resetMain()

    @Test fun theHubsAddressIsKept() {
        val vm = SearchViewModel(loadSpoolmanUrl = { " http://hub.local:7912 " }) { _, _ -> emptyList() }
        assertNull(vm.state.value.spoolmanUrl)
        vm.loadSpoolmanLink()
        assertEquals("http://hub.local:7912", vm.state.value.spoolmanUrl)
    }

    @Test fun noAddressAnOlderHubOrAFailureLeavesNoItem() {
        for (load in listOf<suspend () -> String?>({ null }, { "" }, { "javascript:alert(1)" }, { throw ApiError(404, "not_found", "x") })) {
            val vm = SearchViewModel(loadSpoolmanUrl = load) { _, _ -> emptyList() }
            vm.loadSpoolmanLink()
            assertNull(vm.state.value.spoolmanUrl)
        }
        val without = SearchViewModel { _, _ -> emptyList() }
        without.loadSpoolmanLink()
        assertNull(without.state.value.spoolmanUrl)
    }

    @Test fun onlyWebAddressesAreLinks() {
        assertEquals("https://spoolman.example", spoolmanLink("https://spoolman.example"))
        assertNull(spoolmanLink("file:///etc/passwd"))
        assertNull(spoolmanLink(null))
    }
}
