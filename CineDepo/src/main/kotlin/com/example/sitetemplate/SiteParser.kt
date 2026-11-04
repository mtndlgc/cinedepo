package com.example.sitetemplate

import com.example.sitetemplate.SiteConfig.Selectors
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
    /** Raw JSON from the inline player script, if [SiteConfig.PLAYER_JSON_REGEX] matched. */
    val playerJson: String?,
)

class SiteParser(
    mainUrl: String = SiteConfig.MAIN_URL,
    extraHosts: Set<String> = SiteConfig.ALLOWED_EXTRA_HOSTS,
) {
    private val baseUri: URI = URI(mainUrl)
    private val allowedHosts: Set<String> =
        (extraHosts + listOfNotNull(baseUri.host)).map { it.lowercase().removePrefix("www.") }.toSet()

    // ---------------------------------------------------------------- listing

    fun parseListing(doc: Document): ParsedListing = ParsedListing(
        items = doc.select(Selectors.LIST_ITEM).mapNotNull { parseItem(it) }.distinctBy { it.url },
        hasNext = doc.selectFirst(Selectors.NEXT_PAGE) != null,
    )

    fun parseItem(card: Element): ParsedItem? {
        val link = card.selectFirst(Selectors.ITEM_LINK) ?: return null
        val url = safeUrl(link.attr("href"), sameSiteOnly = true) ?: return null
        val title = card.textOf(Selectors.ITEM_TITLE)
            ?: link.attr("title").cleanText()
            ?: card.selectFirst(Selectors.ITEM_POSTER)?.attr("alt").cleanText()
            ?: return null
        return ParsedItem(
            title = title,
            url = url,
            posterUrl = card.selectFirst(Selectors.ITEM_POSTER)?.imageUrl(),
            isSeries = card.selectFirst(Selectors.ITEM_IS_SERIES) != null,
        )
    }

    // ---------------------------------------------------------------- detail

    fun parseDetail(doc: Document): ParsedDetail? {
        val title = doc.textOf(Selectors.DETAIL_TITLE)
            ?: doc.selectFirst("meta[property=og:title]")?.attr("content").cleanText()
            ?: return null

        val poster = doc.selectFirst(Selectors.DETAIL_POSTER)?.imageUrl()
            ?: safeUrl(doc.selectFirst("meta[property=og:image]")?.attr("content"))

        val plot = doc.textOf(Selectors.DETAIL_PLOT)
            ?: doc.selectFirst("meta[name=description]")?.attr("content").cleanText()

        val trailer = doc.selectFirst(Selectors.DETAIL_TRAILER)?.let { el: Element ->
            safeUrl(el.attr("href").ifBlank { el.attr("src") }, sameSiteOnly = false)
        }

        return ParsedDetail(
            title = title,
            posterUrl = poster,
            plot = plot,
            year = doc.textOf(Selectors.DETAIL_YEAR)?.let { YEAR.find(it)?.value?.toIntOrNull() },
            tags = doc.select(Selectors.DETAIL_TAGS).mapNotNull { it.text().cleanText() }.distinct(),
            actors = doc.select(Selectors.DETAIL_ACTORS).mapNotNull { it.text().cleanText() }.distinct(),
            trailerUrl = trailer,
            episodes = parseEpisodes(doc),
            recommendations = doc.select(Selectors.DETAIL_RECOMMENDED).mapNotNull { parseItem(it) },
        )
    }

    fun parseEpisodes(doc: Document): List<ParsedEpisode> =
        doc.select(Selectors.SEASON_BLOCK).flatMapIndexed { seasonIndex, block ->
            val season = block.attr(Selectors.SEASON_NUMBER_ATTR).toIntOrNull() ?: (seasonIndex + 1)
            block.select(Selectors.EPISODE_ITEM).mapIndexedNotNull { epIndex, li ->
                val url = safeUrl(li.selectFirst(Selectors.EPISODE_LINK)?.attr("href"), sameSiteOnly = true)
                    ?: return@mapIndexedNotNull null
                ParsedEpisode(
                    url = url,
                    name = li.textOf(Selectors.EPISODE_NAME),
                    season = season,
                    episode = li.attr(Selectors.EPISODE_NUMBER_ATTR).toIntOrNull() ?: (epIndex + 1),
                    posterUrl = li.selectFirst(Selectors.EPISODE_THUMB)?.imageUrl(),
                )
            }
        }.distinctBy { it.url }

    // ---------------------------------------------------------------- player

    fun parseSources(doc: Document): ParsedSources {
        val embeds = doc.select(Selectors.PLAYER_IFRAME).mapNotNull {
            // Third-party players are the point of extractors, so any https host is accepted here.
            safeUrl(it.attr("src").ifBlank { it.attr("data-src") }, sameSiteOnly = false)
        }
        val direct = doc.select(Selectors.DIRECT_SOURCE).mapNotNull {
            safeUrl(it.attr("src"), sameSiteOnly = false)
        }
        val subs = doc.select(Selectors.SUBTITLE_TRACK).mapNotNull { track ->
            val url = safeUrl(track.attr("src"), sameSiteOnly = false) ?: return@mapNotNull null
            ParsedSubtitle(url, track.attr("label").cleanText() ?: track.attr("srclang").cleanText() ?: "Unknown")
        }
        val json = SiteConfig.PLAYER_JSON_REGEX?.let { regex ->
            doc.select(Selectors.PLAYER_SCRIPT).asSequence()
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
