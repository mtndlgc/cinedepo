package com.example.sitetemplate

import com.fasterxml.jackson.annotation.JsonProperty
import com.lagradost.cloudstream3.HomePageResponse
import com.lagradost.cloudstream3.LoadResponse
import com.lagradost.cloudstream3.LoadResponse.Companion.addActors
import com.lagradost.cloudstream3.LoadResponse.Companion.addTrailer
import com.lagradost.cloudstream3.MainAPI
import com.lagradost.cloudstream3.MainPageRequest
import com.lagradost.cloudstream3.SearchResponse
import com.lagradost.cloudstream3.SubtitleFile
import com.lagradost.cloudstream3.TvType
import com.lagradost.cloudstream3.app
import com.lagradost.cloudstream3.mainPageOf
import com.lagradost.cloudstream3.newEpisode
import com.lagradost.cloudstream3.newHomePageResponse
import com.lagradost.cloudstream3.newMovieLoadResponse
import com.lagradost.cloudstream3.newMovieSearchResponse
import com.lagradost.cloudstream3.newTvSeriesLoadResponse
import com.lagradost.cloudstream3.newTvSeriesSearchResponse
import com.lagradost.cloudstream3.utils.AppUtils.tryParseJson
import com.lagradost.cloudstream3.utils.ExtractorLink
import com.lagradost.cloudstream3.utils.ExtractorLinkType
import com.lagradost.cloudstream3.utils.Qualities
import com.lagradost.cloudstream3.utils.getQualityFromName
import com.lagradost.cloudstream3.utils.loadExtractor
import com.lagradost.cloudstream3.utils.newExtractorLink
import org.jsoup.nodes.Document
import java.net.URLEncoder

/**
 * Generic HTML provider.
 *
 * Flow inside the app:
 *   getMainPage / search  ->  list of SearchResponse (cards)
 *   load(url)             ->  LoadResponse (detail page; movie or series with episodes)
 *   loadLinks(data)       ->  ExtractorLink callbacks (playable streams) + subtitles
 *
 * All site-specific values come from [SiteConfig]; all HTML parsing is in [SiteParser].
 * This class only fetches pages and maps parsed data to Cloudstream models.
 */
class ExampleSiteProvider : MainAPI() {
    override var mainUrl = SiteConfig.MAIN_URL
    override var name = SiteConfig.NAME
    override var lang = SiteConfig.LANG
    override val hasMainPage = true
    override val hasQuickSearch = false
    override val hasDownloadSupport = true
    override val supportedTypes = setOf(TvType.Movie, TvType.TvSeries)

    // Not lazy-initialised on mainUrl on purpose: users can override mainUrl in the app's
    // settings, so the parser is rebuilt when the value changes.
    private var parserFor: Pair<String, SiteParser>? = null
    private val parser: SiteParser
        get() = parserFor?.takeIf { it.first == mainUrl }?.second
            ?: SiteParser(mainUrl).also { parserFor = mainUrl to it }

    override val mainPage = mainPageOf(
        *SiteConfig.HOME_SECTIONS.map { (path, title) -> "$mainUrl$path" to title }.toTypedArray()
    )

    // ------------------------------------------------------------------ fetch

    /** Single place for HTTP; add headers / cookies / Cloudflare interceptors here. */
    private suspend fun fetch(url: String, referer: String? = mainUrl): Document =
        app.get(
            url,
            referer = referer,
            headers = mapOf("Accept-Language" to "$lang,en;q=0.8"),
            timeout = 30L,
        ).document

    // --------------------------------------------------------------- homepage

    override suspend fun getMainPage(page: Int, request: MainPageRequest): HomePageResponse {
        val url = if ("%d" in request.data) request.data.format(page) else request.data
        val listing = parser.parseListing(fetch(url))
        return newHomePageResponse(
            name = request.name,
            list = listing.items.map { it.toSearchResponse() },
            hasNext = listing.hasNext,
        )
    }

    // ----------------------------------------------------------------- search

    override suspend fun search(query: String): List<SearchResponse> {
        val q = query.trim().takeIf { it.isNotEmpty() } ?: return emptyList()
        val url = mainUrl + SiteConfig.SEARCH_PATH.format(URLEncoder.encode(q, "UTF-8"))
        return parser.parseListing(fetch(url)).items.map { it.toSearchResponse() }
    }

    // ------------------------------------------------------------------- load

