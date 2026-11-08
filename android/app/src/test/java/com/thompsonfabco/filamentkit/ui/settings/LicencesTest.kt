package com.thompsonfabco.filamentkit.ui.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

@RunWith(RobolectricTestRunner::class)
class LicencesTest {
    private fun asset(name: String) =
        RuntimeEnvironment.getApplication().assets.open(name).bufferedReader().use { it.readText() }

    @Test
    fun buildCarriesTheRepositoryNotices() {
        val notices = asset(THIRD_PARTY_ASSET)
        assertTrue(notices.startsWith("# Third-party software and data"))
        assertTrue("ZXing is listed", notices.contains("ZXing"))
        assertTrue(asset(LICENSE_ASSET).contains("GNU GENERAL PUBLIC LICENSE"))
    }

    @Test
    fun markdownBecomesBlocks() {
        val md = """
            # Title

            Some **bold** text with a [link](LICENSE)
            that wraps.

            | Component | Licence |
            |---|---|
            | `zxing` core | Apache-2.0 |

            - first bullet,
              continued
            - second
        """.trimIndent()

        assertEquals(
            listOf(
                NoticeBlock.Heading("Title", 1),
                NoticeBlock.Paragraph("Some bold text with a link that wraps."),
                NoticeBlock.TableRow(listOf("Component", "Licence"), header = true),
                NoticeBlock.TableRow(listOf("zxing core", "Apache-2.0"), header = false),
                NoticeBlock.Bullet("first bullet, continued"),
                NoticeBlock.Bullet("second"),
            ),
            noticeBlocks(md),
        )
    }

    @Test
    fun realNoticesParseWithoutTableSeparators() {
        val blocks = noticeBlocks(asset(THIRD_PARTY_ASSET))
        assertFalse(blocks.any { it is NoticeBlock.TableRow && it.cells.any { c -> c.startsWith("---") } })
        assertTrue(blocks.any { it is NoticeBlock.Heading && it.text == "The Android app" })
    }
}
