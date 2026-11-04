package com.example.internetarchive

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.URLDecoder

class ArchiveApiTest {
    private fun fixture(name: String) = javaClass.getResource("/fixtures/$name")!!.readText()

    @Test
    fun searchParsesLooselyTypedDocs() {
        val (items, hasNext) = ArchiveApi.parseSearch(fixture("search.json"), page = 1)
        assertEquals(listOf("night_of_the_living_dead", "His_Girl_Friday_1940", "no_title_item"), items.map { it.identifier })
        assertEquals(1968, items[0].year)          // year as string
        assertEquals("His Girl Friday", items[1].title)  // title as array
        assertEquals(1940, items[1].year)          // year as number
        assertEquals("no_title_item", items[2].title)    // falls back to identifier
        assertTrue(hasNext)                         // 120 results, 50 per page
        assertFalse(ArchiveApi.parseSearch(fixture("search.json"), page = 3).second)
        assertEquals("https://archive.org/details/night_of_the_living_dead", items[0].detailsUrl)
        assertEquals("https://archive.org/services/img/night_of_the_living_dead", items[0].posterUrl)
    }

    @Test
    fun brokenJsonIsEmpty() {
        assertEquals(0, ArchiveApi.parseSearch("<html>error</html>").first.size)
        assertNull(ArchiveApi.parseMetadata("{}"))
        assertNull(ArchiveApi.parseMetadata("not json"))
    }

    @Test
    fun metadataVideosSubtitlesAndText() {
        val d = ArchiveApi.parseMetadata(fixture("metadata.json"))!!
        assertEquals("Night of the Living Dead", d.title)
        assertEquals(1968, d.year) // from "date"
        assertEquals("A group of people hide from flesh-eating ghouls.\nPublic domain.\nDirected by George A. Romero & others.", d.description)
        assertEquals(listOf("horror", "zombies", "Romero"), d.tags)

        // h.264 first, MPEG2 and Ogg skipped, file names URL-encoded
        assertEquals(
            listOf(
                "https://archive.org/download/night_of_the_living_dead/night_of_the_living_dead.mp4",
                "https://archive.org/download/night_of_the_living_dead/Night%20Of%20The%20Living%20Dead%20HD.mp4",
                "https://archive.org/download/night_of_the_living_dead/night_of_the_living_dead_512kb.mp4",
            ),
            d.videos.map { it.url },
        )
        assertEquals(480, d.videos[0].height)
        assertEquals("720p · MPEG4 · orijinal", d.videos[1].label)

        assertEquals(listOf("EN", "TR"), d.subtitles.map { it.label })
        assertEquals("https://archive.org/download/night_of_the_living_dead/subs/night.tr.vtt", d.subtitles[1].url)
    }

    @Test
    fun nonMovieItemsAreRejected() {
        val audio = fixture("metadata.json").replace("\"mediatype\":\"movies\"", "\"mediatype\":\"audio\"")
        assertNull(ArchiveApi.parseMetadata(audio))
    }

    @Test
    fun identifiers() {
        assertEquals("abc_1940", ArchiveApi.identifierFrom("https://archive.org/details/abc_1940"))
        assertEquals("abc_1940", ArchiveApi.identifierFrom("https://archive.org/details/abc_1940/file.mp4?x=1"))
        assertEquals("abc_1940", ArchiveApi.identifierFrom("abc_1940"))
        assertNull(ArchiveApi.identifierFrom("https://archive.org/details/"))
        assertNull(ArchiveApi.identifierFrom("../../etc"))
    }

    @Test
    fun searchQueryIsEscaped() {
        val url = ArchiveApi.searchQueryUrl("night) OR collection:(x")
        val q = URLDecoder.decode(url.substringAfter("q=").substringBefore("&"), "UTF-8")
        assertTrue(q, q.contains("""title:(night\) OR collection\:\(x)"""))
        assertTrue(q.startsWith("collection:(feature_films OR Film_Noir"))
        assertTrue(url.contains("&page=1&output=json"))
        assertTrue(ArchiveApi.collectionUrl("feature_films", 0).contains("&page=1&"))
    }
}
