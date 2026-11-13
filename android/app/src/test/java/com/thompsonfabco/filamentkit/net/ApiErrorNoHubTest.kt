package com.thompsonfabco.filamentkit.net

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.history.FieldError
import com.thompsonfabco.filamentkit.ui.history.RecentField
import com.thompsonfabco.filamentkit.ui.history.errorText
import org.junit.Assert.assertEquals
import org.junit.Test

/** The two small shared answers: no Hub paired (one source), and the range error's shared text. */
class ApiErrorNoHubTest {
    @Test fun noHubPairedIsTheOfflineAnswerWithNoStatus() {
        val e = ApiError.noHubPaired()
        assertEquals(0, e.status)
        assertEquals("offline", e.code)
        assertEquals("No Hub is paired.", e.message)
    }

    @Test fun theRangeErrorOfTheEditScreenIsTheSharedText() {
        assertEquals(R.string.common_error_range, errorText(FieldError.Range, RecentField.Vendor))
    }
}
