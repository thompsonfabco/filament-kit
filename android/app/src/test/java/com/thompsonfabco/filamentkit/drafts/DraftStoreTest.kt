package com.thompsonfabco.filamentkit.drafts

import java.io.File
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class DraftStoreTest {
    private lateinit var dir: File

    @Before fun setUp() { dir = kotlin.io.path.createTempDirectory("drafts").toFile() }
    @After fun tearDown() { dir.deleteRecursively() }

    @Test fun createAddPhotosUpdateListSurviveNewStore() {
        val store = DraftStore(dir)
        val d = store.create()
        assertNotEquals(d.id, store.create().id)
        val p1 = store.addPhoto(d.id, byteArrayOf(1, 2, 3))
        val p2 = store.addPhoto(d.id, byteArrayOf(4))
        assertEquals("photo1.jpg", p1.name)
        assertEquals("photo2.jpg", p2.name)
        val read = buildJsonObject { put("brand", "SUNLU") }
        val items = JsonArray(listOf(JsonPrimitive("x")))
        store.update(store.get(d.id)!!.copy(
            hint = "grey PLA", tag = "04AABB", weightGrams = 1234.5, sealed = true,
            readResult = read, editedItems = items,
        ))

        val again = DraftStore(dir)
        val all = again.list()
        assertEquals(2, all.size)
        val got = again.get(d.id)!!
        assertEquals(listOf("photo1.jpg", "photo2.jpg"), got.photos.map { it.name })
        assertEquals(3, got.photos[0].length())
        assertEquals("grey PLA", got.hint)
        assertEquals("04AABB", got.tag)
        assertEquals(1234.5, got.weightGrams!!, 0.0)
        assertTrue(got.sealed)
        assertEquals(read, got.readResult)
        assertEquals(items, got.editedItems)
        assertEquals(d.created, got.created)
    }

    @Test fun defaultsAreEmpty() {
        val d = DraftStore(dir).create()
        assertEquals("", d.hint)
        assertNull(d.tag); assertNull(d.weightGrams); assertNull(d.readResult); assertNull(d.editedItems)
        assertFalse(d.sealed)
        assertTrue(d.photos.isEmpty())
    }

    @Test fun deleteRemovesFolder() {
        val store = DraftStore(dir)
        val d = store.create()
        store.addPhoto(d.id, byteArrayOf(1))
        store.delete(d.id)
        assertFalse(File(dir, d.id).exists())
        assertNull(store.get(d.id))
        assertTrue(store.list().isEmpty())
    }

    @Test fun corruptDraftJsonIsSkipped() {
        val store = DraftStore(dir)
        val good = store.create()
        val bad = store.create()
        File(dir, "${bad.id}/draft.json").writeText("{not json")
        assertEquals(listOf(good.id), store.list().map { it.id })
        assertNull(store.get(bad.id))
    }

    @Test fun updateLeavesNoTempFiles() {
        val store = DraftStore(dir)
        val d = store.create()
        store.update(d.copy(hint = "a"))
        store.update(d.copy(hint = "b"))
        assertEquals(setOf("draft.json"), File(dir, d.id).list()!!.toSet())
        assertEquals("b", store.get(d.id)!!.hint)
    }

    private val day = 24L * 60 * 60 * 1000

    @Test fun purgeDeletesOldPhotolessAndUnreadableDraftsButKeepsTheRest() {
        val store = DraftStore(dir)
        val now = 100 * day
        fun draft(ageDays: Long, photos: Int, addedBefore: List<Long>? = null): String {
            val d = store.create()
            repeat(photos) { store.addPhoto(d.id, byteArrayOf(1)) }
            store.update(store.get(d.id)!!.copy(created = now - ageDays * day, addedBefore = addedBefore))
            return d.id
        }
        val fresh = draft(ageDays = 2, photos = 1)
        val old = draft(ageDays = 31, photos = 2)
        val noPhotos = draft(ageDays = 1, photos = 0)
        val warned = draft(ageDays = 60, photos = 0, addedBefore = listOf(7L))
        val unreadable = draft(ageDays = 1, photos = 1)
        File(dir, "$unreadable/draft.json").writeText("{not json")

        assertEquals(3, store.purge(30 * day, now))
        assertEquals(setOf(fresh, warned), dir.list()!!.toSet())
        assertFalse(File(dir, old).exists())
        assertFalse(File(dir, noPhotos).exists())
        assertFalse(File(dir, unreadable).exists())
    }

    @Test fun purgeOfAnEmptyOrMissingFolderDeletesNothing() {
        assertEquals(0, DraftStore(dir).purge(30 * day))
        assertEquals(0, DraftStore(File(dir, "absent")).purge(30 * day))
    }

    @Test fun aDraftExactlyAtTheLimitIsKept() {
        val store = DraftStore(dir)
        val d = store.create()
        store.addPhoto(d.id, byteArrayOf(1))
        store.update(store.get(d.id)!!.copy(created = 70 * day))
        assertEquals(0, store.purge(30 * day, now = 100 * day))
        assertEquals(1, store.purge(30 * day, now = 100 * day + 1))
    }

    @Test fun aHandDraftIsKeptWhileItHoldsTypedSpoolsAndDroppedWhenEmpty() {
        val store = DraftStore(dir)
        val empty = store.create(manual = true)
        val typed = store.create(manual = true)
        store.update(
            store.get(typed.id)!!.copy(
                editedItems = kotlinx.serialization.json.JsonArray(listOf(kotlinx.serialization.json.JsonObject(emptyMap()))),
            ),
        )
        assertTrue(store.get(typed.id)!!.manual)
        assertTrue(store.get(typed.id)!!.hasContent)
        assertFalse(store.get(empty.id)!!.hasContent)
        assertEquals(1, store.purge(30 * day))
        assertEquals(setOf(typed.id), dir.list()!!.toSet())
    }
}
