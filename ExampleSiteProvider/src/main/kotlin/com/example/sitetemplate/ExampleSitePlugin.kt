package com.example.sitetemplate

import android.content.Context
import com.lagradost.cloudstream3.plugins.CloudstreamPlugin
import com.lagradost.cloudstream3.plugins.Plugin

/**
 * Entry point the app loads from the .cs3 file.
 * Register every MainAPI and custom ExtractorApi of this module here.
 */
@CloudstreamPlugin
class ExampleSitePlugin : Plugin() {
    override fun load(context: Context) {
        registerMainAPI(ExampleSiteProvider())
        registerExtractorAPI(ExampleEmbedExtractor())
    }
}
