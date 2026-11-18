package com.thompsonfabco.filamentkit

import android.content.pm.PackageManager
import android.os.Build
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.xmlpull.v1.XmlPullParser

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class ManifestTest {
    private val context = RuntimeEnvironment.getApplication()

    @Test fun theLauncherLabelIsTheCatalogueAppName() {
        assertEquals(context.getString(R.string.app_name), context.packageManager.getApplicationLabel(context.applicationInfo).toString())
        assertEquals(R.string.app_name, context.applicationInfo.labelRes)
    }

    @Test fun theLauncherIconAndRoundIconAreTheAdaptiveMipmaps() {
        assertEquals(R.mipmap.ic_launcher, context.applicationInfo.icon)
        val manifest = context.assets.openXmlResourceParser("AndroidManifest.xml")
        while (manifest.next() != XmlPullParser.END_DOCUMENT) {
            if (manifest.eventType == XmlPullParser.START_TAG && manifest.name == "application") break
        }
        val ns = "http://schemas.android.com/apk/res/android"
        assertEquals(R.mipmap.ic_launcher, manifest.getAttributeResourceValue(ns, "icon", 0))
        assertEquals(R.mipmap.ic_launcher_round, manifest.getAttributeResourceValue(ns, "roundIcon", 0))
    }

    @Test fun backupIsOff() {
        assertEquals(0, context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_ALLOW_BACKUP)
    }

    /** The pairing's bearer token must not reach a backup or another phone, whatever file it later moves to. */
    @Test fun nothingLeavesThePhone() {
        val manifest = context.assets.openXmlResourceParser("AndroidManifest.xml")
        while (manifest.next() != XmlPullParser.END_DOCUMENT) {
            if (manifest.eventType == XmlPullParser.START_TAG && manifest.name == "application") break
        }
        val res = manifest.getAttributeResourceValue("http://schemas.android.com/apk/res/android", "dataExtractionRules", 0)
        assertTrue("android:dataExtractionRules is not set", res != 0)
        val parser = context.resources.getXml(res)
        val excluded = mutableMapOf<String, MutableSet<String>>()
        var section = ""
        while (parser.next() != XmlPullParser.END_DOCUMENT) {
            if (parser.eventType != XmlPullParser.START_TAG) continue
            when (parser.name) {
                "cloud-backup", "device-transfer" -> section = parser.name
                "include" -> throw AssertionError("nothing may be included: ${parser.getAttributeValue(null, "domain")}")
                "exclude" -> {
                    assertEquals(".", parser.getAttributeValue(null, "path"))
                    excluded.getOrPut(section) { mutableSetOf() } += parser.getAttributeValue(null, "domain")
                }
            }
        }
        val all = setOf("root", "file", "database", "sharedpref", "external")
        assertEquals(all, excluded["cloud-backup"])
        assertEquals(all, excluded["device-transfer"])
    }

    @Test fun noMulticastPermissionIsAsked() {
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
        val asked: List<String> = info.requestedPermissions?.toList() ?: emptyList()
        assertFalse("android.permission.CHANGE_WIFI_MULTICAST_STATE" in asked)
        assertTrue("the test must see the real manifest", "android.permission.INTERNET" in asked)
    }

    @Test fun alertsAskTheNotificationAndForegroundServicePermissions() {
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
        val asked = info.requestedPermissions?.toList().orEmpty()
        for (permission in listOf(
            "android.permission.POST_NOTIFICATIONS", "android.permission.FOREGROUND_SERVICE",
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE", "android.permission.RECEIVE_BOOT_COMPLETED",
        )) {
            assertTrue("$permission is not asked", permission in asked)
        }
        assertFalse("dataSync stops after 6 hours: not used", "android.permission.FOREGROUND_SERVICE_DATA_SYNC" in asked)
    }

    /** The watching service is a foreground service of type specialUse (no time limit) with its subtype property. */
    @Test fun theWatchingServiceIsSpecialUseWithItsSubtypeProperty() {
        val ns = "http://schemas.android.com/apk/res/android"
        val manifest = context.assets.openXmlResourceParser("AndroidManifest.xml")
        var inService = false
        var type = -1
        var subtype: String? = null
        var exported: Boolean? = null
        while (manifest.next() != XmlPullParser.END_DOCUMENT) {
            if (manifest.eventType == XmlPullParser.START_TAG && manifest.name == "service" &&
                manifest.getAttributeValue(ns, "name").endsWith("alerts.AlertsService")
            ) {
                inService = true
                type = manifest.getAttributeIntValue(ns, "foregroundServiceType", -1)
                exported = manifest.getAttributeBooleanValue(ns, "exported", true)
            } else if (inService && manifest.eventType == XmlPullParser.START_TAG && manifest.name == "property" &&
                manifest.getAttributeValue(ns, "name") == "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
            ) {
                subtype = manifest.getAttributeValue(ns, "value")
            } else if (manifest.eventType == XmlPullParser.END_TAG && manifest.name == "service") {
                inService = false
            }
        }
        assertEquals("specialUse is 0x40000000", 0x40000000, type)
        assertEquals(false, exported)
        assertTrue("the subtype property is missing", !subtype.isNullOrBlank())
    }

    @Test fun theBootReceiverRestartsTheWatchingService() {
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_RECEIVERS)
        val receiver = info.receivers.orEmpty().firstOrNull { it.name.endsWith("alerts.AlertsBootReceiver") }
        assertTrue("the boot receiver is not declared", receiver != null)
        assertFalse(receiver!!.exported)
    }
}
