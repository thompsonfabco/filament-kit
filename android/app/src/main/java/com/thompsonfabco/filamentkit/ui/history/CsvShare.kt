package com.thompsonfabco.filamentkit.ui.history

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File

/** What became of [shareCsv]. */
internal enum class CsvOutcome { Opened, NoApp }

/**
 * Where a CSV download is written: the app's cache `reports/` folder, the one folder the FileProvider serves (printer
 * reports go there too). Earlier CSV files there are removed first; null when the folder cannot be made.
 */
internal fun csvTarget(context: Context, name: String): File? {
    val dir = File(context.cacheDir, "reports")
    dir.listFiles()?.filter { it.extension == "csv" }?.forEach { it.delete() }
    if (!dir.isDirectory && !dir.mkdirs()) return null
    return File(dir, name)
}

/** Opens the system share sheet on [file], where the owner can save it to the phone's downloads or send it anywhere. */
internal fun shareCsv(context: Context, file: File, subject: String): CsvOutcome {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.reports", file)
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/csv"
        putExtra(Intent.EXTRA_STREAM, uri)
        putExtra(Intent.EXTRA_TITLE, file.name)
        putExtra(Intent.EXTRA_SUBJECT, subject)
        clipData = ClipData.newRawUri(file.name, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    return try {
        context.startActivity(Intent.createChooser(send, subject))
        CsvOutcome.Opened
    } catch (_: ActivityNotFoundException) {
        CsvOutcome.NoApp
    }
}

/** The words for a download the Hub or the phone could not do (404: an older Hub; `storage`: the phone); null for any other failure. */
internal fun csvProblemText(e: com.thompsonfabco.filamentkit.net.ApiError): String? = when {
    e.status == 404 -> HistoryTexts.CSV_UPDATE_HUB
    e.code == "storage" -> HistoryTexts.CSV_NOT_SAVED
    else -> null
}

/** A file name the Hub's set and a printer give: `usage-0948AB.csv`; anything that is not a letter, digit, dot or dash becomes a dash. */
internal fun csvFileName(set: String, subject: String?): String =
    (listOfNotNull(set, subject).joinToString("-").replace(Regex("[^A-Za-z0-9.-]"), "-")) + ".csv"
