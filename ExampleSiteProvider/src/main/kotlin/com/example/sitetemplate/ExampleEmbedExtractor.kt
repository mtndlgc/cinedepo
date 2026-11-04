package com.example.sitetemplate

import com.lagradost.cloudstream3.SubtitleFile
import com.lagradost.cloudstream3.app
import com.lagradost.cloudstream3.utils.ExtractorApi
import com.lagradost.cloudstream3.utils.ExtractorLink
import com.lagradost.cloudstream3.utils.ExtractorLinkType
import com.lagradost.cloudstream3.utils.Qualities
import com.lagradost.cloudstream3.utils.newExtractorLink

/**
 * Template for an embed host that Cloudstream has no built-in extractor for.
 *
 * loadExtractor(url, ...) picks the extractor whose [mainUrl] matches the start of the
 * iframe URL, so set [mainUrl] to the embed host (not to the catalogue site).
 */
class ExampleEmbedExtractor : ExtractorApi() {
    // TODO: the embed player's host, e.g. "https://player.example-cdn.com".
    override val mainUrl = "https://player.example-cdn.com"
    override val name = "ExampleEmbed"
    override val requiresReferer = true

    override suspend fun getUrl(
        url: String,
        referer: String?,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit,
    ) {
        val html = app.get(url, referer = referer).text

        // TODO: adapt to the embed page; often `file:"https://...m3u8"` or a <source> tag.
        val m3u8 = FILE_REGEX.find(html)?.groupValues?.getOrNull(1) ?: return
        if (!m3u8.startsWith("https://")) return

        callback(
            newExtractorLink(
                source = name,
                name = name,
                url = m3u8,
                type = if (".m3u8" in m3u8) ExtractorLinkType.M3U8 else ExtractorLinkType.VIDEO,
            ) {
                this.referer = url
                this.quality = Qualities.Unknown.value
            }
        )
    }

    private companion object {
        val FILE_REGEX = Regex("""file\s*:\s*["']([^"']+)["']""")
    }
}
