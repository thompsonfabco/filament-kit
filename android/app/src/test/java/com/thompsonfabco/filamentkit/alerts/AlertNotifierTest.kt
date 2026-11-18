package com.thompsonfabco.filamentkit.alerts

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Build
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class AlertNotifierTest {
    private val context = RuntimeEnvironment.getApplication()
    private val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private val notifier = AlertNotifier(context)

    private fun event(id: Long, key: String? = null) = AlertEvent(
        id = id, atMillis = null, kind = "print.runout", severity = AlertSeverity.Warn,
        condition = key?.let { AlertCondition(it, "raised") }, alert = true, title = "Filament ran out", text = "Load filament.",
        action = AlertAction("printer", "p-3"),
    )

    private fun shown() = shadowOf(manager).allNotifications

    @Test fun anAlertIsOneNotificationWithTheHubsTitleAndSentence() {
        notifier.act(listOf(NotifyAction.Show("alert:event:1", event(1))))
        val n = shown().single()
        assertEquals("Filament ran out", n.extras.getString("android.title"))
        assertEquals("Load filament.", n.extras.getString("android.text"))
        assertEquals(AlertNotifier.CHANNEL_ALERTS, n.channelId)
    }

    @Test fun theSameConditionReplacesItsNotificationAndClearingRemovesIt() {
        notifier.act(listOf(NotifyAction.Show("alert:c", event(1, "c")), NotifyAction.Show("alert:c", event(2, "c"))))
        assertEquals(1, shown().size)
        notifier.act(listOf(NotifyAction.Cancel("alert:c")))
        assertTrue(shown().isEmpty())
    }

    @Test fun aTestIsShownAsANotification() {
        notifier.act(listOf(NotifyAction.ShowTest(AlertTest("Test alert", "It works."))))
        assertEquals("Test alert", shown().single().extras.getString("android.title"))
    }

    @Test fun nothingIsPostedWhileNotificationsAreBlocked() {
        shadowOf(manager).setNotificationsEnabled(false)
        assertFalse(notifier.allowed())
        notifier.act(listOf(NotifyAction.Show("alert:event:1", event(1))))
        assertTrue(shown().isEmpty())
    }

    @Test fun thePermanentNotificationSaysWhatTheServiceDoesOnItsOwnChannel() {
        val n = notifier.watching()
        assertEquals("Watching the Hub for alerts", n.extras.getString("android.title"))
        assertEquals(AlertNotifier.CHANNEL_WATCHING, n.channelId)
        assertTrue("ongoing", n.flags and android.app.Notification.FLAG_ONGOING_EVENT != 0)
    }

    @Test fun aTappedNotificationNamesItsPlaceAndOtherIntentsNameNone() {
        val tap = Intent().putExtra(AlertNotifier.EXTRA_ALERT, true).putExtra(AlertNotifier.EXTRA_PLACE, "printer")
            .putExtra(AlertNotifier.EXTRA_PLACE_ID, "p-3")
        assertEquals(AlertTarget.Printer("p-3"), AlertNotifier.targetOf(tap))
        assertEquals(AlertTarget.RunningLow, AlertNotifier.targetOf(Intent().putExtra(AlertNotifier.EXTRA_ALERT, true).putExtra(AlertNotifier.EXTRA_PLACE, "running_low")))
        assertNull(AlertNotifier.targetOf(Intent()))
        assertNull(AlertNotifier.targetOf(null))
    }
}
