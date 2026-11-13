package com.thompsonfabco.filamentkit.ui

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * AND-11 / AUT-8: no `Color(0x` literal in the app's Kotlin outside the theme (`ui/theme/`) and the swatch, whose fill
 * comes from the data (`ui/ColorSwatch.kt`). Status and every other colour come from `SpoolwardenTheme.colors`.
 */
class ColorLiteralScanTest {
    private val sources = File("src/main/java")

    private fun allowed(path: String) = "/ui/theme/" in path || path.endsWith("/ui/ColorSwatch.kt")

    private fun literals(text: String): List<Int> =
        text.lines().mapIndexedNotNull { i, line -> if (COLOR_LITERAL.containsMatchIn(line)) i + 1 else null }

    @Test fun noColourLiteralOutsideTheThemeAndTheSwatch() {
        val files = sources.walkTopDown().filter { it.isFile && it.extension == "kt" }.toList()
        assertEquals("the scan found the app's sources", true, files.size > 50)
        val found = files.map { it.invariantSeparatorsPath }.filterNot(::allowed).flatMap { path ->
            literals(File(path).readText()).map { "$path:$it" }
        }
        assertEquals(emptyList<String>(), found)
    }

    @Test fun theScanSeesALiteralAndIgnoresTheLookalikes() {
        assertEquals(listOf(2), literals("val a = 1\nval c = Color(0xFF112233)"))
        assertEquals(emptyList<Int>(), literals("val c = colors.bad\nval d = Color.Transparent\nval e = MyColor(1)"))
    }

    private companion object {
        val COLOR_LITERAL = Regex("""\bColor\(0x""")
    }
}
