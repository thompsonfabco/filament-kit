package com.thompsonfabco.filamentkit.ui.spool

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SpoolViewModelTest {
    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() = Dispatchers.resetMain()

    private fun spool(id: Int, remaining: Double = 800.0, location: String? = "Shelf A") = buildJsonObject {
        put("id", id)
        put("filament", buildJsonObject {
            put("name", "Grey")
            put("material", "PLA")
            put("color_hex", "808080")
            put("vendor", buildJsonObject { put("name", "SUNLU") })
        })
        location?.let { put("location", it) }
        put("remaining_weight", remaining)
    }

    class Call(val name: String, val args: Map<String, Any?>)

    private class FakeBackend : SpoolBackend {
        val calls = mutableListOf<Call>()
        var tagResult: JsonObject? = null
        var tagError: Exception? = null
        val tagGates = mutableMapOf<String, CompletableDeferred<JsonObject?>>()
        var updateError: Exception? = null
        var searchError: Exception? = null
        var locationsError: Exception? = null
        var linkError: ((Boolean) -> Exception?)? = null
        var sealed: List<JsonObject> = emptyList()
        var updateResult: JsonObject = buildJsonObject { put("id", 1) }
        var linkResult: JsonObject = buildJsonObject { put("id", 2) }

        override suspend fun tag(uid: String): JsonObject? {
            calls += Call("tag", mapOf("uid" to uid))
            tagError?.let { throw it }
            tagGates[uid]?.let { return it.await() }
            return tagResult
        }
        override suspend fun link(spoolId: Int, tag: String, force: Boolean, dryRun: Boolean, gross: Double?): JsonObject {
            calls += Call("link", mapOf("id" to spoolId, "tag" to tag, "force" to force, "dry" to dryRun, "gross" to gross))
            linkError?.invoke(dryRun)?.let { throw it }
            return linkResult
        }
        override suspend fun update(spoolId: Int, gross: Double?, location: String?, empty: Boolean, dryRun: Boolean): JsonObject {
            calls += Call("update", mapOf("id" to spoolId, "gross" to gross, "location" to location, "empty" to empty, "dry" to dryRun))
            updateError?.let { throw it }
            return updateResult
        }
        override suspend fun searchSealed(q: String): List<JsonObject> {
            calls += Call("search", mapOf("q" to q))
            searchError?.let { throw it }
            return sealed
        }
        override suspend fun locations(): List<String> {
            locationsError?.let { throw it }
            return listOf("Shelf A", "Dry box")
        }
    }

    private val backend = FakeBackend()
    private fun vm() = SpoolViewModel(backend)

    @Test fun knownTagShowsCard() {
        backend.tagResult = spool(1)
        val vm = vm()
        vm.onTag("4:77:90:e")
        val s = vm.state.value as SpoolUiState.Card
        assertEquals("SUNLU", s.spool.brand)
        assertEquals("Grey", s.spool.name)
        assertEquals("808080", s.spool.colorHex)
        assertEquals("Shelf A", s.spool.location)
        assertEquals(800.0, s.spool.remaining!!, 0.0)
    }

    @Test fun unknownTagShowsChoice() {
        val vm = vm()
        vm.onTag("a:b")
        assertEquals(SpoolUiState.UnknownTag("a:b"), vm.state.value)
    }

    @Test fun apiErrorsAndOtherExceptionsBecomeMessages() {
        backend.tagError = ApiError(0, "offline", "x")
        val vm = vm()
        vm.onTag("a")
        assertTrue((vm.state.value as SpoolUiState.Failed).message.contains("reach", ignoreCase = true))
        backend.tagError = IllegalStateException("boom")
        vm.onTag("a")
        assertEquals("Unexpected response from the server", (vm.state.value as SpoolUiState.Failed).message)
    }

    @Test fun weightPreviewIsDryRunThenConfirmIsNot() {
        backend.tagResult = spool(1)
        val vm = vm()
        vm.onTag("a")
        backend.updateResult = spool(1, remaining = 640.0)
        vm.previewWeight(900.0)
        var c = vm.state.value as SpoolUiState.Card
        assertEquals(640.0, c.weightPreview!!.remaining!!, 0.0)
        assertEquals(true, backend.calls.last().args["dry"])
        assertEquals(900.0, backend.calls.last().args["gross"])
        vm.confirmWeight()
        assertEquals(false, backend.calls.last().args["dry"])
        c = vm.state.value as SpoolUiState.Card
        assertNull(c.weightPreview)
        assertEquals(640.0, c.spool.remaining!!, 0.0)
    }

    @Test fun markEmptySendsEmptyAfterConfirmation() {
        backend.tagResult = spool(1)
        val vm = vm()
        vm.onTag("a")
        vm.askMarkEmpty()
        assertTrue((vm.state.value as SpoolUiState.Card).confirmEmpty)
        assertTrue(backend.calls.none { it.name == "update" })
        backend.updateResult = spool(1, remaining = 0.0)
        vm.confirmEmpty()
        val u = backend.calls.last()
        assertEquals(true, u.args["empty"])
        assertEquals(false, u.args["dry"])
        assertEquals(0.0, (vm.state.value as SpoolUiState.Card).spool.remaining!!, 0.0)
    }

    @Test fun moveSendsLocation() {
        backend.tagResult = spool(1)
        val vm = vm()
        vm.onTag("a")
        backend.updateResult = spool(1, location = "Dry box")
        vm.move("Dry box")
        assertEquals("Dry box", backend.calls.last().args["location"])
        assertEquals("Dry box", (vm.state.value as SpoolUiState.Card).spool.location)
    }

    @Test fun linkPreviewIsDryRunConfirmIsNot() {
        val vm = vm()
        vm.onTag("a:b")
        backend.sealed = listOf(spool(2))
        vm.startLink()
        vm.search("sun")
        assertEquals(1, (vm.state.value as SpoolUiState.LinkSearch).results.size)
        assertEquals("sun", backend.calls.last().args["q"])
        vm.pick(2, 1000.0)
        val p = vm.state.value as SpoolUiState.LinkPreview
        assertEquals(true, backend.calls.last().args["dry"])
        assertEquals(false, backend.calls.last().args["force"])
        assertEquals(1000.0, backend.calls.last().args["gross"])
        assertEquals(2, p.spool.id)
        vm.confirmLink()
        val last = backend.calls.last()
        assertEquals(false, last.args["dry"])
        assertEquals(2, last.args["id"])
        assertEquals("a:b", last.args["tag"])
        assertTrue(vm.state.value is SpoolUiState.Card)
    }

    @Test fun tagOnOtherSpoolConflictThenForce() {
        val vm = vm()
        vm.onTag("a:b")
        val extra = buildJsonObject {
            put("reason", "tag_on_other_spool")
            put("other_spool", spool(9))
        }
        backend.linkError = { dry -> if (dry) ApiError(409, "tag_conflict", "conflict", extra) else null }
        vm.pick(2, null)
        val c = vm.state.value as SpoolUiState.Conflict
        assertEquals(ConflictReason.TagOnOtherSpool, c.reason)
        assertEquals(9, c.otherSpool!!.id)
        assertTrue(c.message.contains("SUNLU"))
        vm.moveTagHere()
        val last = backend.calls.last()
        assertEquals(true, last.args["force"])
        assertEquals(false, last.args["dry"])
        assertTrue(vm.state.value is SpoolUiState.Card)
    }

    @Test fun spoolHasOtherTagConflictHasNoOtherSpool() {
        val vm = vm()
        vm.onTag("a:b")
        val extra = buildJsonObject {
            put("reason", "spool_has_other_tag")
            put("other_spool", JsonNull)
        }
        backend.linkError = { ApiError(409, "tag_conflict", "conflict", extra) }
        vm.pick(2, null)
        val c = vm.state.value as SpoolUiState.Conflict
        assertEquals(ConflictReason.SpoolHasOtherTag, c.reason)
        assertNull(c.otherSpool)
        assertTrue(c.message.contains("different tag"))
        assertTrue(c.message.contains("replaces"))

        backend.linkError = null
        vm.moveTagHere()
        val last = backend.calls.last()
        assertEquals(true, last.args["force"])
        assertEquals(false, last.args["dry"])
        assertEquals(2, last.args["id"])
        assertTrue(vm.state.value is SpoolUiState.Card)
    }

    @Test fun secondTapWinsEvenWhenFirstAnswersLast() {
        val first = CompletableDeferred<JsonObject?>()
        val second = CompletableDeferred<JsonObject?>()
        backend.tagGates["t1"] = first
        backend.tagGates["t2"] = second
        val vm = vm()
        vm.onTag("t1")
        vm.onTag("t2")
        second.complete(spool(22))
        first.complete(spool(11))
        assertEquals(22, (vm.state.value as SpoolUiState.Card).spool.id)
    }

    @Test fun newTapCancelsPendingSearch() {
        val vm = vm()
        vm.onTag("t1")
        vm.startLink()
        backend.tagGates["t2"] = CompletableDeferred<JsonObject?>().also { it.complete(spool(5)) }
        vm.onTag("t2")
        assertEquals(5, (vm.state.value as SpoolUiState.Card).spool.id)
    }

    private val unauthorized = ApiError(401, "unauthorized", "no")

    @Test fun unauthorizedOnEveryPathOffersPairAgain() {
        // tag lookup
        backend.tagError = unauthorized
        var vm = vm()
        vm.onTag("a")
        assertEquals(SpoolUiState.Unauthorized, vm.state.value)
        backend.tagError = null

        // card actions
        backend.tagResult = spool(1)
        vm = vm()
        vm.onTag("a")
        backend.updateError = unauthorized
        vm.previewWeight(500.0)
        assertEquals(SpoolUiState.Unauthorized, vm.state.value)
        vm.onTag("a"); vm.move("Dry box")
        assertEquals(SpoolUiState.Unauthorized, vm.state.value)
        vm.onTag("a"); vm.askMarkEmpty(); vm.confirmEmpty()
        assertEquals(SpoolUiState.Unauthorized, vm.state.value)
        backend.updateError = null
        backend.locationsError = unauthorized
        vm.onTag("a"); vm.openMove()
        assertEquals(SpoolUiState.Unauthorized, vm.state.value)
        backend.locationsError = null

        // search and link
        backend.tagResult = null
        vm = vm()
        vm.onTag("a"); vm.startLink()
        backend.searchError = unauthorized
        vm.search("x")
        assertEquals(SpoolUiState.Unauthorized, vm.state.value)
        backend.searchError = null
        backend.linkError = { unauthorized }
        vm.onTag("a"); vm.pick(2, null)
        assertEquals(SpoolUiState.Unauthorized, vm.state.value)
    }

    @Test fun fingerprintMismatchHasOwnState() {
        backend.tagError = FingerprintMismatch("aa", "bb")
        val vm = vm()
        vm.onTag("a")
        assertEquals(SpoolUiState.Mismatch("aa", "bb"), vm.state.value)
    }

    @Test fun conflictOnConfirmLinkShowsConflict() {
        val vm = vm()
        vm.onTag("a:b")
        vm.pick(2, null)
        assertTrue(vm.state.value is SpoolUiState.LinkPreview)
        val extra = buildJsonObject {
            put("reason", "tag_on_other_spool")
            put("other_spool", spool(9))
        }
        backend.linkError = { dry -> if (!dry) ApiError(409, "tag_conflict", "conflict", extra) else null }
        vm.confirmLink()
        val c = vm.state.value as SpoolUiState.Conflict
        assertEquals(9, c.otherSpool!!.id)
        assertEquals(2, c.spoolId)
    }

    @Test fun failuresKeepTheScreenWithAnInlineMessage() {
        backend.tagResult = spool(1)
        val vm = vm()
        vm.onTag("a")

        backend.updateError = ApiError(500, "internal", "Server broke")
        vm.previewWeight(500.0)
        assertEquals("Server broke", (vm.state.value as SpoolUiState.Card).message)
        backend.updateError = IllegalStateException("boom")
        vm.move("Dry box")
        assertEquals("Unexpected response from the server", (vm.state.value as SpoolUiState.Card).message)
        vm.askMarkEmpty()
        vm.confirmEmpty()
        val c = vm.state.value as SpoolUiState.Card
        assertEquals("Unexpected response from the server", c.message)
        assertEquals(false, c.confirmEmpty)
        assertEquals(1, c.spool.id)

        // link flow keeps its screen
        backend.tagResult = null
        vm.onTag("t")
        vm.startLink()
        backend.searchError = ApiError(0, "offline", "x")
        vm.search("q")
        assertTrue((vm.state.value as SpoolUiState.LinkSearch).error!!.contains("reach"))
        backend.searchError = null
        backend.linkError = { IllegalStateException("x") }
        vm.pick(2, null)
        assertTrue((vm.state.value as SpoolUiState.LinkSearch).error != null)
        backend.linkError = null
        vm.pick(2, null)
        backend.linkError = { IllegalStateException("x") }
        vm.confirmLink()
        assertTrue((vm.state.value as SpoolUiState.LinkPreview).error != null)
    }

    @Test fun moveTagHereFailureStaysOnConflict() {
        val vm = vm()
        vm.onTag("a:b")
        val extra = buildJsonObject { put("reason", "spool_has_other_tag") }
        backend.linkError = { ApiError(409, "tag_conflict", "conflict", extra) }
        vm.pick(2, null)
        backend.linkError = { IllegalStateException("x") }
        vm.moveTagHere()
        assertTrue((vm.state.value as SpoolUiState.Conflict).error != null)
    }

    @Test fun freshCardGetsNewRevision() {
        backend.tagResult = spool(1)
        val vm = vm()
        vm.onTag("a")
        val r1 = (vm.state.value as SpoolUiState.Card).rev
        vm.onTag("a")
        assertTrue((vm.state.value as SpoolUiState.Card).rev != r1)
    }
}
