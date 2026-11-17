package com.thompsonfabco.filamentkit.ui.storage

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.StorageAnswer
import com.thompsonfabco.filamentkit.net.StorageLocation
import com.thompsonfabco.filamentkit.net.StorageWire
import com.thompsonfabco.filamentkit.ui.add.AddText
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StorageRowsTest {
    private fun obj(text: String) = Json.parseToJsonElement(text).jsonObject

    @Test fun howFullForEveryCase() {
        val limited = StorageLocation("Rack 1", limit = 20, used = 18)
        assertEquals(AddText.of(R.string.storage_how_full_limit, 18, 20), limited.howFullText())
        assertEquals(AddText.of(R.string.storage_how_full_spools, 7), StorageLocation("Shelf", used = 7).howFullText())
        assertEquals(AddText.of(R.string.storage_how_full_full), limited.copy(used = 20).howFullText())
        assertEquals(AddText.of(R.string.storage_how_full_full), limited.copy(used = 22).howFullText())
        val box = StorageLocation("Storage box", type = "containers", count = 12, used = 9, free = 3)
        assertEquals(AddText.of(R.string.storage_how_full_free, 3), box.howFullText())
        assertEquals(AddText.of(R.string.storage_how_full_free, 3), box.copy(free = null).howFullText())
        assertEquals(AddText.of(R.string.storage_how_full_full), box.copy(used = 12, free = 0).howFullText())
        assertNull(box.copy(used = null, free = null).howFullText())
        assertNull(StorageLocation("Shelf").howFullText())
        assertNull(limited.copy(used = null).howFullText())
    }

    @Test fun theDefaultOverflowAndSealedLocationsShowTheirLimitLikeAnyBulkLocation() {
        val over = StorageLocation("Overflow", limit = 20, used = 18, defaultOverflow = true)
        assertEquals(AddText.of(R.string.storage_how_full_limit, 18, 20), over.howFullText())
        assertEquals(AddText.of(R.string.storage_how_full_full), over.copy(used = 20).howFullText())
        val sealed = over.copy(defaultOverflow = false, sealed = true)
        assertEquals(AddText.of(R.string.storage_how_full_limit, 18, 20), sealed.howFullText())
        assertEquals(AddText.of(R.string.storage_how_full_spools, 9), over.copy(limit = null, used = 9).howFullText())
    }

    @Test fun rowsKeepFillOrderMarkFullAndStayChoosable() {
        val rows = StorageAnswer(
            listOf(
                StorageLocation("Rack 1", limit = 2, used = 2),
                StorageLocation("Box", type = "containers", count = 2, used = 1, free = 1),
                StorageLocation("Bare"),
            ),
        ).rows()
        assertEquals(listOf("Rack 1", "Box", "Bare"), rows.map { it.name })
        assertEquals(listOf(true, false, false), rows.map { it.full })
        assertNull(rows[2].howFull)
        assertEquals(listOf(null, null, null), StorageAnswer.ofNames(listOf("a", "b", "c")).rows().map { it.howFull })
    }

    @Test fun moveRowsSayNowHereAndHowFull() {
        val row = LocationRow("Rack 1", AddText.of(R.string.storage_how_full_limit, 18, 20), false)
        assertEquals(listOf(AddText.of(R.string.spool_move_here), row.howFull), row.moveLines(here = true, moving = false))
        assertEquals(listOf(row.howFull), row.moveLines(here = false, moving = false))
        assertEquals(listOf(AddText.of(R.string.spool_move_moving)), row.moveLines(here = false, moving = true))
        val bare = LocationRow("Bare", null, false)
        assertTrue(bare.moveLines(here = false, moving = false).isEmpty())
        assertEquals(listOf(AddText.of(R.string.spool_move_here)), bare.moveLines(here = true, moving = false))
    }

    @Test fun aContainersRowHoldsTheContainerNamesTheHubListsOnly() {
        // a migrated set keeps its old prefix: the set is called differently from its containers
        val names = listOf("Storage box 01", "Storage box 03", "Storage box 100")
        val box = LocationRow("Storage box (containers)", null, false, containers = true, containerNames = names)
        assertTrue(box.holds("Storage box 03"))
        assertTrue(box.holds("Storage box 100"))
        assertTrue(box.holds("Storage box (containers)"))
        assertFalse(box.holds("Storage box 3"))
        assertFalse(box.holds("Storage box 02"))
        assertFalse(LocationRow("Rack 1", null, false).holds("Rack 1 02"))
        assertFalse(box.holds(null))
    }

    @Test fun containerNamesComeFromTheAnswerAndReachTheRow() {
        val answer = StorageWire.parse(kotlinx.serialization.json.Json.parseToJsonElement(
            """{"locations":[{"name":"Box","type":"containers","count":2,"prefix":"Box-","containers":[{"name":"Box-01","number":1,"taken":false},{"name":"Box-02","number":2,"taken":true}]}]}"""))!!
        val row = answer.rows().single()
        assertTrue(row.holds("Box-02"))
        assertFalse(row.holds("Box 02"))
    }

    @Test fun reasonsFollowTheCode() {
        assertEquals(AddText.of(R.string.storage_reason_material, "PLA"), reasonOf("material", "PLA"))
        assertEquals(AddText.of(R.string.storage_reason_any), reasonOf("any", null))
        assertEquals(AddText.of(R.string.storage_reason_overflow, "PETG"), reasonOf("overflow", "PETG"))
        assertEquals(AddText.of(R.string.storage_reason_sealed), reasonOf("sealed", null))
        assertNull(reasonOf("material", null))
        assertNull(reasonOf("pla", "PLA")) // an old code is no reason
        assertNull(reasonOf(null, "PLA"))
    }

    @Test fun placesCarryTheirReasonOrNoneForAChosenPlace() {
        val item = obj("""{"material":"PLA"}""")
        val hub = obj(
            """{"placements":[{"location":"Rack 1","spools":2,"placed_by":"material"},
            {"location":"Overflow","spools":1,"placed_by":"overflow"},{"location":"Rack 1","spools":1,"placed_by":"material"}]}""",
        )
        assertEquals(
            listOf(
                Place("Rack 1", AddText.of(R.string.storage_reason_material, "PLA")),
                Place("Overflow", AddText.of(R.string.storage_reason_overflow, "PLA")),
            ),
            placesOf(hub, item),
        )
        assertEquals(listOf(Place("Shelf B", null)), placesOf(obj("""{"placements":[{"location":"Shelf B"}]}"""), item))
        assertEquals(listOf(Place("Shelf A", null)), placesOf(null, obj("""{"location":"Shelf A"}""")))
        assertEquals(
            listOf(Place("Rack 1", AddText.of(R.string.storage_reason_any))),
            placesOf(obj("""{"location":"Rack 1","placed_by":"any"}"""), item),
        )
        assertTrue(placesOf(null, item).isEmpty())
    }

    @Test fun automaticPlacesSkipItemsThatNameTheirOwnPlace() {
        val items = listOf(obj("""{"material":"PLA"}"""), obj("""{"material":"PLA","location":"Shelf A"}"""), obj("""{"material":"PETG"}"""))
        val hub = listOf(
            obj("""{"index":2,"placements":[{"location":"Overflow","placed_by":"overflow"}]}"""),
            obj("""{"index":0,"placements":[{"location":"Rack 1","placed_by":"material"}]}"""),
            obj("""{"index":1,"placements":[{"location":"Shelf A"}]}"""),
        )
        val m = autoPlacesOf(items, hub)
        assertEquals(setOf(0, 2), m.keys)
        assertEquals("Rack 1", m[0]!!.single().location)
        assertEquals(AddText.of(R.string.storage_reason_overflow, "PETG"), m[2]!!.single().reason)
        assertTrue(autoPlacesOf(items, emptyList()).isEmpty())
    }
}
