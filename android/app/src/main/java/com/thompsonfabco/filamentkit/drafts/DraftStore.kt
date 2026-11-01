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
)

@Serializable
private data class DraftJson(
    val hint: String = "",
    val tag: String? = null,
    val weightGrams: Double? = null,
    val sealed: Boolean = false,
    val readResult: JsonObject? = null,
    val editedItems: JsonArray? = null,
    val created: Long = 0,
)

/**
 * Drafts on disk: one folder per draft holding `draft.json` (written atomically) and `photoN.jpg`.
 * Callers delete a draft only after a successful real add.
 */
class DraftStore(private val dir: File) {
    private val json = Json { ignoreUnknownKeys = true }

    fun create(): Draft {
        val id = UUID.randomUUID().toString()
        val draft = Draft(id, emptyList(), "", null, null, false, null, null, System.currentTimeMillis())
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
            Draft(id, photoFiles(folder), d.hint, d.tag, d.weightGrams, d.sealed, d.readResult, d.editedItems, d.created)
        } catch (e: Exception) {
            null
        }
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
            DraftJson(draft.hint, draft.tag, draft.weightGrams, draft.sealed, draft.readResult, draft.editedItems, draft.created),
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

    private companion object {
        const val DRAFT_FILE = "draft.json"
        val PHOTO = Regex("""photo(\d+)\.jpg""")
    }
}
