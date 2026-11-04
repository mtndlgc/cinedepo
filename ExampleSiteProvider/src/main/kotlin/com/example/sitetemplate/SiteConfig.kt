package com.example.sitetemplate

/**
 * Everything that is specific to one website lives here.
 *
 * To target a new site you normally change ONLY this file:
 *  1. set [MAIN_URL],
 *  2. list the homepage sections in [HOME_SECTIONS],
 *  3. open the site in a browser (DevTools > Elements) and replace every selector below.
 *
 * Only use this with sites whose terms allow automated access and content you have the
 * right to watch. The defaults match the fixture pages in src/test/resources/fixtures,
 * not a real site.
 */
object SiteConfig {

    // TODO: your site's base URL, no trailing slash.
    const val MAIN_URL = "https://example-site.com"

    // TODO: name shown in the app.
    const val NAME = "Example Site"

    // TODO: ISO 639-1 language code of the content.
    const val LANG = "tr"

    /**
     * Homepage rows: path (relative to [MAIN_URL]) to row title.
     * `%d` is replaced with the page number for infinite scrolling.
     */
    // TODO: real listing paths.
    val HOME_SECTIONS: List<Pair<String, String>> = listOf(
        "/movies/page/%d" to "Latest Movies",
        "/series/page/%d" to "Latest Series",
        "/trending/page/%d" to "Trending",
    )

    /** Search URL. `%s` is replaced with the URL-encoded query. */
    // TODO: search URL of your site (look at the URL after submitting the search form).
    const val SEARCH_PATH = "/search?q=%s"

    /** Paths that must stay on these hosts (besides MAIN_URL's own host). */
    // TODO: embed / CDN hosts you expect, e.g. "player.example-cdn.com".
    val ALLOWED_EXTRA_HOSTS: Set<String> = setOf()

    object Selectors {
        // ---------- Listing pages (homepage rows and search results) ----------
        // One card per movie / series.
        const val LIST_ITEM = "div.items article.item"
        const val ITEM_TITLE = "h3.title"
        const val ITEM_LINK = "a[href]"
        const val ITEM_POSTER = "img"
        // Optional: an element that only series cards have (badge, class, ...).
        const val ITEM_IS_SERIES = ".badge-series"
        // A "next page" link; when it is missing the app stops asking for more pages.
        const val NEXT_PAGE = "a.next, link[rel=next]"

        // ---------- Detail page ----------
        const val DETAIL_TITLE = "h1.entry-title"
        const val DETAIL_POSTER = "div.poster img"
        const val DETAIL_PLOT = "div.description"
        const val DETAIL_YEAR = "span.year"
        const val DETAIL_TAGS = "div.genres a"
        const val DETAIL_ACTORS = "div.cast a"
        const val DETAIL_TRAILER = "a.trailer[href], iframe.trailer[src]"
        const val DETAIL_RECOMMENDED = "div.related article.item"

        // ---------- Series ----------
        // Container per season. Leave the episode selectors relative to it.
        const val SEASON_BLOCK = "div.seasons div.season"
        // Attribute on SEASON_BLOCK holding the season number (falls back to its index).
        const val SEASON_NUMBER_ATTR = "data-season"
        const val EPISODE_ITEM = "ul.episodes li"
        const val EPISODE_LINK = "a[href]"
        const val EPISODE_NAME = ".episode-title"
        const val EPISODE_NUMBER_ATTR = "data-episode"
        const val EPISODE_THUMB = "img"

        // ---------- Player / video sources ----------
        // Iframes that embed a third-party player (handled by Cloudstream extractors).
        const val PLAYER_IFRAME = "div.player iframe[src], div.player iframe[data-src]"
        // Direct <video>/<source> tags.
        const val DIRECT_SOURCE = "video source[src], video[src]"
        // Subtitle tracks.
        const val SUBTITLE_TRACK = "video track[kind=subtitles][src], video track[kind=captions][src]"
        // A <script> that contains a JSON player config (see [PLAYER_JSON_REGEX]).
        const val PLAYER_SCRIPT = "script"
    }

    /**
     * Many players put their sources in an inline script, e.g.
     * `var playerConfig = {"sources":[{"file":"...","label":"720p"}]};`
     * Group 1 must capture the JSON object.
     */
    // TODO: adapt to the variable name your site uses, or set to null to disable.
    val PLAYER_JSON_REGEX: Regex? = Regex("""playerConfig\s*=\s*(\{.*?\})\s*;""", RegexOption.DOT_MATCHES_ALL)
}
