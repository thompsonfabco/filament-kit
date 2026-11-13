package com.thompsonfabco.filamentkit.ui.printers

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import com.thompsonfabco.filamentkit.net.PrinterReport
import java.io.File

/** What became of [shareReport]. */
internal enum class ShareOutcome { Opened, NoApp, NotWritten }

/**
 * Writes [report] to the app's cache (`reports/`, the one folder the FileProvider serves; earlier reports there are
 * removed first) and opens the system share sheet on it, where the owner can save it or send it anywhere.
 * The sheet's title is [subject] ("Printer report"). Says whether the sheet opened.
 */
internal fun shareReport(context: Context, report: PrinterReport, subject: String): ShareOutcome {
    val dir = File(context.cacheDir, "reports")
    dir.listFiles()?.forEach { it.delete() }
    if (!dir.isDirectory && !dir.mkdirs()) return ShareOutcome.NotWritten
    val file = File(dir, ReportHelp.fileName(report.name))
    file.writeText(report.xml, Charsets.UTF_8)
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.reports", file)
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/xml"
        putExtra(Intent.EXTRA_STREAM, uri)
        putExtra(Intent.EXTRA_TITLE, file.name)
        putExtra(Intent.EXTRA_SUBJECT, subject)
        clipData = ClipData.newRawUri(file.name, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    return try {
        context.startActivity(Intent.createChooser(send, subject))
        ShareOutcome.Opened
    } catch (_: ActivityNotFoundException) {
        ShareOutcome.NoApp
    }
}
