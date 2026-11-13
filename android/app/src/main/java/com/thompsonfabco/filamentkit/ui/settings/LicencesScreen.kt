package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwSkeletonRows
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

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

/**
 * The app's licence and the third-party notices (05-android-app 12.5), readable offline. Both files are read and parsed
 * off the main thread; skeleton rows stand in until they are ready.
 */
@Composable
fun LicencesScreen(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val notices by produceState<List<NoticeBlock>?>(null) {
        value = withContext(Dispatchers.IO) { noticeBlocks(readAsset(context, THIRD_PARTY_ASSET)) }
    }
    var showGpl by remember { mutableStateOf(false) }
    val gpl by produceState<List<NoticeBlock>?>(null, showGpl) {
        value = if (showGpl) withContext(Dispatchers.IO) { noticeBlocks(readAsset(context, LICENSE_ASSET)) } else null
    }
    val space = SpoolwardenTheme.space
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        LazyColumn(
            Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxSize(),
            contentPadding = PaddingValues(space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s2),
        ) {
            item { Text(stringResource(R.string.settings_licences_line), style = MaterialTheme.typography.bodyMedium) }
            item {
                SwButton(
                    stringResource(if (showGpl) R.string.settings_licences_hide else R.string.settings_licences_show),
                    { showGpl = !showGpl }, Modifier.fillMaxWidth(),
                )
            }
            if (showGpl) {
                gpl?.let { blocks -> items(blocks) { NoticeText(it) } } ?: item { SwSkeletonRows() }
            }
            notices?.let { blocks -> items(blocks) { NoticeText(it) } } ?: item { SwSkeletonRows() }
        }
    }
}

@Composable
private fun NoticeText(block: NoticeBlock) {
    when (block) {
        is NoticeBlock.Heading -> Text(
            block.text, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleMedium,
        )
        is NoticeBlock.Paragraph -> Text(block.text, style = MaterialTheme.typography.bodyMedium)
        is NoticeBlock.Bullet -> Text("• ${block.text}", style = MaterialTheme.typography.bodyMedium)
        // a table row is a field row: the first cell names it, the others are its value
        is NoticeBlock.TableRow -> if (!block.header) {
            val cells = block.cells.filter { it.isNotEmpty() }
            FieldRow(cells.firstOrNull().orEmpty(), cells.drop(1).joinToString("  ·  "))
        }
    }
}

private fun readAsset(context: android.content.Context, name: String): String =
    try {
        context.assets.open(name).bufferedReader().use { it.readText() }
    } catch (_: java.io.IOException) {
        context.getString(R.string.settings_licences_missing, name)
    }
