package com.thompsonfabco.filamentkit.ui.search

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.ui.history.HistoryTexts
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
import java.io.File

@OptIn(ExperimentalCoroutinesApi::class)
class SearchCsvTest {
    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() = Dispatchers.resetMain()

    private val files = mutableListOf<File>()
    private var error: Exception? = null
    private fun vm(export: Boolean = true) = SearchViewModel(
        exportCsv = if (export) ({ f -> files += f; error?.let { throw it } }) else null,
    ) { _, _ -> emptyList() }

    @Test fun downloadAsCsvHandsTheFileToTheScreen() {
        val vm = vm()
        val file = File("spoolman-spools.csv")
        vm.downloadCsv(file)
        assertEquals(listOf(file), files)
        assertEquals(file, vm.state.value.csvFile)
        assertFalse(vm.state.value.csvBusy)
        vm.csvShown(null)
        assertNull(vm.state.value.csvFile)
    }

    @Test fun noExportCallMeansNoItem() {
        val vm = vm(export = false)
        assertFalse(vm.canExport)
        vm.downloadCsv(File("a.csv"))
        assertTrue(files.isEmpty())
        assertFalse(vm.state.value.csvBusy)
    }

    @Test fun anOlderHubAndAFullPhoneHaveTheirOwnWords() {
        val vm = vm()
        error = ApiError(404, "not_found", "The Hub returned an error (404)")
        vm.downloadCsv(File("a.csv"))
        assertEquals(HistoryTexts.CSV_UPDATE_HUB, vm.state.value.csvProblem)
        assertNull(vm.state.value.csvFile)
        error = ApiError(0, "storage", "disk full")
        vm.downloadCsv(File("a.csv"))
        assertEquals(HistoryTexts.CSV_NOT_SAVED, vm.state.value.csvProblem)
    }

    @Test fun otherFailuresGoThroughTheUsualHubNotices() {
        val vm = vm()
        error = ApiError(401, "unauthorized", "nope")
        vm.downloadCsv(File("a.csv"))
        assertEquals(HubFailure.NotPaired, vm.state.value.csvFailure)
        assertNull(vm.state.value.csvProblem)
        assertFalse(vm.state.value.csvBusy)
        // the search's own state is untouched
        assertNull(vm.state.value.failure)
    }
}
