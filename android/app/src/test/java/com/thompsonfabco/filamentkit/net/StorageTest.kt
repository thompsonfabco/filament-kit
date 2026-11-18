package com.thompsonfabco.filamentkit.net

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StorageTest {
    private fun parse(text: String) = StorageWire.parse(Json.parseToJsonElement(text))

    @Test fun aFullAnswerIsParsed() {
        val a = parse(
            """{"locations":[
              {"id":"loc-1","name":"Rack 1","type":"bulk","limit":20,"count":null,"used":18,"free":null,"fill":"materials",
               "materials":["PLA"],"overflow":false,"default_overflow":false,"sealed":false,"position":1},
              {"id":"loc-3","name":"Storage box","type":"containers","limit":null,"count":12,"used":9,"free":3,"fill":"any",
               "materials":[],"overflow":false,"default_overflow":false,"sealed":false,"position":2},
              {"id":"loc-4","name":"Overflow","type":"bulk","limit":null,"used":7,"fill":"none","overflow":true,
               "default_overflow":true,"sealed":true,"position":3}],
             "order_by_material":[{"material":"PLA","locations":["Rack 1","Overflow"]}],
             "everything_else":["Storage box","Overflow"]}""",
        )!!
        assertTrue(a.detailed)
        assertEquals(listOf("Rack 1", "Storage box", "Overflow"), a.names)
        assertEquals(StorageLocation("Rack 1", "loc-1", "bulk", 20, null, 18, null, "materials", listOf("PLA"), false, false, false, 1), a.locations[0])
        assertTrue(a.locations[1].containers)
        assertEquals(3, a.locations[1].free)
        assertTrue(a.locations[2].defaultOverflow && a.locations[2].overflow && a.locations[2].sealed)
        assertEquals(listOf(MaterialOrder("PLA", listOf("Rack 1", "Overflow"))), a.orderByMaterial)
        assertEquals(listOf("Storage box", "Overflow"), a.everythingElse)
    }

    @Test fun missingAndOddFieldsAreTolerated() {
        val a = parse(
            """{"locations":["Shelf B",{"name":"Rack","limit":"20","used":"x","type":"weird","overflow":"yes"},
               {"id":"nameless"},7,null,{"name":" "}]}""",
        )!!
        assertEquals(listOf("Shelf B", "Rack"), a.names)
        val rack = a.locations[1]
        assertEquals(20, rack.limit)
        assertNull(rack.used)
        assertEquals("bulk", rack.type)
        assertFalse(rack.overflow)
        assertTrue(a.orderByMaterial.isEmpty() && a.everythingElse.isEmpty())
    }

    @Test fun locationsAreInFillOrderByPositionThenListOrder() {
        val a = parse("""{"locations":[{"name":"C","position":3},{"name":"A","position":1},{"name":"X"},{"name":"B","position":2}]}""")!!
        assertEquals(listOf("A", "B", "C", "X"), a.names)
    }

    @Test fun anAnswerWithoutALocationsListIsNotAStorageAnswer() {
        assertNull(parse("""{"error":"x"}"""))
        assertNull(parse("""[]"""))
        assertNull(StorageWire.parse(null))
    }

    @Test fun theNamesFallbackHasNoDetail() {
        val a = StorageAnswer.ofNames(listOf("Shelf A", "Shelf B"))
        assertFalse(a.detailed)
        assertEquals(listOf("Shelf A", "Shelf B"), a.names)
        assertNull(a.locations[0].used)
    }
}
