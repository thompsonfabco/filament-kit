package com.thompsonfabco.filamentkit.ui.add

import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** The Back rule for an add flow that a new add would replace. */
class AddReplaceTest {
    private val item = JsonObject(emptyMap())

    @Test fun writingOrCheckingWithTheHubIsKept() {
        assertEquals(AddReplace.KeepWriting, addReplace(AddUiState(stage = Stage.Adding)))
        assertEquals(AddReplace.KeepWriting, addReplace(AddUiState(stage = Stage.Previewing, manual = true, items = listOf(item))))
    }

    @Test fun aHandAddWithFieldsAsksBeforeLeaving() {
        assertEquals(AddReplace.AskLeave, addReplace(AddUiState(stage = Stage.Review, manual = true, items = listOf(item))))
        assertEquals(AddReplace.AskLeave, addReplace(AddUiState(stage = Stage.Preview, manual = true, items = listOf(item))))
    }

    @Test fun savedOrEmptyOrFinishedIsReplaced() {
        assertEquals("photo path: the draft is saved", AddReplace.Replace, addReplace(AddUiState(stage = Stage.Review, items = listOf(item))))
        assertEquals(AddReplace.Replace, addReplace(AddUiState(stage = Stage.Capture)))
        assertEquals("a hand add with nothing typed", AddReplace.Replace, addReplace(AddUiState(stage = Stage.Review, manual = true)))
        assertEquals(AddReplace.Replace, addReplace(AddUiState(stage = Stage.Done, manual = true, items = listOf(item))))
    }
}
