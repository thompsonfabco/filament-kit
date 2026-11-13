package com.thompsonfabco.filamentkit.ui.pair

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * 4.8: the Hub's certificate is not the one expected. A panel with the octagon and a title in `bad`; the fingerprints
 * under their labels. [canTrust] offers "Trust the new certificate" (only a saved pairing the app can keep in place);
 * without it "Pair again" is the main button. A saved pairing keeps refusing the Hub until one of the buttons is used,
 * so its Back is the system's; during pairing Back starts over ([onBack]).
 */
@Composable
internal fun PairCertificateScreen(
    mismatch: Mismatch,
    canTrust: Boolean,
    onTrust: () -> Unit,
    onPairAgain: () -> Unit,
    onBack: () -> Unit,
) {
    val text = mismatchText(mismatch.source)
    if (mismatch.source != MismatchSource.STORED) BackHandler(onBack = onBack)
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    PairPage {
        OutlinedCard(
            Modifier.fillMaxWidth(),
            shape = SpoolwardenTheme.shapes.r,
            colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
            border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
        ) {
            Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s3)) {
                Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.Top) {
                    Icon(
                        painterResource(R.drawable.sw_st_octagon), null,
                        Modifier.padding(top = space.s1).size(space.s2 + space.s1 / 2), tint = colors.bad,
                    )
                    Text(
                        text.title, color = colors.bad, style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.semantics { heading() },
                    )
                }
                Text(text.body, style = MaterialTheme.typography.bodyMedium)
                if (text.showsFingerprints) {
                    text.expectedLabel?.let { label ->
                        Text(label, style = MaterialTheme.typography.labelLarge)
                        FingerprintBox(mismatch.expected)
                    }
                    Text(text.actualLabel, style = MaterialTheme.typography.labelLarge)
                    FingerprintBox(mismatch.actual)
                }
                text.whereToCheck?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            }
        }
        val trust = text.trustButton?.takeIf { canTrust }
        if (trust != null) {
            PairButtons(trust, onTrust, text.button, onPairAgain)
        } else {
            SwButton(text.button, onPairAgain, Modifier.fillMaxWidth(), kind = SwButtonKind.Main)
        }
    }
}
