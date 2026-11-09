package com.thompsonfabco.filamentkit.ui.home

import com.thompsonfabco.filamentkit.BuildConfig
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

class VersionLineTest {
    @Test fun pairedWithAKnownServerShowsBoth() {
        assertEquals("App 0.4.3 · Server 0.4.2", versionLine("0.4.3", paired = true, server = "0.4.2"))
    }

    @Test fun notPairedSaysSoEvenIfAnOldVersionIsStillKnown() {
        assertEquals("App 0.4.3 · not paired", versionLine("0.4.3", paired = false, server = null))
        assertEquals("App 0.4.3 · not paired", versionLine("0.4.3", paired = false, server = "0.4.2"))
    }

    @Test fun aPairedServerThatHasNotAnsweredIsLeftOut() {
        assertEquals("App 0.4.3", versionLine("0.4.3", paired = true, server = null))
        assertEquals("App 0.4.3", versionLine("0.4.3", paired = true, server = " "))
    }

    private val kit = Regex("""(?m)^__version__ = "(\d+)\.(\d+)\.(\d+)"""")
        .find(File("../../server/filament_kit/__init__.py").readText())!!.groupValues

    @Test fun theVersionNameIsTheKitsVersion() {
        assertEquals("${kit[1]}.${kit[2]}.${kit[3]}", BuildConfig.VERSION_NAME)
    }

    @Test fun theVersionCodeIsTheReleaseWorkflowsFormula() {
        assumeTrue(System.getenv("FK_VERSION_CODE").isNullOrBlank())
        assertEquals(kit[1].toInt() * 10000 + kit[2].toInt() * 100 + kit[3].toInt(), BuildConfig.VERSION_CODE)
    }
}
