package com.thompsonfabco.filamentkit.ui.add

import android.os.Build
import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.nav.AddRoute
import com.thompsonfabco.filamentkit.nav.HomeGraph
import com.thompsonfabco.filamentkit.nav.HomeRoute
import java.nio.file.Files
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.serialization.json.JsonArray
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The Back rule is read from the add flow that lives in the entry of its screen. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class AddReplaceOwnerTest {
    @get:Rule val rule = createComposeRule()

    private val api = object : IntakeApi {
        override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?) = error("not used")
        override suspend fun retry(readId: String) = error("not used")
        override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?, readId: String?) = error("not used")
        override suspend fun locations(): List<String> = emptyList()
    }

    @Test fun aHandAddIsAskedAboutOnlyOnceFieldsAreTypedIn() {
        lateinit var nav: NavHostController
        var vm: AddViewModel? = null
        rule.setContent {
            nav = rememberNavController()
            NavHost(nav, startDestination = HomeGraph) {
                navigation<HomeGraph>(startDestination = HomeRoute) {
                    composable<HomeRoute> { Text("home") }
                    composable<AddRoute> {
                        vm = viewModel {
                            AddViewModel(api, DraftStore(Files.createTempDirectory("drafts").toFile()), taps = emptyFlow(), manual = true)
                        }
                        Text("add")
                    }
                }
            }
        }
        rule.runOnIdle { nav.navigate(AddRoute(manual = true)) }
        rule.waitForIdle()
        val entry = nav.currentBackStackEntry!!
        assertEquals("nothing typed yet", AddReplace.Replace, addReplaceOf(entry))

        rule.runOnIdle { vm!!.newFilament() }
        rule.waitForIdle()
        assertEquals("a filament line is typed in", AddReplace.AskLeave, addReplaceOf(entry))
    }
}
