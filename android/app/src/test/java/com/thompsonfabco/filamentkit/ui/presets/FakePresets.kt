package com.thompsonfabco.filamentkit.ui.presets

import com.thompsonfabco.filamentkit.net.BuildAttempt
import com.thompsonfabco.filamentkit.net.BuildInfo
import com.thompsonfabco.filamentkit.net.BuildRequested
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.ProfileLine
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.UncoveredFilament
import kotlinx.coroutines.CompletableDeferred

/** The Hub as the Slicer presets tests see it (RFC 5737 / `*.example` data only). */
internal class FakePresets : PresetsBackend {
    var failure: Exception? = null
    var statusFailure: Exception? = null
    var linesFailure: Exception? = null
    var uncoveredFailure: Exception? = null
    var gate: CompletableDeferred<Unit>? = null
    var linesGate: CompletableDeferred<Unit>? = null
    val parentLists = mutableMapOf<String, ParentList>()
    val parentCalls = mutableListOf<String>()
    val added = mutableListOf<Pair<String, Int>>()
    val created = mutableListOf<List<String>>()
    val reparented = mutableListOf<Pair<String, String>>()
    var updatesInfo: com.thompsonfabco.filamentkit.net.UpdatesInfo? = null
    var builds = 0
    var statusCalls = 0
    var linesCalls = 0
    var uncoveredList = listOf(
        UncoveredFilament(7, "Example Filaments", "PolyTerra Neon Pink", "PLA", listOf("Example Filaments PolyTerra", "Example Filaments Silk")),
        UncoveredFilament(9, "Example Filaments", "Matte Black", "PLA", emptyList()),
    )
    var lines = listOf(
        ProfileLine(lineId = "example--polyterra", vendor = "Example Filaments", product = "PolyTerra", material = "PLA", presets = 4, bambuParent = "Generic PLA"),
        ProfileLine(lineId = "example--silk", vendor = "Example Filaments", product = "Silk", material = "PLA"),
    )

    override suspend fun status(): ProfileStatus {
        statusCalls++
        statusFailure?.let { throw it }
        return ProfileStatus(
            lines = 6, presets = 24, build = BuildInfo("s1", "h", "2026-11-02T01:02:03Z", presets = 24),
            lastAttempt = BuildAttempt("2026-11-02T01:02:03Z", ok = true), updates = updatesInfo,
        )
    }

    override suspend fun lines(): List<ProfileLine> {
        linesCalls++
        linesGate?.await()
        linesFailure?.let { throw it }
        return lines
    }

    override suspend fun uncovered(): List<UncoveredFilament> {
        uncoveredFailure?.let { throw it }
        return uncoveredList
    }

    override suspend fun parents(material: String): ParentList {
        parentCalls += material
        return parentLists[material] ?: ParentList(emptyList(), synced = false)
    }

    override suspend fun setLineParent(lineId: String, parent: String): ProfileLine {
        reparented += lineId to parent
        gate?.await()
        failure?.let { throw it }
        return lines.first { it.lineId == lineId }.copy(bambuParent = parent, parentSource = "user", presets = 0)
    }

    override suspend fun addToLine(lineId: String, id: Int): ProfileLine {
        added += lineId to id
        gate?.await()
        failure?.let { throw it }
        return lines.first()
    }

    override suspend fun newLine(name: String, vendor: String, id: Int, template: String): ProfileLine {
        created += listOf(name, vendor, id.toString(), template)
        gate?.await()
        failure?.let { throw it }
        // the line view of the new line, as the Hub answers; the list has it from now on
        val made = ProfileLine(
            lineId = name.lowercase().replace(' ', '-'), vendor = vendor, product = name.removePrefix("$vendor ").trim(),
            material = "PLA", bambuParent = template,
        )
        lines = lines + made
        return made
    }

    override suspend fun build(): BuildRequested {
        builds++
        gate?.await()
        failure?.let { throw it }
        return BuildRequested(requested = true, output = "a build is requested")
    }
}