    override suspend fun load(url: String): LoadResponse? {
        val doc = fetch(url)
        val detail = parser.parseDetail(doc) ?: return null
        val recommendations = detail.recommendations.map { it.toSearchResponse() }

        return if (detail.isSeries) {
            val episodes = detail.episodes.map { ep ->
                // `data` is what loadLinks receives later: here the episode page URL.
                newEpisode(ep.url) {
                    name = ep.name
                    season = ep.season
                    episode = ep.episode
                    posterUrl = ep.posterUrl
                }
            }
            newTvSeriesLoadResponse(detail.title, url, TvType.TvSeries, episodes) {
                posterUrl = detail.posterUrl
                plot = detail.plot
                year = detail.year
                tags = detail.tags
                this.recommendations = recommendations
                addActors(detail.actors)
                addTrailer(detail.trailerUrl)
            }
        } else {
            // For a movie the detail page itself hosts the player.
            // TODO: if the player lives on a separate "/watch/..." page, pass that URL instead.
            newMovieLoadResponse(detail.title, url, TvType.Movie, url) {
                posterUrl = detail.posterUrl
                plot = detail.plot
                year = detail.year
                tags = detail.tags
                this.recommendations = recommendations
                addActors(detail.actors)
                addTrailer(detail.trailerUrl)
            }
        }
    }

    // -------------------------------------------------------------- loadLinks

    override suspend fun loadLinks(
        data: String,
        isCasting: Boolean,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit,
    ): Boolean {
        // `data` comes back from our own load(); still refuse anything off-site.
        val pageUrl = parser.safeUrl(data, sameSiteOnly = true) ?: return false
        val sources = parser.parseSources(fetch(pageUrl))
        var found = false

        sources.subtitles.forEach { subtitleCallback(SubtitleFile(it.lang, it.url)) }

        // 1) Third-party embeds: Cloudstream ships extractors for many hosts.
        //    Unknown hosts are ignored by loadExtractor (returns false); add your own
        //    ExtractorApi (see ExampleEmbedExtractor) and register it in the plugin.
        sources.embedUrls.forEach { embed ->
            if (loadExtractor(embed, pageUrl, subtitleCallback, callback)) found = true
        }

        // 2) Direct <video>/<source> URLs.
        sources.directUrls.forEach { src ->
            callback(link(src, label = null, referer = pageUrl))
            found = true
        }

        // 3) Inline JSON player config, parsed with AppUtils.tryParseJson.
        //    tryParseJson returns null instead of throwing on malformed JSON.
        val config = sources.playerJson?.let { tryParseJson<PlayerConfig>(it) }
        for (s in config?.sources.orEmpty()) {
            val file = parser.safeUrl(s.file) ?: continue
            callback(link(file, s.label, referer = pageUrl))
            found = true
        }
        for (track in config?.tracks.orEmpty()) {
            val file = parser.safeUrl(track.file) ?: continue
            subtitleCallback(SubtitleFile(track.label ?: "Unknown", file))
        }

        return found
    }

    // ---------------------------------------------------------------- mapping

    private fun ParsedItem.toSearchResponse(): SearchResponse =
        if (isSeries) {
            newTvSeriesSearchResponse(title, url, TvType.TvSeries) { this.posterUrl = this@toSearchResponse.posterUrl }
        } else {
            newMovieSearchResponse(title, url, TvType.Movie) { this.posterUrl = this@toSearchResponse.posterUrl }
        }

    private suspend fun link(url: String, label: String?, referer: String): ExtractorLink =
        newExtractorLink(
            source = name,
            name = listOfNotNull(name, label).joinToString(" "),
            url = url,
            type = if (url.substringBefore('?').endsWith(".m3u8")) ExtractorLinkType.M3U8 else ExtractorLinkType.VIDEO,
        ) {
            this.referer = referer
            this.quality = label?.let { getQualityFromName(it) } ?: Qualities.Unknown.value
        }

    // ------------------------------------------------------------------- JSON

    /** Shape of the inline `playerConfig` JSON. TODO: match your site's keys. */
    data class PlayerConfig(
        @JsonProperty("sources") val sources: List<PlayerSource>? = null,
        @JsonProperty("tracks") val tracks: List<PlayerTrack>? = null,
    )

    data class PlayerSource(
        @JsonProperty("file") val file: String? = null,
        @JsonProperty("label") val label: String? = null,
    )

    data class PlayerTrack(
        @JsonProperty("file") val file: String? = null,
        @JsonProperty("label") val label: String? = null,
    )
}
