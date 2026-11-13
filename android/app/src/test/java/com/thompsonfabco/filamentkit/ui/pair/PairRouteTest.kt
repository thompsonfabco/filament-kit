package com.thompsonfabco.filamentkit.ui.pair

import com.thompsonfabco.filamentkit.nav.PairAddressRoute
import com.thompsonfabco.filamentkit.nav.PairCertificateRoute
import com.thompsonfabco.filamentkit.nav.PairCodeRoute
import com.thompsonfabco.filamentkit.nav.PairFingerprintRoute
import com.thompsonfabco.filamentkit.nav.PairNetworkAccessRoute
import com.thompsonfabco.filamentkit.nav.PairRoute
import org.junit.Assert.assertEquals
import org.junit.Test

/** One destination per pairing step (05-android-app 4). */
class PairRouteTest {
    private val mismatch = { source: MismatchSource -> Mismatch("a", "b", source) }

    @Test fun eachStepHasItsOwnDestination() {
        assertEquals(PairRoute, pairRouteFor(PairUi(step = Step.Choose), true))
        assertEquals(PairAddressRoute, pairRouteFor(PairUi(step = Step.Address), true))
        assertEquals(PairFingerprintRoute, pairRouteFor(PairUi(step = Step.Confirm), true))
        assertEquals(PairCodeRoute, pairRouteFor(PairUi(step = Step.Code), true))
    }

    @Test fun aCertificateQuestionNamesWhereItCameFrom() {
        for (source in MismatchSource.entries) {
            val ui = PairUi(mismatch = mismatch(source))
            assertEquals(PairCertificateRoute(source.name.lowercase()), pairRouteFor(ui, true))
        }
        assertEquals(listOf("stored", "qr", "manual"), MismatchSource.entries.map { it.routeSource() })
    }

    @Test fun withoutLocalNetworkAccessEveryStepIsTheAccessStep() {
        assertEquals(PairNetworkAccessRoute, pairRouteFor(PairUi(), false))
        assertEquals(PairNetworkAccessRoute, pairRouteFor(PairUi(step = Step.Code), false))
        assertEquals(PairNetworkAccessRoute, pairRouteFor(PairUi(mismatch = mismatch(MismatchSource.STORED)), false))
    }
}
