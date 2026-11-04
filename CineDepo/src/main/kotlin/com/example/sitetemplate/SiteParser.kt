package com.example.sitetemplate

import org.jsoup.nodes.Document
import org.jsoup.nodes.Element
import java.net.URI

/*
 * Pure Jsoup layer: HTML in, plain data classes out.
 *
 * It does no networking and does not touch Cloudstream types, so it can be unit
 * tested on the JVM against saved HTML (see SiteParserTest). The provider maps
 * these results to Cloudstream models.
 *
 * Parsing rules used throughout:
 *  - a missing optional field becomes null / empty, never an exception;
 *  - a card without a title or link is dropped;
 *  - every URL is made absolute and must be http(s) on an allowed host.
 */

data class ParsedItem(
    val title: String,
    val url: String,
    val posterUrl: String?,
    val isSeries: Boolean,
)

data class ParsedListing(
    val items: List<ParsedItem>,
    val hasNext: Boolean,
)

data class ParsedEpisode(
    val url: String,
    val name: String?,
    val season: Int?,
    val episode: Int?,
    val posterUrl: String?,
)

data class ParsedDetail(
    val title: String,
    val posterUrl: String?,
    val plot: String?,
    val year: Int?,
    val tags: List<String>,
    val actors: List<String>,
    val trailerUrl: String?,
    val episodes: List<ParsedEpisode>,
    val recommendations: List<ParsedItem>,
) {
    val isSeries: Boolean get() = episodes.isNotEmpty()
}

data class ParsedSubtitle(val url: String, val lang: String)

data class ParsedSources(
    /** Embedded players for Cloudstream's extractors (loadExtractor). */
    val embedUrls: List<String>,
    /** Direct file / HLS URLs found in <video>/<source>. */
    val directUrls: List<String>,
    val subtitles: List<ParsedSubtitle>,
    /** Raw JSON from the inline player script, if [SiteSelectors.playerJsonRegex] matched. */
    val playerJson: String?,
)

/**
 * The CSS selectors the parser uses. Production code takes them from [SiteConfig]
 * ([fromConfig]); tests pass their own set that matches the fixture pages, so
 * changing SiteConfig for a real site does not break the unit tests.
 */
data class SiteSelectors(
    val listItem: String,
    val itemTitle: String,
    val itemLink: String,
    val itemPoster: String,
    val itemIsSeries: String,
    val nextPage: String,
    val detailTitle: String,
    val detailPoster: String,
    val detailPlot: String,
    val detailYear: String,
    val detailTags: String,
    val detailActors: String,
    val detailTrailer: String,
    val detailRecommended: String,
    val seasonBlock: String,
    val seasonNumberAttr: String,
    val episodeItem: String,
    val episodeLink: String,
    val episodeName: String,
    val episodeNumberAttr: String,
    val episodeThumb: String,
    val playerIframe: String,
    val directSource: String,
    val subtitleTrack: String,
    val playerScript: String,
    val playerJsonRegex: Regex?,
) {
    companion object {
        fun fromConfig() = SiteSelectors(
            listItem = SiteConfig.Selectors.LIST_ITEM,
            itemTitle = SiteConfig.Selectors.ITEM_TITLE,
            itemLink = SiteConfig.Selectors.ITEM_LINK,
            itemPoster = SiteConfig.Selectors.ITEM_POSTER,
            itemIsSeries = SiteConfig.Selectors.ITEM_IS_SERIES,
            nextPage = SiteConfig.Selectors.NEXT_PAGE,
            detailTitle = SiteConfig.Selectors.DETAIL_TITLE,
            detailPoster = SiteConfig.Selectors.DETAIL_POSTER,
            detailPlot = SiteConfig.Selectors.DETAIL_PLOT,
            detailYear = SiteConfig.Selectors.DETAIL_YEAR,
            detailTags = SiteConfig.Selectors.DETAIL_TAGS,
            detailActors = SiteConfig.Selectors.DETAIL_ACTORS,
            detailTrailer = SiteConfig.Selectors.DETAIL_TRAILER,
            detailRecommended = SiteConfig.Selectors.DETAIL_RECOMMENDED,
            seasonBlock = SiteConfig.Selectors.SEASON_BLOCK,
            seasonNumberAttr = SiteConfig.Selectors.SEASON_NUMBER_ATTR,
            episodeItem = SiteConfig.Selectors.EPISODE_ITEM,
            episodeLink = SiteConfig.Selectors.EPISODE_LINK,
            episodeName = SiteConfig.Selectors.EPISODE_NAME,
            episodeNumberAttr = SiteConfig.Selectors.EPISODE_NUMBER_ATTR,
            episodeThumb = SiteConfig.Selectors.EPISODE_THUMB,
            playerIframe = SiteConfig.Selectors.PLAYER_IFRAME,
            directSource = SiteConfig.Selectors.DIRECT_SOURCE,
            subtitleTrack = SiteConfig.Selectors.SUBTITLE_TRACK,
            playerScript = SiteConfig.Selectors.PLAYER_SCRIPT,
            playerJsonRegex = SiteConfig.PLAYER_JSON_REGEX,
        )
    }
}

