package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/** Asset names; the build copies both from the repository root (copyNotices in app/build.gradle.kts). */
const val THIRD_PARTY_ASSET = "THIRD-PARTY.md"
const val LICENSE_ASSET = "LICENSE"

/** One piece of a notices file, as shown on screen. */
sealed interface NoticeBlock {
    data class Heading(val text: String, val level: Int) : NoticeBlock
    data class Paragraph(val text: String) : NoticeBlock
    data class Bullet(val text: String) : NoticeBlock
    data class TableRow(val cells: List<String>, val header: Boolean) : NoticeBlock
}

/**
 * Splits the simple markdown of THIRD-PARTY.md (headings, paragraphs, bullets, tables) into blocks, with emphasis,
 * code marks and link targets dropped. Plain text such as LICENSE comes out as paragraphs.
 */
fun noticeBlocks(markdown: String): List<NoticeBlock> {
    val out = mutableListOf<NoticeBlock>()
    val para = StringBuilder()
    var tableStart = true
    fun flush() {
        if (para.isNotEmpty()) out += NoticeBlock.Paragraph(para.toString())
        para.clear()
    }
    for (raw in markdown.lines()) {
        val line = raw.trim()
        when {
            line.isEmpty() -> { flush(); tableStart = true }
            line.startsWith("#") -> {
                flush()
                val level = line.takeWhile { it == '#' }.length
                out += NoticeBlock.Heading(plain(line.drop(level).trim()), level)
            }
            line.startsWith("|") -> {
                flush()
                val cells = line.trim('|').split("|").map { plain(it.trim()) }
                if (cells.all { c -> c.isNotEmpty() && c.all { it == '-' || it == ':' } }) continue // |---|---|
                out += NoticeBlock.TableRow(cells, header = tableStart)
                tableStart = false
            }
            line.startsWith("- ") -> { flush(); out += NoticeBlock.Bullet(plain(line.drop(2))) }
            // A bullet's wrapped second line continues it.
            raw.startsWith("  ") && para.isEmpty() && out.lastOrNull() is NoticeBlock.Bullet -> {
                val b = out.removeAt(out.lastIndex) as NoticeBlock.Bullet
                out += NoticeBlock.Bullet(b.text + " " + plain(line))
            }
            else -> { if (para.isNotEmpty()) para.append(' '); para.append(plain(line)) }
        }
    }
    flush()
    return out
}

private val link = Regex("""\[([^\]]+)]\([^)]*\)""")

private fun plain(s: String) = link.replace(s, "$1").replace("**", "").replace("~~", "").replace("`", "")

/** The app's licence and the third-party notices, readable offline. */
@Composable
fun LicencesScreen(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val notices = remember { noticeBlocks(readAsset(context, THIRD_PARTY_ASSET)) }
    var showGpl by remember { mutableStateOf(false) }
    val gpl = remember(showGpl) { if (showGpl) noticeBlocks(readAsset(context, LICENSE_ASSET)) else emptyList() }
    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item { Text("Licences", style = MaterialTheme.typography.headlineSmall) }
        item { Text("filament-kit is free software under GPL-3.0-or-later. It comes with no warranty.") }
        item {
            OutlinedButton(onClick = { showGpl = !showGpl }, modifier = Modifier.fillMaxWidth()) {
                Text(if (showGpl) "Hide the GPL-3.0 text" else "Show the GPL-3.0 text")
            }
        }
        items(gpl) { NoticeText(it) }
        items(notices) { NoticeText(it) }
    }
}

@Composable
private fun NoticeText(block: NoticeBlock) {
    when (block) {
        is NoticeBlock.Heading -> Text(
            block.text,
            style = if (block.level <= 1) MaterialTheme.typography.titleLarge else MaterialTheme.typography.titleMedium,
        )
        is NoticeBlock.Paragraph -> Text(block.text, style = MaterialTheme.typography.bodyMedium)
        is NoticeBlock.Bullet -> Text("• ${block.text}", style = MaterialTheme.typography.bodyMedium)
        is NoticeBlock.TableRow -> Text(
            block.cells.filter { it.isNotEmpty() }.joinToString("  ·  "),
            style = MaterialTheme.typography.bodySmall,
            fontWeight = if (block.header) FontWeight.Bold else null,
        )
    }
}

private fun readAsset(context: android.content.Context, name: String): String =
    try {
        context.assets.open(name).bufferedReader().use { it.readText() }
    } catch (_: java.io.IOException) {
        "$name is missing from this build."
    }
