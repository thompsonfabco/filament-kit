package com.thompsonfabco.filamentkit.ui.add

import android.os.Build
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** The "may have been added already" text (05-android-app 6.3): one whole text per case, ids joined by ", ". */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class AddedBeforeTextTest {
    private val context = RuntimeEnvironment.getApplication()

    @Test fun oneKnownSpool() {
        assertEquals(
            "This spool may have been added already: spool 212. Check Spoolman before adding it again.",
            AddedBefore(listOf(212L)).text(context),
        )
    }

    @Test fun twoKnownSpoolsAreJoinedByACommaNeverAnd() {
        assertEquals(
            "These spools may have been added already: spool 212, spool 213. Check Spoolman before adding them again.",
            AddedBefore(listOf(212L, 213L)).text(context),
        )
    }

    @Test fun theHubsOwnWordsWithNoSpoolNumbers() {
        assertEquals(
            "These spools may have been added already: spoolman failed part-way. Check Spoolman before adding them again.",
            AddedBefore(emptyList(), "spoolman failed part-way").text(context),
        )
    }

    @Test fun neitherIsTheLostConnectionText() {
        assertEquals(
            "These spools may have been added already: the connection was lost before the Hub answered. Check Spoolman before adding them again.",
            AddedBefore(emptyList()).text(context),
        )
    }
}