class SiteParser(
    mainUrl: String = SiteConfig.MAIN_URL,
    extraHosts: Set<String> = SiteConfig.ALLOWED_EXTRA_HOSTS,
    private val sel: SiteSelectors = SiteSelectors.fromConfig(),
) {
    private val baseUri: URI = URI(mainUrl)
    private val allowedHosts: Set<String> =
        (extraHosts + listOfNotNull(baseUri.host)).map { it.lowercase().removePrefix("www.") }.toSet()

    // ---------------------------------------------------------------- listing

    fun parseListing(doc: Document): ParsedListing = ParsedListing(
        items = doc.select(sel.listItem).mapNotNull { parseItem(it) }.distinctBy { it.url },
        hasNext = doc.selectFirst(sel.nextPage) != null,
    )

    fun parseItem(card: Element): ParsedItem? {
        val link = card.selectFirst(sel.itemLink) ?: return null
        val url = safeUrl(link.attr("href"), sameSiteOnly = true) ?: return null
        val title = card.textOf(sel.itemTitle)
            ?: link.attr("title").cleanText()
            ?: card.selectFirst(sel.itemPoster)?.attr("alt").cleanText()
            ?: return null
        return ParsedItem(
            title = title,
            url = url,
            posterUrl = card.selectFirst(sel.itemPoster)?.imageUrl(),
            isSeries = card.selectFirst(sel.itemIsSeries) != null,
        )
    }

    // ---------------------------------------------------------------- detail

    fun parseDetail(doc: Document): ParsedDetail? {
        val title = doc.textOf(sel.detailTitle)
            ?: doc.selectFirst("meta[property=og:title]")?.attr("content").cleanText()
            ?: return null

        val poster = doc.selectFirst(sel.detailPoster)?.imageUrl()
            ?: safeUrl(doc.selectFirst("meta[property=og:image]")?.attr("content"))

        val plot = doc.textOf(sel.detailPlot)
            ?: doc.selectFirst("meta[name=description]")?.attr("content").cleanText()

        val trailer = doc.selectFirst(sel.detailTrailer)?.let { el: Element ->
            safeUrl(el.attr("href").ifBlank { el.attr("src") }, sameSiteOnly = false)
        }

        return ParsedDetail(
            title = title,
            posterUrl = poster,
            plot = plot,
            year = doc.textOf(sel.detailYear)?.let { YEAR.find(it)?.value?.toIntOrNull() },
            tags = doc.select(sel.detailTags).mapNotNull { it.text().cleanText() }.distinct(),
            actors = doc.select(sel.detailActors).mapNotNull { it.text().cleanText() }.distinct(),
            trailerUrl = trailer,
            episodes = parseEpisodes(doc),
            recommendations = doc.select(sel.detailRecommended).mapNotNull { parseItem(it) },
        )
    }

    fun parseEpisodes(doc: Document): List<ParsedEpisode> =
        doc.select(sel.seasonBlock).flatMapIndexed { seasonIndex, block ->
            val season = block.attr(sel.seasonNumberAttr).toIntOrNull() ?: (seasonIndex + 1)
            block.select(sel.episodeItem).mapIndexedNotNull { epIndex, li ->
                val url = safeUrl(li.selectFirst(sel.episodeLink)?.attr("href"), sameSiteOnly = true)
                    ?: return@mapIndexedNotNull null
                ParsedEpisode(
                    url = url,
                    name = li.textOf(sel.episodeName),
                    season = season,
                    episode = li.attr(sel.episodeNumberAttr).toIntOrNull() ?: (epIndex + 1),
                    posterUrl = li.selectFirst(sel.episodeThumb)?.imageUrl(),
                )
            }
        }.distinctBy { it.url }

    // ---------------------------------------------------------------- player

    fun parseSources(doc: Document): ParsedSources {
        val embeds = doc.select(sel.playerIframe).mapNotNull {
            // Third-party players are the point of extractors, so any https host is accepted here.
            safeUrl(it.attr("src").ifBlank { it.attr("data-src") }, sameSiteOnly = false)
        }
        val direct = doc.select(sel.directSource).mapNotNull {
            safeUrl(it.attr("src"), sameSiteOnly = false)
        }
        val subs = doc.select(sel.subtitleTrack).mapNotNull { track ->
            val url = safeUrl(track.attr("src"), sameSiteOnly = false) ?: return@mapNotNull null
            ParsedSubtitle(url, track.attr("label").cleanText() ?: track.attr("srclang").cleanText() ?: "Unknown")
        }
        val json = sel.playerJsonRegex?.let { regex ->
            doc.select(sel.playerScript).asSequence()
                .map { it.data() }
                .mapNotNull { regex.find(it)?.groupValues?.getOrNull(1) }
                .firstOrNull()
        }
        return ParsedSources(embeds.distinct(), direct.distinct(), subs.distinctBy { it.url }, json)
    }

    // ---------------------------------------------------------------- helpers

    /**
     * Resolves [raw] against the site and validates it.
     * Returns null for blank values, javascript:/data: URLs, non-http(s) schemes and,
     * when [sameSiteOnly] is true, hosts outside the allow-list.
     */
    fun safeUrl(raw: String?, sameSiteOnly: Boolean = false): String? {
        val value = raw?.trim()?.takeIf { it.isNotEmpty() && !it.startsWith("#") } ?: return null
        val uri = runCatching {
            if (value.startsWith("//")) URI("${baseUri.scheme}:$value") else baseUri.resolve(value.replace(" ", "%20"))
        }.getOrNull() ?: return null
        if (uri.scheme?.lowercase() !in setOf("http", "https")) return null
        val host = uri.host?.lowercase()?.removePrefix("www.") ?: return null
        if (sameSiteOnly && host !in allowedHosts) return null
        return uri.toString()
    }

    /** Lazy-loading sites keep the real image in data-* attributes. */
    private fun Element.imageUrl(): String? =
        sequenceOf("data-src", "data-lazy-src", "data-original", "src")
            .map { attr(it) }
            .firstOrNull { it.isNotBlank() && !it.startsWith("data:") }
            ?.let { safeUrl(it) }
            ?: attr("srcset").split(',').firstOrNull()?.trim()?.substringBefore(' ')?.let { safeUrl(it) }

    private fun Element.textOf(css: String): String? = selectFirst(css)?.text().cleanText()

    private fun String?.cleanText(): String? = this?.replace(WHITESPACE, " ")?.trim()?.takeIf { it.isNotEmpty() }

    private companion object {
        val WHITESPACE = Regex("\\s+")
        val YEAR = Regex("(19|20)\\d{2}")
    }
}
