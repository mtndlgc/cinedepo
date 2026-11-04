package com.example.sitetemplate

import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Runs on the JVM, no device or network. Save real pages of your target site into
 * src/test/resources/fixtures and adapt these assertions when you change selectors.
 */
class SiteParserTest {
    // Selectors of the fixture pages in src/test/resources/fixtures. Independent of
    // SiteConfig on purpose: retargeting the plugin must not break these tests.
    private val fixtureSelectors = SiteSelectors(
        listItem = "div.items article.item",
        itemTitle = "h3.title",
        itemLink = "a[href]",
        itemPoster = "img",
        itemIsSeries = ".badge-series",
        nextPage = "a.next, link[rel=next]",
        detailTitle = "h1.entry-title",
        detailPoster = "div.poster img",
        detailPlot = "div.description",
        detailYear = "span.year",
        detailTags = "div.genres a",
        detailActors = "div.cast a",
        detailTrailer = "a.trailer[href], iframe.trailer[src]",
        detailRecommended = "div.related article.item",
        seasonBlock = "div.seasons div.season",
        seasonNumberAttr = "data-season",
        episodeItem = "ul.episodes li",
        episodeLink = "a[href]",
        episodeName = ".episode-title",
        episodeNumberAttr = "data-episode",
        episodeThumb = "img",
        playerIframe = "div.player iframe[src], div.player iframe[data-src]",
        directSource = "video source[src], video[src]",
        subtitleTrack = "video track[kind=subtitles][src], video track[kind=captions][src]",
        playerScript = "script",
        playerJsonRegex = Regex("""playerConfig\s*=\s*(\{.*?\})\s*;""", RegexOption.DOT_MATCHES_ALL),
    )

    private val parser = SiteParser("https://example-site.com", setOf("cdn.example-site.com"), fixtureSelectors)

    private fun fixture(name: String): Document {
        val html = javaClass.getResource("/fixtures/$name")!!.readText()
        return Jsoup.parse(html, "https://example-site.com/")
    }

    @Test
    fun listingKeepsValidCardsOnly() {
        val listing = parser.parseListing(fixture("listing.html"))
        assertEquals(listOf("First Movie", "Some Show"), listing.items.map { it.title })
        assertTrue(listing.hasNext)

        val movie = listing.items[0]
        assertEquals("https://example-site.com/movie/first-movie", movie.url)
        assertEquals("https://example-site.com/img/first.jpg", movie.posterUrl) // data-src beats data: placeholder
        assertFalse(movie.isSeries)

        val show = listing.items[1]
        assertTrue(show.isSeries)
        assertEquals("https://example-site.com/img/show.jpg", show.posterUrl) // protocol-relative
    }

    @Test
    fun movieDetail() {
        val d = parser.parseDetail(fixture("movie.html"))
        assertNotNull(d)
        d!!
        assertEquals("First Movie", d.title)
        assertEquals("https://example-site.com/img/first-large.jpg", d.posterUrl)
        assertEquals(2021, d.year)
        assertEquals(listOf("Drama", "Comedy"), d.tags)
        assertEquals(listOf("Actor One", "Actor Two"), d.actors)
        assertEquals("https://www.youtube.com/watch?v=abc123", d.trailerUrl)
        assertFalse(d.isSeries)
        assertEquals(listOf("Other"), d.recommendations.map { it.title })
    }

    @Test
    fun seriesEpisodes() {
        val d = parser.parseDetail(fixture("series.html"))!!
        assertTrue(d.isSeries)
        assertEquals(3, d.episodes.size)
        assertEquals(Triple(1, 2, "Second"), d.episodes[1].let { Triple(it.season, it.episode, it.name) })
        // season without data-season -> index-based, episode without data-episode -> index-based
        assertEquals(2, d.episodes[2].season)
        assertEquals(1, d.episodes[2].episode)
        assertEquals("https://example-site.com/img/s2e1.jpg", d.episodes[2].posterUrl)
    }

    @Test
    fun sources() {
        val s = parser.parseSources(fixture("movie.html"))
        assertEquals(
            listOf("https://player.example-cdn.com/embed/xyz", "https://other-host.example.org/e/1"),
            s.embedUrls,
        )
        assertEquals(listOf("https://example-site.com/media/first.m3u8"), s.directUrls)
        assertEquals("English", s.subtitles.single().lang)
        assertTrue(s.playerJson!!.contains("first-720.mp4"))
    }

    @Test
    fun safeUrlRejectsUnsafeValues() {
        assertNull(parser.safeUrl("javascript:alert(1)"))
        assertNull(parser.safeUrl("data:text/html,hi"))
        assertNull(parser.safeUrl("  "))
        assertNull(parser.safeUrl("#top"))
        assertNull(parser.safeUrl("https://evil.example.net/", sameSiteOnly = true))
        assertEquals("https://cdn.example-site.com/a", parser.safeUrl("https://cdn.example-site.com/a", sameSiteOnly = true))
        assertEquals("https://example-site.com/a%20b", parser.safeUrl("/a b", sameSiteOnly = true))
    }

    @Test
    fun missingTitleMeansNoDetail() {
        assertNull(parser.parseDetail(Jsoup.parse("<html><body><p>nothing</p></body></html>")))
    }

    @Test
    fun configSelectorsMapCompletely() {
        // Fails to compile or throws if SiteConfig and SiteSelectors drift apart.
        assertNotNull(SiteSelectors.fromConfig().listItem)
    }
}
