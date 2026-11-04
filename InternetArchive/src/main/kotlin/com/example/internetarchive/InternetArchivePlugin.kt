package com.example.internetarchive

import android.content.Context
import com.lagradost.cloudstream3.plugins.CloudstreamPlugin
import com.lagradost.cloudstream3.plugins.Plugin

@CloudstreamPlugin
class InternetArchivePlugin : Plugin() {
    override fun load(context: Context) {
        registerMainAPI(InternetArchiveProvider())
    }
}
