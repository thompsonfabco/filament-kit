package com.thompsonfabco.filamentkit.drafts

import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** One in-progress intake. [photos] are the `photoN.jpg` files in the draft's folder, in order. */
data class Draft(
    val id: String,
    val photos: List<File>,
    val hint: String,
    val tag: String?,
    val weightGrams: Double?,
    val sealed: Boolean,
    val readResult: JsonObject?,
    val editedItems: JsonArray?,
    val created: Long,
    /** Set after a real add that may have written spools (partial Spoolman failure, or the reply was lost): the ids
     * already created (possibly none known). The next real add needs an explicit "I checked". */
    val addedBefore: List<Long>? = null,
    /** An add by hand: no photos, the typed spools are the content. */
    val manual: Boolean = false,
) {
    /** Something worth keeping: photos, a tag that was tapped, or a hand add with spools typed in (Home lists these; start-up keeps them). */
    val hasContent: Boolean get() = photos.isNotEmpty() || tag != null || (manual && editedItems?.isNotEmpty() == true)
}

@Serializable
private data class DraftJson(
    val hint: String = "",
    val tag: String? = null,
    val weightGrams: Double? = null,
    val sealed: Boolean = false,
    val readResult: JsonObject? = null,
    val editedItems: JsonArray? = null,
    val created: Long = 0,
    val addedBefore: List<Long>? = null,
    val manual: Boolean = false,
)

/**
 * Drafts on disk: one folder per draft holding `draft.json` (written atomically) and `photoN.jpg`.
 * Callers delete a draft only after a successful real add.
 */
class DraftStore(private val dir: File) {
    private val json = Json { ignoreUnknownKeys = true }

    fun create(manual: Boolean = false): Draft {
        val id = UUID.randomUUID().toString()
        val draft = Draft(id, emptyList(), "", null, null, true, null, null, System.currentTimeMillis(), manual = manual) // "Still sealed" starts on
        folder(id).mkdirs()
        write(draft)
        return draft
    }

    fun addPhoto(id: String, jpeg: ByteArray): File {
        val folder = folder(id)
        require(File(folder, DRAFT_FILE).isFile) { "no such draft: $id" }
        val next = (photoFiles(folder).maxOfOrNull { photoIndex(it) } ?: 0) + 1
        val target = File(folder, "photo$next.jpg")
        val tmp = File(folder, "photo$next.jpg.tmp")
        tmp.writeBytes(jpeg)
        move(tmp, target)
        return target
    }

    fun update(draft: Draft) {
        require(folder(draft.id).isDirectory) { "no such draft: ${draft.id}" }
        write(draft)
    }

    fun list(): List<Draft> =
        (dir.listFiles { f -> f.isDirectory } ?: emptyArray())
            .mapNotNull { get(it.name) }
            .sortedBy { it.created }

    /** Null when the draft is missing or its `draft.json` is unreadable. */
    fun get(id: String): Draft? {
        val folder = folder(id)
        val file = File(folder, DRAFT_FILE)
        if (!file.isFile) return null
        return try {
            val d = json.decodeFromString<DraftJson>(file.readText())
            Draft(id, photoFiles(folder), d.hint, d.tag, d.weightGrams, d.sealed, d.readResult, d.editedItems, d.created, d.addedBefore, d.manual)
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Housekeeping, run once when the app starts: deletes the draft folders whose `draft.json` cannot be read, drafts
     * older than [maxAgeMs] and drafts with no photos (Home hides those, so nobody could discard them). A draft that
     * holds [Draft.addedBefore] is kept: it carries the "may already be added" warning. Returns how many were deleted.
     */
    fun purge(maxAgeMs: Long, now: Long = System.currentTimeMillis(), open: Set<String> = emptySet()): Int {
        var n = 0
        for (folder in dir.listFiles { f -> f.isDirectory }.orEmpty()) {
            val d = get(folder.name)
            val drop = when {
                d == null -> true
                folder.name in open -> false // an add that is open right now is never taken from under its screen
                d.addedBefore != null -> false
                // a draft with nothing in it goes after a day; one just created or restored is never touched
                else -> now - d.created > maxAgeMs || (!d.hasContent && now - d.created > EMPTY_GRACE_MS)
            }
            if (drop && folder.deleteRecursively()) n++
        }
        return n
    }

    fun delete(id: String) {
        folder(id).deleteRecursively()
    }

    private fun folder(id: String): File {
        require(id.isNotEmpty() && '/' !in id && '\\' !in id && id != "." && id != "..") { "bad draft id" }
        return File(dir, id)
    }

    private fun write(draft: Draft) {
        val folder = folder(draft.id)
        val body = json.encodeToString(
            // JSON has no NaN/Infinity: such a weight would make every later write of this draft fail.
            DraftJson(
                draft.hint, draft.tag, draft.weightGrams?.takeIf { it.isFinite() }, draft.sealed, draft.readResult,
                draft.editedItems, draft.created, draft.addedBefore, draft.manual,
            ),
        )
        val tmp = File(folder, "$DRAFT_FILE.tmp")
        tmp.writeText(body)
        move(tmp, File(folder, DRAFT_FILE))
    }

    private fun move(from: File, to: File) {
        Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
    }

    private fun photoFiles(folder: File): List<File> =
        (folder.listFiles { f -> PHOTO.matches(f.name) } ?: emptyArray()).sortedBy { photoIndex(it) }

    private fun photoIndex(f: File): Int = PHOTO.matchEntire(f.name)!!.groupValues[1].toInt()

    companion object {
        /** Drafts older than this are deleted at start ([purge]). */
        const val MAX_AGE_MS = 30L * 24 * 60 * 60 * 1000

        /** A draft with nothing in it is deleted at start only when it is older than this. */
        const val EMPTY_GRACE_MS = 24L * 60 * 60 * 1000
        private const val DRAFT_FILE = "draft.json"
        private val PHOTO = Regex("""photo(\d+)\.jpg""")
    }
}
