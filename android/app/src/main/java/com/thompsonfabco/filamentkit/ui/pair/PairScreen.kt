package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.DiscoveredServer
import com.thompsonfabco.filamentkit.ui.LocalNetworkAccess
import com.thompsonfabco.filamentkit.ui.components.LocalNetworkNotice
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

// The pairing screens (05-android-app 4): one destination per step, all in one column up to `column-max` wide.

/** The layout all pairing screens share: one centred column, 16 dp gutters, the step's main button last in it. */
@Composable
internal fun PairPage(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val space = SpoolwardenTheme.space
    Box(modifier.fillMaxSize().verticalScroll(rememberScrollState()), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth().padding(space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
            content = content,
        )
    }
}

@Composable
internal fun PairHeading(text: String) {
    Text(text, style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
}

/** "App 0.5.2" (`--mono`, `--muted`). */
@Composable
internal fun PairVersion(appVersion: String) {
    Text(stringResource(R.string.pair_version, appVersion), style = SpoolwardenTheme.type.dataSmall, color = SpoolwardenTheme.colors.muted)
}

/** The step's two buttons: side by side on a medium window, stacked full width with the main one on top on a compact one. */
@Composable
internal fun PairButtons(
    mainText: String,
    onMain: () -> Unit,
    otherText: String,
    onOther: () -> Unit,
    modifier: Modifier = Modifier,
    mainKind: SwButtonKind = SwButtonKind.Main,
) {
    val gap = Arrangement.spacedBy(SpoolwardenTheme.space.s2)
    if (SpoolwardenTheme.window == WindowClass.Phone) {
        Column(modifier.fillMaxWidth(), verticalArrangement = gap) {
            SwButton(mainText, onMain, Modifier.fillMaxWidth(), kind = mainKind)
            SwButton(otherText, onOther, Modifier.fillMaxWidth())
        }
    } else {
        Row(modifier.fillMaxWidth(), horizontalArrangement = gap) {
            SwButton(mainText, onMain, Modifier.weight(1f), kind = mainKind)
            SwButton(otherText, onOther, Modifier.weight(1f))
        }
    }
}

/** A fingerprint in a `code` box, four groups to a line; selectable, and read group by group (05-android-app 4.6). */
@Composable
internal fun FingerprintBox(fingerprint: String, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val shape = SpoolwardenTheme.shapes.r
    val spoken = groupFingerprint(fingerprint).replace(" ", ", ")
    Box(
        modifier.fillMaxWidth().background(colors.code, shape)
            .border(SpoolwardenTheme.sizes.hairline, colors.border, shape).padding(SpoolwardenTheme.space.s3),
    ) {
        SelectionContainer {
            Text(
                fingerprintLines(fingerprint).joinToString("\n"),
                style = MaterialTheme.typography.bodyLarge.copy(fontFamily = SpoolwardenTheme.type.data.fontFamily),
                modifier = Modifier.semantics { contentDescription = spoken },
            )
        }
    }
}

/** 4.2: the page header, the version, and the local network panel; pairing moves on by itself once access is granted. */
@Composable
internal fun PairNetworkAccessScreen(access: LocalNetworkAccess, appVersion: String) {
    PairPage {
        PairHeading(stringResource(R.string.pair_title))
        PairVersion(appVersion)
        LocalNetworkNotice(access)
    }
}

/** 4.3: scan, or pick a Hub found on the network, or type its address. */
@Composable
internal fun PairStartScreen(
    ui: PairUi,
    discovered: List<DiscoveredServer>,
    appVersion: String,
    onScan: () -> Unit,
    onPick: (DiscoveredServer) -> Unit,
    onEnterAddress: () -> Unit,
    /** The Hub stopped accepting this phone (4.1). */
    unpairedBanner: Boolean = false,
    access: LocalNetworkAccess? = null,
) {
    PairPage {
        if (unpairedBanner) NoticeCard(NoticeKind.Bad, stringResource(R.string.pair_banner_unpaired))
        PairVersion(appVersion)
        Text(introText(), style = MaterialTheme.typography.bodyLarge)
        SwButton(
            stringResource(if (ui.busy) R.string.common_connecting else R.string.pair_start_scan), onScan,
            Modifier.fillMaxWidth(), kind = SwButtonKind.Main, enabled = !ui.busy, busy = ui.busy,
        )
        ui.error?.let { PairErrorLine(it, access) }
        FoundHubs(discovered, enabled = !ui.busy, onPick = onPick)
        SwButton(stringResource(R.string.pair_start_enter_address), onEnterAddress, Modifier.fillMaxWidth(), enabled = !ui.busy)
    }
}

/** The intro, with the command in `--mono`. */
@Composable
private fun introText() = stringResource(R.string.pair_start_intro).let { text ->
    val command = Regex("sudo \\S+ pair").find(text)
    buildAnnotatedString {
        if (command == null) {
            append(text)
        } else {
            append(text.substring(0, command.range.first))
            withStyle(SpanStyle(fontFamily = SpoolwardenTheme.type.data.fontFamily)) { append(command.value) }
            append(text.substring(command.range.last + 1))
        }
    }
}

/** The panel "Hubs found on this network". */
@Composable
private fun FoundHubs(discovered: List<DiscoveredServer>, enabled: Boolean, onPick: (DiscoveredServer) -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    OutlinedCard(
        Modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Column(Modifier.padding(vertical = space.s2)) {
            Text(
                stringResource(R.string.pair_start_found_title), style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = space.s4, vertical = space.s2).semantics { heading() },
            )
            if (discovered.isEmpty()) {
                SwProgress(null, Modifier.padding(horizontal = space.s4))
                Text(
                    stringResource(R.string.pair_start_found_looking), style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(horizontal = space.s4, vertical = space.s2),
                )
            }
            discovered.forEach { hub ->
                Row(
                    Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.density.row)
                        .clickable(enabled = enabled, role = Role.Button) { onPick(hub) }
                        .padding(horizontal = space.s4, vertical = space.s2),
                    horizontalArrangement = Arrangement.spacedBy(space.s3),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(painterResource(R.drawable.sw_st_filled), null, Modifier.size(space.s2), tint = colors.ok)
                    Column(Modifier.weight(1f)) {
                        Text(hub.name, style = MaterialTheme.typography.bodyLarge)
                        Text(hub.host, style = SpoolwardenTheme.type.dataSmall, color = colors.muted)
                    }
                    Icon(painterResource(R.drawable.sw_ic_chevron), null, tint = colors.muted)
                }
            }
        }
    }
}
