package com.thompsonfabco.filamentkit.alerts

import android.annotation.SuppressLint
import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.thompsonfabco.filamentkit.MainActivity
import com.thompsonfabco.filamentkit.R

/**
 * The Android side of the alerts: the two channels, the permanent notification of the watching service and one
 * notification per alert. Thin on purpose; what notifies is decided by [notifyActions].
 */
class AlertNotifier(private val context: Context) {
    private val manager = NotificationManagerCompat.from(context)

    fun ensureChannels() {
        manager.createNotificationChannel(
            NotificationChannelCompat.Builder(CHANNEL_ALERTS, NotificationManagerCompat.IMPORTANCE_HIGH)
                .setName(context.getString(R.string.alerts_channel_alerts)).build(),
        )
        manager.createNotificationChannel(
            NotificationChannelCompat.Builder(CHANNEL_WATCHING, NotificationManagerCompat.IMPORTANCE_LOW)
                .setName(context.getString(R.string.alerts_channel_watching)).build(),
        )
    }

    /** Android's own answer: the notification permission (API 33+) and the app's notification switch. */
    fun allowed(): Boolean = manager.areNotificationsEnabled()

    /** The permanent notification Android requires while the service watches. */
    fun watching(): Notification {
        ensureChannels()
        return NotificationCompat.Builder(context, CHANNEL_WATCHING)
            .setSmallIcon(R.drawable.sw_ic_spool)
            .setContentTitle(context.getString(R.string.alerts_watching_title))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setContentIntent(open(null, null, WATCHING_REQUEST))
            .build()
    }

    fun act(actions: List<NotifyAction>) {
        actions.forEach { a ->
            when (a) {
                is NotifyAction.Show -> show(a)
                is NotifyAction.Cancel -> manager.cancel(a.tag, NOTIFICATION_ID)
                is NotifyAction.ShowTest -> showText(TEST_TAG, a.test.title, a.test.text, null, null)
            }
        }
    }

    private fun show(a: NotifyAction.Show) =
        showText(a.tag, a.event.title, a.event.text, a.event.action.place, a.event.action.id)

    @SuppressLint("MissingPermission") // checked: nothing is posted while notifications are not allowed
    private fun showText(tag: String, title: String, text: String, place: String?, placeId: String?) {
        if (!allowed()) return
        ensureChannels()
        val notification = NotificationCompat.Builder(context, CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.sw_ic_spool)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setContentIntent(open(place, placeId, tag.hashCode()))
            .build()
        try {
            manager.notify(tag, NOTIFICATION_ID, notification)
        } catch (_: SecurityException) {
            // the permission was taken away between the check and the post
        }
    }

    /** Tapping opens the app on the alert's place ([MainActivity] reads the extras). */
    private fun open(place: String?, placeId: String?, request: Int): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        if (place != null) intent.putExtra(EXTRA_PLACE, place)
        if (placeId != null) intent.putExtra(EXTRA_PLACE_ID, placeId)
        if (place != null) intent.putExtra(EXTRA_ALERT, true)
        return PendingIntent.getActivity(context, request, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    companion object {
        const val CHANNEL_ALERTS = "alerts"
        const val CHANNEL_WATCHING = "watching"
        const val WATCHING_ID = 1
        private const val NOTIFICATION_ID = 2
        private const val WATCHING_REQUEST = 1
        private const val TEST_TAG = "alert:test"

        /** The intent extras of a tapped alert: its place and the place's id (the printer's). */
        const val EXTRA_ALERT = "filamentkit.alert"
        const val EXTRA_PLACE = "filamentkit.alert.place"
        const val EXTRA_PLACE_ID = "filamentkit.alert.place_id"

        /** The place an alert's tap carries, null for any other intent. A test alert and a place-less one open the list. */
        fun targetOf(intent: Intent?): AlertTarget? {
            if (intent?.getBooleanExtra(EXTRA_ALERT, false) != true) return null
            return alertTarget(intent.getStringExtra(EXTRA_PLACE), intent.getStringExtra(EXTRA_PLACE_ID))
        }
    }
}
