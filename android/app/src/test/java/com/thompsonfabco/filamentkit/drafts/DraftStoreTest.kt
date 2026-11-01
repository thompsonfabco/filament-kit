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
}
